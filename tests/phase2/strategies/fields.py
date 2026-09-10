"""Strategies para campos e valores opacos sintéticos."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Final, Iterable

from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy

from .common import (
    assert_no_raw_source_reference,
    is_synthetic_token,
    is_typed_placeholder,
)

DEFAULT_PLACEHOLDER_PREFIXES: Final = (
    "CALL_ID",
    "UUID",
    "TELEFONE",
    "DOCUMENTO",
    "IP",
    "HOST_INTERNO",
    "URL_INTERNA",
    "CREDENCIAL",
    "DADO_CLIENTE",
)
_PREFIX_RE: Final = re.compile(r"^[A-Z][A-Z0-9_]*$")
_FIELD_NAME_RE: Final = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


def _validated_prefix(prefix: str) -> str:
    normalized = prefix.upper()
    if not _PREFIX_RE.fullmatch(normalized):
        raise ValueError("prefixo sintético inválido")
    return normalized


@dataclass(frozen=True)
class OpaqueField:
    """Campo sem semântica de produção, com valor comprovadamente sintético."""

    name: str
    value: str

    def __post_init__(self) -> None:
        if not _FIELD_NAME_RE.fullmatch(self.name):
            raise ValueError("nome de campo sintético inválido")
        if not (is_synthetic_token(self.value) or is_typed_placeholder(self.value)):
            raise ValueError("valor opaco deve ser sintético ou placeholder tipado")
        assert_no_raw_source_reference((self.name, self.value))


def opaque_values(
    prefix: str = "OPAQUE",
    *,
    min_bytes: int = 4,
    max_bytes: int = 16,
) -> SearchStrategy[str]:
    """Gera tokens ASCII opacos marcados por ``SYN_`` em tempo de teste."""

    safe_prefix = _validated_prefix(prefix)
    if min_bytes < 1 or max_bytes < min_bytes:
        raise ValueError("limites de bytes inválidos")
    return st.binary(min_size=min_bytes, max_size=max_bytes).map(
        lambda payload: f"SYN_{safe_prefix}_{payload.hex().upper()}"
    )


def typed_placeholders(
    prefixes: Iterable[str] | None = None,
    *,
    min_index: int = 1,
    max_index: int = 999,
) -> SearchStrategy[str]:
    """Gera placeholders tipados, sem qualquer valor de origem embutido."""

    selected = tuple(
        _validated_prefix(prefix)
        for prefix in (prefixes or DEFAULT_PLACEHOLDER_PREFIXES)
    )
    if not selected:
        raise ValueError("ao menos um tipo de placeholder é necessário")
    if min_index < 1 or max_index < min_index:
        raise ValueError("intervalo de índice inválido")
    return st.tuples(
        st.sampled_from(selected),
        st.integers(min_value=min_index, max_value=max_index),
    ).map(lambda item: f"<{item[0]}_{item[1]}>")


def opaque_fields(
    field_names: Iterable[str] | None = None,
    *,
    placeholder_prefixes: Iterable[str] | None = None,
) -> SearchStrategy[OpaqueField]:
    """Gera um campo opaco cujo valor nunca deriva de fixture ou arquivo local."""

    if field_names is None:
        names: SearchStrategy[str] = opaque_values("FIELD").map(
            lambda token: token.removeprefix("SYN_")
        )
    else:
        selected_names = tuple(field_names)
        if not selected_names or any(
            not _FIELD_NAME_RE.fullmatch(name) for name in selected_names
        ):
            raise ValueError("nomes de campo inválidos")
        names = st.sampled_from(selected_names)

    values = st.one_of(
        opaque_values("OPAQUE"),
        typed_placeholders(placeholder_prefixes),
    )
    return st.builds(OpaqueField, name=names, value=values)


def opaque_mappings(
    *,
    min_size: int = 0,
    max_size: int = 8,
) -> SearchStrategy[dict[str, str]]:
    """Gera mapeamentos pequenos com nomes únicos e valores opacos seguros."""

    if min_size < 0 or max_size < min_size:
        raise ValueError("limites de mapeamento inválidos")
    return st.lists(
        opaque_fields(),
        min_size=min_size,
        max_size=max_size,
        unique_by=lambda field: field.name,
    ).map(lambda items: {item.name: item.value for item in items})
