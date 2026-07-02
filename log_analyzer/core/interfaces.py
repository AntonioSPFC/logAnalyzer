"""Interfaces abstratas (contratos) do Analisador de Logs.

Define as interfaces comuns que toda Aplicação deve implementar para ser
registrada no sistema. Segue o princípio aberto/fechado: o núcleo depende
apenas dessas abstrações, nunca de implementações concretas.
"""

from abc import ABC, abstractmethod
from typing import Iterable

from log_analyzer.core.modelos import Categoria, EntradaDeLog


class Padrao_de_Analise(ABC):
    """Interface comum para Padrões de Análise (Req 7.4, 5.3, 5.4).

    Todo Padrao_de_Analise deve:
    - Declarar as categorias suportadas (incluindo no mínimo SUCESSO e ERRO).
    - Classificar uma EntradaDeLog em exatamente uma dessas categorias,
      retornando NAO_CLASSIFICADA quando nenhuma regra casar.
    """

    @property
    @abstractmethod
    def categorias(self) -> tuple[Categoria, ...]:
        """Categorias suportadas; DEVE incluir no mínimo SUCESSO e ERRO (Req 5.3)."""

    @abstractmethod
    def classificar(self, entrada: EntradaDeLog) -> Categoria:
        """Aplica as regras na ordem definida; retorna a categoria da primeira regra
        correspondente, ou NAO_CLASSIFICADA se nenhuma regra casar (Req 5.4, 5.5).
        Na Fase 1, sempre retorna NAO_CLASSIFICADA (Req 6.6)."""

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Valida que subclasses concretas definem categorias com SUCESSO e ERRO."""
        super().__init_subclass__(**kwargs)
        # Só valida se a subclasse é concreta (não possui métodos abstratos restantes)
        if getattr(cls, "__abstractmethods__", None):
            return
        # Verifica a propriedade 'categorias' no nível da instância ao invés de classe,
        # portanto a validação completa ocorre na primeira instanciação.
        original_init = cls.__init__ if hasattr(cls, "__init__") else None

        def _validating_init(self: "Padrao_de_Analise", *args: object, **kw: object) -> None:
            if original_init and original_init is not object.__init__:
                original_init(self, *args, **kw)  # type: ignore[misc]
            cats = self.categorias
            if Categoria.SUCESSO not in cats:
                raise TypeError(
                    f"{type(self).__name__}.categorias deve incluir Categoria.SUCESSO"
                )
            if Categoria.ERRO not in cats:
                raise TypeError(
                    f"{type(self).__name__}.categorias deve incluir Categoria.ERRO"
                )

        cls.__init__ = _validating_init  # type: ignore[assignment]


class Parser_de_Aplicacao(ABC):
    """Interface comum para Parsers de Aplicação (Req 7.3, 4.1, 4.2, 4.3, 4.4).

    Todo Parser_de_Aplicacao deve:
    - Declarar os níveis de severidade válidos da Aplicação.
    - Interpretar uma linha bruta em uma EntradaDeLog estruturada.
    - Imprimir uma EntradaDeLog de volta para representação textual.
    - Interpretar um arquivo inteiro (default em streaming, linha a linha).
    """

    @property
    @abstractmethod
    def niveis_de_severidade(self) -> frozenset[str]:
        """Conjunto de níveis de severidade válidos definidos pela Aplicação."""

    @abstractmethod
    def interpretar_entrada(self, texto: str) -> EntradaDeLog:
        """Converte uma linha bruta em EntradaDeLog estruturada.

        Se faltar carimbo de tempo válido, severidade válida ou mensagem,
        retorna uma EntradaDeLog marcada como nao_interpretada, preservando o texto original.
        (Req 4.1, 4.2, 4.3)
        """

    @abstractmethod
    def imprimir_entrada(self, entrada: EntradaDeLog) -> str:
        """Produz a representação textual contendo carimbo de tempo, severidade e mensagem.

        (Req 4.4) — deve satisfazer o round-trip do Req 4.5 para entradas interpretadas.
        """

    def interpretar_arquivo(self, linhas: Iterable[str]) -> list[EntradaDeLog]:
        """Interpretação em streaming, linha a linha (default fornecido pela classe base)."""
        return [self.interpretar_entrada(l) for l in linhas]
