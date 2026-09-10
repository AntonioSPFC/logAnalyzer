"""Strategies para catálogos e regras inteiramente sintéticos."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from typing import Any, Iterable

from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy

from .common import assert_no_raw_source_reference
from .fields import opaque_values, typed_placeholders
from .timestamps import ork_timestamps


class CatalogCompleteness(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True)
class ConditionSpec:
    condition_id: str
    operator: str
    field: str
    expected: str

    def to_mapping(self) -> dict[str, str]:
        return {
            "condition_id": self.condition_id,
            "operator": self.operator,
            "field": self.field,
            "expected": self.expected,
        }


@dataclass(frozen=True)
class RuleSpec:
    rule_id: str
    version: int
    category: str
    applications: tuple[str, ...]
    conditions: tuple[ConditionSpec, ...]
    fixture_ids: tuple[str, ...]
    fixture_digests: tuple[str, ...]
    state: str
    approved_by: str
    approved_at: str
    approval_reference: str
    precedence: int
    omitted_fields: frozenset[str] = frozenset()

    def to_mapping(self) -> dict[str, Any]:
        mapping: dict[str, Any] = {
            "rule_id": self.rule_id,
            "version": self.version,
            "category": self.category,
            "applications": list(self.applications),
            "conditions": [condition.to_mapping() for condition in self.conditions],
            "fixture_ids": list(self.fixture_ids),
            "fixture_digests": list(self.fixture_digests),
            "state": self.state,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "approval_reference": self.approval_reference,
            "precedence": self.precedence,
        }
        return {
            key: value
            for key, value in mapping.items()
            if key not in self.omitted_fields
        }


@dataclass(frozen=True)
class CatalogSpec:
    catalog_version: str
    rules: tuple[RuleSpec, ...]
    labeled_successes: int
    labeled_errors: int
    completeness: CatalogCompleteness
    omitted_fields: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        assert_no_raw_source_reference(self)

    def to_mapping(self) -> dict[str, Any]:
        mapping: dict[str, Any] = {
            "catalog_version": self.catalog_version,
            "coverage": {
                "labeled_successes": self.labeled_successes,
                "labeled_errors": self.labeled_errors,
            },
            "rules": [rule.to_mapping() for rule in self.rules],
        }
        result = {
            key: value
            for key, value in mapping.items()
            if key not in self.omitted_fields
        }
        assert_no_raw_source_reference(result)
        return result


_RULE_REQUIRED_FIELDS = (
    "rule_id",
    "version",
    "category",
    "applications",
    "conditions",
    "fixture_ids",
    "fixture_digests",
    "state",
    "approved_by",
    "approved_at",
    "approval_reference",
    "precedence",
)


def catalog_specs(
    completeness: Iterable[CatalogCompleteness] | None = None,
    *,
    min_rules: int = 0,
    max_rules: int = 4,
) -> SearchStrategy[CatalogSpec]:
    """Gera catálogos serializáveis completos ou com um gate ausente."""

    selected_completeness = tuple(completeness or tuple(CatalogCompleteness))
    if not selected_completeness:
        raise ValueError("ao menos um estado de completude é necessário")
    if min_rules < 0 or max_rules < min_rules:
        raise ValueError("limites de regras inválidos")

    @st.composite
    def _strategy(draw):
        selected = draw(st.sampled_from(selected_completeness))
        rule_count = draw(st.integers(min_value=min_rules, max_value=max_rules))
        catalog_token = draw(opaque_values("CATALOG", min_bytes=4, max_bytes=8))
        salt = catalog_token.rsplit("_", 1)[1]
        rules: list[RuleSpec] = []

        for index in range(rule_count):
            condition_count = draw(st.integers(min_value=1, max_value=4))
            conditions = tuple(
                ConditionSpec(
                    condition_id=f"SYN_CONDITION_{salt}_{index:02X}_{condition_index:02X}",
                    operator=draw(
                        st.sampled_from(
                            (
                                "APPLICATION_PRESENT",
                                "FIELD_EQUALS",
                                "RELATION_PRESENT",
                                "FACT_PRESENT",
                            )
                        )
                    ),
                    field=f"SYN_FIELD_{salt}_{condition_index:02X}",
                    expected=draw(
                        st.one_of(
                            opaque_values("EXPECTED"),
                            typed_placeholders(),
                        )
                    ),
                )
                for condition_index in range(condition_count)
            )
            fixture_id = f"SYN_FIXTURE_{salt}_{index:02X}"
            fixture_digest = sha256(fixture_id.encode("ascii")).hexdigest()
            approved_at = draw(ork_timestamps()).expected_utc.isoformat()
            omitted = frozenset()
            if selected is CatalogCompleteness.INCOMPLETE and index == 0:
                omitted = frozenset(
                    {draw(st.sampled_from(_RULE_REQUIRED_FIELDS))}
                )
            rules.append(
                RuleSpec(
                    rule_id=f"SYN_RULE_{salt}_{index:02X}",
                    version=draw(st.integers(min_value=1, max_value=9)),
                    category=draw(
                        st.sampled_from(
                            ("SUCESSO", "ERRO", "NAO_CLASSIFICADA")
                        )
                    ),
                    applications=tuple(
                        sorted(
                            draw(
                                st.sets(
                                    st.sampled_from(("VPL", "ORK")),
                                    min_size=1,
                                    max_size=2,
                                )
                            )
                        )
                    ),
                    conditions=conditions,
                    fixture_ids=(fixture_id,),
                    fixture_digests=(fixture_digest,),
                    state=draw(
                        st.sampled_from(
                            ("CANDIDATE", "APPROVED", "ACTIVE")
                        )
                    ),
                    approved_by=f"<DOMAIN_OWNER_{index + 1}>",
                    approved_at=approved_at,
                    approval_reference=f"SYN_APPROVAL_{salt}_{index:02X}",
                    precedence=index,
                    omitted_fields=omitted,
                )
            )

        catalog_omissions = frozenset()
        if selected is CatalogCompleteness.INCOMPLETE and not rules:
            catalog_omissions = frozenset(
                {draw(st.sampled_from(("catalog_version", "coverage")))}
            )

        return CatalogSpec(
            catalog_version=catalog_token,
            rules=tuple(rules),
            labeled_successes=draw(st.integers(min_value=0, max_value=10)),
            labeled_errors=draw(st.integers(min_value=0, max_value=10)),
            completeness=selected,
            omitted_fields=catalog_omissions,
        )

    return _strategy()
