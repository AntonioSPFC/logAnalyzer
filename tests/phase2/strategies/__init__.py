"""Builders Hypothesis comuns e exclusivamente sintéticos da Fase 2."""

from .blocks import (
    BlockSpec,
    CRLF,
    LF,
    LINE_TERMINATORS,
    LineKind,
    PhysicalLineSpec,
    block_sequences,
    blocks,
    line_terminators,
    physical_lines,
)
from .catalogs import (
    CatalogCompleteness,
    CatalogSpec,
    ConditionSpec,
    RuleSpec,
    catalog_specs,
)
from .common import (
    assert_no_raw_source_reference,
    is_synthetic_token,
    is_typed_placeholder,
)
from .fields import (
    DEFAULT_PLACEHOLDER_PREFIXES,
    OpaqueField,
    opaque_fields,
    opaque_mappings,
    opaque_values,
    typed_placeholders,
)
from .files import TemporaryLogFactory, TemporaryLogFile
from .graphs import (
    GraphEdgeSpec,
    GraphNodeSpec,
    GraphSpec,
    GraphTopology,
    graph_specs,
)
from .sensitive import (
    SensitiveDatum,
    SensitiveKind,
    is_generated_sensitive_value,
    sensitive_data,
    sensitive_placeholders,
)
from .timestamps import (
    TimestampProfile,
    TimestampSpec,
    ork_timestamps,
    timestamps,
    vpl_timestamps,
)

__all__ = [
    "BlockSpec",
    "CRLF",
    "CatalogCompleteness",
    "CatalogSpec",
    "ConditionSpec",
    "DEFAULT_PLACEHOLDER_PREFIXES",
    "GraphEdgeSpec",
    "GraphNodeSpec",
    "GraphSpec",
    "GraphTopology",
    "LF",
    "LINE_TERMINATORS",
    "LineKind",
    "OpaqueField",
    "PhysicalLineSpec",
    "RuleSpec",
    "SensitiveDatum",
    "SensitiveKind",
    "TemporaryLogFactory",
    "TemporaryLogFile",
    "TimestampProfile",
    "TimestampSpec",
    "assert_no_raw_source_reference",
    "block_sequences",
    "blocks",
    "catalog_specs",
    "graph_specs",
    "is_generated_sensitive_value",
    "is_synthetic_token",
    "is_typed_placeholder",
    "line_terminators",
    "opaque_fields",
    "opaque_mappings",
    "opaque_values",
    "ork_timestamps",
    "physical_lines",
    "sensitive_data",
    "sensitive_placeholders",
    "timestamps",
    "typed_placeholders",
    "vpl_timestamps",
]
