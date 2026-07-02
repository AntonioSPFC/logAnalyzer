"""Agrupamento de entradas de log por Aplicação.

Particiona uma lista de EntradaDeLog em um dicionário cujas chaves são os
identificadores de aplicação (app_id) e cujos valores são listas de entradas
pertencentes a cada aplicação. A união disjunta de todos os grupos é igual ao
conjunto total de entradas fornecidas (Req 3.3, Property 6).
"""

from collections import defaultdict

from log_analyzer.core.modelos import EntradaDeLog


def agrupar_por_aplicacao(
    entradas: list[EntradaDeLog],
) -> dict[str, list[EntradaDeLog]]:
    """Particiona entradas pelo campo `aplicacao`.

    Returns a dict where keys are application names (app_id) and values are lists
    of entries belonging to that application. The union of all values equals the
    input list. Each entry appears in exactly one group.

    Args:
        entradas: Lista de entradas de log a agrupar.

    Returns:
        Dicionário mapeando app_id -> lista de entradas daquela aplicação.
        A ordem das entradas dentro de cada grupo preserva a ordem original da
        lista de entrada.
    """
    grupos: dict[str, list[EntradaDeLog]] = defaultdict(list)
    for entrada in entradas:
        grupos[entrada.aplicacao].append(entrada)
    return dict(grupos)
