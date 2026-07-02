"""Ordenação determinística da linha do tempo de Entradas de Log.

Ordena as entradas pela chave total (carimbo_de_tempo, nome_da_aplicacao, ordem_de_leitura):
- Tempo crescente
- Empates resolvidos pelo nome da Aplicação em ordem alfabética
- Empates subsequentes resolvidos pela ordem de leitura no arquivo

Entradas não interpretadas (sem carimbo_de_tempo) são posicionadas ao final usando
datetime.max como chave de ordenação.

Requirements: 3.4, 8.1, 8.2
"""

from datetime import datetime

from log_analyzer.core.modelos import EntradaDeLog


def ordenar_linha_do_tempo(entradas: list[EntradaDeLog]) -> list[EntradaDeLog]:
    """Sorts entries by the total key (carimbo_de_tempo, aplicacao, ordem_de_leitura).

    Only interpreted entries with a valid carimbo_de_tempo are included in the sorted timeline.
    Non-interpreted entries (without timestamp) are placed at the end using datetime.max
    as the sort key.

    Returns a new sorted list (does not mutate the input).
    """
    return sorted(
        entradas,
        key=lambda e: (
            e.carimbo_de_tempo if e.carimbo_de_tempo is not None else datetime.max,
            e.aplicacao,
            e.ordem_de_leitura,
        ),
    )
