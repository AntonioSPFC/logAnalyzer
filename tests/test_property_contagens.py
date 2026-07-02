"""Teste de propriedade: Integridade das contagens do Resultado_de_Analise.

Feature: log-analyzer, Property 15: Integridade das contagens do Resultado_de_Analise

**Validates: Requirements 9.4**

Para todo Resultado_de_Analise, a soma das contagens em contagem_por_categoria é igual ao
total de Entradas_de_Log selecionadas, a soma das contagens em contagem_por_aplicacao também
é igual a esse total, e cada contagem corresponde exatamente ao número real de entradas daquela
categoria/Aplicação.
"""

from collections import Counter

from hypothesis import given, settings
from hypothesis import strategies as st

from log_analyzer.core.contagens import calcular_contagens
from log_analyzer.core.modelos import Categoria, EntradaDeLog


# --- Strategies ---

_categorias = st.sampled_from(list(Categoria))
_app_ids = st.sampled_from(["VPL", "ORK", "VOCI", "APP_X", "APP_Y"])

_texto_original = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"),
        blacklist_characters="\x00",
    ),
    min_size=1,
    max_size=100,
)


@st.composite
def entrada_de_log(draw):
    """Gera uma EntradaDeLog não interpretada com categoria e aplicação variadas."""
    texto = draw(_texto_original)
    app = draw(_app_ids)
    ordem = draw(st.integers(min_value=0, max_value=10000))
    categoria = draw(_categorias)
    return EntradaDeLog(
        texto_original=texto,
        aplicacao=app,
        ordem_de_leitura=ordem,
        interpretada=False,
        categoria=categoria,
    )


_lista_de_entradas = st.lists(entrada_de_log(), min_size=0, max_size=50)


# --- Teste de propriedade ---


@settings(max_examples=100)
@given(entradas=_lista_de_entradas)
def test_integridade_das_contagens_do_resultado_de_analise(entradas):
    """Property 15: Integridade das contagens do Resultado_de_Analise.

    Feature: log-analyzer, Property 15: Integridade das contagens do Resultado_de_Analise

    Para todo Resultado_de_Analise, a soma das contagens em contagem_por_categoria é igual
    ao total de Entradas_de_Log selecionadas, a soma das contagens em contagem_por_aplicacao
    também é igual a esse total, e cada contagem corresponde exatamente ao número real de
    entradas daquela categoria/Aplicação.

    **Validates: Requirements 9.4**
    """
    contagem_por_categoria, contagem_por_aplicacao = calcular_contagens(entradas)

    # 1. sum(contagem_por_categoria.values()) == len(entradas)
    assert sum(contagem_por_categoria.values()) == len(entradas), (
        f"Soma das contagens por categoria ({sum(contagem_por_categoria.values())}) "
        f"difere do total de entradas ({len(entradas)})."
    )

    # 2. sum(contagem_por_aplicacao.values()) == len(entradas)
    assert sum(contagem_por_aplicacao.values()) == len(entradas), (
        f"Soma das contagens por aplicação ({sum(contagem_por_aplicacao.values())}) "
        f"difere do total de entradas ({len(entradas)})."
    )

    # 3. Para cada categoria c, contagem_por_categoria[c] == contagem real
    contagem_real_categoria = Counter(e.categoria for e in entradas)
    for cat, count in contagem_real_categoria.items():
        assert contagem_por_categoria.get(cat, 0) == count, (
            f"Contagem por categoria incorreta para {cat.name}: "
            f"esperado {count}, obtido {contagem_por_categoria.get(cat, 0)}."
        )
    # Não há categorias extras no resultado que não existam nas entradas
    for cat in contagem_por_categoria:
        assert cat in contagem_real_categoria, (
            f"Categoria {cat.name} presente no resultado mas não nas entradas."
        )

    # 4. Para cada app a, contagem_por_aplicacao[a] == contagem real
    contagem_real_aplicacao = Counter(e.aplicacao for e in entradas)
    for app, count in contagem_real_aplicacao.items():
        assert contagem_por_aplicacao.get(app, 0) == count, (
            f"Contagem por aplicação incorreta para {app!r}: "
            f"esperado {count}, obtido {contagem_por_aplicacao.get(app, 0)}."
        )
    # Não há aplicações extras no resultado que não existam nas entradas
    for app in contagem_por_aplicacao:
        assert app in contagem_real_aplicacao, (
            f"Aplicação {app!r} presente no resultado mas não nas entradas."
        )
