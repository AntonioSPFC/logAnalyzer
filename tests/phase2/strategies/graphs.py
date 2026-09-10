"""Strategies para grafos sintéticos de identificadores e evidências."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy

from .common import assert_no_raw_source_reference
from .fields import opaque_values


class GraphTopology(str, Enum):
    EMPTY = "empty"
    PATH = "path"
    DISCONNECTED = "disconnected"
    CYCLE = "cycle"
    CONTRADICTORY = "contradictory"
    RANDOM = "random"


@dataclass(frozen=True)
class GraphNodeSpec:
    identifier: str
    identifier_type: str

    def __post_init__(self) -> None:
        assert_no_raw_source_reference((self.identifier, self.identifier_type))


@dataclass(frozen=True)
class GraphEdgeSpec:
    source: str
    target: str
    relation: str
    evidence: str
    explicit: bool = True
    ambiguous: bool = False

    def __post_init__(self) -> None:
        if self.source == self.target:
            raise ValueError("arestas sintéticas não usam self-loop")
        assert_no_raw_source_reference(self)


@dataclass(frozen=True)
class GraphSpec:
    topology: GraphTopology
    nodes: tuple[GraphNodeSpec, ...]
    edges: tuple[GraphEdgeSpec, ...]

    def __post_init__(self) -> None:
        node_ids = tuple(node.identifier for node in self.nodes)
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("identificadores de nós devem ser únicos")
        known = set(node_ids)
        if any(
            edge.source not in known or edge.target not in known
            for edge in self.edges
        ):
            raise ValueError("aresta referencia nó inexistente")
        assert_no_raw_source_reference(self)


def graph_specs(
    topologies: Iterable[GraphTopology] | None = None,
    *,
    min_nodes: int = 0,
    max_nodes: int = 8,
) -> SearchStrategy[GraphSpec]:
    """Gera grafos vazios, desconectados, cíclicos e contraditórios."""

    selected_topologies = tuple(topologies or tuple(GraphTopology))
    if not selected_topologies:
        raise ValueError("ao menos uma topologia é necessária")
    if min_nodes < 0 or max_nodes < max(3, min_nodes):
        raise ValueError("limites de nós inválidos")

    @st.composite
    def _strategy(draw):
        topology = draw(st.sampled_from(selected_topologies))
        lower_bound = min_nodes
        if topology is GraphTopology.EMPTY:
            node_count = 0
        else:
            required = {
                GraphTopology.PATH: 1,
                GraphTopology.DISCONNECTED: 2,
                GraphTopology.CYCLE: 2,
                GraphTopology.CONTRADICTORY: 3,
                GraphTopology.RANDOM: 1,
            }[topology]
            node_count = draw(
                st.integers(
                    min_value=max(required, lower_bound),
                    max_value=max_nodes,
                )
            )

        salt = draw(opaque_values("GRAPH", min_bytes=4, max_bytes=8)).rsplit("_", 1)[1]
        nodes = tuple(
            GraphNodeSpec(
                identifier=f"SYN_NODE_{salt}_{index:02X}",
                identifier_type=draw(
                    st.sampled_from(("CALL", "CHANNEL", "SESSION"))
                ),
            )
            for index in range(node_count)
        )

        pairs: list[tuple[int, int, bool]] = []
        if topology is GraphTopology.PATH:
            pairs = [(index, index + 1, False) for index in range(node_count - 1)]
        elif topology is GraphTopology.DISCONNECTED:
            split = node_count // 2
            pairs = [
                (index, index + 1, False)
                for start, end in ((0, split), (split, node_count))
                for index in range(start, max(start, end - 1))
            ]
        elif topology is GraphTopology.CYCLE:
            pairs = [
                (index, (index + 1) % node_count, False)
                for index in range(node_count)
            ]
        elif topology is GraphTopology.CONTRADICTORY:
            pairs = [(0, 1, True), (0, 2, True)]
        elif topology is GraphTopology.RANDOM and node_count > 1:
            candidates = [
                (source, target)
                for source in range(node_count)
                for target in range(node_count)
                if source != target
            ]
            selected = draw(
                st.sets(
                    st.sampled_from(candidates),
                    min_size=0,
                    max_size=min(len(candidates), node_count * 2),
                )
            )
            pairs = [
                (source, target, False)
                for source, target in sorted(selected)
            ]

        edges = tuple(
            GraphEdgeSpec(
                source=nodes[source].identifier,
                target=nodes[target].identifier,
                relation=f"SYN_RELATION_{salt}_{index:02X}",
                evidence=f"SYN_EVIDENCE_{salt}_{index:02X}",
                explicit=True,
                ambiguous=ambiguous,
            )
            for index, (source, target, ambiguous) in enumerate(pairs)
        )
        return GraphSpec(topology=topology, nodes=nodes, edges=edges)

    return _strategy()
