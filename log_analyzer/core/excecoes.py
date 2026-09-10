"""Hierarquia de exceções do Analisador de Logs.

As exceções legadas preservam seus contratos da Fase 1. As exceções da Fase 2
expõem somente contexto seguro e estruturado: código, token de arquivo e
posição. Dados brutos não fazem parte das mensagens dessas exceções.
"""

from __future__ import annotations

import re
from typing import Any


class ErroDoAnalisador(Exception):
    """Exceção base para todos os erros do Analisador de Logs."""

    def __init__(self, mensagem: str, *, contexto: dict[str, Any] | None = None) -> None:
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.contexto: dict[str, Any] = contexto or {}


class ErroDeRegistro(ErroDoAnalisador):
    """Erro ao registrar ou resolver uma Aplicação no Registro_de_Aplicacoes.

    Situações cobertas (Req 7.5, 7.6, 6.8, 2.2):
      - Parser ou padrão não implementa a interface comum.
      - Identificador de Aplicação duplicado.
      - Aplicação não suportada (não registrada).
    """

    def __init__(self, mensagem: str, *, app_id: str | None = None, **extra: Any) -> None:
        contexto: dict[str, Any] = {}
        if app_id is not None:
            contexto["app_id"] = app_id
        contexto.update(extra)
        super().__init__(mensagem, contexto=contexto)
        self.app_id = app_id


class ErroDeArquivo(ErroDoAnalisador):
    """Erro relacionado a um Arquivo_de_Log específico.

    Situações cobertas (Req 1.2, 1.4, 10.5):
      - Arquivo ilegível.
      - Arquivo vazio.
      - Arquivo excede 500 MB.
      - Formato inválido / não reconhecido pelo parser.
    """

    def __init__(self, mensagem: str, *, caminho: str | None = None, **extra: Any) -> None:
        contexto: dict[str, Any] = {}
        if caminho is not None:
            contexto["caminho"] = caminho
        contexto.update(extra)
        super().__init__(mensagem, contexto=contexto)
        self.caminho = caminho


class ErroDeIdentificador(ErroDoAnalisador):
    """Erro de validação do Identificador fornecido pelo usuário.

    Situações cobertas (Req 3.5, 10.2, 10.3):
      - Identificador vazio.
      - Identificador composto apenas por espaços em branco.
      - Identificador com mais de 256 caracteres.
    """

    def __init__(self, mensagem: str, *, identificador: str | None = None, **extra: Any) -> None:
        contexto: dict[str, Any] = {}
        if identificador is not None:
            contexto["identificador"] = identificador
        contexto.update(extra)
        super().__init__(mensagem, contexto=contexto)
        self.identificador = identificador


_PADRAO_CODIGO_SEGURO = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")
_PADRAO_TOKEN_SEGURO = re.compile(
    r"(?:<[A-Za-z][A-Za-z0-9_-]{0,63}>|[A-Za-z][A-Za-z0-9_-]{0,63})\Z"
)


def _criar_contexto_seguro(
    *,
    codigo: str,
    arquivo_token: str | None,
    posicao: int | None,
) -> dict[str, str | int]:
    """Valida e cria contexto que pode atravessar fronteiras de diagnóstico.

    Os erros de validação também usam textos constantes para não ecoar o valor
    rejeitado. Tokens aceitam somente um identificador opaco, com ou sem
    delimitadores ``<...>``; separadores de caminho não são permitidos.
    """

    if not isinstance(codigo, str) or _PADRAO_CODIGO_SEGURO.fullmatch(codigo) is None:
        raise ValueError("Código de erro seguro inválido.")

    if arquivo_token is not None and (
        not isinstance(arquivo_token, str)
        or _PADRAO_TOKEN_SEGURO.fullmatch(arquivo_token) is None
    ):
        raise ValueError("Token de arquivo seguro inválido.")

    if posicao is not None and (
        isinstance(posicao, bool) or not isinstance(posicao, int) or posicao < 0
    ):
        raise ValueError("Posição segura inválida.")

    contexto: dict[str, str | int] = {"codigo": codigo}
    if arquivo_token is not None:
        contexto["arquivo_token"] = arquivo_token
    if posicao is not None:
        contexto["posicao"] = posicao
    return contexto


class _ErroComContextoSeguro(ErroDoAnalisador):
    """Base interna para falhas da Fase 2 que podem chegar à saída segura."""

    CODIGO_PADRAO = "ANALYZER_ERROR"
    MENSAGEM_SEGURA = "Falha no Analisador de Logs."

    def __init__(
        self,
        *,
        codigo: str | None = None,
        arquivo_token: str | None = None,
        posicao: int | None = None,
    ) -> None:
        codigo_resolvido = self.CODIGO_PADRAO if codigo is None else codigo
        contexto = _criar_contexto_seguro(
            codigo=codigo_resolvido,
            arquivo_token=arquivo_token,
            posicao=posicao,
        )
        super().__init__(self.MENSAGEM_SEGURA, contexto=contexto)
        self.codigo = codigo_resolvido
        self.arquivo_token = arquivo_token
        self.posicao = posicao


class ErroDeDecodificacao(_ErroComContextoSeguro):
    """Falha de decodificação estrita sem exposição dos bytes de origem."""

    CODIGO_PADRAO = "DECODE_ERROR"
    MENSAGEM_SEGURA = "Falha de decodificação da fonte."


class ErroTemporal(_ErroComContextoSeguro):
    """Falha ao resolver um timestamp sem exposição do texto original."""

    CODIGO_PADRAO = "TEMPORAL_ERROR"
    MENSAGEM_SEGURA = "Falha na resolução temporal da entrada."


class ErroDeCatalogo(_ErroComContextoSeguro):
    """Falha de carga, integridade ou avaliação do catálogo de regras."""

    CODIGO_PADRAO = "CATALOG_ERROR"
    MENSAGEM_SEGURA = "Falha no catálogo de regras."


class ErroDeSanitizacao(_ErroComContextoSeguro):
    """Falha fail-closed que suprime qualquer conteúdo parcialmente sanitizado."""

    CODIGO_PADRAO = "SANITIZATION_ERROR"
    MENSAGEM_SEGURA = "Falha de sanitização; conteúdo suprimido."


class ErroDeIntegridadeDaFonte(_ErroComContextoSeguro):
    """Falha quando a fonte muda ou não pode ter sua identidade confirmada."""

    CODIGO_PADRAO = "SOURCE_CHANGED"
    MENSAGEM_SEGURA = "A integridade da fonte não pôde ser confirmada."
