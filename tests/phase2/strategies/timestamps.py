"""Strategies de timestamps sintéticos VPL e ORK."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy

VPL_TIMEZONE_NAME = "America/Sao_Paulo"
# O Brasil não observa horário de verão desde 2019. Restringir o builder a
# 2020–2024 mantém os casos historicamente resolvíveis e evita exigir o pacote
# opcional tzdata em ambientes Windows de teste.
_VPL_POST_DST_TIMEZONE = timezone(
    timedelta(hours=-3),
    name=VPL_TIMEZONE_NAME,
)


class TimestampProfile(str, Enum):
    VPL_LOCAL = "vpl_local"
    ORK_OFFSET = "ork_offset"


@dataclass(frozen=True)
class TimestampSpec:
    """Representação gerada e seu instante UTC esperado."""

    profile: TimestampProfile
    original: str
    source_datetime: datetime
    expected_utc: datetime
    precision: int
    offset_minutes: int | None

    def __post_init__(self) -> None:
        if not 0 <= self.precision <= 6:
            raise ValueError("precisão temporal fora do intervalo suportado")
        if self.expected_utc.tzinfo is None:
            raise ValueError("instante esperado deve ser timezone-aware")
        if self.expected_utc.utcoffset() != timedelta(0):
            raise ValueError("instante esperado deve estar em UTC")


def _fraction_and_microsecond(precision: int, value: int) -> tuple[str, int]:
    if precision == 0:
        return "", 0
    digits = f"{value:0{precision}d}"
    return f".{digits}", value * (10 ** (6 - precision))


def vpl_timestamps() -> SearchStrategy[TimestampSpec]:
    """Gera horários VPL resolvíveis no fuso normativo, sem usar amostras."""

    @st.composite
    def _strategy(draw):
        generated_date = draw(
            st.dates(
                min_value=date(2020, 1, 1),
                max_value=date(2024, 12, 31),
            )
        )
        hour = draw(st.integers(min_value=0, max_value=23))
        minute = draw(st.integers(min_value=0, max_value=59))
        second = draw(st.integers(min_value=0, max_value=59))
        precision = draw(st.integers(min_value=0, max_value=6))
        fraction_value = draw(
            st.integers(min_value=0, max_value=(10**precision) - 1)
        ) if precision else 0
        fraction, microsecond = _fraction_and_microsecond(
            precision, fraction_value
        )
        local_naive = datetime(
            generated_date.year,
            generated_date.month,
            generated_date.day,
            hour,
            minute,
            second,
            microsecond,
        )
        localized = local_naive.replace(tzinfo=_VPL_POST_DST_TIMEZONE)
        original = local_naive.strftime("%Y-%m-%d %H:%M:%S") + fraction
        return TimestampSpec(
            profile=TimestampProfile.VPL_LOCAL,
            original=original,
            source_datetime=local_naive,
            expected_utc=localized.astimezone(timezone.utc),
            precision=precision,
            offset_minutes=None,
        )

    return _strategy()


def ork_timestamps() -> SearchStrategy[TimestampSpec]:
    """Gera timestamps ISO 8601 com offsets explícitos sintéticos."""

    @st.composite
    def _strategy(draw):
        generated_date = draw(
            st.dates(
                min_value=date(2020, 1, 1),
                max_value=date(2035, 12, 31),
            )
        )
        hour = draw(st.integers(min_value=0, max_value=23))
        minute = draw(st.integers(min_value=0, max_value=59))
        second = draw(st.integers(min_value=0, max_value=59))
        precision = draw(st.integers(min_value=0, max_value=6))
        fraction_value = draw(
            st.integers(min_value=0, max_value=(10**precision) - 1)
        ) if precision else 0
        fraction, microsecond = _fraction_and_microsecond(
            precision, fraction_value
        )
        offset_minutes = draw(st.integers(min_value=-48, max_value=56)) * 15
        offset = timezone(timedelta(minutes=offset_minutes))
        aware = datetime(
            generated_date.year,
            generated_date.month,
            generated_date.day,
            hour,
            minute,
            second,
            microsecond,
            tzinfo=offset,
        )
        sign = "+" if offset_minutes >= 0 else "-"
        absolute_offset = abs(offset_minutes)
        offset_text = (
            f"{sign}{absolute_offset // 60:02d}:{absolute_offset % 60:02d}"
        )
        original = aware.strftime("%Y-%m-%dT%H:%M:%S") + fraction + offset_text
        return TimestampSpec(
            profile=TimestampProfile.ORK_OFFSET,
            original=original,
            source_datetime=aware,
            expected_utc=aware.astimezone(timezone.utc),
            precision=precision,
            offset_minutes=offset_minutes,
        )

    return _strategy()


def timestamps() -> SearchStrategy[TimestampSpec]:
    """Gera casos temporais dos dois perfis da Fase 2."""

    return st.one_of(vpl_timestamps(), ork_timestamps())
