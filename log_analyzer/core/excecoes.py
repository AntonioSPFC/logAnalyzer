"""Hierarquia de exceções do Analisador de Logs.

Exceções:
    ErroDoAnalisador — exceção base de todo o analisador.
    ErroDeRegistro   — interface não implementada, id duplicado, app não suportada.
    ErroDeArquivo    — arquivo ilegível, vazio, grande demais ou formato inválido.
    ErroDeIdentificador — identificador inválido (vazio, espaços ou > 256 caracteres).
"""

from __future__ import annotations

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
