"""Testes unitários da partição temporal aditiva da Fase 2.

Os casos usam somente entradas sintéticas e mantêm o wrapper legado coberto por
``tests/test_ordenacao.py`` e pela caracterização da Fase 1.

Validates: Requirements 1.4, 6.5, 6.6, 6.7, 15.5, 16.1.
"""

from datetime import datetime, timezone

from log_analyzer.core.modelos import EntradaDeLog
from log_analyzer.core.ordenacao import particionar_linha_do_tempo


def _entrada(
    *,
    texto: str,
    aplicacao: str,
    ordem: int,
    carimbo: datetime,
    timestamp_normalizado: datetime | None,
    arquivo_token: str | None = "<ARQUIVO_1>",
    posicao_inicial: int | None = 1,
) -> EntradaDeLog:
    return EntradaDeLog(
        texto_original=texto,
        aplicacao=aplicacao,
        ordem_de_leitura=ordem,
        interpretada=True,
        carimbo_de_tempo=carimbo,
        nivel_de_severidade="INFO",
        mensagem=texto,
        entrada_id=f"{aplicacao}:{ordem}:{texto}",
        arquivo_token=arquivo_token,
        posicao_inicial=posicao_inicial,
        posicao_final=posicao_inicial,
        timestamp_original="2024-01-01T00:00:00",
        timestamp_normalizado=timestamp_normalizado,
    )


def test_particiona_e_ordena_utc_por_chave_total_sem_mutar_entrada() -> None:
    instante = datetime(2024, 1, 1, 12, tzinfo=timezone.utc)
    ork_ordem_2 = _entrada(
        texto="ork 2",
        aplicacao="ORK",
        ordem=2,
        carimbo=datetime(2024, 1, 1, 9),
        timestamp_normalizado=instante,
        posicao_inicial=2,
    )
    vpl = _entrada(
        texto="vpl",
        aplicacao="VPL",
        ordem=0,
        carimbo=datetime(2024, 1, 1, 9),
        timestamp_normalizado=instante,
        posicao_inicial=3,
    )
    ork_ordem_1 = _entrada(
        texto="ork 1",
        aplicacao="ORK",
        ordem=1,
        carimbo=datetime(2024, 1, 1, 9),
        timestamp_normalizado=instante,
        posicao_inicial=1,
    )
    sem_utc = _entrada(
        texto="sem utc",
        aplicacao="ORK",
        ordem=3,
        carimbo=datetime(2024, 1, 1, 8),
        timestamp_normalizado=None,
        posicao_inicial=4,
    )
    entradas = [sem_utc, vpl, ork_ordem_2, ork_ordem_1]
    snapshot = list(entradas)

    linha_do_tempo, fora_da_cronologia = particionar_linha_do_tempo(entradas)

    assert linha_do_tempo == [ork_ordem_1, ork_ordem_2, vpl]
    assert fora_da_cronologia == [sem_utc]
    assert entradas == snapshot
    assert linha_do_tempo is not entradas
    assert fora_da_cronologia is not entradas


def test_usa_timestamp_normalizado_em_vez_do_carimbo_legado() -> None:
    utc_anterior = _entrada(
        texto="utc anterior",
        aplicacao="VPL",
        ordem=0,
        carimbo=datetime(2024, 1, 2),
        timestamp_normalizado=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    utc_posterior = _entrada(
        texto="utc posterior",
        aplicacao="VPL",
        ordem=1,
        carimbo=datetime(2024, 1, 1),
        timestamp_normalizado=datetime(2024, 1, 2, tzinfo=timezone.utc),
        posicao_inicial=2,
    )

    linha_do_tempo, fora_da_cronologia = particionar_linha_do_tempo(
        [utc_posterior, utc_anterior]
    )

    assert linha_do_tempo == [utc_anterior, utc_posterior]
    assert fora_da_cronologia == []


def test_sem_utc_usa_ordem_de_apresentacao_e_estabilidade() -> None:
    carimbo = datetime(2024, 1, 1)
    ork_a_primeira = _entrada(
        texto="ork a primeira",
        aplicacao="ORK",
        ordem=20,
        carimbo=carimbo,
        timestamp_normalizado=None,
        arquivo_token="<ARQUIVO_A>",
        posicao_inicial=5,
    )
    ork_a_segunda = _entrada(
        texto="ork a segunda",
        aplicacao="ORK",
        ordem=1,
        carimbo=carimbo,
        timestamp_normalizado=None,
        arquivo_token="<ARQUIVO_A>",
        posicao_inicial=5,
    )
    ork_b = _entrada(
        texto="ork b",
        aplicacao="ORK",
        ordem=0,
        carimbo=carimbo,
        timestamp_normalizado=None,
        arquivo_token="<ARQUIVO_B>",
        posicao_inicial=1,
    )
    vpl = _entrada(
        texto="vpl",
        aplicacao="VPL",
        ordem=0,
        carimbo=carimbo,
        timestamp_normalizado=None,
        arquivo_token="<ARQUIVO_A>",
        posicao_inicial=1,
    )

    linha_do_tempo, fora_da_cronologia = particionar_linha_do_tempo(
        [vpl, ork_b, ork_a_primeira, ork_a_segunda]
    )

    assert linha_do_tempo == []
    assert fora_da_cronologia == [
        ork_a_primeira,
        ork_a_segunda,
        ork_b,
        vpl,
    ]


def test_sem_metadados_de_origem_preserva_ordem_relativa() -> None:
    carimbo = datetime(2024, 1, 1)
    primeira = _entrada(
        texto="primeira",
        aplicacao="ORK",
        ordem=9,
        carimbo=carimbo,
        timestamp_normalizado=None,
        arquivo_token=None,
        posicao_inicial=None,
    )
    segunda = _entrada(
        texto="segunda",
        aplicacao="ORK",
        ordem=0,
        carimbo=carimbo,
        timestamp_normalizado=None,
        arquivo_token=None,
        posicao_inicial=None,
    )

    _, fora_da_cronologia = particionar_linha_do_tempo([primeira, segunda])

    assert fora_da_cronologia == [primeira, segunda]
