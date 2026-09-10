"""Segundo passe seletivo com verificação de integridade da fonte.

O materializador mantém caminhos somente em objetos internos, relê apenas os
intervalos selecionados e não libera conteúdo de uma fonte até que todos os
seus intervalos tenham sido validados. Uma divergência de identidade,
tamanho, ``mtime_ns`` ou SHA-256 invalida a fonte inteira com
``SOURCE_CHANGED``; as demais fontes continuam sendo processadas.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
import hashlib
import hmac
import os
import re
from typing import Protocol

from log_analyzer.core.excecoes import (
    ErroDeDecodificacao,
    ErroDeIntegridadeDaFonte,
)
from log_analyzer.core.modelos import EntradaIndexada
from log_analyzer.core.streaming import FingerprintArquivo


_TOKEN_ARQUIVO = re.compile(r"<ARQUIVO_[1-9][0-9]*>\Z")
_SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")


class _FonteAlterada(Exception):
    """Sentinela interna que nunca transporta caminho ou conteúdo."""


class _Fechavel(Protocol):
    def close(self) -> None:
        """Libera o recurso temporário."""


@dataclass(frozen=True, slots=True)
class FonteMaterializacao:
    """Fonte interna e fingerprint capturado durante o primeiro passe.

    ``caminho`` é deliberadamente omitido de ``repr`` para impedir exposição
    acidental em diagnósticos. Falhas públicas usam apenas ``arquivo_token``.
    """

    arquivo_token: str
    caminho: str | os.PathLike[str] = field(repr=False)
    fingerprint: FingerprintArquivo

    def __post_init__(self) -> None:
        _validar_token(self.arquivo_token)
        try:
            caminho = os.fspath(self.caminho)
        except TypeError:
            raise TypeError("caminho interno da fonte inválido.") from None
        if not isinstance(caminho, str) or not caminho:
            raise ValueError("caminho interno da fonte inválido.")
        if not isinstance(self.fingerprint, FingerprintArquivo):
            raise TypeError("fingerprint deve ser FingerprintArquivo.")
        object.__setattr__(self, "caminho", caminho)


@dataclass(frozen=True, slots=True)
class EntradaMaterializada:
    """Entrada indexada acompanhada do texto original reconstruído."""

    entrada_indexada: EntradaIndexada
    texto_original: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.entrada_indexada, EntradaIndexada):
            raise TypeError("entrada_indexada deve ser EntradaIndexada.")
        if not isinstance(self.texto_original, str):
            raise TypeError("texto_original deve ser str.")

    @property
    def entrada_id(self) -> str:
        return self.entrada_indexada.entrada_id

    @property
    def arquivo_token(self) -> str:
        return self.entrada_indexada.texto_ref.arquivo_token


FalhaMaterializacao = ErroDeIntegridadeDaFonte | ErroDeDecodificacao


@dataclass(frozen=True, slots=True)
class ResultadoMaterializacao:
    """Resultado parcial, sem conteúdo para fontes cuja integridade falhou."""

    entradas: tuple[EntradaMaterializada, ...] = ()
    falhas: tuple[FalhaMaterializacao, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.entradas, tuple) or not all(
            isinstance(entrada, EntradaMaterializada) for entrada in self.entradas
        ):
            raise TypeError("entradas deve ser uma tupla de EntradaMaterializada.")
        if not isinstance(self.falhas, tuple) or not all(
            isinstance(falha, (ErroDeIntegridadeDaFonte, ErroDeDecodificacao))
            for falha in self.falhas
        ):
            raise TypeError("falhas deve conter somente falhas seguras de materialização.")

    def texto_por_entrada_id(self) -> dict[str, str]:
        """Cria uma visão interna dos textos selecionados por ``entrada_id``."""

        return {
            entrada.entrada_id: entrada.texto_original for entrada in self.entradas
        }


@dataclass(frozen=True, slots=True)
class _Solicitacao:
    ordem_selecao: int
    entrada: EntradaIndexada


class MaterializadorSeletivo:
    """Relê referências selecionadas e isola alterações por fonte."""

    def __init__(self, fontes: Iterable[FonteMaterializacao]) -> None:
        if isinstance(fontes, FonteMaterializacao):
            fontes_iteraveis: Iterable[FonteMaterializacao] = (fontes,)
        elif isinstance(fontes, (str, bytes, os.PathLike)):
            raise TypeError("fontes deve ser um iterável de FonteMaterializacao.")
        else:
            fontes_iteraveis = fontes

        fontes_por_token: dict[str, FonteMaterializacao] = {}
        try:
            for fonte in fontes_iteraveis:
                if not isinstance(fonte, FonteMaterializacao):
                    raise TypeError(
                        "fontes deve conter somente FonteMaterializacao."
                    )
                if fonte.arquivo_token in fontes_por_token:
                    raise ValueError("arquivo_token duplicado nas fontes.")
                fontes_por_token[fonte.arquivo_token] = fonte
        except TypeError as erro:
            if str(erro) == "fontes deve conter somente FonteMaterializacao.":
                raise
            raise TypeError(
                "fontes deve ser um iterável de FonteMaterializacao."
            ) from None

        self._fontes = fontes_por_token

    def materializar(
        self,
        entradas_selecionadas: Iterable[EntradaIndexada],
        *,
        indice_temporario: _Fechavel | None = None,
    ) -> ResultadoMaterializacao:
        """Materializa em ordem de seleção e opcionalmente encerra o índice.

        Quando ``indice_temporario`` é fornecido, seu ``close`` é executado em
        ``finally`` tanto no sucesso quanto diante de qualquer exceção.
        """

        if indice_temporario is None:
            return self._materializar(entradas_selecionadas)

        fechar = _obter_fechamento(indice_temporario)
        try:
            return self._materializar(entradas_selecionadas)
        finally:
            fechar()

    def _materializar(
        self,
        entradas_selecionadas: Iterable[EntradaIndexada],
    ) -> ResultadoMaterializacao:
        solicitacoes_por_fonte: dict[str, list[_Solicitacao]] = defaultdict(list)
        try:
            for ordem, entrada in enumerate(entradas_selecionadas):
                if not isinstance(entrada, EntradaIndexada):
                    raise TypeError(
                        "entradas_selecionadas deve conter somente EntradaIndexada."
                    )
                referencia = entrada.texto_ref
                _validar_token(referencia.arquivo_token)
                _validar_sha256(referencia.sha256)
                solicitacoes_por_fonte[referencia.arquivo_token].append(
                    _Solicitacao(ordem, entrada)
                )
        except TypeError as erro:
            if str(erro) == (
                "entradas_selecionadas deve conter somente EntradaIndexada."
            ):
                raise
            raise TypeError(
                "entradas_selecionadas deve ser um iterável de EntradaIndexada."
            ) from None

        materializadas: list[tuple[int, EntradaMaterializada]] = []
        falhas: list[tuple[int, FalhaMaterializacao]] = []

        for arquivo_token, solicitacoes in solicitacoes_por_fonte.items():
            primeira_ordem = solicitacoes[0].ordem_selecao
            fonte = self._fontes.get(arquivo_token)
            if fonte is None:
                falhas.append((primeira_ordem, _erro_fonte_alterada(arquivo_token)))
                continue

            try:
                conteudos = _reler_intervalos(fonte, solicitacoes)
            except _FonteAlterada:
                # Nenhum intervalo dessa fonte é liberado: isso impede combinar
                # metadados do primeiro passe com conteúdo de outra versão.
                falhas.append((primeira_ordem, _erro_fonte_alterada(arquivo_token)))
                continue

            for solicitacao, conteudo in conteudos:
                referencia = solicitacao.entrada.texto_ref
                try:
                    texto = conteudo.decode("utf-8", errors="strict")
                except UnicodeDecodeError as erro:
                    falhas.append(
                        (
                            solicitacao.ordem_selecao,
                            ErroDeDecodificacao(
                                codigo="INVALID_UTF8",
                                arquivo_token=arquivo_token,
                                posicao=referencia.inicio_byte + erro.start,
                            ),
                        )
                    )
                    continue

                # Decodificação UTF-8 estrita é reversível; esta asserção
                # defensiva garante que nenhum terminador ou byte foi alterado.
                if texto.encode("utf-8") != conteudo:
                    raise AssertionError("Reconstrução UTF-8 não reversível.")
                materializadas.append(
                    (
                        solicitacao.ordem_selecao,
                        EntradaMaterializada(solicitacao.entrada, texto),
                    )
                )

        materializadas.sort(key=lambda item: item[0])
        falhas.sort(key=lambda item: item[0])
        return ResultadoMaterializacao(
            entradas=tuple(entrada for _, entrada in materializadas),
            falhas=tuple(falha for _, falha in falhas),
        )


def materializar_selecao(
    entradas_selecionadas: Iterable[EntradaIndexada],
    fontes: Iterable[FonteMaterializacao],
    *,
    indice_temporario: _Fechavel,
) -> ResultadoMaterializacao:
    """Executa materialização e garante o descarte do índice em ``finally``.

    A construção do materializador também fica dentro do bloco protegido, de
    modo que uma fonte inválida ou um iterador que falhe não deixe o índice no
    disco.
    """

    fechar = _obter_fechamento(indice_temporario)
    try:
        return MaterializadorSeletivo(fontes)._materializar(
            entradas_selecionadas
        )
    finally:
        fechar()


def _validar_token(arquivo_token: object) -> str:
    if (
        not isinstance(arquivo_token, str)
        or _TOKEN_ARQUIVO.fullmatch(arquivo_token) is None
    ):
        raise ValueError("Token local de arquivo inválido.")
    return arquivo_token


def _validar_sha256(digest: object) -> str:
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise ValueError("SHA-256 da referência inválido.")
    return digest.casefold()


def _obter_fechamento(indice_temporario: _Fechavel) -> Callable[[], None]:
    fechar = getattr(indice_temporario, "close", None)
    if not callable(fechar):
        raise TypeError("indice_temporario deve fornecer close().")
    return fechar


def _erro_fonte_alterada(arquivo_token: str) -> ErroDeIntegridadeDaFonte:
    return ErroDeIntegridadeDaFonte(arquivo_token=arquivo_token)


def _identidade_status(status: os.stat_result) -> tuple[int, int, int, int]:
    return (
        status.st_dev,
        status.st_ino,
        status.st_size,
        status.st_mtime_ns,
    )


def _status_confere(
    status: os.stat_result,
    esperado: FingerprintArquivo,
) -> bool:
    return _identidade_status(status) == esperado.identidade


def _ler_exatamente(stream: object, tamanho: int) -> bytes:
    if tamanho == 0:
        return b""

    partes: list[bytes] = []
    restante = tamanho
    while restante:
        parte = stream.read(restante)  # type: ignore[attr-defined]
        if not parte:
            raise _FonteAlterada
        partes.append(parte)
        restante -= len(parte)
    return b"".join(partes)


def _reler_intervalos(
    fonte: FonteMaterializacao,
    solicitacoes: list[_Solicitacao],
) -> list[tuple[_Solicitacao, bytes]]:
    esperado = fonte.fingerprint
    conteudos: list[tuple[_Solicitacao, bytes]] = []

    try:
        with open(fonte.caminho, "rb", buffering=0) as stream:
            if not _status_confere(os.fstat(stream.fileno()), esperado):
                raise _FonteAlterada

            for solicitacao in sorted(
                solicitacoes,
                key=lambda item: (
                    item.entrada.texto_ref.inicio_byte,
                    item.entrada.texto_ref.fim_byte,
                    item.ordem_selecao,
                ),
            ):
                referencia = solicitacao.entrada.texto_ref
                if referencia.fim_byte > esperado.tamanho_bytes:
                    raise _FonteAlterada

                stream.seek(referencia.inicio_byte, os.SEEK_SET)
                conteudo = _ler_exatamente(
                    stream, referencia.fim_byte - referencia.inicio_byte
                )
                digest_atual = hashlib.sha256(conteudo).hexdigest()
                digest_esperado = _validar_sha256(referencia.sha256)
                if not hmac.compare_digest(digest_atual, digest_esperado):
                    raise _FonteAlterada
                conteudos.append((solicitacao, conteudo))

            # Confirma o descritor lido e o alvo atual do caminho. Assim, uma
            # substituição concorrente não passa apenas porque o descritor
            # antigo continuou válido até o fim das leituras.
            if not _status_confere(os.fstat(stream.fileno()), esperado):
                raise _FonteAlterada
            if not _status_confere(os.stat(fonte.caminho), esperado):
                raise _FonteAlterada
    except _FonteAlterada:
        raise
    except OSError:
        raise _FonteAlterada from None

    return conteudos


__all__ = [
    "EntradaMaterializada",
    "FalhaMaterializacao",
    "FonteMaterializacao",
    "MaterializadorSeletivo",
    "ResultadoMaterializacao",
    "materializar_selecao",
]
