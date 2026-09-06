from __future__ import annotations

from dataclasses import asdict, dataclass, field
from copy import deepcopy
import json
import re
from pathlib import Path
from typing import Any

from ..ir import Edge, GraphIR, Node
from .static import analyze_graph


@dataclass(slots=True)
class NodeChange:
    before_id: str
    after_id: str
    path: str
    changes: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(slots=True)
class NodeMatch:
    before_id: str
    after_id: str
    status: str
    confidence: float
    reasons: list[str]
    before_operation_ids: list[str] = field(default_factory=list)
    after_operation_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class GraphDiff:
    added_nodes: list[str] = field(default_factory=list)
    removed_nodes: list[str] = field(default_factory=list)
    changed_nodes: list[NodeChange] = field(default_factory=list)
    added_edges: list[str] = field(default_factory=list)
    removed_edges: list[str] = field(default_factory=list)
    matches: list[NodeMatch] = field(default_factory=list)
    unmatched_before: list[str] = field(default_factory=list)
    unmatched_after: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _node_key(node: Node) -> str:
    return node.path or node.source.get("trace_id") or node.name


def _edge_key(edge: Edge, graph: GraphIR) -> tuple[str, str, str]:
    nodes = graph.node_map()
    source = _node_key(nodes[edge.source]) if edge.source in nodes else edge.source
    target = _node_key(nodes[edge.target]) if edge.target in nodes else edge.target
    return source, target, edge.kind


def compare_graphs(before: GraphIR, after: GraphIR) -> GraphDiff:
    weight_only = _weight_only(before) or _weight_only(after)
    matches, unmatched_before, unmatched_after = _match_nodes(before, after)
    before_map = before.node_map()
    after_map = after.node_map()
    changes: list[NodeChange] = []
    fields = ("op_type", "category", "parameters", "trainable_parameters", "buffers", "shared_weights")
    for match in matches:
        old, new = before_map[match.before_id], after_map[match.after_id]
        node_changes: dict[str, dict[str, Any]] = {}
        for field_name in fields:
            old_value, new_value = getattr(old, field_name), getattr(new, field_name)
            if old_value != new_value:
                node_changes[field_name] = {"before": old_value, "after": new_value}
        old_shapes = [[port.tensor.shape if port.tensor else None for port in old.inputs], [port.tensor.shape if port.tensor else None for port in old.outputs]]
        new_shapes = [[port.tensor.shape if port.tensor else None for port in new.inputs], [port.tensor.shape if port.tensor else None for port in new.outputs]]
        if old_shapes != new_shapes:
            node_changes["tensor_shapes"] = {"before": old_shapes, "after": new_shapes}
        old_runtime = {key: value for key, value in old.analysis.items() if key in {"duration_ms", "peak_memory_bytes"}}
        new_runtime = {key: value for key, value in new.analysis.items() if key in {"duration_ms", "peak_memory_bytes"}}
        if old_runtime != new_runtime:
            node_changes["runtime"] = {"before": old_runtime, "after": new_runtime}
        old_flops = old.analysis.get("flops", old.attributes.get("flops"))
        new_flops = new.analysis.get("flops", new.attributes.get("flops"))
        if old_flops != new_flops:
            node_changes["flops"] = {"before": old_flops, "after": new_flops}
        if match.status == "probable" and old.path != new.path:
            node_changes["path"] = {"before": old.path, "after": new.path}
        if node_changes:
            changes.append(NodeChange(old.id, new.id, _node_key(new), node_changes))
    match_targets = {item.before_id: item.after_id for item in matches}
    before_edges: dict[tuple[str, str, str], Edge] = {}
    for edge in before.edges:
        source = match_targets.get(edge.source, f"before:{edge.source}")
        target = match_targets.get(edge.target, f"before:{edge.target}")
        before_edges[(source, target, edge.kind)] = edge
    # Use after IDs as the common endpoint identity so moved/probable nodes do
    # not manufacture connection changes.
    after_edges = {(edge.source, edge.target, edge.kind): edge for edge in after.edges}
    before_analysis = analyze_graph(before)["summary"]
    after_analysis = analyze_graph(after)["summary"]
    metric_deltas = {
        metric: {"before": before_analysis[metric], "after": after_analysis[metric], "delta": after_analysis[metric] - before_analysis[metric]}
        for metric in ("total_parameters", "trainable_parameters", "flops", "activation_bytes", "depth")
    }
    before_runtime = _runtime_totals(before)
    after_runtime = _runtime_totals(after)
    metric_deltas.update({
        metric: {"before": before_runtime[metric], "after": after_runtime[metric], "delta": after_runtime[metric] - before_runtime[metric]}
        for metric in ("duration_ms", "peak_memory_bytes")
    })
    result = GraphDiff(
        added_nodes=sorted(unmatched_after),
        removed_nodes=sorted(unmatched_before),
        changed_nodes=changes,
        added_edges=[after_edges[key].id for key in sorted(after_edges.keys() - before_edges.keys())],
        removed_edges=[before_edges[key].id for key in sorted(before_edges.keys() - after_edges.keys())],
        summary={
            "added": len(unmatched_after), "removed": len(unmatched_before), "changed": len(changes),
            "connections_added": len(after_edges.keys() - before_edges.keys()),
            "connections_removed": len(before_edges.keys() - after_edges.keys()),
            "metrics": metric_deltas,
            "matching": {
                "exact": sum(item.status == "exact" for item in matches),
                "probable": sum(item.status == "probable" for item in matches),
                "unmatched": len(unmatched_before) + len(unmatched_after),
            },
            "change_kinds": {
                "moved": sum("path" in item.changes for item in changes),
                "shared": sum("shared_weights" in item.changes for item in changes),
                "shape": sum("tensor_shapes" in item.changes for item in changes),
                "parameters": sum("parameters" in item.changes for item in changes),
                "flops": sum("flops" in item.changes for item in changes),
            },
            "comparison_scope": "weight-groups-only" if weight_only else "structure",
            "structure_claimed": not weight_only,
            "warning": (
                "A state_dict exposes weight groups but not executable topology; differences are weight-group changes, not recovered structural changes."
                if weight_only else None
            ),
        },
        matches=matches,
        unmatched_before=sorted(unmatched_before),
        unmatched_after=sorted(unmatched_after),
    )
    return result


def _match_nodes(before: GraphIR, after: GraphIR) -> tuple[list[NodeMatch], set[str], set[str]]:
    unmatched_before = {node.id for node in before.nodes}
    unmatched_after = {node.id for node in after.nodes}
    candidates: list[tuple[float, str, str, list[str]]] = []
    for old in before.nodes:
        for new in after.nodes:
            score, reasons = _match_score(old, new, before, after)
            if score >= 0.62:
                candidates.append((score, old.id, new.id, reasons))
    matches: list[NodeMatch] = []
    before_map, after_map = before.node_map(), after.node_map()
    for score, before_id, after_id, reasons in sorted(candidates, key=lambda item: (-item[0], item[1], item[2])):
        if before_id not in unmatched_before or after_id not in unmatched_after:
            continue
        old, new = before_map[before_id], after_map[after_id]
        status = "exact" if score >= 0.999 else "probable"
        matches.append(NodeMatch(
            before_id,
            after_id,
            status,
            round(score, 5),
            reasons,
            _operation_ids(old),
            _operation_ids(new),
        ))
        unmatched_before.remove(before_id)
        unmatched_after.remove(after_id)
    return sorted(matches, key=lambda item: (item.status != "exact", item.before_id)), unmatched_before, unmatched_after


def _match_score(old: Node, new: Node, before: GraphIR, after: GraphIR) -> tuple[float, list[str]]:
    old_key, new_key = _node_key(old), _node_key(new)
    if old_key == new_key:
        return 1.0, ["Stable path/trace identity is equal; operation changes are reported separately."]
    old_normalized = _normalized_path(old_key)
    new_normalized = _normalized_path(new_key)
    if old_normalized == new_normalized and old.op_type == new.op_type:
        return 0.92, ["Digit-normalized module paths and operation types match."]
    old_name, new_name = _normalized_path(old.name), _normalized_path(new.name)
    if old_name == new_name and old.op_type == new.op_type:
        return 0.86, ["Normalized node labels and operation types match despite path movement."]
    if old.op_type != new.op_type or old.category != new.category:
        return 0.0, []
    old_neighbors = _neighbor_types(old.id, before)
    new_neighbors = _neighbor_types(new.id, after)
    union = old_neighbors | new_neighbors
    similarity = len(old_neighbors & new_neighbors) / max(len(union), 1)
    score = 0.64 + 0.16 * similarity
    return score, [f"Operation/category match with {similarity:.2f} neighboring-type similarity."]


def _normalized_path(value: str) -> str:
    return re.sub(r"\d+", "#", re.sub(r"[^a-z0-9]+", ".", value.lower())).strip(".")


def _neighbor_types(node_id: str, graph: GraphIR) -> set[str]:
    nodes = graph.node_map()
    neighbors = {
        edge.source if edge.target == node_id else edge.target
        for edge in graph.edges
        if edge.source == node_id or edge.target == node_id
    }
    return {nodes[item].op_type for item in neighbors if item in nodes}


def _operation_ids(node: Node) -> list[str]:
    values = node.attributes.get("operation_ids") or node.attributes.get("source_nodes") or node.source.get("source_nodes") or [node.id]
    return [str(item) for item in values]


def _weight_only(graph: GraphIR) -> bool:
    return graph.metadata.get("structure_available") is False or graph.metadata.get("representation") == "weight-groups-only"


def _runtime_totals(graph: GraphIR) -> dict[str, float | int]:
    summary = graph.analysis.get("runtime", {})
    duration = summary.get("total_duration_ms")
    if duration is None:
        duration = sum(float(node.analysis.get("duration_ms", 0) or 0) for node in graph.nodes)
    peak = summary.get("peak_memory_bytes")
    if peak is None:
        peak = max((int(node.analysis.get("peak_memory_bytes", 0) or 0) for node in graph.nodes), default=0)
    return {"duration_ms": float(duration), "peak_memory_bytes": int(peak)}


def visualize_diff(before: GraphIR, after: GraphIR, *, view: str = "overlay") -> GraphIR:
    """Build a renderable union graph tagged as diff-added/removed/changed."""
    if view not in {"side-by-side", "overlay", "change-only", "summary"}:
        raise ValueError("diff view must be side-by-side, overlay, change-only, or summary")
    difference = compare_graphs(before, after)
    if view == "summary":
        return _summary_graph(before, after, difference)
    if view == "side-by-side":
        return _side_by_side(before, after, difference)
    visual = after.copy()
    visual.name = f"{before.name} → {after.name}"
    visual.metadata["diff"] = difference.to_dict()
    added = set(difference.added_nodes)
    changed = {item.after_id for item in difference.changed_nodes}
    for node in visual.nodes:
        if node.id in added and "diff-added" not in node.tags:
            node.tags.append("diff-added")
        if node.id in changed and "diff-changed" not in node.tags:
            node.tags.append("diff-changed")
    for edge in visual.edges:
        if edge.id in difference.added_edges:
            edge.attributes.update({"diff_status": "added", "color": "#16a34a", "line_width": 2.5})

    before_nodes = {_node_key(node): node for node in before.nodes}
    after_nodes = {_node_key(node): node for node in after.nodes}
    before_to_visual: dict[str, str] = {}
    for key, node in before_nodes.items():
        if key in after_nodes:
            before_to_visual[node.id] = after_nodes[key].id
            continue
        removed = deepcopy(node)
        if removed.id in visual.node_map():
            removed.id = f"removed_{removed.id}"
        removed.tags = list(dict.fromkeys([*removed.tags, "diff-removed"]))
        removed.visible = True
        before_to_visual[node.id] = removed.id
        visual.nodes.append(removed)
    removed_edge_ids = set(difference.removed_edges)
    for edge in before.edges:
        if edge.id not in removed_edge_ids:
            continue
        source = before_to_visual.get(edge.source)
        target = before_to_visual.get(edge.target)
        if not source or not target or source == target:
            continue
        removed_edge = Edge.create(source, target, kind=edge.kind, label=edge.label, tensor=edge.tensor)
        removed_edge.attributes.update({"diff_status": "removed", "color": "#dc2626", "dashed": True, "line_width": 2.2})
        visual.edges.append(removed_edge)
    for match in difference.matches:
        node = visual.node_map().get(match.after_id)
        if node:
            node.attributes["diff_match"] = asdict(match)
            node.attributes["before_node_id"] = match.before_id
            node.attributes["after_node_id"] = match.after_id
    if view == "change-only":
        selected = set(difference.added_nodes) | {item.after_id for item in difference.changed_nodes}
        selected |= {before_to_visual[item] for item in difference.removed_nodes if item in before_to_visual}
        visual.nodes = [node for node in visual.nodes if node.id in selected]
        selected_ids = {node.id for node in visual.nodes}
        visual.edges = [edge for edge in visual.edges if edge.source in selected_ids and edge.target in selected_ids]
        selected_edges = {edge.id for edge in visual.edges}
        for group in visual.subgraphs:
            group.node_ids = [item for item in group.node_ids if item in selected_ids]
        visual.subgraphs = [group for group in visual.subgraphs if group.node_ids]
        selected_groups = {group.id for group in visual.subgraphs}
        for group in visual.subgraphs:
            if group.parent not in selected_groups:
                group.parent = None
        for node in visual.nodes:
            if node.parent not in selected_groups and node.parent not in selected_ids:
                node.parent = None
        visual.annotations = [
            annotation
            for annotation in visual.annotations
            if all(item in selected_ids | selected_edges | selected_groups for item in annotation.target_ids)
        ]
        visual.constraints = [
            constraint
            for constraint in visual.constraints
            if all(item in selected_ids | selected_edges | selected_groups for item in constraint.target_ids)
        ]
    return visual.validate()


def _side_by_side(before: GraphIR, after: GraphIR, difference: GraphDiff) -> GraphIR:
    left = _prefixed(before, "before")
    right = _prefixed(after, "after")
    result = GraphIR(
        name=f"{before.name} ↔ {after.name}",
        nodes=[*left.nodes, *right.nodes],
        edges=[*left.edges, *right.edges],
        subgraphs=[*left.subgraphs, *right.subgraphs],
        annotations=[*left.annotations, *right.annotations],
        metadata={"diff": difference.to_dict(), "diff_view": "side-by-side"},
    )
    for match in difference.matches:
        edge = Edge.create(f"before__{match.before_id}", f"after__{match.after_id}", kind="semantic-connection", label=match.status)
        edge.attributes = {"dashed": True, "not_model_data_edge": True, "match_confidence": match.confidence}
        result.edges.append(edge)
    return result.validate()


def _prefixed(graph: GraphIR, prefix: str) -> GraphIR:
    result = graph.copy()
    node_ids = {node.id: f"{prefix}__{node.id}" for node in result.nodes}
    port_ids = {port.id: f"{prefix}__{port.id}" for node in result.nodes for port in [*node.inputs, *node.outputs]}
    group_ids = {group.id: f"{prefix}__{group.id}" for group in result.subgraphs}
    edge_ids = {edge.id: f"{prefix}__{edge.id}" for edge in result.edges}
    for node in result.nodes:
        old = node.id
        node.id = node_ids[old]
        node.parent = group_ids.get(node.parent or "", node_ids.get(node.parent or "", node.parent))
        node.attributes = {**node.attributes, "diff_side": prefix, "source_node_id": old}
        for port in [*node.inputs, *node.outputs]:
            port.id = port_ids[port.id]
    for edge in result.edges:
        edge.id = edge_ids[edge.id]
        edge.source = node_ids[edge.source]
        edge.target = node_ids[edge.target]
        edge.source_port = port_ids.get(edge.source_port or "")
        edge.target_port = port_ids.get(edge.target_port or "")
    for group in result.subgraphs:
        old = group.id
        group.id = group_ids[old]
        group.node_ids = [node_ids[item] for item in group.node_ids]
        group.parent = group_ids.get(group.parent or "")
    for annotation in result.annotations:
        annotation.id = f"{prefix}__{annotation.id}"
        annotation.target_ids = [node_ids.get(item, edge_ids.get(item, group_ids.get(item, item))) for item in annotation.target_ids]
    for constraint in result.constraints:
        constraint.target_ids = [node_ids.get(item, edge_ids.get(item, group_ids.get(item, item))) for item in constraint.target_ids]
    return result.validate()


def _summary_graph(before: GraphIR, after: GraphIR, difference: GraphDiff) -> GraphIR:
    counts = [
        ("Added", difference.summary["added"], "diff-added"),
        ("Removed", difference.summary["removed"], "diff-removed"),
        ("Modified", difference.summary["changed"], "diff-changed"),
        ("Moved", difference.summary["change_kinds"]["moved"], "diff-moved"),
    ]
    nodes = [
        Node.create(label, "DiffSummary", category="operation", path=f"diff.{label.lower()}", attributes={"count": count}, tags=[tag])
        for label, count, tag in counts
    ]
    return GraphIR(f"{before.name} → {after.name} summary", nodes=nodes, metadata={"diff": difference.to_dict(), "diff_view": "summary"}).validate()


def export_diff(
    before: GraphIR,
    after: GraphIR,
    output: str | Path,
    *,
    view: str = "change-only",
    formats: tuple[str, ...] = ("svg", "pdf", "tikz"),
) -> list[Path]:
    """Export a paper diagram plus its machine-readable matching report."""
    from ..layout import LayoutEngine
    from ..render import export_graph
    from ..themes import get_theme

    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    difference = compare_graphs(before, after)
    report_path = target.with_suffix(".diff.json")
    report_path.write_text(json.dumps(difference.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    graph = visualize_diff(before, after, view=view)
    layout = LayoutEngine().layout(graph, page_preset="wide-two-column", label_density="paper")
    return [report_path, *export_graph(graph, layout, get_theme("colorblind", page="wide-two-column"), target, formats=formats)]
