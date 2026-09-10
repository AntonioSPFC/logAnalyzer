"""Preflight seguro e leitura binária incremental de arquivos de log.

Este módulo é o caminho de entrada da Fase 2 para VPL/ORK. Ele não materializa
o arquivo completo, não chama ``carregar_arquivo`` e nunca usa substituição de
caracteres durante a decodificação. Caminhos permanecem internos ao leitor;
falhas expõem somente tokens locais e códigos seguros.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import os
import re
import stat
from typing import Iterable, Iterator

from log_analyzer.core.carregador import TAMANHO_MAXIMO_BYTES
from log_analyzer.core.excecoes import ErroDeArquivo, ErroDeDecodificacao

MAXIMO_ARQUIVOS_POR_LOTE = 100

_TOKEN_ARQUIVO = re.compile(r"<ARQUIVO_[1-9][0-9]*>\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class FingerprintArquivo:
    """Identidade estável observada no início de uma leitura.

    O SHA-256 é calculado no mesmo passe que produz as linhas e, portanto, fica
    disponível somente depois de o iterador ser consumido até o EOF.
    """

    dispositivo: int
    inode: int
    tamanho_bytes: int
    mtime_ns: int
    sha256: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.tamanho_bytes, int) or self.tamanho_bytes < 0:
            raise ValueError("tamanho_bytes deve ser um inteiro não negativo.")
        if not isinstance(self.mtime_ns, int):
            raise TypeError("mtime_ns deve ser inteiro.")
        if self.sha256 is not None and _SHA256.fullmatch(self.sha256) is None:
            raise ValueError("sha256 deve ser um digest hexadecimal válido.")

    @property
    def identidade(self) -> tuple[int, int, int, int]:
        """Metadados usados posteriormente para confirmar a mesma fonte."""

        return (self.dispositivo, self.inode, self.tamanho_bytes, self.mtime_ns)


@dataclass(frozen=True, slots=True)
class LinhaFisica:
    """Uma linha física e seu intervalo exato na fonte binária.

    ``inicio_byte`` é inclusivo e ``fim_byte`` é exclusivo. O intervalo inclui
    o terminador, de modo que linhas consecutivas formam intervalos contíguos.
    ``texto`` nunca inclui o terminador. Quando os bytes não formam UTF-8
    válido, ``texto`` é ``None`` e ``falha`` contém somente contexto seguro.
    """

    numero_1_based: int
    inicio_byte: int
    fim_byte: int
    texto: str | None
    terminador: str
    sha256: str | None = None
    falha: ErroDeDecodificacao | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.numero_1_based, bool)
            or not isinstance(self.numero_1_based, int)
            or self.numero_1_based < 1
        ):
            raise ValueError("numero_1_based deve ser um inteiro positivo.")
        if (
            isinstance(self.inicio_byte, bool)
            or not isinstance(self.inicio_byte, int)
            or self.inicio_byte < 0
        ):
            raise ValueError("inicio_byte deve ser um inteiro não negativo.")
        if (
            isinstance(self.fim_byte, bool)
            or not isinstance(self.fim_byte, int)
            or self.fim_byte < self.inicio_byte
        ):
            raise ValueError("fim_byte não pode anteceder inicio_byte.")
        if self.terminador not in {"", "\n", "\r\n"}:
            raise ValueError("terminador deve ser LF, CRLF ou EOF.")
        if self.sha256 is not None and _SHA256.fullmatch(self.sha256) is None:
            raise ValueError("sha256 deve ser um digest hexadecimal válido.")
        if self.texto is None:
            if not isinstance(self.falha, ErroDeDecodificacao):
                raise ValueError("linha sem texto requer falha de decodificação.")
        elif not isinstance(self.texto, str):
            raise TypeError("texto deve ser str ou None.")
        elif self.falha is not None:
            raise ValueError("linha decodificada não pode conter falha.")

    @property
    def tamanho_bytes(self) -> int:
        """Quantidade de bytes do texto mais seu terminador."""

        return self.fim_byte - self.inicio_byte

    @property
    def decodificada(self) -> bool:
        """Indica se o texto pôde ser decodificado estritamente."""

        return self.falha is None

    @property
    def texto_com_terminador(self) -> str | None:
        """Reconstrói a linha válida sem normalizar sua quebra."""

        if self.texto is None:
            return None
        return self.texto + self.terminador


@dataclass(frozen=True, slots=True)
class ResultadoPreflightLote:
    """Resultado itemizado do preflight, preservando fontes válidas."""

    leitores: tuple["LeitorStreaming", ...]
    falhas: tuple[ErroDeArquivo, ...]


_MENSAGENS_DE_ARQUIVO = {
    "FILE_UNAVAILABLE": "Fonte indisponível para leitura.",
    "NOT_REGULAR_FILE": "Fonte não é um arquivo regular.",
    "FILE_NOT_READABLE": "Fonte não está disponível para leitura.",
    "EMPTY_FILE": "Fonte vazia não pode ser analisada.",
    "FILE_TOO_LARGE": "Fonte excede o limite permitido de 500 MB.",
    "FILE_METADATA_ERROR": "Metadados da fonte não puderam ser obtidos.",
    "FILE_OPEN_ERROR": "Fonte não pôde ser aberta para leitura.",
    "FILE_READ_ERROR": "Fonte não pôde ser lida integralmente.",
    "BATCH_LIMIT_EXCEEDED": "Fonte excede o limite de 100 arquivos por lote.",
}


def _erro_de_arquivo(codigo: str, arquivo_token: str) -> ErroDeArquivo:
    """Cria erro sem caminho, texto, bytes ou exceção de sistema."""

    return ErroDeArquivo(
        _MENSAGENS_DE_ARQUIVO[codigo],
        codigo=codigo,
        arquivo_token=arquivo_token,
    )


def _validar_token(arquivo_token: str) -> str:
    if not isinstance(arquivo_token, str) or _TOKEN_ARQUIVO.fullmatch(arquivo_token) is None:
        raise ValueError("Token local de arquivo inválido.")
    return arquivo_token


def _fingerprint(status: os.stat_result) -> FingerprintArquivo:
    return FingerprintArquivo(
        dispositivo=status.st_dev,
        inode=status.st_ino,
        tamanho_bytes=status.st_size,
        mtime_ns=status.st_mtime_ns,
    )


class LeitorStreaming:
    """Valida uma fonte e produz suas linhas sem carregar o arquivo inteiro."""

    def __init__(
        self,
        caminho: str | os.PathLike[str],
        arquivo_token: str = "<ARQUIVO_1>",
    ) -> None:
        self._arquivo_token = _validar_token(arquivo_token)
        try:
            caminho_normalizado = os.fspath(caminho)
        except TypeError:
            raise _erro_de_arquivo("FILE_UNAVAILABLE", self._arquivo_token) from None
        if not isinstance(caminho_normalizado, str) or not caminho_normalizado:
            raise _erro_de_arquivo("FILE_UNAVAILABLE", self._arquivo_token)
        self._caminho = caminho_normalizado
        self._fingerprint = self._executar_preflight()

    @property
    def arquivo_token(self) -> str:
        return self._arquivo_token

    @property
    def fingerprint(self) -> FingerprintArquivo:
        return self._fingerprint

    @property
    def sha256_arquivo(self) -> str | None:
        """Digest disponível após consumo completo de ``iterar_linhas``."""

        return self._fingerprint.sha256

    @classmethod
    def validar_lote(
        cls,
        caminhos: Iterable[str | os.PathLike[str]],
    ) -> ResultadoPreflightLote:
        """Faz preflight de um lote e isola falhas por token local.

        As primeiras 100 fontes são validadas independentemente. Cada fonte
        além desse limite gera uma falha própria e não impede o uso das fontes
        válidas anteriores.
        """

        if isinstance(caminhos, (str, os.PathLike)):
            fontes: Iterable[str | os.PathLike[str]] = (caminhos,)
        else:
            fontes = caminhos

        leitores: list[LeitorStreaming] = []
        falhas: list[ErroDeArquivo] = []
        for indice, caminho in enumerate(fontes, start=1):
            arquivo_token = f"<ARQUIVO_{indice}>"
            if indice > MAXIMO_ARQUIVOS_POR_LOTE:
                falhas.append(
                    _erro_de_arquivo("BATCH_LIMIT_EXCEEDED", arquivo_token)
                )
                continue
            try:
                leitores.append(cls(caminho, arquivo_token))
            except ErroDeArquivo as erro:
                falhas.append(erro)
        return ResultadoPreflightLote(tuple(leitores), tuple(falhas))

    def _validar_status(self, status: os.stat_result) -> None:
        if not stat.S_ISREG(status.st_mode):
            raise _erro_de_arquivo("NOT_REGULAR_FILE", self._arquivo_token)
        if status.st_size == 0:
            raise _erro_de_arquivo("EMPTY_FILE", self._arquivo_token)
        if status.st_size > TAMANHO_MAXIMO_BYTES:
            raise _erro_de_arquivo("FILE_TOO_LARGE", self._arquivo_token)

    def _executar_preflight(self) -> FingerprintArquivo:
        try:
            status_inicial = os.stat(self._caminho)
        except (FileNotFoundError, NotADirectoryError):
            raise _erro_de_arquivo("FILE_UNAVAILABLE", self._arquivo_token) from None
        except OSError:
            raise _erro_de_arquivo("FILE_METADATA_ERROR", self._arquivo_token) from None

        self._validar_status(status_inicial)
        if not os.access(self._caminho, os.R_OK):
            raise _erro_de_arquivo("FILE_NOT_READABLE", self._arquivo_token)

        try:
            with open(self._caminho, "rb") as stream:
                status_aberto = os.fstat(stream.fileno())
        except OSError:
            raise _erro_de_arquivo("FILE_OPEN_ERROR", self._arquivo_token) from None

        self._validar_status(status_aberto)
        return _fingerprint(status_aberto)

    def iterar_linhas(self) -> Iterator[LinhaFisica]:
        """Lê bytes sequencialmente e preserva offsets e terminadores.

        Uma linha com UTF-8 inválido ainda é emitida, sem texto e sem os bytes
        originais. Seu intervalo, tamanho, hash e posição da falha permitem que
        o pipeline registre uma referência segura e prossiga nas demais linhas.
        """

        digest_arquivo = hashlib.sha256()
        deslocamento = 0
        numero_linha = 0

        try:
            with open(self._caminho, "rb") as stream:
                status_aberto = os.fstat(stream.fileno())
                self._validar_status(status_aberto)
                self._fingerprint = _fingerprint(status_aberto)

                for bytes_linha in stream:
                    numero_linha += 1
                    digest_arquivo.update(bytes_linha)
                    inicio_byte = deslocamento
                    deslocamento += len(bytes_linha)
                    if deslocamento > TAMANHO_MAXIMO_BYTES:
                        raise _erro_de_arquivo(
                            "FILE_TOO_LARGE", self._arquivo_token
                        )

                    if bytes_linha.endswith(b"\r\n"):
                        bytes_texto = bytes_linha[:-2]
                        terminador = "\r\n"
                    elif bytes_linha.endswith(b"\n"):
                        bytes_texto = bytes_linha[:-1]
                        terminador = "\n"
                    else:
                        bytes_texto = bytes_linha
                        terminador = ""

                    digest_linha = hashlib.sha256(bytes_linha).hexdigest()
                    try:
                        texto = bytes_texto.decode("utf-8", errors="strict")
                    except UnicodeDecodeError as erro:
                        falha = ErroDeDecodificacao(
                            codigo="INVALID_UTF8",
                            arquivo_token=self._arquivo_token,
                            posicao=inicio_byte + erro.start,
                        )
                        yield LinhaFisica(
                            numero_1_based=numero_linha,
                            inicio_byte=inicio_byte,
                            fim_byte=deslocamento,
                            texto=None,
                            terminador=terminador,
                            sha256=digest_linha,
                            falha=falha,
                        )
                    else:
                        yield LinhaFisica(
                            numero_1_based=numero_linha,
                            inicio_byte=inicio_byte,
                            fim_byte=deslocamento,
                            texto=texto,
                            terminador=terminador,
                            sha256=digest_linha,
                        )
        except ErroDeArquivo:
            raise
        except OSError:
            raise _erro_de_arquivo("FILE_READ_ERROR", self._arquivo_token) from None
        else:
            self._fingerprint = replace(
                self._fingerprint,
                sha256=digest_arquivo.hexdigest(),
            )

    def __iter__(self) -> Iterator[LinhaFisica]:
        return self.iterar_linhas()


def validar_lote(
    caminhos: Iterable[str | os.PathLike[str]],
) -> ResultadoPreflightLote:
    """Atalho funcional para o preflight itemizado de ``LeitorStreaming``."""

    return LeitorStreaming.validar_lote(caminhos)
