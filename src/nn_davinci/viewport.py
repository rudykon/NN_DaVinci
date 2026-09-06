"""Bounded, deterministic lazy-canvas slices.

The browser never needs to instantiate the complete operation graph.  A
virtual coordinate system gives every semantic node a stable address; each
request returns nearby nodes, internal edges, and explicit boundary proxies.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from math import ceil
import time
from typing import Any, Iterable

from .errors import ValidationError
from .ir import Edge, GraphIR, Node, stable_id
from .layout import EdgeRoute, LayoutResult, NodePlacement
from .scaling import DEFAULT_SCALE_POLICY, summarize_graph_structure
from .semantic import SemanticView, derive_semantic_view

VIEWPORT_API_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class Viewport:
    x: float = 0.0
    y: float = 0.0
    width: float = 960.0
    height: float = 540.0
    padding: float = 240.0

    def validate(self) -> "Viewport":
        values = (self.x, self.y, self.width, self.height, self.padding)
        if not all(isinstance(value, (int, float)) for value in values):
            raise ValidationError("Viewport coordinates must be numeric")
        if self.width <= 0 or self.height <= 0 or self.padding < 0:
            raise ValidationError("Viewport width/height must be positive and padding non-negative")
        if self.width > 100_000 or self.height > 100_000 or self.padding > 20_000:
            raise ValidationError("Viewport request exceeds the local canvas budget", hint="Zoom in or request a smaller viewport.")
        return self


@dataclass(slots=True)
class ViewportSlice:
    graph: GraphIR
    layout: LayoutResult
    viewport: Viewport
    source_node_count: int
    source_edge_count: int
    boundary_proxy_count: int
    rendered_node_count: int
    rendered_edge_count: int
    dom_object_estimate: int
    truncated: bool
    elapsed_ms: float
    api_version: str = VIEWPORT_API_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "graph": self.graph.to_dict(),
            "layout": self.layout.to_dict(),
            "viewport": asdict(self.viewport),
        }


def lazy_summary(graph: GraphIR, semantic: SemanticView | None = None) -> dict[str, Any]:
    deferred = semantic is None and len(graph.nodes) > 2_000
    structure = summarize_graph_structure(graph)
    if deferred:
        stage_count = sum(group.level == "stage" for group in graph.subgraphs) or 1
        block_count = sum(group.level in {"block", "module"} for group in graph.subgraphs) or len(graph.nodes)
        counts = {"model": 1, "stage": stage_count, "block": block_count, "layer": len(graph.nodes), "operation": len(graph.nodes)}
        semantic_version = "1.0"
    else:
        semantic = semantic or derive_semantic_view(graph)
        counts = {level: len(semantic.entities_at(level)) for level in ("model", "stage", "block", "layer", "operation")}
        semantic_version = semantic.semantic_version
    recommended_level = "operation"
    for level in ("block", "stage", "model"):
        if counts[level] <= DEFAULT_SCALE_POLICY.maximum_focus_nodes:
            recommended_level = level
            break
    return {
        **structure,
        "strategy": "lazy-semantic",
        "semantic_version": semantic_version,
        "semantic_counts": counts,
        "semantic_index_deferred": deferred,
        "summary_basis": "explicit stage boundaries and conservative node-count upper bounds" if deferred else "complete semantic index",
        "recommended_level": recommended_level,
        "recommended_view": "faithful",
        "maximum_visible_nodes": DEFAULT_SCALE_POLICY.maximum_focus_nodes,
        "maximum_dom_objects": 2_000,
    }


def coarse_semantic_graph(graph: GraphIR, *, level: str = "stage") -> GraphIR:
    """Build a bounded first screen without indexing every operation."""
    if level not in {"model", "stage"}:
        raise ValidationError("Coarse semantic graph supports model or stage level")
    if level == "model":
        regions = [(graph.name, [node.id for node in graph.nodes[:32]], len(graph.nodes), "model", 1.0, "Top-level imported Graph IR boundary.")]
    else:
        explicit = [group for group in graph.subgraphs if group.level == "stage"]
        if explicit:
            regions = [
                (group.name, group.node_ids[:32], len(group.node_ids), "stage", 0.98, "Explicit Graph IR stage boundary; full provenance remains server-side.")
                for group in explicit[:500]
            ]
        else:
            regions = [("Unclassified stage", [node.id for node in graph.nodes[:32]], len(graph.nodes), "unknown", 0.2, "No reliable stage boundary; operations remain available through lazy viewport/search.")]
    nodes = []
    for index, (name, preview, count, semantic_type, confidence, reason) in enumerate(regions):
        nodes.append(Node(
            id=stable_id("coarse_semantic", f"{level}:{index}:{name}"),
            name=name,
            op_type="Unknown" if semantic_type == "unknown" else semantic_type.title(),
            category="model" if level == "model" else "operation",
            path=f"semantic.{level}.{index}",
            level=level,
            attributes={
                "semantic_level": level,
                "semantic_view": "faithful",
                "semantic_type": semantic_type,
                "confidence": confidence,
                "recognition_reasons": [reason],
                "source_nodes": preview,
                "source_node_count": count,
                "source_provenance_ref": f"coarse:{level}:{index}",
                "unknown_semantics": semantic_type == "unknown",
            },
            source={"format": "coarse-semantic-summary", "source_nodes": preview, "source_node_count": count},
        ))
    return GraphIR(
        f"{graph.name} · {level.title()} summary",
        nodes=nodes,
        metadata={**graph.metadata, "semantic_view": {"version": "1.0", "level": level, "view": "faithful", "deferred": True}},
    ).validate()


def viewport_slice(
    graph: GraphIR,
    viewport: Viewport | dict[str, Any],
    *,
    include: Iterable[str] = (),
    maximum_nodes: int = 500,
    maximum_dom_objects: int = 2_000,
    node_width: float = 154.0,
    node_height: float = 66.0,
) -> ViewportSlice:
    """Return a bounded slice in stable virtual coordinates.

    This operation is O(nodes + edges), creates at most ``maximum_nodes`` real
    nodes, and never invokes full-graph layout.  It therefore remains valid
    when synchronous full rendering is intentionally rejected.
    """
    started = time.perf_counter()
    request = viewport if isinstance(viewport, Viewport) else Viewport(**viewport)
    request.validate()
    if maximum_nodes < 1 or maximum_nodes > DEFAULT_SCALE_POLICY.maximum_focus_nodes:
        raise ValidationError(
            f"maximum_nodes must be between 1 and {DEFAULT_SCALE_POLICY.maximum_focus_nodes}",
            hint="Use a coarser semantic level rather than increasing the viewport budget.",
        )
    if maximum_dom_objects < maximum_nodes or maximum_dom_objects > 2_000:
        raise ValidationError("maximum_dom_objects must be between maximum_nodes and 2000")

    columns = max(8, min(64, int(ceil(len(graph.nodes) ** 0.5))))
    x_step = node_width + 72.0
    y_step = node_height + 54.0
    positions: dict[str, NodePlacement] = {}
    visible_ids: list[str] = []
    included = set(include)
    left, right = request.x - request.padding, request.x + request.width + request.padding
    top, bottom = request.y - request.padding, request.y + request.height + request.padding
    for index, node in enumerate(graph.nodes):
        column, row = index % columns, index // columns
        x, y = 34.0 + column * x_step, 34.0 + row * y_step
        if node.id in included or (x + node_width >= left and x <= right and y + node_height >= top and y <= bottom):
            visible_ids.append(node.id)
            positions[node.id] = NodePlacement(x, y, node_width, node_height, rank=column, order=row)

    truncated = len(visible_ids) > maximum_nodes
    if truncated:
        included_visible = [node_id for node_id in visible_ids if node_id in included][:maximum_nodes]
        remaining = [node_id for node_id in visible_ids if node_id not in included]
        visible_ids = (included_visible + remaining)[:maximum_nodes]
        positions = {node_id: positions[node_id] for node_id in visible_ids}
    selected = set(visible_ids)
    source_nodes = graph.node_map()
    nodes = [_clone_node(source_nodes[node_id]) for node_id in visible_ids]
    for node in nodes:
        _compact_provenance(node)
    edges: list[Edge] = []
    routes: dict[str, EdgeRoute] = {}
    proxies: dict[tuple[str, str], Node] = {}

    # Reserve two SVG objects for a typical edge and four for a node (group,
    # shape, title and detail).  This conservative estimate keeps the actual
    # browser DOM below the requested 2,000-object ceiling.
    object_budget = maximum_dom_objects - 4 * len(nodes)
    maximum_edges = max(0, object_budget // 2)
    for source_edge in graph.edges:
        source_inside = source_edge.source in selected
        target_inside = source_edge.target in selected
        if not source_inside and not target_inside:
            continue
        if len(edges) >= maximum_edges:
            truncated = True
            break
        if source_inside and target_inside:
            edge = _clone_edge(source_edge)
            edges.append(edge)
            routes[edge.id] = _straight_route(edge, positions, node_width, node_height)
            continue
        inside = source_edge.source if source_inside else source_edge.target
        outside = source_edge.target if source_inside else source_edge.source
        direction = "out" if source_inside else "in"
        proxy_key = (outside, direction)
        proxy = proxies.get(proxy_key)
        if proxy is None:
            if len(nodes) + len(proxies) >= maximum_nodes:
                truncated = True
                continue
            proxy_id = stable_id("boundary", f"{outside}:{direction}")
            outside_node = source_nodes[outside]
            proxy = Node(
                id=proxy_id,
                name=f"{'→' if direction == 'out' else '←'} {outside_node.name}",
                op_type="BoundaryProxy",
                category="operation",
                path=f"boundary.{outside}",
                namespace="lazy-canvas",
                attributes={
                    "boundary_proxy": True,
                    "source_node": outside,
                    "direction": direction,
                    "stable_stub": True,
                },
                source={"format": "viewport", "source_nodes": [outside]},
                tags=["boundary", direction],
            )
            proxies[proxy_key] = proxy
            anchor = positions[inside]
            if direction == "out":
                px = min(request.x + request.width + max(10.0, request.padding / 3), anchor.x + x_step)
            else:
                px = max(request.x - max(10.0, request.padding / 3), anchor.x - x_step)
            positions[proxy.id] = NodePlacement(px, anchor.y, node_width * 0.74, node_height * 0.72)
        edge = _clone_edge(source_edge)
        original_binding = {
            "source_node": source_edge.source,
            "source_port": source_edge.source_port,
            "target_node": source_edge.target,
            "target_port": source_edge.target_port,
            "tensor": asdict(source_edge.tensor) if source_edge.tensor else None,
            "status": "exact" if source_edge.source_port and source_edge.target_port else "partial-or-unknown",
        }
        if source_inside:
            edge.target = proxy.id
            # A boundary proxy deliberately has no invented ports.  Clear only
            # its synthetic endpoint binding and retain the exact source edge
            # binding below for traceability and Figure reconstruction.
            edge.target_port = None
        else:
            edge.source = proxy.id
            edge.source_port = None
        edge.id = stable_id("viewport_edge", f"{source_edge.id}:{proxy.id}")
        edge.attributes.update({
            "boundary_proxy": proxy.id,
            "source_edges": [source_edge.id],
            "outside_node": outside,
            "source_edge_port_binding": original_binding,
            "proxy_side_binding_cleared": "target" if source_inside else "source",
        })
        edges.append(edge)
        routes[edge.id] = _straight_route(edge, positions, node_width, node_height)

    nodes.extend(proxies.values())
    slice_graph = GraphIR(
        name=f"{graph.name} viewport",
        nodes=nodes,
        edges=edges,
        annotations=[],
        constraints=[],
        metadata={
            **graph.metadata,
            "viewport": {
                "api_version": VIEWPORT_API_VERSION,
                "source_nodes": len(graph.nodes),
                "source_edges": len(graph.edges),
                "boundary_proxies": len(proxies),
                "truncated": truncated,
            },
        },
        analysis=dict(graph.analysis),
        ir_version=graph.ir_version,
    ).validate()
    width = max((placement.x + placement.width for placement in positions.values()), default=request.width)
    height = max((placement.y + placement.height for placement in positions.values()), default=request.height)
    layout = LayoutResult(
        engine="viewport-grid",
        direction="LR",
        nodes=positions,
        edges=routes,
        width=width,
        height=height,
        metadata={
            "lazy": True,
            "viewport_api_version": VIEWPORT_API_VERSION,
            "source_node_count": len(graph.nodes),
            "visible_node_count": len(nodes),
            "boundary_proxy_count": len(proxies),
        },
    )
    dom_estimate = 4 * len(nodes) + 2 * len(edges)
    return ViewportSlice(
        graph=slice_graph,
        layout=layout,
        viewport=request,
        source_node_count=len(graph.nodes),
        source_edge_count=len(graph.edges),
        boundary_proxy_count=len(proxies),
        rendered_node_count=len(nodes),
        rendered_edge_count=len(edges),
        dom_object_estimate=dom_estimate,
        truncated=truncated,
        elapsed_ms=round((time.perf_counter() - started) * 1000.0, 3),
    )


def neighborhood_slice(graph: GraphIR, node_ids: Iterable[str], *, hops: int = 1, maximum_nodes: int = 500) -> GraphIR:
    if hops < 0 or hops > 8:
        raise ValidationError("Neighborhood hops must be between 0 and 8")
    known = set(graph.node_map())
    frontier = {node_id for node_id in node_ids if node_id in known}
    if not frontier:
        raise ValidationError("Neighborhood requires at least one known node ID")
    selected = set(frontier)
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in known}
    for edge in graph.edges:
        adjacency[edge.source].add(edge.target)
        adjacency[edge.target].add(edge.source)
    for _ in range(hops):
        frontier = {neighbor for node_id in frontier for neighbor in adjacency[node_id]} - selected
        selected.update(frontier)
        if len(selected) > maximum_nodes:
            selected = set(sorted(selected)[:maximum_nodes])
            break
    return graph.induced(selected, name=f"{graph.name} neighborhood")


def _clone_node(node: Node) -> Node:
    return deepcopy(node)


def _clone_edge(edge: Edge) -> Edge:
    return deepcopy(edge)


def _compact_provenance(node: Node, *, preview_limit: int = 32) -> None:
    source_nodes = list(node.attributes.get("source_nodes", []))
    source_edges = list(node.attributes.get("source_edges", []))
    if len(source_nodes) > preview_limit:
        node.attributes["source_node_count"] = len(source_nodes)
        node.attributes["source_nodes_preview"] = source_nodes[:preview_limit]
        node.attributes["source_provenance_ref"] = node.id
        node.attributes["source_nodes"] = source_nodes[:preview_limit]
        node.source["source_node_count"] = len(source_nodes)
        node.source["source_nodes"] = source_nodes[:preview_limit]
    if len(source_edges) > preview_limit:
        node.attributes["source_edge_count"] = len(source_edges)
        node.attributes["source_edges_preview"] = source_edges[:preview_limit]
        node.attributes["source_provenance_ref"] = node.id
        node.attributes["source_edges"] = source_edges[:preview_limit]
        node.source["source_edge_count"] = len(source_edges)
        node.source["source_edges"] = source_edges[:preview_limit]


def _straight_route(edge: Edge, positions: dict[str, NodePlacement], node_width: float, node_height: float) -> EdgeRoute:
    source = positions[edge.source]
    target = positions[edge.target]
    del node_width, node_height
    return EdgeRoute([
        (source.x + source.width, source.y + source.height / 2),
        (target.x, target.y + target.height / 2),
    ], back_edge=target.x < source.x)


__all__ = [
    "VIEWPORT_API_VERSION",
    "Viewport",
    "ViewportSlice",
    "lazy_summary",
    "coarse_semantic_graph",
    "neighborhood_slice",
    "viewport_slice",
]
