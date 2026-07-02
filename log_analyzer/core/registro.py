"""Registro de Aplicações — catálogo central de plugins.

Associa cada app_id a um par (Parser_de_Aplicacao, Padrao_de_Analise),
servindo como ponto de extensão do sistema (Req 5.1, 7.1, 7.2, 7.5, 7.6).
"""

from __future__ import annotations

from log_analyzer.core.excecoes import ErroDeRegistro
from log_analyzer.core.interfaces import Padrao_de_Analise, Parser_de_Aplicacao


class Registro_de_Aplicacoes:
    """Catálogo central que associa cada app_id a um par parser/padrão.

    Métodos:
        registrar — registra uma nova Aplicação com validações.
        obter — resolve o par parser/padrão para um app_id; levanta ErroDeRegistro se ausente.
        aplicacoes_suportadas — lista os app_ids registrados.
        esta_registrada — verifica se um app_id está no catálogo.
    """

    def __init__(self) -> None:
        self._catalogo: dict[str, tuple[Parser_de_Aplicacao, Padrao_de_Analise]] = {}

    def registrar(
        self,
        app_id: str,
        parser: Parser_de_Aplicacao,
        padrao: Padrao_de_Analise,
    ) -> None:
        """Registra uma Aplicação. Valida:

        - app_id único (Req 7.6) — rejeita duplicado preservando o existente
        - parser implementa Parser_de_Aplicacao (Req 7.5)
        - padrao implementa Padrao_de_Analise (Req 7.5)

        Em falha, levanta ErroDeRegistro indicando a interface/causa e NÃO altera o catálogo.
        """
        # Validar que parser implementa a interface comum
        if not isinstance(parser, Parser_de_Aplicacao):
            raise ErroDeRegistro(
                f"O parser fornecido para '{app_id}' não implementa Parser_de_Aplicacao.",
                app_id=app_id,
                interface="Parser_de_Aplicacao",
            )

        # Validar que padrao implementa a interface comum
        if not isinstance(padrao, Padrao_de_Analise):
            raise ErroDeRegistro(
                f"O padrão fornecido para '{app_id}' não implementa Padrao_de_Analise.",
                app_id=app_id,
                interface="Padrao_de_Analise",
            )

        # Validar app_id único — rejeitar duplicado preservando o existente
        if app_id in self._catalogo:
            raise ErroDeRegistro(
                f"Identificador de Aplicação duplicado: '{app_id}'.",
                app_id=app_id,
                causa="duplicado",
            )

        # Todas as validações passaram — registrar no catálogo
        self._catalogo[app_id] = (parser, padrao)

    def obter(self, app_id: str) -> tuple[Parser_de_Aplicacao, Padrao_de_Analise]:
        """Resolve o par parser/padrão; levanta ErroDeRegistro se ausente (Req 1.5, 2.2, 6.8)."""
        if app_id not in self._catalogo:
            raise ErroDeRegistro(
                f"Aplicação não suportada: '{app_id}'.",
                app_id=app_id,
                causa="nao_suportada",
            )
        return self._catalogo[app_id]

    def aplicacoes_suportadas(self) -> tuple[str, ...]:
        """Lista os app_ids registrados."""
        return tuple(self._catalogo.keys())

    def esta_registrada(self, app_id: str) -> bool:
        """Verifica se um app_id está no catálogo."""
        return app_id in self._catalogo
