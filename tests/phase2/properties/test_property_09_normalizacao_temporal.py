"""Property 9: normalização temporal preserva instante e precisão."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from hypothesis import given, settings

from log_analyzer.core.modelos import Proveniencia
from log_analyzer.core.temporal import (
    NormalizadorTemporal,
    ResultadoNormalizacaoTemporal,
)
from tests.phase2.strategies.timestamps import (
    TimestampSpec,
    ork_timestamps,
    vpl_timestamps,
)

_FUSO_VPL = ZoneInfo(NormalizadorTemporal.FUSO_HORARIO_VPL)


def _proveniencia_sintetica() -> Proveniencia:
    return Proveniencia(
        arquivo_token="<ARQUIVO_PROPERTY_9>",
        entrada_id="entrada-property-9",
        linha_inicial=1,
        linha_final=1,
        nome_campo="timestamp",
        regra_extracao="property-09-sintetica-v1",
    )


def _formatar_utc_com_precisao(instante: datetime, precisao: int) -> str:
    assert instante.tzinfo is not None
    assert instante.utcoffset() == timedelta(0)

    texto = instante.strftime("%Y-%m-%dT%H:%M:%S")
    if precisao:
        texto += f".{instante.microsecond:06d}"[: precisao + 1]
    return f"{texto}+00:00"


def _formatar_ork_com_offset(instante: datetime, precisao: int) -> str:
    deslocamento = instante.utcoffset()
    assert deslocamento is not None

    texto = instante.strftime("%Y-%m-%dT%H:%M:%S")
    if precisao:
        texto += f".{instante.microsecond:06d}"[: precisao + 1]

    minutos = int(deslocamento.total_seconds() // 60)
    sinal = "+" if minutos >= 0 else "-"
    minutos_absolutos = abs(minutos)
    return (
        f"{texto}{sinal}{minutos_absolutos // 60:02d}:"
        f"{minutos_absolutos % 60:02d}"
    )


def _assert_normalizacao_igual_referencia(
    resultado: ResultadoNormalizacaoTemporal,
    original: str,
    esperado_utc: datetime,
    precisao: int,
) -> None:
    assert resultado.resolvido
    assert resultado.timestamp_original == original
    assert resultado.timestamp_normalizado == esperado_utc
    assert resultado.timestamp_normalizado is not None
    assert resultado.timestamp_normalizado.tzinfo is timezone.utc
    assert resultado.precisao_fracionaria == precisao
    assert resultado.timestamp_normalizado_texto == _formatar_utc_com_precisao(
        esperado_utc,
        precisao,
    )
    assert resultado.falhas == ()


# Feature: log-analyzer-phase-2, Property 9: Normalização temporal preserva o instante e a precisão
@given(vpl=vpl_timestamps(), ork=ork_timestamps())
@settings(max_examples=100)
def test_property_09_normalizacao_temporal_preserva_instante_e_precisao(
    vpl: TimestampSpec,
    ork: TimestampSpec,
) -> None:
    """Os dois perfis equivalem à referência temporal da biblioteca padrão.

    **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.8**
    """

    normalizador = NormalizadorTemporal()
    proveniencia = _proveniencia_sintetica()

    local_vpl = datetime.fromisoformat(vpl.original)
    assert local_vpl.tzinfo is None
    referencia_vpl_local = local_vpl.replace(tzinfo=_FUSO_VPL, fold=0)
    esperado_vpl_utc = referencia_vpl_local.astimezone(timezone.utc)
    assert esperado_vpl_utc.astimezone(_FUSO_VPL).replace(
        tzinfo=None,
    ) == local_vpl

    resultado_vpl = normalizador.normalizar_vpl(vpl.original, proveniencia)
    _assert_normalizacao_igual_referencia(
        resultado_vpl,
        vpl.original,
        esperado_vpl_utc,
        vpl.precision,
    )

    referencia_ork_aware = datetime.fromisoformat(ork.original)
    assert referencia_ork_aware.tzinfo is not None
    assert referencia_ork_aware.utcoffset() is not None
    esperado_ork_utc = referencia_ork_aware.astimezone(timezone.utc)

    resultado_ork = normalizador.normalizar_ork(ork.original, proveniencia)
    _assert_normalizacao_igual_referencia(
        resultado_ork,
        ork.original,
        esperado_ork_utc,
        ork.precision,
    )

    ork_do_mesmo_instante = esperado_vpl_utc.astimezone(
        referencia_ork_aware.tzinfo,
    )
    original_ork_equivalente = _formatar_ork_com_offset(
        ork_do_mesmo_instante,
        vpl.precision,
    )
    resultado_ork_equivalente = normalizador.normalizar_ork(
        original_ork_equivalente,
        proveniencia,
    )

    _assert_normalizacao_igual_referencia(
        resultado_ork_equivalente,
        original_ork_equivalente,
        esperado_vpl_utc,
        vpl.precision,
    )
    assert resultado_ork_equivalente.timestamp_normalizado == (
        resultado_vpl.timestamp_normalizado
    )
