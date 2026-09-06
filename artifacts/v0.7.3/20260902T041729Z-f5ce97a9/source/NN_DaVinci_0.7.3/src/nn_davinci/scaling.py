"""Synchronous graph-size policy for API, CLI, and Web render paths.

0.2.1 intentionally provides a small, deterministic preflight instead of a
lazy canvas or task queue.  Large graphs remain analyzable, while rendering is
limited to a bounded focus view.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import shlex
from typing import Iterable

from .errors import GraphTooLargeError
from .ir import GraphIR


@dataclass(frozen=True, slots=True)
class ScalePolicy:
    maximum_synchronous_nodes: int = 2_000
    maximum_synchronous_edges: int = 12_000
    maximum_focus_nodes: int = 500


@dataclass(frozen=True, slots=True)
class ScaleDecision:
    strategy: str
    node_count: int
    edge_count: int
    focused: bool
    limits: ScalePolicy

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "limits": asdict(self.limits)}


DEFAULT_SCALE_POLICY = ScalePolicy()


def preflight_graph(
    graph: GraphIR,
    *,
    focus: Iterable[str] = (),
    operation: str = "render",
    policy: ScalePolicy = DEFAULT_SCALE_POLICY,
    recovery_source: str = "MODEL",
) -> ScaleDecision:
    focus_ids = tuple(dict.fromkeys(str(item) for item in focus))
    recovery_argument = shlex.quote(recovery_source)
    node_count, edge_count = len(graph.nodes), len(graph.edges)
    if operation == "summary":
        return ScaleDecision("summary", node_count, edge_count, False, policy)
    if node_count <= policy.maximum_synchronous_nodes and edge_count <= policy.maximum_synchronous_edges:
        return ScaleDecision("full", node_count, edge_count, bool(focus_ids), policy)
    if focus_ids:
        return ScaleDecision("focus", node_count, edge_count, True, policy)
    raise GraphTooLargeError(
        f"Synchronous full-graph {operation} rejected for {node_count:,} nodes and {edge_count:,} edges",
        hint=(
            f"Select one or more node/group IDs and request a focus view of at most "
            f"{policy.maximum_focus_nodes} rendered nodes, or request a structural summary. "
            f"CLI: nnviz render {recovery_argument} --focus NODE_ID --focus-hops 2; "
            f"summary: nnviz render {recovery_argument} --summary"
        ),
        details={
            "node_count": node_count,
            "edge_count": edge_count,
            "maximum_synchronous_nodes": policy.maximum_synchronous_nodes,
            "maximum_synchronous_edges": policy.maximum_synchronous_edges,
            "maximum_focus_nodes": policy.maximum_focus_nodes,
            "allowed_strategies": ["focus", "summary"],
            "recovery_commands": {
                "focus": f"nnviz render {recovery_argument} --focus NODE_ID --focus-hops 2",
                "summary": f"nnviz render {recovery_argument} --summary",
            },
        },
    )


def enforce_focus_bound(view: GraphIR, *, policy: ScalePolicy = DEFAULT_SCALE_POLICY) -> None:
    if len(view.nodes) > policy.maximum_focus_nodes:
        raise GraphTooLargeError(
            f"Focused view still contains {len(view.nodes):,} nodes",
            hint=f"Reduce focus_hops or choose a smaller focus set (maximum {policy.maximum_focus_nodes} rendered nodes).",
            details={"rendered_nodes": len(view.nodes), "maximum_focus_nodes": policy.maximum_focus_nodes},
        )


def summarize_graph_structure(graph: GraphIR) -> dict[str, object]:
    """Return a bounded structural summary without constructing a layout/SVG."""
    preflight_graph(graph, operation="summary")
    visible_nodes = [node for node in graph.nodes if node.visible]
    visible_ids = {node.id for node in visible_nodes}
    visible_edges = [edge for edge in graph.edges if edge.visible and edge.source in visible_ids and edge.target in visible_ids]
    categories: dict[str, int] = {}
    edge_kinds: dict[str, int] = {}
    for node in visible_nodes:
        categories[node.category] = categories.get(node.category, 0) + 1
    for edge in visible_edges:
        edge_kinds[edge.kind] = edge_kinds.get(edge.kind, 0) + 1
    return {
        "strategy": "summary",
        "nodes": len(graph.nodes), "edges": len(graph.edges),
        "visible_nodes": len(visible_nodes), "visible_edges": len(visible_edges),
        "inputs": len(graph.inputs), "outputs": len(graph.outputs),
        "subgraphs": len(graph.subgraphs), "annotations": len(graph.annotations),
        "categories": dict(sorted(categories.items())), "edge_kinds": dict(sorted(edge_kinds.items())),
        "rendered_nodes": 0, "layout_constructed": False, "svg_constructed": False,
    }


__all__ = [
    "DEFAULT_SCALE_POLICY",
    "ScaleDecision",
    "ScalePolicy",
    "enforce_focus_bound",
    "preflight_graph",
    "summarize_graph_structure",
]
