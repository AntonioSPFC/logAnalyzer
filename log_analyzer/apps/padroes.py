"""Padrões de Análise das Aplicações iniciais (Fase 1).

Na Fase 1, todos os Padrões de Análise classificam toda Entrada_de_Log como
NAO_CLASSIFICADA. A estrutura é estabelecida para que a Fase 2 adicione regras
reais sem modificar o código existente.
"""

from log_analyzer.core.interfaces import Padrao_de_Analise
from log_analyzer.core.modelos import Categoria, EntradaDeLog


class VplPadrao(Padrao_de_Analise):
    """Padrão de Análise para a Aplicação VPL (Fase 1 — Req 6.6)."""

    @property
    def categorias(self) -> tuple[Categoria, ...]:
        """Categorias suportadas: SUCESSO, ERRO, NAO_CLASSIFICADA."""
        return (Categoria.SUCESSO, Categoria.ERRO, Categoria.NAO_CLASSIFICADA)

    def classificar(self, entrada: EntradaDeLog) -> Categoria:
        """Fase 1: sempre retorna NAO_CLASSIFICADA (Req 5.4, 6.6)."""
        return Categoria.NAO_CLASSIFICADA


class OrkPadrao(Padrao_de_Analise):
    """Padrão de Análise para a Aplicação ORK (Fase 1 — Req 6.6)."""

    @property
    def categorias(self) -> tuple[Categoria, ...]:
        """Categorias suportadas: SUCESSO, ERRO, NAO_CLASSIFICADA."""
        return (Categoria.SUCESSO, Categoria.ERRO, Categoria.NAO_CLASSIFICADA)

    def classificar(self, entrada: EntradaDeLog) -> Categoria:
        """Fase 1: sempre retorna NAO_CLASSIFICADA (Req 5.4, 6.6)."""
        return Categoria.NAO_CLASSIFICADA


class VociPadrao(Padrao_de_Analise):
    """Padrão de Análise para a Aplicação VOCI (Fase 1 — Req 6.6)."""

    @property
    def categorias(self) -> tuple[Categoria, ...]:
        """Categorias suportadas: SUCESSO, ERRO, NAO_CLASSIFICADA."""
        return (Categoria.SUCESSO, Categoria.ERRO, Categoria.NAO_CLASSIFICADA)

    def classificar(self, entrada: EntradaDeLog) -> Categoria:
        """Fase 1: sempre retorna NAO_CLASSIFICADA (Req 5.4, 6.6)."""
        return Categoria.NAO_CLASSIFICADA
