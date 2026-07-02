"""Testes de propriedade para a correlação VPL ↔ ORK.

Feature: log-analyzer
"""

from __future__ import annotations

from datetime import datetime

from hypothesis import given, settings
from hypothesis import strategies as st

from log_analyzer.core.correlacao import correlacionar_vpl_ork
from log_analyzer.core.modelos import EntradaDeLog


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Texto original não vazio para entradas de log
_texto_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z"), min_codepoint=32),
    min_size=1,
    max_size=100,
)

# Identificador válido (1–256 caracteres, não apenas espaços)
_identificador_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P"), min_codepoint=48),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip() != "")

# Timestamp para entradas interpretadas
_timestamp_strategy = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
)

# Severidade
_severidade_strategy = st.sampled_from(["INFO", "WARNING", "ERROR", "DEBUG"])

# Mensagem não vazia
_mensagem_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z"), min_codepoint=32),
    min_size=1,
    max_size=80,
)


@st.composite
def _entrada_de_log(draw: st.DrawFn, aplicacao: str) -> EntradaDeLog:
    """Gera uma EntradaDeLog para a aplicação fornecida (interpretada ou não)."""
    interpretada = draw(st.booleans())
    texto = draw(_texto_strategy)
    ordem = draw(st.integers(min_value=0, max_value=10000))

    if interpretada:
        return EntradaDeLog(
            texto_original=texto,
            aplicacao=aplicacao,
            ordem_de_leitura=ordem,
            interpretada=True,
            carimbo_de_tempo=draw(_timestamp_strategy),
            nivel_de_severidade=draw(_severidade_strategy),
            mensagem=draw(_mensagem_strategy),
        )
    return EntradaDeLog(
        texto_original=texto,
        aplicacao=aplicacao,
        ordem_de_leitura=ordem,
        interpretada=False,
    )


# Listas de entradas VPL e ORK
_entradas_vpl_strategy = st.lists(_entrada_de_log("VPL"), min_size=0, max_size=10)
_entradas_ork_strategy = st.lists(_entrada_de_log("ORK"), min_size=0, max_size=10)


# ---------------------------------------------------------------------------
# Property 14: Correlação VPL ↔ ORK marca exatamente os Identificadores compartilhados
# ---------------------------------------------------------------------------


@given(
    entradas_vpl=_entradas_vpl_strategy,
    entradas_ork=_entradas_ork_strategy,
    identificador=_identificador_strategy,
)
@settings(max_examples=100)
def test_property_14_correlacao_vpl_ork_marca_identificadores_compartilhados(
    entradas_vpl: list[EntradaDeLog],
    entradas_ork: list[EntradaDeLog],
    identificador: str,
) -> None:
    """Feature: log-analyzer, Property 14: Correlação VPL ↔ ORK marca exatamente os Identificadores compartilhados

    Para todo conjunto de EntradaDeLog de VPL e ORK, uma entrada é marcada como
    correlacionada=True se e somente se existe uma entrada da outra Aplicação que
    compartilha o mesmo Identificador; quando nenhum Identificador é compartilhado,
    correlacao_encontrada é False e todas as entradas são preservadas sem alteração.

    **Validates: Requirements 8.3, 8.4**
    """
    vpl_out, ork_out, correlacao_encontrada, erros = correlacionar_vpl_ork(
        entradas_vpl, entradas_ork, identificador
    )

    # --- Caso 1: Ambas as listas não vazias ---
    if entradas_vpl and entradas_ork:
        # Todas as entradas devem ser marcadas como correlacionada=True
        assert correlacao_encontrada is True, (
            "correlacao_encontrada deveria ser True quando ambos os lados possuem entradas."
        )
        assert all(e.correlacionada for e in vpl_out), (
            "Todas as entradas VPL devem ser marcadas como correlacionada=True."
        )
        assert all(e.correlacionada for e in ork_out), (
            "Todas as entradas ORK devem ser marcadas como correlacionada=True."
        )
        # Quantidade de entradas preservada
        assert len(vpl_out) == len(entradas_vpl)
        assert len(ork_out) == len(entradas_ork)
        # Sem erros
        assert erros == []

    # --- Caso 2: Ambas as listas vazias ---
    elif not entradas_vpl and not entradas_ork:
        assert correlacao_encontrada is False, (
            "correlacao_encontrada deveria ser False quando ambos os lados estão vazios."
        )
        assert vpl_out == []
        assert ork_out == []
        assert erros == []

    # --- Caso 3: Apenas um lado possui entradas ---
    else:
        assert correlacao_encontrada is False, (
            "correlacao_encontrada deveria ser False quando apenas um lado possui entradas."
        )
        # Deve haver exatamente um erro identificando o lado indisponível
        assert len(erros) == 1

        if not entradas_vpl:
            # VPL indisponível: erro referencia VPL, entradas ORK preservadas sem alteração
            assert erros[0].arquivo_ou_app == "VPL"
            assert ork_out == list(entradas_ork)
            assert all(not e.correlacionada for e in ork_out), (
                "Entradas ORK não devem ser marcadas como correlacionadas quando VPL ausente."
            )
        else:
            # ORK indisponível: erro referencia ORK, entradas VPL preservadas sem alteração
            assert erros[0].arquivo_ou_app == "ORK"
            assert vpl_out == list(entradas_vpl)
            assert all(not e.correlacionada for e in vpl_out), (
                "Entradas VPL não devem ser marcadas como correlacionadas quando ORK ausente."
            )

    # --- Invariante transversal: texto_original sempre preservado ---
    for original, resultado in zip(entradas_vpl, vpl_out):
        assert resultado.texto_original == original.texto_original, (
            "texto_original de entrada VPL não foi preservado após correlação."
        )
    for original, resultado in zip(entradas_ork, ork_out):
        assert resultado.texto_original == original.texto_original, (
            "texto_original de entrada ORK não foi preservado após correlação."
        )
