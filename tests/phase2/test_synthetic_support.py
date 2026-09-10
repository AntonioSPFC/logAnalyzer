"""Testes focados do suporte sintético compartilhado da Fase 2.

Validates: Requirements 4.3, 5.1, 14.5, 14.8, 15.4.
"""

from __future__ import annotations

import ast
from datetime import timedelta
import inspect
import json
from pathlib import Path

from hypothesis import find, settings
import pytest

from tests.phase2.strategies import (
    BlockSpec,
    CRLF,
    LF,
    CatalogCompleteness,
    GraphTopology,
    LineKind,
    PhysicalLineSpec,
    SensitiveKind,
    TemporaryLogFactory,
    assert_no_raw_source_reference,
    blocks,
    catalog_specs,
    graph_specs,
    is_generated_sensitive_value,
    is_synthetic_token,
    is_typed_placeholder,
    opaque_fields,
    opaque_values,
    ork_timestamps,
    sensitive_data,
    typed_placeholders,
    vpl_timestamps,
)

_FIND_SETTINGS = settings(
    max_examples=200,
    derandomize=True,
    database=None,
    deadline=None,
)


def _example(strategy, predicate=lambda value: True):
    """Obtém um caso reproduzível sem declarar uma propriedade futura."""

    return find(strategy, predicate, settings=_FIND_SETTINGS)


def test_opaque_builders_emit_only_marked_values() -> None:
    token = _example(opaque_values("TEST_FIELD"))
    placeholder = _example(typed_placeholders(("CALL_ID",)))
    field = _example(opaque_fields(("CallId",)))

    assert is_synthetic_token(token)
    assert placeholder.startswith("<CALL_ID_")
    assert is_typed_placeholder(placeholder)
    assert is_synthetic_token(field.value) or is_typed_placeholder(field.value)
    assert_no_raw_source_reference((token, placeholder, field))


def test_timestamp_builders_keep_source_and_utc_reference() -> None:
    vpl = _example(vpl_timestamps(), lambda value: value.precision == 6)
    ork = _example(
        ork_timestamps(),
        lambda value: value.precision == 3 and value.offset_minutes != 0,
    )

    assert vpl.source_datetime.tzinfo is None
    assert vpl.expected_utc.utcoffset() == timedelta(0)
    assert len(vpl.original.rsplit(".", 1)[1]) == 6

    assert ork.source_datetime.tzinfo is not None
    assert ork.expected_utc.utcoffset() == timedelta(0)
    assert ork.offset_minutes is not None
    assert ork.original[-6] in {"+", "-"}


def test_block_builder_preserves_text_order_and_terminators() -> None:
    block = _example(
        blocks(min_continuations=2, max_continuations=2, final_newline=True),
        lambda value: {line.terminator for line in value.lines} == {LF, CRLF},
    )

    expected = "".join(line.text + line.terminator for line in block.lines)
    assert block.text == expected
    assert block.payload == expected.encode("utf-8")
    assert block.lines[0].kind in {
        LineKind.VALID_HEADER,
        LineKind.INVALID_HEADER,
    }
    assert all(
        line.kind is LineKind.CONTINUATION for line in block.lines[1:]
    )


@pytest.mark.parametrize("topology", tuple(GraphTopology))
def test_graph_builder_emits_only_consistent_graphs(topology: GraphTopology) -> None:
    graph = _example(graph_specs((topology,)))
    node_ids = {node.identifier for node in graph.nodes}

    assert graph.topology is topology
    assert all(edge.source in node_ids and edge.target in node_ids for edge in graph.edges)
    assert all(edge.explicit for edge in graph.edges)
    assert_no_raw_source_reference(graph)

    if topology is GraphTopology.EMPTY:
        assert graph.nodes == () and graph.edges == ()
    elif topology is GraphTopology.PATH:
        assert len(graph.edges) == len(graph.nodes) - 1
    elif topology is GraphTopology.CYCLE:
        assert len(graph.edges) == len(graph.nodes)
    elif topology is GraphTopology.CONTRADICTORY:
        assert len(graph.edges) == 2
        assert all(edge.ambiguous for edge in graph.edges)


def test_catalog_builder_produces_json_safe_complete_and_incomplete_cases() -> None:
    complete = _example(
        catalog_specs((CatalogCompleteness.COMPLETE,), min_rules=1, max_rules=1)
    )
    incomplete = _example(
        catalog_specs((CatalogCompleteness.INCOMPLETE,), min_rules=1, max_rules=1)
    )

    complete_mapping = complete.to_mapping()
    incomplete_mapping = incomplete.to_mapping()

    assert complete.rules[0].omitted_fields == frozenset()
    assert incomplete.rules[0].omitted_fields
    assert set(incomplete.rules[0].to_mapping()) < set(complete.rules[0].to_mapping())
    assert json.loads(json.dumps(complete_mapping)) == complete_mapping
    assert_no_raw_source_reference((complete_mapping, incomplete_mapping))


@pytest.mark.parametrize("kind", tuple(SensitiveKind))
def test_sensitive_builder_uses_reserved_synthetic_namespaces(
    kind: SensitiveKind,
) -> None:
    datum = _example(sensitive_data((kind,)))

    assert datum.kind is kind
    assert is_generated_sensitive_value(kind, datum.synthetic_value)
    assert is_typed_placeholder(datum.placeholder)
    assert datum.synthetic_value not in datum.placeholder
    assert_no_raw_source_reference(datum)


def test_temporary_factory_writes_lf_and_crlf_exactly(tmp_path: Path) -> None:
    factory = TemporaryLogFactory(tmp_path)

    lf_file = factory.write_lines(
        ("SYN_LINE_A", "SYN_LINE_B"),
        newline=LF,
        final_newline=True,
        filename="synthetic-lf.log",
    )
    crlf_file = factory.write_lines(
        ("SYN_LINE_A", "SYN_LINE_B"),
        newline=CRLF,
        final_newline=False,
        filename="synthetic-crlf.log",
    )

    assert lf_file.path.read_bytes() == b"SYN_LINE_A\nSYN_LINE_B\n"
    assert lf_file.payload == b"SYN_LINE_A\nSYN_LINE_B\n"
    assert lf_file.terminators == (LF, LF)
    assert crlf_file.path.read_bytes() == b"SYN_LINE_A\r\nSYN_LINE_B"
    assert crlf_file.payload == b"SYN_LINE_A\r\nSYN_LINE_B"
    assert crlf_file.terminators == (CRLF, "")


def test_temporary_factory_preserves_mixed_blocks_and_builds_invalid_utf8(
    tmp_path: Path,
) -> None:
    factory = TemporaryLogFactory(tmp_path)
    block = BlockSpec(
        (
            PhysicalLineSpec(LineKind.VALID_HEADER, "SYN_HEADER_A", LF),
            PhysicalLineSpec(LineKind.CONTINUATION, "SYN_BODY_B", CRLF),
            PhysicalLineSpec(LineKind.CONTINUATION, "SYN_BODY_C", ""),
        )
    )

    mixed_file = factory.write_blocks((block,), filename="synthetic-mixed.log")
    invalid_file = factory.write_invalid_utf8(filename="synthetic-invalid.log")

    assert mixed_file.path.read_bytes() == block.payload
    assert mixed_file.terminators == (LF, CRLF, "")
    with pytest.raises(UnicodeDecodeError):
        invalid_file.decode_utf8()


def test_raw_source_references_and_escape_from_tmp_are_rejected(
    tmp_path: Path,
) -> None:
    factory = TemporaryLogFactory(tmp_path)

    with pytest.raises(ValueError, match="fonte bruta"):
        assert_no_raw_source_reference(r"C:\synthetic\logs\sample.log")
    with pytest.raises(ValueError, match="fonte bruta"):
        factory.write_lines(("logs/sample.log",))
    with pytest.raises(ValueError, match="nome de arquivo"):
        factory.write_lines(("SYN_LINE",), filename="../outside.log")

    assert not (tmp_path.parent / "outside.log").exists()


def test_strategy_modules_do_not_import_production_or_copy_sources() -> None:
    strategy_directory = Path(inspect.getfile(opaque_values)).parent
    forbidden_calls = {"copy", "copy2", "copyfile", "read_text", "read_bytes"}

    for source_path in strategy_directory.glob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported_modules = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported_modules.update(
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        called_attributes = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }

        assert not any(
            module == "log_analyzer" or module.startswith("log_analyzer.")
            for module in imported_modules
        )
        assert called_attributes.isdisjoint(forbidden_calls)
