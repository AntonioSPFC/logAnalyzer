"""Filtragem de Entradas de Log por Identificador.

Implementa a busca case-insensitive de um Identificador no texto_original
de cada EntradaDeLog (Req 3.1, 3.2).
"""

from log_analyzer.core.modelos import EntradaDeLog


def filtrar_por_identificador(
    entradas: list[EntradaDeLog], identificador: str
) -> list[EntradaDeLog]:
    """Seleciona entradas cujo texto_original contém o identificador (case-insensitive).

    Retorna exatamente as entradas onde o identificador aparece como substring
    em texto_original, sem diferenciar maiúsculas de minúsculas.

    Args:
        entradas: Lista de EntradaDeLog a filtrar.
        identificador: Cadeia de texto a buscar (substring match, case-insensitive).

    Returns:
        Lista contendo apenas as entradas cujo texto_original contém o identificador.
    """
    id_lower = identificador.lower()
    return [e for e in entradas if id_lower in e.texto_original.lower()]
