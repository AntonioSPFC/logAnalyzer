"""Teste de propriedade: Classificação na Fase 1 é uma categoria válida e "não classificada".

Feature: log-analyzer, Property 10: Classificação na Fase 1 é uma categoria válida e "não classificada"

**Validates: Requirements 5.3, 5.4, 6.6**

Para toda EntradaDeLog de qualquer Aplicação inicial (VPL, ORK, VOCI), o Padrao_de_Analise
retorna exatamente uma categoria pertencente ao seu conjunto `categorias` e, na Fase 1, essa
categoria é sempre NAO_CLASSIFICADA.
"""

from hypothesis import given, settings
from hypothesis import strategies as st
from datetime import datetime, timezone

from log_analyzer.core.modelos import Categoria, EntradaDeLog
from log_analyzer.apps.padroes import VplPadrao, OrkPadrao, VociPadrao


# --- Strategy para gerar EntradaDeLog arbitrárias ---

_aplicacoes = st.sampled_from(["VPL", "ORK", "VOCI"])

_texto_original = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"),
        blacklist_characters="\x00",
    ),
    min_size=1,
    max_size=200,
)

_ordem_de_leitura = st.integers(min_value=0, max_value=100_000)

_timestamps = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(2099, 12, 31),
    timezones=st.just(timezone.utc) | st.none(),
)

_niveis = st.sampled_from([
    "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL",
    "NOTICE", "WARN", "FATAL", "ERR", "CRIT", "ALERT",
])

_mensagens = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"),
        blacklist_characters="\x00",
    ),
    min_size=1,
    max_size=100,
).filter(lambda s: s.strip() != "")


@st.composite
def entrada_de_log_interpretada(draw):
    """Gera uma EntradaDeLog interpretada (com campos obrigatórios preenchidos)."""
    app = draw(_aplicacoes)
    texto = draw(_texto_original)
    ordem = draw(_ordem_de_leitura)
    ts = draw(_timestamps)
    nivel = draw(_niveis)
    msg = draw(_mensagens)

    return EntradaDeLog(
        texto_original=texto,
        aplicacao=app,
        ordem_de_leitura=ordem,
        interpretada=True,
        carimbo_de_tempo=ts,
        nivel_de_severidade=nivel,
        mensagem=msg,
    )


@st.composite
def entrada_de_log_nao_interpretada(draw):
    """Gera uma EntradaDeLog não interpretada (campos opcionais são None)."""
    app = draw(_aplicacoes)
    texto = draw(_texto_original)
    ordem = draw(_ordem_de_leitura)

    return EntradaDeLog(
        texto_original=texto,
        aplicacao=app,
        ordem_de_leitura=ordem,
        interpretada=False,
    )


# Strategy que gera ambos os tipos de entradas
_entrada_de_log = st.one_of(
    entrada_de_log_interpretada(),
    entrada_de_log_nao_interpretada(),
)


# --- Teste de propriedade ---

@settings(max_examples=100)
@given(entrada=_entrada_de_log)
def test_classificacao_fase1_categoria_valida_e_nao_classificada(entrada: EntradaDeLog):
    """Property 10: Classificação na Fase 1 é uma categoria válida e "não classificada".

    Feature: log-analyzer, Property 10: Classificação na Fase 1 é uma categoria válida e "não classificada"

    Para toda EntradaDeLog de qualquer Aplicação inicial (VPL, ORK, VOCI), o Padrao_de_Analise
    retorna exatamente uma categoria pertencente ao seu conjunto `categorias` e, na Fase 1,
    essa categoria é sempre NAO_CLASSIFICADA.

    **Validates: Requirements 5.3, 5.4, 6.6**
    """
    padroes = [VplPadrao(), OrkPadrao(), VociPadrao()]

    for padrao in padroes:
        resultado = padrao.classificar(entrada)

        # A categoria retornada deve ser NAO_CLASSIFICADA na Fase 1
        assert resultado == Categoria.NAO_CLASSIFICADA, (
            f"{padrao.__class__.__name__}.classificar() retornou {resultado} "
            f"em vez de NAO_CLASSIFICADA para entrada: {entrada.texto_original!r}"
        )

        # A categoria retornada deve pertencer ao conjunto `categorias` do padrão
        assert resultado in padrao.categorias, (
            f"{padrao.__class__.__name__}.classificar() retornou {resultado} "
            f"que não pertence a categorias={padrao.categorias}"
        )
