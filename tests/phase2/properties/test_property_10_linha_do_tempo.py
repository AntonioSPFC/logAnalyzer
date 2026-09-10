"""Property 10: partição total e determinística da linha do tempo."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy

from log_analyzer.core.modelos import EntradaDeLog, FalhaDeEntrada, Proveniencia
from log_analyzer.core.ordenacao import particionar_linha_do_tempo

_ChaveUtc = tuple[int, int, str, int]
_EspecificacaoSemUtc = tuple[str, str, int, int]

_BASE_UTC = datetime(2030, 1, 1, tzinfo=timezone.utc)
_APLICACOES = ("ORK", "VPL")

_CHAVES_UTC: SearchStrategy[_ChaveUtc] = st.tuples(
    st.integers(min_value=0, max_value=4),
    st.sampled_from((0, 1, 123456, 999999)),
    st.sampled_from(_APLICACOES),
    st.integers(min_value=0, max_value=8),
)
_ESPECIFICACOES_SEM_UTC: SearchStrategy[_EspecificacaoSemUtc] = st.tuples(
    st.sampled_from(_APLICACOES),
    st.sampled_from(("<ARQUIVO_1>", "<ARQUIVO_2>")),
    st.integers(min_value=1, max_value=8),
    st.integers(min_value=0, max_value=8),
)


def _criar_entrada_com_utc(chave: _ChaveUtc, indice: int) -> EntradaDeLog:
    segundos, microssegundos, aplicacao, ordem = chave
    timestamp_utc = _BASE_UTC + timedelta(
        seconds=segundos,
        microseconds=microssegundos,
    )
    texto = f"EVENTO_SINTETICO_COM_UTC_{indice}"
    return EntradaDeLog(
        texto_original=texto,
        aplicacao=aplicacao,
        ordem_de_leitura=ordem,
        interpretada=True,
        carimbo_de_tempo=timestamp_utc,
        nivel_de_severidade="INFO",
        mensagem=texto,
        entrada_id=f"property-10-entry-{indice}",
        arquivo_token="<ARQUIVO_UTC_1>",
        posicao_inicial=indice + 1,
        posicao_final=indice + 1,
        timestamp_original=timestamp_utc.isoformat(),
        timestamp_normalizado=timestamp_utc,
    )


def _criar_entrada_sem_utc(
    especificacao: _EspecificacaoSemUtc,
    indice: int,
) -> EntradaDeLog:
    aplicacao, arquivo_token, posicao, ordem = especificacao
    entrada_id = f"property-10-entry-{indice}"
    proveniencia = Proveniencia(
        arquivo_token=arquivo_token,
        entrada_id=entrada_id,
        linha_inicial=posicao,
        linha_final=posicao,
        nome_campo="timestamp",
        regra_extracao="property-10-synthetic-time",
    )
    falha = FalhaDeEntrada(
        codigo="TIMESTAMP_NAO_RESOLVIDO",
        proveniencia=proveniencia,
        detalhe_seguro="Timestamp sintético não pôde ser normalizado.",
    )
    texto = f"EVENTO_SINTETICO_SEM_UTC_{indice}"
    return EntradaDeLog(
        texto_original=texto,
        aplicacao=aplicacao,
        ordem_de_leitura=ordem,
        interpretada=True,
        carimbo_de_tempo=datetime(2030, 1, 1),
        nivel_de_severidade="INFO",
        mensagem=texto,
        entrada_id=entrada_id,
        arquivo_token=arquivo_token,
        posicao_inicial=posicao,
        posicao_final=posicao,
        timestamp_original="SYN_TIMESTAMP_NAO_RESOLVIDO",
        timestamp_normalizado=None,
        falhas=(falha,),
    )


@st.composite
def _colecoes_temporais(
    draw: st.DrawFn,
) -> tuple[EntradaDeLog, ...]:
    """Gera ambas as partições e força empates e ocorrências repetidas."""

    segundo_compartilhado = draw(st.integers(min_value=0, max_value=4))
    microssegundo_compartilhado = draw(
        st.sampled_from((0, 1, 123456, 999999))
    )
    aplicacao_compartilhada = draw(st.sampled_from(_APLICACOES))
    ordens_distintas = sorted(
        draw(
            st.lists(
                st.integers(min_value=0, max_value=8),
                min_size=2,
                max_size=2,
                unique=True,
            )
        )
    )
    outra_aplicacao = (
        "VPL" if aplicacao_compartilhada == "ORK" else "ORK"
    )
    chave_duplicada = (
        segundo_compartilhado,
        microssegundo_compartilhado,
        aplicacao_compartilhada,
        ordens_distintas[0],
    )
    chaves_utc = [
        chave_duplicada,
        chave_duplicada,
        (
            segundo_compartilhado,
            microssegundo_compartilhado,
            aplicacao_compartilhada,
            ordens_distintas[1],
        ),
        (
            segundo_compartilhado,
            microssegundo_compartilhado,
            outra_aplicacao,
            ordens_distintas[0],
        ),
        *draw(st.lists(_CHAVES_UTC, min_size=0, max_size=8)),
    ]

    especificacao_duplicada = draw(_ESPECIFICACOES_SEM_UTC)
    especificacoes_sem_utc = [
        especificacao_duplicada,
        especificacao_duplicada,
        *draw(
            st.lists(
                _ESPECIFICACOES_SEM_UTC,
                min_size=0,
                max_size=6,
            )
        ),
    ]

    entradas: list[EntradaDeLog] = []
    for chave in chaves_utc:
        entradas.append(_criar_entrada_com_utc(chave, len(entradas)))
    for especificacao in especificacoes_sem_utc:
        entradas.append(_criar_entrada_sem_utc(especificacao, len(entradas)))

    return tuple(draw(st.permutations(entradas)))


_COLECOES_TEMPORAIS: SearchStrategy[tuple[EntradaDeLog, ...]] = (
    _colecoes_temporais()
)


def _chave_temporal(entrada: EntradaDeLog) -> tuple[datetime, str, int]:
    assert entrada.timestamp_normalizado is not None
    return (
        entrada.timestamp_normalizado,
        entrada.aplicacao,
        entrada.ordem_de_leitura,
    )


def _chave_sem_utc(entrada: EntradaDeLog) -> tuple[str, str, int]:
    assert entrada.arquivo_token is not None
    assert entrada.posicao_inicial is not None
    return (
        entrada.aplicacao,
        entrada.arquivo_token,
        entrada.posicao_inicial,
    )


# Feature: log-analyzer-phase-2, Property 10: Linha do tempo é uma partição total e determinística
@given(entradas_geradas=_COLECOES_TEMPORAIS)
@settings(max_examples=100)
def test_property_10_linha_do_tempo_e_particao_total_e_deterministica(
    entradas_geradas: tuple[EntradaDeLog, ...],
) -> None:
    """A partição preserva ocorrências e aplica a chave temporal total.

    **Validates: Requirements 6.5, 6.6, 6.7, 15.5**
    """

    entradas = list(entradas_geradas)
    identidade_original = tuple(id(entrada) for entrada in entradas)

    linha_do_tempo, sem_ordenacao_temporal = particionar_linha_do_tempo(
        entradas
    )
    linha_repetida, sem_utc_repetidas = particionar_linha_do_tempo(entradas)

    ids_timeline = tuple(id(entrada) for entrada in linha_do_tempo)
    ids_sem_utc = tuple(id(entrada) for entrada in sem_ordenacao_temporal)
    assert set(ids_timeline).isdisjoint(ids_sem_utc)
    assert Counter((*ids_timeline, *ids_sem_utc)) == Counter(
        identidade_original
    )
    assert len(linha_do_tempo) + len(sem_ordenacao_temporal) == len(entradas)
    assert tuple(id(entrada) for entrada in entradas) == identidade_original

    esperado_timeline = sorted(
        (
            entrada
            for entrada in entradas
            if entrada.timestamp_normalizado is not None
        ),
        key=_chave_temporal,
    )
    esperado_sem_utc = sorted(
        (
            entrada
            for entrada in entradas
            if entrada.timestamp_normalizado is None
        ),
        key=_chave_sem_utc,
    )
    assert ids_timeline == tuple(id(entrada) for entrada in esperado_timeline)
    assert ids_sem_utc == tuple(id(entrada) for entrada in esperado_sem_utc)
    assert [_chave_temporal(entrada) for entrada in linha_do_tempo] == sorted(
        _chave_temporal(entrada) for entrada in linha_do_tempo
    )

    chaves_utc_entrada = Counter(
        _chave_temporal(entrada)
        for entrada in entradas
        if entrada.timestamp_normalizado is not None
    )
    chaves_utc_saida = Counter(
        _chave_temporal(entrada) for entrada in linha_do_tempo
    )
    chaves_sem_utc_entrada = Counter(
        _chave_sem_utc(entrada)
        for entrada in entradas
        if entrada.timestamp_normalizado is None
    )
    chaves_sem_utc_saida = Counter(
        _chave_sem_utc(entrada) for entrada in sem_ordenacao_temporal
    )
    assert chaves_utc_saida == chaves_utc_entrada
    assert chaves_sem_utc_saida == chaves_sem_utc_entrada
    assert max(chaves_utc_entrada.values()) >= 2
    assert max(chaves_sem_utc_entrada.values()) >= 2

    assert all(
        entrada.timestamp_normalizado is not None
        for entrada in linha_do_tempo
    )
    assert all(
        entrada.timestamp_normalizado is None
        and len(entrada.falhas) == 1
        and entrada.falhas[0].codigo == "TIMESTAMP_NAO_RESOLVIDO"
        for entrada in sem_ordenacao_temporal
    )
    assert tuple(id(entrada) for entrada in linha_repetida) == ids_timeline
    assert tuple(id(entrada) for entrada in sem_utc_repetidas) == ids_sem_utc
