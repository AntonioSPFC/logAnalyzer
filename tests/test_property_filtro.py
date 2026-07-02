"""Teste de propriedade: Filtragem por Identificador é correta e completa.

Feature: log-analyzer, Property 4: Filtragem por Identificador é correta e completa

**Validates: Requirements 3.1, 3.2**

Para todo conjunto de EntradaDeLog e Identificador válido, o conjunto selecionado contém
exatamente as entradas cujo conteúdo corresponde ao Identificador sem diferenciar maiúsculas
de minúsculas — toda entrada correspondente é incluída e nenhuma entrada não correspondente
é incluída.
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from log_analyzer.core.filtro import filtrar_por_identificador
from log_analyzer.core.modelos import EntradaDeLog


# --- Strategies ---

# Identificador válido: 1 a 256 caracteres, não vazio nem só espaços
_identificador_valido = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S"),
        blacklist_characters="\n\r\x00",
    ),
    min_size=1,
    max_size=20,
).filter(lambda s: s.strip() != "")

# Texto original para entradas de log (pode conter qualquer coisa exceto null)
_texto_original = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"),
        blacklist_characters="\x00",
    ),
    min_size=0,
    max_size=200,
)

_app_ids = st.sampled_from(["VPL", "ORK", "VOCI"])


@st.composite
def entrada_de_log(draw, texto=None):
    """Gera uma EntradaDeLog não interpretada com texto_original arbitrário."""
    text = draw(texto) if texto is not None else draw(_texto_original)
    app = draw(_app_ids)
    ordem = draw(st.integers(min_value=0, max_value=10000))
    return EntradaDeLog(
        texto_original=text,
        aplicacao=app,
        ordem_de_leitura=ordem,
        interpretada=False,
    )


@st.composite
def entradas_e_identificador(draw):
    """Gera uma lista de EntradaDeLog e um identificador válido para filtragem."""
    identificador = draw(_identificador_valido)
    entradas = draw(st.lists(entrada_de_log(), min_size=0, max_size=30))
    return entradas, identificador


# --- Teste de propriedade ---


@settings(max_examples=100)
@given(data=entradas_e_identificador())
def test_filtragem_por_identificador_correta_e_completa(data):
    """Property 4: Filtragem por Identificador é correta e completa.

    Feature: log-analyzer, Property 4: Filtragem por Identificador é correta e completa

    Para todo conjunto de EntradaDeLog e Identificador válido, o conjunto selecionado contém
    exatamente as entradas cujo conteúdo corresponde ao Identificador sem diferenciar
    maiúsculas de minúsculas — toda entrada correspondente é incluída e nenhuma entrada não
    correspondente é incluída.

    **Validates: Requirements 3.1, 3.2**
    """
    entradas, identificador = data

    resultado = filtrar_por_identificador(entradas, identificador)

    id_lower = identificador.lower()

    # 1. Toda entrada no resultado contém o identificador (case-insensitive)
    for entry in resultado:
        assert id_lower in entry.texto_original.lower(), (
            f"Entrada no resultado não contém o identificador.\n"
            f"Identificador: {identificador!r}\n"
            f"texto_original: {entry.texto_original!r}"
        )

    # 2. Toda entrada NÃO no resultado NÃO contém o identificador (case-insensitive)
    resultado_set = set(id(e) for e in resultado)
    for entry in entradas:
        if id(entry) not in resultado_set:
            assert id_lower not in entry.texto_original.lower(), (
                f"Entrada que contém o identificador não está no resultado.\n"
                f"Identificador: {identificador!r}\n"
                f"texto_original: {entry.texto_original!r}"
            )

    # 3. O resultado é um subconjunto da entrada (preserva identidade)
    assert len(resultado) <= len(entradas), (
        f"Resultado tem mais entradas ({len(resultado)}) que a entrada ({len(entradas)})."
    )
    for entry in resultado:
        assert entry in entradas, (
            f"Entrada no resultado não pertence à lista de entrada original.\n"
            f"texto_original: {entry.texto_original!r}"
        )
