"""Composição determinística de linhas do tempo legadas e da Fase 2.

O wrapper legado usa ``carimbo_de_tempo`` e mantém entradas sem carimbo ao
final. A composição da Fase 2 usa exclusivamente ``timestamp_normalizado``:
entradas com UTC são ordenadas cronologicamente e as demais permanecem em uma
coleção separada, sem atribuir a elas uma ordem temporal fictícia.

Requirements: 1.4, 6.5, 6.6, 6.7, 15.5, 16.1
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


def _chave_apresentacao_sem_utc(
    entrada: EntradaDeLog,
) -> tuple[str, bool, str, bool, int]:
    """Ordena entradas sem UTC apenas pelos metadados seguros de apresentação.

    Os indicadores booleanos mantêm metadados conhecidos antes dos ausentes sem
    comparar ``None`` com ``str`` ou ``int``. Como ``sorted`` é estável, entradas
    com a mesma chave (inclusive metadados ausentes) preservam a ordem recebida.
    """

    return (
        entrada.aplicacao,
        entrada.arquivo_token is None,
        entrada.arquivo_token or "",
        entrada.posicao_inicial is None,
        entrada.posicao_inicial if entrada.posicao_inicial is not None else 0,
    )


def particionar_linha_do_tempo(
    entradas: list[EntradaDeLog],
) -> tuple[list[EntradaDeLog], list[EntradaDeLog]]:
    """Compõe a partição temporal da Fase 2 sem alterar ``entradas``.

    A primeira lista contém exatamente as entradas com
    ``timestamp_normalizado`` UTC, ordenadas por
    ``(timestamp_normalizado, aplicacao, ordem_de_leitura)``. A segunda contém
    exatamente as entradas sem UTC, ordenadas somente para apresentação por
    ``(aplicacao, arquivo_token, posicao_inicial)`` e de forma estável.

    A validade UTC de ``timestamp_normalizado`` é garantida pelo invariante de
    :class:`EntradaDeLog`; uma falha de normalização é preservada na própria
    entrada, que permanece na segunda coleção.
    """

    com_utc: list[EntradaDeLog] = []
    sem_utc: list[EntradaDeLog] = []

    for entrada in entradas:
        destino = com_utc if entrada.timestamp_normalizado is not None else sem_utc
        destino.append(entrada)

    linha_do_tempo = sorted(
        com_utc,
        key=lambda entrada: (
            entrada.timestamp_normalizado,
            entrada.aplicacao,
            entrada.ordem_de_leitura,
        ),
    )
    entradas_sem_ordenacao_temporal = sorted(
        sem_utc,
        key=_chave_apresentacao_sem_utc,
    )
    return linha_do_tempo, entradas_sem_ordenacao_temporal
