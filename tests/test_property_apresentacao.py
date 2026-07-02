"""Teste de propriedade: Completude dos atributos apresentados por entrada.

Feature: log-analyzer, Property 16: Completude dos atributos apresentados por entrada

**Validates: Requirements 9.1**

Para todo Resultado_de_Analise não vazio, cada Entrada_de_Log apresentada inclui o seu
conteúdo, a Aplicação de origem e a categoria atribuída.
"""

from datetime import datetime

from hypothesis import given, settings
from hypothesis import strategies as st

from log_analyzer.cli.apresentacao import renderizar_resultado
from log_analyzer.core.modelos import (
    Categoria,
    EntradaDeLog,
    ResultadoDeAnalise,
)


# --- Strategies ---

_categorias = st.sampled_from(list(Categoria))
_app_ids = st.sampled_from(["VPL", "ORK", "VOCI"])

# Texto sem caracteres nulos, com pelo menos 1 caractere visível para ser encontrável
_texto_original = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S"),
        blacklist_characters="\x00\r\n",
    ),
    min_size=1,
    max_size=80,
)

_mensagem = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S"),
        blacklist_characters="\x00\r\n",
    ),
    min_size=1,
    max_size=80,
)

_severidades = st.sampled_from(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])

_timestamps = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(2030, 12, 31),
)


@st.composite
def entrada_interpretada(draw):
    """Gera uma EntradaDeLog interpretada com campos completos."""
    texto = draw(_texto_original)
    app = draw(_app_ids)
    ordem = draw(st.integers(min_value=0, max_value=10000))
    categoria = draw(_categorias)
    mensagem = draw(_mensagem)
    severidade = draw(_severidades)
    carimbo = draw(_timestamps)

    return EntradaDeLog(
        texto_original=texto,
        aplicacao=app,
        ordem_de_leitura=ordem,
        interpretada=True,
        carimbo_de_tempo=carimbo,
        nivel_de_severidade=severidade,
        mensagem=mensagem,
        categoria=categoria,
    )


@st.composite
def entrada_nao_interpretada(draw):
    """Gera uma EntradaDeLog não interpretada (texto original preservado)."""
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


_entrada_de_log = st.one_of(entrada_interpretada(), entrada_nao_interpretada())


@st.composite
def resultado_nao_vazio(draw):
    """Gera um ResultadoDeAnalise com ao menos uma entrada."""
    entradas = draw(st.lists(_entrada_de_log, min_size=1, max_size=20))

    # Agrupar entradas por aplicação
    entradas_por_aplicacao: dict[str, list[EntradaDeLog]] = {}
    for entrada in entradas:
        entradas_por_aplicacao.setdefault(entrada.aplicacao, []).append(entrada)

    identificador = draw(
        st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N"),
                blacklist_characters="\x00",
            ),
            min_size=1,
            max_size=30,
        )
    )

    return ResultadoDeAnalise(
        identificador=identificador,
        entradas_por_aplicacao=entradas_por_aplicacao,
    )


# --- Teste de propriedade ---


@settings(max_examples=100)
@given(resultado=resultado_nao_vazio())
def test_completude_dos_atributos_apresentados_por_entrada(resultado):
    """Property 16: Completude dos atributos apresentados por entrada.

    Feature: log-analyzer, Property 16: Completude dos atributos apresentados por entrada

    Para todo Resultado_de_Analise não vazio, cada Entrada_de_Log apresentada inclui o seu
    conteúdo, a Aplicação de origem e a categoria atribuída.

    **Validates: Requirements 9.1**
    """
    saida = renderizar_resultado(resultado)

    for app, entradas in resultado.entradas_por_aplicacao.items():
        # A aplicação de origem deve aparecer na saída
        assert app in saida, (
            f"A aplicação de origem '{app}' não aparece na saída renderizada."
        )

        for entrada in entradas:
            # O conteúdo da entrada deve aparecer na saída:
            # Para entradas interpretadas, a mensagem é exibida
            # Para entradas não interpretadas, o texto_original é exibido
            if entrada.interpretada:
                assert entrada.mensagem in saida, (
                    f"A mensagem '{entrada.mensagem}' da entrada interpretada "
                    f"não aparece na saída renderizada."
                )
            else:
                assert entrada.texto_original in saida, (
                    f"O texto_original '{entrada.texto_original}' da entrada não "
                    f"interpretada não aparece na saída renderizada."
                )

            # A categoria atribuída deve aparecer na saída
            assert entrada.categoria.value in saida, (
                f"A categoria '{entrada.categoria.value}' não aparece na saída "
                f"renderizada."
            )
