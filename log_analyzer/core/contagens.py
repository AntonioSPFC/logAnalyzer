"""Cálculo de contagens por categoria e por Aplicação.

Computa os dicionários `contagem_por_categoria` e `contagem_por_aplicacao` a partir
de uma lista de EntradaDeLog selecionadas. Ambas as somas devem ser iguais ao total
de entradas (Req 9.4, Property 15).
"""

from collections import Counter

from log_analyzer.core.modelos import Categoria, EntradaDeLog


def calcular_contagens(
    entradas: list[EntradaDeLog],
) -> tuple[dict[Categoria, int], dict[str, int]]:
    """Calcula contagens por categoria e por aplicação.

    Para uma lista de entradas selecionadas, retorna:
    - contagem_por_categoria: dict mapeando Categoria -> quantidade de entradas
      com aquela categoria.
    - contagem_por_aplicacao: dict mapeando app_id -> quantidade de entradas
      daquela aplicação.

    Ambas as somas são iguais a len(entradas).

    Args:
        entradas: Lista de entradas de log selecionadas.

    Returns:
        Tupla (contagem_por_categoria, contagem_por_aplicacao).
    """
    contagem_por_categoria: dict[Categoria, int] = dict(
        Counter(entrada.categoria for entrada in entradas)
    )
    contagem_por_aplicacao: dict[str, int] = dict(
        Counter(entrada.aplicacao for entrada in entradas)
    )
    return contagem_por_categoria, contagem_por_aplicacao
