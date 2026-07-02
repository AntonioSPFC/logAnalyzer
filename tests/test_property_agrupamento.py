"""Teste de propriedade: Agrupamento por Aplicação.

Feature: log-analyzer, Property 6: Agrupamento por Aplicação

**Validates: Requirements 3.3**

Para todo ResultadoDeAnalise, as Entradas_de_Log estão particionadas por Aplicação: cada
grupo contém somente entradas da Aplicação correspondente e a união disjunta dos grupos é
igual ao conjunto total de entradas selecionadas.
"""

from datetime import datetime

from hypothesis import given, settings
from hypothesis import strategies as st

from log_analyzer.core.modelos import EntradaDeLog
from log_analyzer.core.agrupamento import agrupar_por_aplicacao


# --- Strategies para gerar EntradaDeLog com aplicações variadas ---

_aplicacoes = st.sampled_from(["VPL", "ORK", "VOCI", "APP_X", "APP_Y"])

_timestamps = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(2099, 12, 31, 23, 59, 59),
)


@st.composite
def entrada_de_log(draw):
    """Gera uma EntradaDeLog com aplicação variada."""
    aplicacao = draw(_aplicacoes)
    ordem = draw(st.integers(min_value=0, max_value=10000))
    interpretada = draw(st.booleans())

    if interpretada:
        carimbo = draw(_timestamps)
        return EntradaDeLog(
            texto_original=f"log line {aplicacao} {ordem}",
            aplicacao=aplicacao,
            ordem_de_leitura=ordem,
            interpretada=True,
            carimbo_de_tempo=carimbo,
            nivel_de_severidade="INFO",
            mensagem=f"mensagem {ordem}",
        )
    else:
        return EntradaDeLog(
            texto_original=f"raw line {aplicacao} {ordem}",
            aplicacao=aplicacao,
            ordem_de_leitura=ordem,
            interpretada=False,
        )


_lista_de_entradas = st.lists(entrada_de_log(), min_size=0, max_size=50)


# --- Teste de propriedade ---


@settings(max_examples=100)
@given(entradas=_lista_de_entradas)
def test_agrupamento_por_aplicacao(entradas):
    """Property 6: Agrupamento por Aplicação.

    Feature: log-analyzer, Property 6: Agrupamento por Aplicação

    Para todo ResultadoDeAnalise, as entradas estão particionadas por Aplicação:
    cada grupo contém somente entradas da Aplicação correspondente e a união
    disjunta dos grupos é igual ao conjunto total de entradas selecionadas.

    **Validates: Requirements 3.3**
    """
    grupos = agrupar_por_aplicacao(entradas)

    # 1. Cada grupo contém apenas entradas da aplicação correspondente
    for app_id, entradas_do_grupo in grupos.items():
        for entrada in entradas_do_grupo:
            assert entrada.aplicacao == app_id, (
                f"Entrada com aplicacao='{entrada.aplicacao}' encontrada no grupo "
                f"de '{app_id}'."
            )

    # 2. A união de todos os grupos é igual ao conjunto total de entradas
    total_nos_grupos = sum(len(g) for g in grupos.values())
    assert total_nos_grupos == len(entradas), (
        f"Total nos grupos ({total_nos_grupos}) difere do total de entradas "
        f"({len(entradas)}). Entradas perdidas ou duplicadas."
    )

    # 3. Nenhuma entrada aparece em múltiplos grupos (partição disjunta)
    # Verificado usando identidade de objeto (id)
    ids_vistos: set[int] = set()
    for entradas_do_grupo in grupos.values():
        for entrada in entradas_do_grupo:
            obj_id = id(entrada)
            assert obj_id not in ids_vistos, (
                f"Entrada duplicada detectada em múltiplos grupos: {entrada}"
            )
            ids_vistos.add(obj_id)

    # 4. Todas as entradas originais estão presentes nos grupos
    ids_entrada = set(id(e) for e in entradas)
    assert ids_vistos == ids_entrada, (
        "Os elementos nos grupos não coincidem com os elementos de entrada."
    )

    # 5. Se a lista de entrada é vazia, o resultado deve ser um dicionário vazio
    if len(entradas) == 0:
        assert grupos == {}, (
            "Para lista vazia, o agrupamento deve retornar dicionário vazio."
        )
