"""Agrupamento multiline determinístico para o pipeline da Fase 2.

A máquina de estados deste módulo trabalha somente com fronteiras físicas e com
a classificação trivalente fornecida por ``Parser_de_Bloco``. Ela não usa
tempo, identificadores ou conteúdo semântico para decidir associações.

Cada ``LinhaFisica`` recebida pertence a exatamente um ``BlocoLog``. Blocos
emitidos preservam intervalos, caracteres, terminadores e hashes das linhas;
continuações órfãs e cabeçalhos aparentes inválidos são marcados como não
interpretáveis sem serem descartados.

Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from enum import Enum
import hashlib

from log_analyzer.core.interfaces import Parser_de_Bloco, TipoInicio
from log_analyzer.core.modelos import ReferenciaTextoOriginal
from log_analyzer.core.streaming import LinhaFisica

DetectorInicio = Callable[[LinhaFisica], TipoInicio]
FabricaEntradaId = Callable[[str, int], str]


class EstadoAgrupamento(Enum):
    """Estados possíveis da máquina de agrupamento multiline."""

    SEM_BLOCO = "sem_bloco"
    BLOCO_ABERTO = "bloco_aberto"


@dataclass(frozen=True, slots=True)
class BlocoLog:
    """Partição lógica lossless de uma ou mais linhas físicas contíguas.

    ``tipo_inicio`` preserva a decisão trivalente que abriu a entrada. Uma
    continuação só pode iniciar um bloco quando é órfã e, nesse caso, o bloco é
    necessariamente autônomo e não interpretável.
    """

    entrada_id: str
    arquivo_token: str
    ordem_de_leitura: int
    tipo_inicio: TipoInicio
    linhas: tuple[LinhaFisica, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.entrada_id, str) or not self.entrada_id.strip():
            raise ValueError("entrada_id deve ser uma string não vazia.")
        if not isinstance(self.arquivo_token, str) or not self.arquivo_token.strip():
            raise ValueError("arquivo_token deve ser uma string não vazia.")
        if (
            isinstance(self.ordem_de_leitura, bool)
            or not isinstance(self.ordem_de_leitura, int)
            or self.ordem_de_leitura < 0
        ):
            raise ValueError("ordem_de_leitura deve ser um inteiro não negativo.")
        if not isinstance(self.tipo_inicio, TipoInicio):
            raise TypeError("tipo_inicio deve ser TipoInicio.")
        if not isinstance(self.linhas, tuple) or not self.linhas:
            raise ValueError("linhas deve ser uma tupla não vazia de LinhaFisica.")
        if not all(isinstance(linha, LinhaFisica) for linha in self.linhas):
            raise TypeError("linhas deve conter somente LinhaFisica.")
        if self.tipo_inicio is TipoInicio.CONTINUACAO and len(self.linhas) != 1:
            raise ValueError("continuação órfã deve formar um bloco autônomo.")

        for anterior, atual in zip(self.linhas, self.linhas[1:]):
            if anterior.terminador == "":
                raise ValueError("linha em EOF não pode anteceder outra linha do bloco.")
            if atual.numero_1_based != anterior.numero_1_based + 1:
                raise ValueError("linhas do bloco devem ter numeração contígua.")
            if atual.inicio_byte != anterior.fim_byte:
                raise ValueError("intervalos de bytes do bloco devem ser contíguos.")

    @property
    def interpretavel(self) -> bool:
        """Indica se o bloco começou por um cabeçalho estruturalmente válido."""

        return self.tipo_inicio is TipoInicio.CABECALHO_VALIDO

    @property
    def entrada_nao_interpretada(self) -> bool:
        """Indica entradas que o agrupador deve preservar sem interpretação."""

        return not self.interpretavel

    @property
    def linha_inicial(self) -> int:
        return self.linhas[0].numero_1_based

    @property
    def linha_final(self) -> int:
        return self.linhas[-1].numero_1_based

    @property
    def inicio_byte(self) -> int:
        return self.linhas[0].inicio_byte

    @property
    def fim_byte(self) -> int:
        return self.linhas[-1].fim_byte

    @property
    def intervalo_linhas(self) -> tuple[int, int]:
        return (self.linha_inicial, self.linha_final)

    @property
    def intervalo_bytes(self) -> tuple[int, int]:
        return (self.inicio_byte, self.fim_byte)

    @property
    def terminadores(self) -> tuple[str, ...]:
        """Terminadores físicos, na mesma ordem em que foram recebidos."""

        return tuple(linha.terminador for linha in self.linhas)

    @property
    def hashes_linhas(self) -> tuple[str | None, ...]:
        """Hashes seguros de cada linha, inclusive quando UTF-8 é inválido."""

        return tuple(linha.sha256 for linha in self.linhas)

    @property
    def possui_falha_decodificacao(self) -> bool:
        return any(not linha.decodificada for linha in self.linhas)

    @property
    def falhas_decodificacao(self) -> tuple[object, ...]:
        """Falhas seguras preservadas sem reter os bytes que não decodificaram."""

        return tuple(
            linha.falha for linha in self.linhas if linha.falha is not None
        )

    @property
    def texto_original(self) -> str | None:
        """Reconstrói exatamente caracteres e quebras, quando todas são UTF-8."""

        partes = tuple(linha.texto_com_terminador for linha in self.linhas)
        if any(parte is None for parte in partes):
            return None
        return "".join(parte for parte in partes if parte is not None)

    @property
    def sha256(self) -> str | None:
        """SHA-256 exato do intervalo quando os bytes podem ser reconstruídos.

        Para uma linha indecodificável autônoma, o hash produzido pelo leitor já
        é o hash exato do bloco. Em blocos mistos, os hashes individuais seguem
        disponíveis, mas o módulo não tenta combinar digests como se fossem os
        bytes originais.
        """

        texto = self.texto_original
        if texto is not None:
            return hashlib.sha256(texto.encode("utf-8")).hexdigest()
        if len(self.linhas) == 1:
            return self.linhas[0].sha256
        return None

    @property
    def texto_ref(self) -> ReferenciaTextoOriginal | None:
        """Cria a referência de origem quando há um hash exato do intervalo."""

        digest = self.sha256
        if digest is None:
            return None
        return ReferenciaTextoOriginal(
            arquivo_token=self.arquivo_token,
            inicio_byte=self.inicio_byte,
            fim_byte=self.fim_byte,
            linha_inicial=self.linha_inicial,
            linha_final=self.linha_final,
            sha256=digest,
        )


@dataclass(slots=True)
class _BlocoAberto:
    entrada_id: str
    ordem_de_leitura: int
    tipo_inicio: TipoInicio
    linhas: list[LinhaFisica]


class AgrupadorMultiline:
    """Máquina incremental que transforma linhas em uma partição de blocos.

    O detector pode ser um ``Parser_de_Bloco``, um objeto que exponha
    ``detectar_inicio`` ou uma função com a mesma assinatura. O helper
    ``para_parser`` realiza a integração estrita com o protocolo opcional.
    """

    def __init__(
        self,
        detector: Parser_de_Bloco | DetectorInicio | object,
        arquivo_token: str,
        *,
        fabrica_entrada_id: FabricaEntradaId | None = None,
    ) -> None:
        if not isinstance(arquivo_token, str) or not arquivo_token.strip():
            raise ValueError("arquivo_token deve ser uma string não vazia.")

        metodo_detector = getattr(detector, "detectar_inicio", None)
        if callable(metodo_detector):
            self._detectar_inicio: DetectorInicio = metodo_detector
        elif callable(detector):
            self._detectar_inicio = detector
        else:
            raise TypeError(
                "detector deve implementar detectar_inicio ou ser chamável."
            )

        if fabrica_entrada_id is not None and not callable(fabrica_entrada_id):
            raise TypeError("fabrica_entrada_id deve ser chamável ou None.")

        self._arquivo_token = arquivo_token
        self._fabrica_entrada_id = (
            fabrica_entrada_id or self._entrada_id_padrao
        )
        self._estado = EstadoAgrupamento.SEM_BLOCO
        self._bloco_aberto: _BlocoAberto | None = None
        self._ultima_linha: LinhaFisica | None = None
        self._proxima_ordem = 0
        self._eof_finalizado = False

    @classmethod
    def para_parser(
        cls,
        parser: object,
        arquivo_token: str,
        *,
        fabrica_entrada_id: FabricaEntradaId | None = None,
    ) -> AgrupadorMultiline:
        """Cria o agrupador somente para plugins com a capacidade opcional."""

        if not isinstance(parser, Parser_de_Bloco):
            raise TypeError("parser não implementa o protocolo Parser_de_Bloco.")
        return cls(
            parser,
            arquivo_token,
            fabrica_entrada_id=fabrica_entrada_id,
        )

    @property
    def estado(self) -> EstadoAgrupamento:
        return self._estado

    @property
    def eof_finalizado(self) -> bool:
        return self._eof_finalizado

    @staticmethod
    def _entrada_id_padrao(arquivo_token: str, ordem: int) -> str:
        return f"{arquivo_token}:entrada:{ordem}"

    def _novo_identificador(self) -> tuple[str, int]:
        ordem = self._proxima_ordem
        entrada_id = self._fabrica_entrada_id(self._arquivo_token, ordem)
        if not isinstance(entrada_id, str) or not entrada_id.strip():
            raise ValueError("fábrica deve produzir entrada_id não vazio.")
        self._proxima_ordem += 1
        return entrada_id, ordem

    def _validar_proxima_linha(self, linha: LinhaFisica) -> None:
        if not isinstance(linha, LinhaFisica):
            raise TypeError("linha deve ser LinhaFisica.")
        if self._eof_finalizado:
            raise RuntimeError("não é possível processar linhas após o EOF.")

        anterior = self._ultima_linha
        if anterior is None:
            return
        if anterior.terminador == "":
            raise ValueError("linha em EOF não pode anteceder outra linha física.")
        if linha.numero_1_based != anterior.numero_1_based + 1:
            raise ValueError("linhas físicas devem ter numeração contígua.")
        if linha.inicio_byte != anterior.fim_byte:
            raise ValueError("intervalos físicos devem ser contíguos e disjuntos.")

    def _classificar(self, linha: LinhaFisica) -> TipoInicio:
        # Não há texto seguro que um plugin possa inspecionar em uma falha de
        # decodificação. Ela segue a regra de continuação e permanece registrada
        # no bloco aberto ou em uma entrada autônoma.
        if not linha.decodificada:
            return TipoInicio.CONTINUACAO
        tipo = self._detectar_inicio(linha)
        if not isinstance(tipo, TipoInicio):
            raise TypeError("detectar_inicio deve retornar TipoInicio.")
        return tipo

    def _criar_bloco(
        self,
        tipo_inicio: TipoInicio,
        linhas: tuple[LinhaFisica, ...],
    ) -> BlocoLog:
        entrada_id, ordem = self._novo_identificador()
        return BlocoLog(
            entrada_id=entrada_id,
            arquivo_token=self._arquivo_token,
            ordem_de_leitura=ordem,
            tipo_inicio=tipo_inicio,
            linhas=linhas,
        )

    def _abrir_bloco(self, tipo: TipoInicio, linha: LinhaFisica) -> None:
        entrada_id, ordem = self._novo_identificador()
        self._bloco_aberto = _BlocoAberto(
            entrada_id=entrada_id,
            ordem_de_leitura=ordem,
            tipo_inicio=tipo,
            linhas=[linha],
        )
        self._estado = EstadoAgrupamento.BLOCO_ABERTO

    def _fechar_bloco(self) -> BlocoLog:
        aberto = self._bloco_aberto
        if aberto is None or self._estado is not EstadoAgrupamento.BLOCO_ABERTO:
            raise RuntimeError("não há bloco aberto para finalizar.")

        bloco = BlocoLog(
            entrada_id=aberto.entrada_id,
            arquivo_token=self._arquivo_token,
            ordem_de_leitura=aberto.ordem_de_leitura,
            tipo_inicio=aberto.tipo_inicio,
            linhas=tuple(aberto.linhas),
        )
        self._bloco_aberto = None
        self._estado = EstadoAgrupamento.SEM_BLOCO
        return bloco

    def processar_linha(self, linha: LinhaFisica) -> tuple[BlocoLog, ...]:
        """Processa uma linha e retorna, no máximo, o bloco anterior fechado."""

        self._validar_proxima_linha(linha)
        tipo = self._classificar(linha)
        emitidos: tuple[BlocoLog, ...]

        if self._estado is EstadoAgrupamento.SEM_BLOCO:
            if tipo is TipoInicio.CONTINUACAO:
                emitidos = (self._criar_bloco(tipo, (linha,)),)
            else:
                self._abrir_bloco(tipo, linha)
                emitidos = ()
        elif tipo is TipoInicio.CONTINUACAO:
            assert self._bloco_aberto is not None
            self._bloco_aberto.linhas.append(linha)
            emitidos = ()
        else:
            anterior = self._fechar_bloco()
            self._abrir_bloco(tipo, linha)
            emitidos = (anterior,)

        self._ultima_linha = linha
        return emitidos

    def finalizar(self) -> tuple[BlocoLog, ...]:
        """Finaliza o bloco aberto uma única vez ao alcançar o EOF.

        Chamadas posteriores são idempotentes e não emitem bloco vazio nem uma
        segunda cópia do último bloco.
        """

        if self._eof_finalizado:
            return ()
        self._eof_finalizado = True
        if self._estado is EstadoAgrupamento.SEM_BLOCO:
            return ()
        return (self._fechar_bloco(),)

    def agrupar(self, linhas: Iterable[LinhaFisica]) -> Iterator[BlocoLog]:
        """Consome uma fonte até EOF e emite sua partição completa em ordem."""

        for linha in linhas:
            yield from self.processar_linha(linha)
        yield from self.finalizar()


def agrupador_para_parser(
    parser: object,
    arquivo_token: str,
    *,
    fabrica_entrada_id: FabricaEntradaId | None = None,
) -> AgrupadorMultiline | None:
    """Seleciona a capacidade multiline sem torná-la obrigatória para plugins."""

    if not isinstance(parser, Parser_de_Bloco):
        return None
    return AgrupadorMultiline.para_parser(
        parser,
        arquivo_token,
        fabrica_entrada_id=fabrica_entrada_id,
    )


def agrupar_multiline(
    linhas: Iterable[LinhaFisica],
    parser: object,
    arquivo_token: str,
    *,
    fabrica_entrada_id: FabricaEntradaId | None = None,
) -> Iterator[BlocoLog]:
    """Agrupa linhas quando o plugin implementa ``Parser_de_Bloco``.

    Plugins line-based continuam no fluxo legado: este helper não altera nem
    substitui ``agrupar_por_aplicacao`` e rejeita uso direto sem a capacidade
    opcional.
    """

    agrupador = agrupador_para_parser(
        parser,
        arquivo_token,
        fabrica_entrada_id=fabrica_entrada_id,
    )
    if agrupador is None:
        raise TypeError("parser não implementa o protocolo Parser_de_Bloco.")
    return agrupador.agrupar(linhas)
