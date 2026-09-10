"""Índice temporário seguro com spill controlado para SQLite.

O índice aceita somente metadados mínimos e valores normalizados usados de forma
transitória para calcular HMAC-SHA-256. Texto de log, caminhos de origem e valores
originais não fazem parte do esquema em memória nem do esquema SQLite.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import tempfile
from types import TracebackType
from typing import Final


_MODO_RESTRITO: Final = stat.S_IRUSR | stat.S_IWUSR
_DOMINIO_HMAC: Final = b"log-analyzer-index-v1\x00"
_PADRAO_TOKEN: Final = re.compile(
    r"(?:<[A-Za-z][A-Za-z0-9_-]{0,127}>|[A-Za-z0-9][A-Za-z0-9_.:@-]{0,254})\Z"
)
_PADRAO_CODIGO: Final = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,127}\Z")
_PADRAO_CODIGO_FALHA: Final = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")

_SQL_INSERCAO: Final = {
    "entrada": """
        INSERT INTO entradas (
            sequencia, entrada_id, arquivo_token, aplicacao_codigo,
            ordem_de_leitura, inicio_byte, fim_byte, linha_inicial,
            linha_final, timestamp_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "identificador": """
        INSERT INTO identificadores (
            sequencia, entrada_id, namespace_codigo, hmac_sha256
        ) VALUES (?, ?, ?, ?)
    """,
    "codigo": """
        INSERT INTO codigos (sequencia, entrada_id, codigo)
        VALUES (?, ?, ?)
    """,
    "aresta": """
        INSERT INTO arestas (
            sequencia, origem_namespace, origem_hmac_sha256,
            destino_namespace, destino_hmac_sha256,
            relacao_codigo, evidencia_entrada_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
}
_ORDEM_TABELAS: Final = ("entrada", "identificador", "codigo", "aresta")


@dataclass(frozen=True, slots=True)
class RegistroEntradaIndice:
    """Metadados não reversíveis necessários para localizar uma entrada."""

    entrada_id: str
    arquivo_token: str
    aplicacao_codigo: str
    ordem_de_leitura: int
    inicio_byte: int
    fim_byte: int
    linha_inicial: int
    linha_final: int
    timestamp_normalizado: datetime | None = None


@dataclass(frozen=True, slots=True)
class IdentificadorIndexado:
    """Referência segura a um identificador, sem o valor que originou o HMAC."""

    entrada_id: str
    namespace: str
    hmac_sha256: str


@dataclass(frozen=True, slots=True)
class ArestaIndexada:
    """Aresta formada somente por HMACs separados por namespace e códigos."""

    origem_namespace: str
    origem_hmac_sha256: str
    destino_namespace: str
    destino_hmac_sha256: str
    relacao_codigo: str
    evidencia_entrada_id: str


RegistroPendente = tuple[str, tuple[object, ...]]


def _validar_inteiro_nao_negativo(valor: object, nome: str) -> int:
    if isinstance(valor, bool) or not isinstance(valor, int) or valor < 0:
        raise ValueError(f"{nome} deve ser um inteiro não negativo.")
    return valor


def _validar_token(valor: object, nome: str) -> str:
    if not isinstance(valor, str) or _PADRAO_TOKEN.fullmatch(valor) is None:
        raise ValueError(f"{nome} deve ser um token opaco seguro.")
    return valor


def _validar_codigo(valor: object, nome: str) -> str:
    if not isinstance(valor, str) or _PADRAO_CODIGO.fullmatch(valor) is None:
        raise ValueError(f"{nome} deve ser um código seguro.")
    return valor


def _validar_codigo_falha(valor: object) -> str:
    if not isinstance(valor, str) or _PADRAO_CODIGO_FALHA.fullmatch(valor) is None:
        raise ValueError("codigo deve ser um código de falha seguro.")
    return valor


def _validar_timestamp(valor: datetime | None) -> datetime | None:
    if valor is None:
        return None
    if not isinstance(valor, datetime):
        raise TypeError("timestamp_normalizado deve ser datetime ou None.")
    if valor.tzinfo is None or valor.utcoffset() is None:
        raise ValueError("timestamp_normalizado deve possuir timezone UTC.")
    if valor.utcoffset() != timedelta(0):
        raise ValueError("timestamp_normalizado deve estar normalizado em UTC.")
    return valor


def _serializar_timestamp(valor: datetime | None) -> str | None:
    return None if valor is None else valor.isoformat()


def _desserializar_timestamp(valor: str | None) -> datetime | None:
    return None if valor is None else datetime.fromisoformat(valor)


def _restringir_permissoes(descritor: int, caminho: Path) -> None:
    """Aplica modo somente para o usuário antes de o SQLite abrir o arquivo."""

    try:
        os.fchmod(descritor, _MODO_RESTRITO)
    except (AttributeError, OSError):
        os.chmod(caminho, _MODO_RESTRITO)
    else:
        os.chmod(caminho, _MODO_RESTRITO)

    if os.name == "posix" and stat.S_IMODE(caminho.stat().st_mode) & 0o077:
        raise PermissionError("Não foi possível restringir o índice temporário.")


class IndiceTemporario:
    """Índice de análise com backend em memória e spill SQLite temporário.

    ``limiar_memoria`` limita o total de registros leves (entradas,
    identificadores, códigos e arestas). Ultrapassá-lo migra atomicamente os
    registros existentes para SQLite. Depois do spill, gravações são agrupadas
    em transações de até ``tamanho_lote`` registros.

    A chave HMAC é aleatória para cada instância, nunca é persistida e é apagada
    da memória mutável durante :meth:`close`.
    """

    def __init__(
        self,
        *,
        limiar_memoria: int = 10_000,
        tamanho_lote: int = 256,
        diretorio_temporario: str | os.PathLike[str] | None = None,
    ) -> None:
        self._limiar_memoria = _validar_inteiro_nao_negativo(
            limiar_memoria, "limiar_memoria"
        )
        self._tamanho_lote = _validar_inteiro_nao_negativo(
            tamanho_lote, "tamanho_lote"
        )
        if self._tamanho_lote == 0:
            raise ValueError("tamanho_lote deve ser maior que zero.")

        self._diretorio_temporario = (
            None
            if diretorio_temporario is None
            else os.fspath(diretorio_temporario)
        )
        self._chave_hmac = bytearray(secrets.token_bytes(hashlib.sha256().digest_size))
        self._fechado = False
        self._conexao: sqlite3.Connection | None = None
        self._caminho_temporario: Path | None = None
        self._pendentes: list[RegistroPendente] = []

        self._entradas_memoria: list[tuple[int, RegistroEntradaIndice]] = []
        self._identificadores_memoria: list[
            tuple[int, str, str, bytes]
        ] = []
        self._codigos_memoria: list[tuple[int, str, str]] = []
        self._arestas_memoria: list[
            tuple[int, str, bytes, str, bytes, str, str]
        ] = []
        self._entrada_ids_memoria: set[str] = set()

        self._proxima_sequencia = 0
        self._quantidade_registros = 0

    def __enter__(self) -> IndiceTemporario:
        self._assegurar_aberto()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        self.close()
        return False

    def __del__(self) -> None:
        try:
            self.close()
        except BaseException:
            # Destrutores não podem substituir a exceção em andamento.
            pass

    @property
    def em_disco(self) -> bool:
        """Indica se o limiar já causou spill para SQLite."""

        return self._conexao is not None

    @property
    def fechado(self) -> bool:
        return self._fechado

    @property
    def caminho_temporario(self) -> Path | None:
        """Caminho do próprio índice para inspeção/lifecycle; nunca da fonte."""

        return self._caminho_temporario

    @property
    def quantidade_registros(self) -> int:
        return self._quantidade_registros

    def __len__(self) -> int:
        return self._quantidade_registros

    def calcular_hmac(self, namespace: str, valor_normalizado: str) -> str:
        """Calcula o digest efêmero sem reter ``valor_normalizado``."""

        return self._calcular_hmac_bytes(namespace, valor_normalizado).hex()

    def adicionar_entrada(
        self,
        *,
        entrada_id: str,
        arquivo_token: str,
        aplicacao_codigo: str,
        ordem_de_leitura: int,
        inicio_byte: int,
        fim_byte: int,
        linha_inicial: int,
        linha_final: int,
        timestamp_normalizado: datetime | None = None,
        codigos: Iterable[str] = (),
    ) -> RegistroEntradaIndice:
        """Adiciona somente localização, timestamp e códigos seguros."""

        self._assegurar_aberto()
        entrada_id = _validar_token(entrada_id, "entrada_id")
        arquivo_token = _validar_token(arquivo_token, "arquivo_token")
        aplicacao_codigo = _validar_codigo(
            aplicacao_codigo, "aplicacao_codigo"
        )
        ordem_de_leitura = _validar_inteiro_nao_negativo(
            ordem_de_leitura, "ordem_de_leitura"
        )
        inicio_byte = _validar_inteiro_nao_negativo(inicio_byte, "inicio_byte")
        fim_byte = _validar_inteiro_nao_negativo(fim_byte, "fim_byte")
        linha_inicial = _validar_inteiro_nao_negativo(
            linha_inicial, "linha_inicial"
        )
        linha_final = _validar_inteiro_nao_negativo(linha_final, "linha_final")
        if fim_byte < inicio_byte:
            raise ValueError("fim_byte não pode anteceder inicio_byte.")
        if linha_inicial < 1:
            raise ValueError("linha_inicial deve ser maior ou igual a 1.")
        if linha_final < linha_inicial:
            raise ValueError("linha_final não pode anteceder linha_inicial.")
        timestamp_normalizado = _validar_timestamp(timestamp_normalizado)

        if isinstance(codigos, (str, bytes)):
            raise TypeError("codigos deve ser um iterável de códigos seguros.")
        try:
            codigos_validados = tuple(
                _validar_codigo_falha(codigo) for codigo in codigos
            )
        except TypeError as erro:
            raise TypeError(
                "codigos deve ser um iterável de códigos seguros."
            ) from erro

        if self._entrada_existe(entrada_id):
            raise ValueError("entrada_id já está indexado.")

        registro = RegistroEntradaIndice(
            entrada_id=entrada_id,
            arquivo_token=arquivo_token,
            aplicacao_codigo=aplicacao_codigo,
            ordem_de_leitura=ordem_de_leitura,
            inicio_byte=inicio_byte,
            fim_byte=fim_byte,
            linha_inicial=linha_inicial,
            linha_final=linha_final,
            timestamp_normalizado=timestamp_normalizado,
        )
        registros: list[RegistroPendente] = [
            (
                "entrada",
                (
                    self._nova_sequencia(),
                    entrada_id,
                    arquivo_token,
                    aplicacao_codigo,
                    ordem_de_leitura,
                    inicio_byte,
                    fim_byte,
                    linha_inicial,
                    linha_final,
                    _serializar_timestamp(timestamp_normalizado),
                ),
            )
        ]
        registros.extend(
            (
                "codigo",
                (self._nova_sequencia(), entrada_id, codigo),
            )
            for codigo in codigos_validados
        )
        self._armazenar(registros)
        return registro

    def indexar_identificador(
        self,
        *,
        entrada_id: str,
        namespace: str,
        valor_normalizado: str,
    ) -> IdentificadorIndexado:
        """Indexa igualdade por HMAC; o valor não entra em nenhuma coleção."""

        self._assegurar_aberto()
        entrada_id = _validar_token(entrada_id, "entrada_id")
        if not self._entrada_existe(entrada_id):
            raise KeyError("entrada_id não indexado.")
        namespace = _validar_codigo(namespace, "namespace")
        digest = self._calcular_hmac_bytes(namespace, valor_normalizado)
        self._armazenar(
            [
                (
                    "identificador",
                    (self._nova_sequencia(), entrada_id, namespace, digest),
                )
            ]
        )
        return IdentificadorIndexado(entrada_id, namespace, digest.hex())

    def adicionar_codigo(self, *, entrada_id: str, codigo: str) -> None:
        """Associa um código seguro a uma entrada existente."""

        self._assegurar_aberto()
        entrada_id = _validar_token(entrada_id, "entrada_id")
        if not self._entrada_existe(entrada_id):
            raise KeyError("entrada_id não indexado.")
        codigo = _validar_codigo_falha(codigo)
        self._armazenar(
            [("codigo", (self._nova_sequencia(), entrada_id, codigo))]
        )

    def adicionar_aresta(
        self,
        *,
        origem_namespace: str,
        origem_valor_normalizado: str,
        destino_namespace: str,
        destino_valor_normalizado: str,
        relacao_codigo: str,
        evidencia_entrada_id: str,
    ) -> ArestaIndexada:
        """Adiciona aresta sem persistir nenhum dos valores dos extremos."""

        self._assegurar_aberto()
        origem_namespace = _validar_codigo(
            origem_namespace, "origem_namespace"
        )
        destino_namespace = _validar_codigo(
            destino_namespace, "destino_namespace"
        )
        relacao_codigo = _validar_codigo(relacao_codigo, "relacao_codigo")
        evidencia_entrada_id = _validar_token(
            evidencia_entrada_id, "evidencia_entrada_id"
        )
        if not self._entrada_existe(evidencia_entrada_id):
            raise KeyError("evidencia_entrada_id não indexado.")

        origem_digest = self._calcular_hmac_bytes(
            origem_namespace, origem_valor_normalizado
        )
        destino_digest = self._calcular_hmac_bytes(
            destino_namespace, destino_valor_normalizado
        )
        self._armazenar(
            [
                (
                    "aresta",
                    (
                        self._nova_sequencia(),
                        origem_namespace,
                        origem_digest,
                        destino_namespace,
                        destino_digest,
                        relacao_codigo,
                        evidencia_entrada_id,
                    ),
                )
            ]
        )
        return ArestaIndexada(
            origem_namespace=origem_namespace,
            origem_hmac_sha256=origem_digest.hex(),
            destino_namespace=destino_namespace,
            destino_hmac_sha256=destino_digest.hex(),
            relacao_codigo=relacao_codigo,
            evidencia_entrada_id=evidencia_entrada_id,
        )

    def buscar_identificador(
        self, namespace: str, valor_normalizado: str
    ) -> tuple[str, ...]:
        """Retorna tokens de entrada na ordem de primeira indexação."""

        self._assegurar_aberto()
        namespace = _validar_codigo(namespace, "namespace")
        digest = self._calcular_hmac_bytes(namespace, valor_normalizado)

        if self._conexao is None:
            encontrados: list[str] = []
            vistos: set[str] = set()
            for _, entrada_id, namespace_item, digest_item in sorted(
                self._identificadores_memoria, key=lambda item: item[0]
            ):
                if (
                    namespace_item == namespace
                    and hmac.compare_digest(digest_item, digest)
                    and entrada_id not in vistos
                ):
                    vistos.add(entrada_id)
                    encontrados.append(entrada_id)
            return tuple(encontrados)

        self.flush()
        assert self._conexao is not None
        cursor = self._conexao.execute(
            """
            SELECT entrada_id
            FROM identificadores
            WHERE namespace_codigo = ? AND hmac_sha256 = ?
            GROUP BY entrada_id
            ORDER BY MIN(sequencia)
            """,
            (namespace, digest),
        )
        return tuple(str(linha[0]) for linha in cursor)

    def obter_entrada(self, entrada_id: str) -> RegistroEntradaIndice | None:
        self._assegurar_aberto()
        entrada_id = _validar_token(entrada_id, "entrada_id")

        if self._conexao is None:
            for _, registro in self._entradas_memoria:
                if registro.entrada_id == entrada_id:
                    return registro
            return None

        self.flush()
        assert self._conexao is not None
        linha = self._conexao.execute(
            """
            SELECT entrada_id, arquivo_token, aplicacao_codigo,
                   ordem_de_leitura, inicio_byte, fim_byte,
                   linha_inicial, linha_final, timestamp_utc
            FROM entradas WHERE entrada_id = ?
            """,
            (entrada_id,),
        ).fetchone()
        return None if linha is None else self._registro_entrada_de_linha(linha)

    def iterar_entradas(self) -> Iterator[RegistroEntradaIndice]:
        self._assegurar_aberto()
        if self._conexao is None:
            for _, registro in sorted(
                self._entradas_memoria, key=lambda item: item[0]
            ):
                yield registro
            return

        self.flush()
        assert self._conexao is not None
        cursor = self._conexao.execute(
            """
            SELECT entrada_id, arquivo_token, aplicacao_codigo,
                   ordem_de_leitura, inicio_byte, fim_byte,
                   linha_inicial, linha_final, timestamp_utc
            FROM entradas ORDER BY sequencia
            """
        )
        for linha in cursor:
            yield self._registro_entrada_de_linha(linha)

    def iterar_identificadores(self) -> Iterator[IdentificadorIndexado]:
        self._assegurar_aberto()
        if self._conexao is None:
            for _, entrada_id, namespace, digest in sorted(
                self._identificadores_memoria, key=lambda item: item[0]
            ):
                yield IdentificadorIndexado(entrada_id, namespace, digest.hex())
            return

        self.flush()
        assert self._conexao is not None
        cursor = self._conexao.execute(
            """
            SELECT entrada_id, namespace_codigo, hmac_sha256
            FROM identificadores ORDER BY sequencia
            """
        )
        for entrada_id, namespace, digest in cursor:
            yield IdentificadorIndexado(
                str(entrada_id), str(namespace), bytes(digest).hex()
            )

    def codigos_da_entrada(self, entrada_id: str) -> tuple[str, ...]:
        self._assegurar_aberto()
        entrada_id = _validar_token(entrada_id, "entrada_id")
        if self._conexao is None:
            return tuple(
                codigo
                for _, item_entrada_id, codigo in sorted(
                    self._codigos_memoria, key=lambda item: item[0]
                )
                if item_entrada_id == entrada_id
            )

        self.flush()
        assert self._conexao is not None
        cursor = self._conexao.execute(
            """
            SELECT codigo FROM codigos
            WHERE entrada_id = ? ORDER BY sequencia
            """,
            (entrada_id,),
        )
        return tuple(str(linha[0]) for linha in cursor)

    def iterar_arestas(self) -> Iterator[ArestaIndexada]:
        self._assegurar_aberto()
        if self._conexao is None:
            linhas: Iterable[tuple[object, ...]] = (
                linha[1:]
                for linha in sorted(
                    self._arestas_memoria, key=lambda item: item[0]
                )
            )
        else:
            self.flush()
            assert self._conexao is not None
            linhas = self._conexao.execute(
                """
                SELECT origem_namespace, origem_hmac_sha256,
                       destino_namespace, destino_hmac_sha256,
                       relacao_codigo, evidencia_entrada_id
                FROM arestas ORDER BY sequencia
                """
            )

        for linha in linhas:
            yield ArestaIndexada(
                origem_namespace=str(linha[0]),
                origem_hmac_sha256=bytes(linha[1]).hex(),
                destino_namespace=str(linha[2]),
                destino_hmac_sha256=bytes(linha[3]).hex(),
                relacao_codigo=str(linha[4]),
                evidencia_entrada_id=str(linha[5]),
            )

    def flush(self) -> None:
        """Confirma o lote SQLite pendente em uma única transação."""

        self._assegurar_aberto()
        if not self._pendentes:
            return
        pendentes = list(self._pendentes)
        self._executar_transacao(pendentes)
        self._pendentes.clear()

    def close(self) -> None:
        """Descarta chave, memória e qualquer arquivo SQLite, mesmo sob falha."""

        if getattr(self, "_fechado", True):
            return

        self._fechado = True
        caminho = self._caminho_temporario
        conexao = self._conexao
        self._conexao = None
        self._caminho_temporario = None
        try:
            if conexao is not None:
                conexao.close()
        finally:
            try:
                if caminho is not None:
                    self._remover_arquivos_sqlite(caminho)
            finally:
                self._pendentes.clear()
                self._entradas_memoria.clear()
                self._identificadores_memoria.clear()
                self._codigos_memoria.clear()
                self._arestas_memoria.clear()
                self._entrada_ids_memoria.clear()
                for indice in range(len(self._chave_hmac)):
                    self._chave_hmac[indice] = 0

    def _assegurar_aberto(self) -> None:
        if self._fechado:
            raise RuntimeError("Índice temporário fechado.")

    def _nova_sequencia(self) -> int:
        sequencia = self._proxima_sequencia
        self._proxima_sequencia += 1
        return sequencia

    def _calcular_hmac_bytes(
        self, namespace: str, valor_normalizado: str
    ) -> bytes:
        self._assegurar_aberto()
        namespace = _validar_codigo(namespace, "namespace")
        if not isinstance(valor_normalizado, str) or not valor_normalizado.strip():
            raise ValueError("valor_normalizado deve ser texto não vazio.")

        namespace_bytes = namespace.encode("utf-8")
        valor_bytes = valor_normalizado.encode("utf-8")
        mensagem = (
            _DOMINIO_HMAC
            + len(namespace_bytes).to_bytes(2, "big")
            + namespace_bytes
            + valor_bytes
        )
        return hmac.new(
            self._chave_hmac, mensagem, digestmod=hashlib.sha256
        ).digest()

    def _entrada_existe(self, entrada_id: str) -> bool:
        if self._conexao is None:
            return entrada_id in self._entrada_ids_memoria

        if any(
            tipo == "entrada" and str(valores[1]) == entrada_id
            for tipo, valores in self._pendentes
        ):
            return True
        assert self._conexao is not None
        return (
            self._conexao.execute(
                "SELECT 1 FROM entradas WHERE entrada_id = ? LIMIT 1",
                (entrada_id,),
            ).fetchone()
            is not None
        )

    def _armazenar(self, registros: Iterable[RegistroPendente]) -> None:
        registros_materializados = list(registros)
        if not registros_materializados:
            return

        if (
            self._conexao is None
            and self._quantidade_registros + len(registros_materializados)
            > self._limiar_memoria
        ):
            self._spill_para_sqlite()

        for registro in registros_materializados:
            if self._conexao is None:
                self._armazenar_em_memoria(registro)
            else:
                self._pendentes.append(registro)
                if len(self._pendentes) >= self._tamanho_lote:
                    self.flush()
            self._quantidade_registros += 1

    def _armazenar_em_memoria(self, registro: RegistroPendente) -> None:
        tipo, valores = registro
        if tipo == "entrada":
            registro_entrada = RegistroEntradaIndice(
                entrada_id=str(valores[1]),
                arquivo_token=str(valores[2]),
                aplicacao_codigo=str(valores[3]),
                ordem_de_leitura=int(valores[4]),
                inicio_byte=int(valores[5]),
                fim_byte=int(valores[6]),
                linha_inicial=int(valores[7]),
                linha_final=int(valores[8]),
                timestamp_normalizado=_desserializar_timestamp(
                    None if valores[9] is None else str(valores[9])
                ),
            )
            self._entradas_memoria.append((int(valores[0]), registro_entrada))
            self._entrada_ids_memoria.add(registro_entrada.entrada_id)
        elif tipo == "identificador":
            self._identificadores_memoria.append(
                (
                    int(valores[0]),
                    str(valores[1]),
                    str(valores[2]),
                    bytes(valores[3]),
                )
            )
        elif tipo == "codigo":
            self._codigos_memoria.append(
                (int(valores[0]), str(valores[1]), str(valores[2]))
            )
        elif tipo == "aresta":
            self._arestas_memoria.append(
                (
                    int(valores[0]),
                    str(valores[1]),
                    bytes(valores[2]),
                    str(valores[3]),
                    bytes(valores[4]),
                    str(valores[5]),
                    str(valores[6]),
                )
            )
        else:
            raise RuntimeError("Tipo interno de registro inválido.")

    def _spill_para_sqlite(self) -> None:
        self._criar_sqlite()
        registros: list[RegistroPendente] = []
        registros.extend(
            (
                "entrada",
                (
                    sequencia,
                    entrada.entrada_id,
                    entrada.arquivo_token,
                    entrada.aplicacao_codigo,
                    entrada.ordem_de_leitura,
                    entrada.inicio_byte,
                    entrada.fim_byte,
                    entrada.linha_inicial,
                    entrada.linha_final,
                    _serializar_timestamp(entrada.timestamp_normalizado),
                ),
            )
            for sequencia, entrada in self._entradas_memoria
        )
        registros.extend(
            ("identificador", tuple(item))
            for item in self._identificadores_memoria
        )
        registros.extend(("codigo", tuple(item)) for item in self._codigos_memoria)
        registros.extend(("aresta", tuple(item)) for item in self._arestas_memoria)

        try:
            if registros:
                self._executar_transacao(registros)
        except BaseException:
            caminho = self._caminho_temporario
            conexao = self._conexao
            self._conexao = None
            self._caminho_temporario = None
            try:
                if conexao is not None:
                    conexao.close()
            finally:
                if caminho is not None:
                    self._remover_arquivos_sqlite(caminho)
            raise
        else:
            self._entradas_memoria.clear()
            self._identificadores_memoria.clear()
            self._codigos_memoria.clear()
            self._arestas_memoria.clear()
            self._entrada_ids_memoria.clear()

    def _criar_sqlite(self) -> None:
        descritor, nome = tempfile.mkstemp(
            prefix=".log-analyzer-index-",
            suffix=".sqlite3",
            dir=self._diretorio_temporario,
        )
        caminho = Path(nome)
        conexao: sqlite3.Connection | None = None
        try:
            _restringir_permissoes(descritor, caminho)
            os.close(descritor)
            descritor = -1

            conexao = sqlite3.connect(caminho, isolation_level=None)
            conexao.execute("PRAGMA foreign_keys = ON")
            conexao.execute("PRAGMA journal_mode = MEMORY")
            conexao.execute("PRAGMA synchronous = OFF")
            conexao.execute("PRAGMA temp_store = MEMORY")
            conexao.execute("PRAGMA secure_delete = ON")
            conexao.executescript(
                """
                CREATE TABLE entradas (
                    sequencia INTEGER NOT NULL UNIQUE,
                    entrada_id TEXT PRIMARY KEY,
                    arquivo_token TEXT NOT NULL,
                    aplicacao_codigo TEXT NOT NULL,
                    ordem_de_leitura INTEGER NOT NULL,
                    inicio_byte INTEGER NOT NULL,
                    fim_byte INTEGER NOT NULL,
                    linha_inicial INTEGER NOT NULL,
                    linha_final INTEGER NOT NULL,
                    timestamp_utc TEXT
                );

                CREATE TABLE identificadores (
                    sequencia INTEGER NOT NULL UNIQUE,
                    entrada_id TEXT NOT NULL,
                    namespace_codigo TEXT NOT NULL,
                    hmac_sha256 BLOB NOT NULL CHECK(length(hmac_sha256) = 32),
                    FOREIGN KEY (entrada_id) REFERENCES entradas(entrada_id)
                );

                CREATE TABLE codigos (
                    sequencia INTEGER NOT NULL UNIQUE,
                    entrada_id TEXT NOT NULL,
                    codigo TEXT NOT NULL,
                    FOREIGN KEY (entrada_id) REFERENCES entradas(entrada_id)
                );

                CREATE TABLE arestas (
                    sequencia INTEGER NOT NULL UNIQUE,
                    origem_namespace TEXT NOT NULL,
                    origem_hmac_sha256 BLOB NOT NULL
                        CHECK(length(origem_hmac_sha256) = 32),
                    destino_namespace TEXT NOT NULL,
                    destino_hmac_sha256 BLOB NOT NULL
                        CHECK(length(destino_hmac_sha256) = 32),
                    relacao_codigo TEXT NOT NULL,
                    evidencia_entrada_id TEXT NOT NULL,
                    FOREIGN KEY (evidencia_entrada_id)
                        REFERENCES entradas(entrada_id)
                );

                CREATE INDEX idx_identificadores_busca
                    ON identificadores(namespace_codigo, hmac_sha256, sequencia);
                CREATE INDEX idx_arestas_origem
                    ON arestas(origem_namespace, origem_hmac_sha256, sequencia);
                CREATE INDEX idx_arestas_destino
                    ON arestas(destino_namespace, destino_hmac_sha256, sequencia);
                CREATE INDEX idx_codigos_entrada
                    ON codigos(entrada_id, sequencia);
                PRAGMA user_version = 1;
                """
            )
            os.chmod(caminho, _MODO_RESTRITO)
        except BaseException:
            if descritor >= 0:
                os.close(descritor)
            if conexao is not None:
                conexao.close()
            self._remover_arquivos_sqlite(caminho)
            raise

        self._conexao = conexao
        self._caminho_temporario = caminho

    def _executar_transacao(
        self, registros: Iterable[RegistroPendente]
    ) -> None:
        assert self._conexao is not None
        agrupados: dict[str, list[tuple[object, ...]]] = {
            tipo: [] for tipo in _ORDEM_TABELAS
        }
        for tipo, valores in registros:
            agrupados[tipo].append(valores)

        self._conexao.execute("BEGIN IMMEDIATE")
        try:
            for tipo in _ORDEM_TABELAS:
                if agrupados[tipo]:
                    self._conexao.executemany(
                        _SQL_INSERCAO[tipo], agrupados[tipo]
                    )
        except BaseException:
            self._conexao.rollback()
            raise
        else:
            self._conexao.commit()

    @staticmethod
    def _registro_entrada_de_linha(
        linha: tuple[object, ...],
    ) -> RegistroEntradaIndice:
        return RegistroEntradaIndice(
            entrada_id=str(linha[0]),
            arquivo_token=str(linha[1]),
            aplicacao_codigo=str(linha[2]),
            ordem_de_leitura=int(linha[3]),
            inicio_byte=int(linha[4]),
            fim_byte=int(linha[5]),
            linha_inicial=int(linha[6]),
            linha_final=int(linha[7]),
            timestamp_normalizado=_desserializar_timestamp(
                None if linha[8] is None else str(linha[8])
            ),
        )

    @staticmethod
    def _remover_arquivos_sqlite(caminho: Path) -> None:
        for candidato in (
            caminho,
            Path(f"{caminho}-journal"),
            Path(f"{caminho}-wal"),
            Path(f"{caminho}-shm"),
        ):
            try:
                candidato.unlink(missing_ok=True)
            except OSError:
                # Uma segunda tentativa após fechar handles cobre o caso comum
                # sem incluir o caminho em mensagens de diagnóstico.
                try:
                    os.remove(candidato)
                except FileNotFoundError:
                    pass
