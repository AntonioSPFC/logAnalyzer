"""Testes focados da normalização temporal por perfil.

Todos os timestamps são sintéticos e construídos diretamente no teste.

Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.7, 6.8.
"""

from datetime import datetime, timezone

import pytest

from log_analyzer.core.modelos import EntradaDeLog, Proveniencia
from log_analyzer.core.temporal import NormalizadorTemporal


def _proveniencia() -> Proveniencia:
    return Proveniencia(
        arquivo_token="<ARQUIVO_1>",
        entrada_id="entrada-sintetica-1",
        linha_inicial=1,
        linha_final=1,
        nome_campo="timestamp",
        regra_extracao="temporal-sintetica-v1",
    )


def test_vpl_e_ork_do_mesmo_instante_produzem_o_mesmo_utc() -> None:
    normalizador = NormalizadorTemporal()
    proveniencia = _proveniencia()

    vpl = normalizador.normalizar_vpl(
        "2030-02-03 04:05:06.007",
        proveniencia,
    )
    ork = normalizador.normalizar_ork(
        "2030-02-03T09:05:06.007+02:00",
        proveniencia,
    )

    esperado = datetime(2030, 2, 3, 7, 5, 6, 7000, tzinfo=timezone.utc)
    assert vpl.timestamp_normalizado == esperado
    assert ork.timestamp_normalizado == esperado
    assert vpl.timestamp_original == "2030-02-03 04:05:06.007"
    assert ork.timestamp_original == "2030-02-03T09:05:06.007+02:00"
    assert vpl.precisao_fracionaria == ork.precisao_fracionaria == 3
    assert vpl.timestamp_normalizado_texto == "2030-02-03T07:05:06.007+00:00"
    assert ork.timestamp_normalizado_texto == "2030-02-03T07:05:06.007+00:00"
    assert vpl.falhas == ork.falhas == ()


@pytest.mark.parametrize("precisao", range(7))
def test_ork_preserva_cada_precisao_suportada(precisao: int) -> None:
    digitos = "123456"[:precisao]
    fracao = f".{digitos}" if digitos else ""
    original = f"2031-04-05T06:07:08{fracao}Z"

    resultado = NormalizadorTemporal().normalizar(
        "ORK",
        original,
        _proveniencia(),
    )

    assert resultado.resolvido
    assert resultado.precisao_fracionaria == precisao
    assert resultado.timestamp_original == original
    assert resultado.timestamp_normalizado_texto == (
        f"2031-04-05T06:07:08{fracao}+00:00"
    )


@pytest.mark.parametrize(
    ("original", "codigo"),
    (
        (
            "2018-11-04 00:30:00",
            NormalizadorTemporal.CODIGO_HORARIO_INEXISTENTE,
        ),
        (
            "2018-02-17 23:30:00",
            NormalizadorTemporal.CODIGO_HORARIO_AMBIGUO,
        ),
    ),
    ids=("inexistente", "ambiguo"),
)
def test_vpl_rejeita_transicoes_sem_escolher_fold(
    original: str,
    codigo: str,
) -> None:
    resultado = NormalizadorTemporal().normalizar_vpl(
        original,
        _proveniencia(),
    )

    assert not resultado.resolvido
    assert resultado.timestamp_original == original
    assert resultado.timestamp_normalizado is None
    assert resultado.precisao_fracionaria == 0
    assert resultado.falha is not None
    assert resultado.falha.codigo == codigo
    assert original not in resultado.falha.detalhe_seguro


@pytest.mark.parametrize(
    "aplicacao, original",
    (
        ("VPL", "2030-02-03 04:05:06.1234567"),
        ("ORK", "2030-02-03T04:05:06.1234567-03:00"),
    ),
)
def test_precisao_maior_que_seis_falha_sem_truncar(
    aplicacao: str,
    original: str,
) -> None:
    resultado = NormalizadorTemporal().normalizar(
        aplicacao,
        original,
        _proveniencia(),
    )

    assert resultado.timestamp_original == original
    assert resultado.timestamp_normalizado is None
    assert resultado.precisao_fracionaria is None
    assert resultado.falha is not None
    assert (
        resultado.falha.codigo
        == NormalizadorTemporal.CODIGO_PRECISAO_NAO_SUPORTADA
    )
    assert original not in resultado.falha.detalhe_seguro


def test_ork_sem_offset_retorna_falha_segura() -> None:
    original = "2030-02-03T04:05:06.123456"
    resultado = NormalizadorTemporal().normalizar_ork(
        original,
        _proveniencia(),
    )

    assert resultado.timestamp_original == original
    assert resultado.timestamp_normalizado is None
    assert resultado.falha is not None
    assert resultado.falha.codigo == NormalizadorTemporal.CODIGO_OFFSET_AUSENTE
    assert original not in resultado.falha.detalhe_seguro


def test_metadados_aditivos_nao_alteram_carimbo_de_tempo_legado() -> None:
    normalizado = NormalizadorTemporal().normalizar_vpl(
        "2030-02-03 04:05:06",
        _proveniencia(),
    )
    carimbo_legado = datetime(2030, 2, 3, 4, 5, 6)

    entrada = EntradaDeLog(
        texto_original="evento temporal sintético",
        aplicacao="VPL",
        ordem_de_leitura=0,
        interpretada=True,
        carimbo_de_tempo=carimbo_legado,
        nivel_de_severidade="INFO",
        mensagem="evento temporal sintético",
        entrada_id="entrada-sintetica-1",
        arquivo_token="<ARQUIVO_1>",
        posicao_inicial=1,
        posicao_final=1,
        timestamp_original=normalizado.timestamp_original,
        timestamp_normalizado=normalizado.timestamp_normalizado,
        precisao_fracionaria=normalizado.precisao_fracionaria,
        falhas=normalizado.falhas,
    )

    assert entrada.carimbo_de_tempo is carimbo_legado
    assert entrada.timestamp_normalizado == datetime(
        2030,
        2,
        3,
        7,
        5,
        6,
        tzinfo=timezone.utc,
    )
