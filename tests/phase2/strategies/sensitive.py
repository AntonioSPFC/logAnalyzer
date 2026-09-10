"""Dados sensíveis de teste gerados em faixas e namespaces sintéticos."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from ipaddress import ip_address, ip_network
import re
from typing import Final, Iterable
from urllib.parse import urlparse
from uuid import UUID

from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy

from .common import assert_no_raw_source_reference, is_typed_placeholder
from .fields import opaque_values


class SensitiveKind(str, Enum):
    CALL_ID = "call_id"
    UUID = "uuid"
    PHONE = "phone"
    DOCUMENT = "document"
    IP = "ip"
    INTERNAL_HOST = "internal_host"
    INTERNAL_URL = "internal_url"
    CREDENTIAL = "credential"
    CUSTOMER_DATA = "customer_data"


_PLACEHOLDER_PREFIX: Final = {
    SensitiveKind.CALL_ID: "CALL_ID",
    SensitiveKind.UUID: "UUID",
    SensitiveKind.PHONE: "TELEFONE",
    SensitiveKind.DOCUMENT: "DOCUMENTO",
    SensitiveKind.IP: "IP",
    SensitiveKind.INTERNAL_HOST: "HOST_INTERNO",
    SensitiveKind.INTERNAL_URL: "URL_INTERNA",
    SensitiveKind.CREDENTIAL: "CREDENCIAL",
    SensitiveKind.CUSTOMER_DATA: "DADO_CLIENTE",
}
_DOCUMENTATION_NETWORKS: Final = tuple(
    ip_network(network)
    for network in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")
)
_DOCUMENT_RE: Final = re.compile(r"^[0-9]{3}\.[0-9]{3}\.[0-9]{3}-[0-9]{2}$")


def _cpf_check_digits(base: str) -> tuple[int, int]:
    numbers = [int(character) for character in base]
    total = sum(number * weight for number, weight in zip(numbers, range(10, 1, -1)))
    first = 0 if (remainder := 11 - total % 11) >= 10 else remainder
    total = sum(
        number * weight
        for number, weight in zip((*numbers, first), range(11, 1, -1))
    )
    second = 0 if (remainder := 11 - total % 11) >= 10 else remainder
    return first, second


def _invalid_document(base_number: int) -> str:
    base = f"{base_number:09d}"
    first, second = _cpf_check_digits(base)
    deliberately_wrong_second = (second + 1) % 10
    digits = f"{base}{first}{deliberately_wrong_second}"
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"


def _is_invalid_document(value: str) -> bool:
    if not _DOCUMENT_RE.fullmatch(value):
        return False
    digits = "".join(character for character in value if character.isdigit())
    return tuple(map(int, digits[9:])) != _cpf_check_digits(digits[:9])


def is_generated_sensitive_value(kind: SensitiveKind, value: str) -> bool:
    """Confirma que o valor pertence a um namespace reservado de teste."""

    try:
        if kind is SensitiveKind.CALL_ID:
            return value.startswith("SYN_CALL_")
        if kind is SensitiveKind.UUID:
            return UUID(value).version == 4
        if kind is SensitiveKind.PHONE:
            return bool(re.fullmatch(r"\+1-202-555-01[0-9]{2}", value))
        if kind is SensitiveKind.DOCUMENT:
            return _is_invalid_document(value)
        if kind is SensitiveKind.IP:
            parsed = ip_address(value)
            return any(parsed in network for network in _DOCUMENTATION_NETWORKS)
        if kind is SensitiveKind.INTERNAL_HOST:
            return value.endswith(".invalid") and value.startswith("syn-")
        if kind is SensitiveKind.INTERNAL_URL:
            parsed_url = urlparse(value)
            return (
                parsed_url.scheme == "https"
                and parsed_url.hostname is not None
                and parsed_url.hostname.endswith(".invalid")
            )
        if kind is SensitiveKind.CREDENTIAL:
            return value.startswith("SYN_TEST_CREDENTIAL_")
        if kind is SensitiveKind.CUSTOMER_DATA:
            return value.startswith("SYNTHETIC_CUSTOMER_")
    except ValueError:
        return False
    return False


@dataclass(frozen=True)
class SensitiveDatum:
    """Par de valor sensível sintético e placeholder seguro correspondente."""

    kind: SensitiveKind
    synthetic_value: str
    placeholder: str

    def __post_init__(self) -> None:
        if not is_generated_sensitive_value(self.kind, self.synthetic_value):
            raise ValueError("valor sensível não pertence ao namespace sintético")
        if not is_typed_placeholder(self.placeholder):
            raise ValueError("placeholder sensível inválido")
        expected_prefix = f"<{_PLACEHOLDER_PREFIX[self.kind]}_"
        if not self.placeholder.startswith(expected_prefix):
            raise ValueError("tipo do placeholder não corresponde ao valor")
        assert_no_raw_source_reference(self)


def _synthetic_value_strategy(kind: SensitiveKind) -> SearchStrategy[str]:
    if kind is SensitiveKind.CALL_ID:
        return opaque_values("CALL").map(lambda value: value)
    if kind is SensitiveKind.UUID:
        return st.integers(min_value=0, max_value=(1 << 128) - 1).map(
            lambda value: str(UUID(int=value, version=4))
        )
    if kind is SensitiveKind.PHONE:
        return st.integers(min_value=0, max_value=99).map(
            lambda suffix: f"+1-202-555-01{suffix:02d}"
        )
    if kind is SensitiveKind.DOCUMENT:
        return st.integers(min_value=0, max_value=999_999_999).map(
            _invalid_document
        )
    if kind is SensitiveKind.IP:
        return st.tuples(
            st.sampled_from(("192.0.2", "198.51.100", "203.0.113")),
            st.integers(min_value=1, max_value=254),
        ).map(lambda item: f"{item[0]}.{item[1]}")
    if kind is SensitiveKind.INTERNAL_HOST:
        return opaque_values("HOST").map(
            lambda value: f"syn-{value.rsplit('_', 1)[1].lower()}.invalid"
        )
    if kind is SensitiveKind.INTERNAL_URL:
        return opaque_values("URL").map(
            lambda value: (
                "https://syn-service.invalid/synthetic/"
                f"{value.rsplit('_', 1)[1].lower()}"
            )
        )
    if kind is SensitiveKind.CREDENTIAL:
        return opaque_values("TEST_CREDENTIAL")
    if kind is SensitiveKind.CUSTOMER_DATA:
        return opaque_values("CUSTOMER").map(
            lambda value: value.replace("SYN_CUSTOMER_", "SYNTHETIC_CUSTOMER_", 1)
        )
    raise AssertionError("tipo sensível sem strategy")


def sensitive_data(
    kinds: Iterable[SensitiveKind] | None = None,
    *,
    min_index: int = 1,
    max_index: int = 999,
) -> SearchStrategy[SensitiveDatum]:
    """Gera dados reconhecíveis por scanners, mas reservados para testes."""

    selected_kinds = tuple(kinds or tuple(SensitiveKind))
    if not selected_kinds:
        raise ValueError("ao menos um tipo sensível é necessário")
    if min_index < 1 or max_index < min_index:
        raise ValueError("intervalo de placeholder inválido")

    @st.composite
    def _strategy(draw):
        kind = draw(st.sampled_from(selected_kinds))
        synthetic_value = draw(_synthetic_value_strategy(kind))
        index = draw(st.integers(min_value=min_index, max_value=max_index))
        return SensitiveDatum(
            kind=kind,
            synthetic_value=synthetic_value,
            placeholder=f"<{_PLACEHOLDER_PREFIX[kind]}_{index}>",
        )

    return _strategy()


def sensitive_placeholders(
    kinds: Iterable[SensitiveKind] | None = None,
    *,
    min_index: int = 1,
    max_index: int = 999,
) -> SearchStrategy[str]:
    """Gera somente a representação persistível de dados sensíveis."""

    return sensitive_data(
        kinds,
        min_index=min_index,
        max_index=max_index,
    ).map(lambda datum: datum.placeholder)
