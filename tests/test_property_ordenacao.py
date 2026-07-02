"""Teste de propriedade: Ordenação determinística da linha do tempo.

Feature: log-analyzer, Property 5: Ordenação determinística da linha do tempo

**Validates: Requirements 3.4, 8.1, 8.2**

Para todo conjunto de Entradas_de_Log interpretadas (incluindo a fusão de VPL e ORK), a
linha_do_tempo resultante está ordenada de forma total e determinística pela chave
(carimbo_de_tempo, nome_da_aplicacao, ordem_de_leitura), ou seja, por tempo crescente, com
empates resolvidos pelo nome da Aplicação em ordem alfabética e, então, pela ordem de leitura.
"""

from datetime import datetime

from hypothesis import given, settings
from hypothesis import strategies as st

from log_analyzer.core.modelos import EntradaDeLog
from log_analyzer.core.ordenacao import ordenar_linha_do_tempo


# --- Strategies para gerar EntradaDeLog com timestamps variados ---

_aplicacoes = st.sampled_from(["VPL", "ORK", "VOCI"])

_timestamps = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(2099, 12, 31, 23, 59, 59),
)

# Permite gerar entradas com ou sem timestamp (interpretadas ou não)
_timestamps_ou_none = st.one_of(st.none(), _timestamps)


@st.composite
def entrada_de_log(draw):
    """Gera uma EntradaDeLog com timestamp aleatório, app e ordem de leitura."""
    aplicacao = draw(_aplicacoes)
    ordem = draw(st.integers(min_value=0, max_value=10000))
    carimbo = draw(_timestamps_ou_none)
    interpretada = carimbo is not None

    if interpretada:
        return EntradaDeLog(
            texto_original=f"log line {ordem}",
            aplicacao=aplicacao,
            ordem_de_leitura=ordem,
            interpretada=True,
            carimbo_de_tempo=carimbo,
            nivel_de_severidade="INFO",
            mensagem=f"mensagem {ordem}",
        )
    else:
        return EntradaDeLog(
            texto_original=f"raw line {ordem}",
            aplicacao=aplicacao,
            ordem_de_leitura=ordem,
            interpretada=False,
        )


_lista_de_entradas = st.lists(entrada_de_log(), min_size=0, max_size=50)


# --- Teste de propriedade ---


@settings(max_examples=100)
@given(entradas=_lista_de_entradas)
def test_ordenacao_deterministica_linha_do_tempo(entradas):
    """Property 5: Ordenação determinística da linha do tempo.

    Feature: log-analyzer, Property 5: Ordenação determinística da linha do tempo

    Para todo conjunto de EntradaDeLog (incluindo a fusão VPL/ORK), a linha_do_tempo
    resultante é ordenada de forma total e determinística pela chave
    (carimbo_de_tempo ou datetime.max, aplicacao, ordem_de_leitura).

    **Validates: Requirements 3.4, 8.1, 8.2**
    """
    resultado = ordenar_linha_do_tempo(entradas)

    # 1. Resultado está ordenado: para cada par consecutivo, a chave de a <= chave de b
    for i in range(len(resultado) - 1):
        a = resultado[i]
        b = resultado[i + 1]

        chave_a = (
            a.carimbo_de_tempo if a.carimbo_de_tempo is not None else datetime.max,
            a.aplicacao,
            a.ordem_de_leitura,
        )
        chave_b = (
            b.carimbo_de_tempo if b.carimbo_de_tempo is not None else datetime.max,
            b.aplicacao,
            b.ordem_de_leitura,
        )

        assert chave_a <= chave_b, (
            f"Entradas fora de ordem no índice {i}→{i+1}.\n"
            f"Chave[{i}]: {chave_a}\n"
            f"Chave[{i+1}]: {chave_b}"
        )

    # 2. Resultado contém os mesmos elementos que a entrada (sem perda, sem duplicação)
    assert len(resultado) == len(entradas), (
        f"Tamanho diferente: entrada={len(entradas)}, resultado={len(resultado)}"
    )
    # Verificar que os conjuntos de ids são os mesmos (usando identidade de objeto)
    ids_entrada = sorted(id(e) for e in entradas)
    ids_resultado = sorted(id(e) for e in resultado)
    assert ids_entrada == ids_resultado, (
        "Os elementos do resultado não são os mesmos da entrada (perda ou duplicação)."
    )

    # 3. Executar a ordenação novamente produz o mesmo resultado (idempotente/determinístico)
    resultado2 = ordenar_linha_do_tempo(resultado)
    assert resultado == resultado2, (
        "A ordenação não é idempotente: ordenar duas vezes produz resultados diferentes."
    )
