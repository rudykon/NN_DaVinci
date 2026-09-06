"""Reviewable paper-layout suggestions that preserve manual constraints."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import hypot
from statistics import fmean, pstdev
from typing import Any

from .ir import GraphIR
from .labels import measure_text_width, node_label_lines
from .layout import LayoutEngine, LayoutResult
from .spatial import rectangles_overlap
from .themes import get_theme

OPTIMIZER_VERSION = "1.0"

PAPER_PRESETS: dict[str, dict[str, Any]] = {
    "compact": {"label_density": "compact", "rank_gap": 68.0, "node_gap": 24.0},
    "paper": {"label_density": "paper", "rank_gap": 88.0, "node_gap": 34.0},
    "detailed": {"label_density": "detailed", "rank_gap": 104.0, "node_gap": 44.0},
    "teaching": {"theme": "teaching", "label_density": "detailed", "rank_gap": 112.0, "node_gap": 52.0},
    "grayscale": {"theme": "grayscale", "label_density": "paper", "rank_gap": 90.0, "node_gap": 36.0},
    "colorblind": {"theme": "colorblind", "label_density": "paper", "rank_gap": 90.0, "node_gap": 36.0},
}


@dataclass(slots=True)
class PaperMetrics:
    node_overlap: int
    edge_node_collision: int
    crossing: int
    bend_count: int
    path_length: float
    symmetry: float
    whitespace_balance: float
    label_overflow: int
    minimum_font: float
    critical_edge_salience: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LayoutDiff:
    moved_nodes: dict[str, dict[str, list[float]]] = field(default_factory=dict)
    rerouted_edges: dict[str, dict[str, list[list[float]]]] = field(default_factory=dict)
    page_before: str = "fit-content"
    page_after: str = "fit-content"
    protected_nodes: list[str] = field(default_factory=list)
    protected_edges: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PaperSuggestion:
    id: str
    title: str
    rationale: str
    before: PaperMetrics
    after: PaperMetrics
    score_delta: float
    diff: LayoutDiff
    layout: LayoutResult
    warnings: list[str] = field(default_factory=list)
    optimizer_version: str = OPTIMIZER_VERSION

    def to_dict(self, *, include_layout: bool = True) -> dict[str, Any]:
        result = {
            "id": self.id,
            "title": self.title,
            "rationale": self.rationale,
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "score_delta": self.score_delta,
            "diff": asdict(self.diff),
            "warnings": list(self.warnings),
            "optimizer_version": self.optimizer_version,
        }
        if include_layout:
            result["layout"] = self.layout.to_dict()
        return result


def assess_paper_metrics(graph: GraphIR, layout: LayoutResult) -> PaperMetrics:
    placements = layout.nodes
    node_ids = list(placements)
    overlap = 0
    for index, first_id in enumerate(node_ids):
        first = placements[first_id]
        for second_id in node_ids[index + 1:]:
            second = placements[second_id]
            if rectangles_overlap(first, second):
                overlap += 1

    segments: list[tuple[str, tuple[float, float], tuple[float, float]]] = []
    bends = 0
    path_length = 0.0
    for edge_id, route in layout.edges.items():
        bends += max(0, len(route.points) - 2)
        for start, end in zip(route.points, route.points[1:]):
            segments.append((edge_id, start, end))
            path_length += hypot(end[0] - start[0], end[1] - start[1])

    crossings = 0
    edge_map = graph.edge_map()
    for index, (first_edge, start_a, end_a) in enumerate(segments):
        for second_edge, start_b, end_b in segments[index + 1:]:
            first_source = edge_map.get(first_edge)
            second_source = edge_map.get(second_edge)
            shared_endpoint = bool(
                first_source and second_source
                and {first_source.source, first_source.target}.intersection({second_source.source, second_source.target})
            )
            if first_edge != second_edge and not shared_endpoint and _segments_cross(start_a, end_a, start_b, end_b):
                crossings += 1

    edge_node = 0
    for edge_id, start, end in segments:
        endpoints = set()
        source_edge = edge_map.get(edge_id)
        if source_edge:
            endpoints = {source_edge.source, source_edge.target}
        for node_id, placement in placements.items():
            if node_id in endpoints:
                continue
            if _segment_intersects_rect(start, end, placement.x, placement.y, placement.width, placement.height):
                edge_node += 1

    rank_groups: dict[int, list[float]] = {}
    for placement in placements.values():
        rank_groups.setdefault(placement.rank, []).append(placement.y + placement.height / 2)
    symmetry_values = []
    for values in rank_groups.values():
        if len(values) > 1:
            center = fmean(values)
            distances = sorted(abs(value - center) for value in values)
            paired = [abs(distances[index] - distances[-index - 1]) for index in range(len(distances) // 2)]
            symmetry_values.extend(paired)
    symmetry = fmean(symmetry_values) if symmetry_values else 0.0

    centers_x = [placement.x + placement.width / 2 for placement in placements.values()]
    centers_y = [placement.y + placement.height / 2 for placement in placements.values()]
    whitespace = 0.0
    if centers_x and centers_y:
        mid_x = (min(centers_x) + max(centers_x)) / 2
        mid_y = (min(centers_y) + max(centers_y)) / 2
        quadrants = [0, 0, 0, 0]
        for x, y in zip(centers_x, centers_y):
            quadrants[(1 if x >= mid_x else 0) + (2 if y >= mid_y else 0)] += 1
        whitespace = pstdev(quadrants) / max(fmean(quadrants), 1.0)

    label_overflow = 0
    graph_nodes = graph.node_map()
    theme = get_theme("neurips")
    density = str(layout.metadata.get("label_density", "paper"))
    for node_id, placement in placements.items():
        node = graph_nodes.get(node_id)
        if node:
            maximum = max(20.0, placement.width - 2 * float(theme["node_padding"]))
            node_density = str(node.attributes.get("figure_panel_label_density", density))
            lines = node_label_lines(node, theme, density=node_density, max_width=maximum)
            horizontal = any(
                measure_text_width(line.text, max(10.0, float(theme["font_size"])) * line.font_scale, str(theme["font_family"]))
                > maximum + 0.25
                for line in lines
            )
            vertical = len(lines) * max(10.0, float(theme["font_size"])) * 1.12 > placement.height - 8.0
            if horizontal or vertical:
                label_overflow += 1

    paper = layout.metadata.get("paper", {})
    minimum_font = float(paper.get("final_body_font_pt", 9.0))
    critical = layout.metadata.get("critical_edges", [])
    if critical:
        salient = 0
        for item in critical:
            edge = edge_map.get(str(item.get("edge_id")))
            critical_route = layout.edges.get(str(item.get("edge_id")))
            if edge and critical_route and (edge.kind != "data" or edge.attributes.get("line_width", 0) >= 1.5 or critical_route.back_edge):
                salient += 1
        critical_salience = salient / len(critical)
    else:
        critical_salience = 1.0
    return PaperMetrics(
        node_overlap=overlap,
        edge_node_collision=edge_node,
        crossing=crossings,
        bend_count=bends,
        path_length=round(path_length, 3),
        symmetry=round(symmetry, 3),
        whitespace_balance=round(whitespace, 5),
        label_overflow=label_overflow,
        minimum_font=round(minimum_font, 3),
        critical_edge_salience=round(critical_salience, 5),
    )


class PaperOptimizer:
    def suggest(
        self,
        graph: GraphIR,
        layout: LayoutResult | dict[str, Any],
        style: dict[str, Any],
        *,
        page: str = "double-column",
        preset: str = "paper",
        maximum_candidates: int = 3,
    ) -> list[PaperSuggestion]:
        if isinstance(layout, dict):
            layout = LayoutResult.from_dict(layout)
        maximum_candidates = max(1, min(3, maximum_candidates))
        config = PAPER_PRESETS.get(preset, PAPER_PRESETS["paper"])
        before = assess_paper_metrics(graph, layout)
        algorithm = str(layout.metadata.get("algorithm", layout.engine if layout.engine in LayoutEngine.available() else "auto"))
        direction = layout.direction
        page_name = _page_alias(page)
        variants = [
            ("balanced", "Balance spacing and crossings", 1.0, 1.0, direction, page_name),
            ("readability", "Prioritize labels and minimum font", 1.18, 1.22, direction, page_name),
            ("compact", "Reduce path length and whitespace", 0.82, 0.78, direction, "wide-two-column" if page_name == "double-column" else page_name),
        ]
        suggestions: list[PaperSuggestion] = []
        for identifier, title, rank_factor, node_factor, candidate_direction, candidate_page in variants:
            page_key = _page_alias(candidate_page)
            page_config = _page_config(page_key, style.get("page", {}))
            candidate = LayoutEngine().layout(
                graph,
                algorithm=algorithm,
                direction=candidate_direction,
                node_width=float(style.get("node_width", 154)),
                node_height=float(style.get("node_height", 66)),
                rank_gap=float(config.get("rank_gap", 88)) * rank_factor,
                node_gap=float(config.get("node_gap", 34)) * node_factor,
                previous=layout,
                page=page_config,
                page_preset=page_key,
                font_size=float(style.get("font_size", 12)),
                minimum_font_pt=float(style.get("minimum_font_pt", 7)),
                label_density=str(config.get("label_density", "paper")),
            )
            _assert_protected(graph, layout, candidate)
            after = assess_paper_metrics(graph, candidate)
            diff = _layout_diff(graph, layout, candidate)
            score_delta = round(_score(before) - _score(after), 5)
            warnings = list(candidate.metadata.get("paper", {}).get("warnings", []))
            if after.minimum_font < 7.0:
                warnings.append(
                    f"The protected geometry can provide only {after.minimum_font:.2f} pt body text; unlock distant nodes, shorten manual routes, use wide-two-column, or split panels."
                )
            suggestions.append(PaperSuggestion(
                id=f"paper_{identifier}",
                title=title,
                rationale=_rationale(before, after),
                before=before,
                after=after,
                score_delta=score_delta,
                diff=diff,
                layout=candidate,
                warnings=list(dict.fromkeys(warnings)),
            ))
        suggestions.sort(key=lambda item: (-item.score_delta, -item.after.minimum_font, item.id))
        return suggestions[:maximum_candidates]

    def one_click_readability(
        self,
        graph: GraphIR,
        layout: LayoutResult | dict[str, Any],
        style: dict[str, Any],
        *,
        page: str = "double-column",
    ) -> PaperSuggestion:
        suggestions = self.suggest(graph, layout, style, page=page, preset="detailed", maximum_candidates=3)
        return max(suggestions, key=lambda item: (item.after.minimum_font >= 7.0, item.after.minimum_font, item.score_delta))


def apply_suggestion(current: LayoutResult | dict[str, Any], suggestion: PaperSuggestion | dict[str, Any]) -> tuple[LayoutResult, LayoutResult]:
    """Return ``(applied, undo_snapshot)``; neither argument is mutated."""
    before = LayoutResult.from_dict(current) if isinstance(current, dict) else LayoutResult.from_dict(current.to_dict())
    if isinstance(suggestion, dict):
        applied = LayoutResult.from_dict(suggestion["layout"])
    else:
        applied = LayoutResult.from_dict(suggestion.layout.to_dict())
    return applied, before


def proof_preview(layout: LayoutResult | dict[str, Any]) -> dict[str, Any]:
    if isinstance(layout, dict):
        layout = LayoutResult.from_dict(layout)
    paper = layout.metadata.get("paper", {})
    page = paper.get("page", {})
    return {
        "page": paper.get("selected_page", "fit-content"),
        "physical": {
            "width_pt": float(page.get("width") or layout.width) * 0.75,
            "height_pt": float(page.get("height") or layout.height) * 0.75,
            "margin_pt": float(page.get("margin", 0)) * 0.75,
        },
        "diagram_scale": float(paper.get("diagram_scale", 1.0)),
        "body_font_pt": float(paper.get("final_body_font_pt", 9.0)),
        "minimum_font_pt": float(paper.get("minimum_body_font_pt", 7.0)),
        "readable": float(paper.get("final_body_font_pt", 9.0)) >= float(paper.get("minimum_body_font_pt", 7.0)),
        "panels": list(layout.metadata.get("panels", [])),
        "warnings": list(paper.get("warnings", [])),
    }


def _layout_diff(graph: GraphIR, before: LayoutResult, after: LayoutResult) -> LayoutDiff:
    protected_nodes = {target for constraint in graph.constraints if constraint.locked and constraint.kind == "position" for target in constraint.target_ids}
    protected_edges = {target for constraint in graph.constraints if constraint.locked and constraint.kind == "edge-route" for target in constraint.target_ids}
    moved: dict[str, dict[str, list[float]]] = {}
    for node_id in sorted(set(before.nodes).intersection(after.nodes)):
        old, new = before.nodes[node_id], after.nodes[node_id]
        if abs(old.x - new.x) > 1e-6 or abs(old.y - new.y) > 1e-6:
            moved[node_id] = {"before": [old.x, old.y], "after": [new.x, new.y]}
    rerouted: dict[str, dict[str, list[list[float]]]] = {}
    for edge_id in sorted(set(before.edges).intersection(after.edges)):
        old_points = [list(point) for point in before.edges[edge_id].points]
        new_points = [list(point) for point in after.edges[edge_id].points]
        if old_points != new_points:
            rerouted[edge_id] = {"before": old_points, "after": new_points}
    return LayoutDiff(
        moved_nodes=moved,
        rerouted_edges=rerouted,
        page_before=str(before.metadata.get("paper", {}).get("selected_page", "fit-content")),
        page_after=str(after.metadata.get("paper", {}).get("selected_page", "fit-content")),
        protected_nodes=sorted(protected_nodes),
        protected_edges=sorted(protected_edges),
    )


def _assert_protected(graph: GraphIR, before: LayoutResult, after: LayoutResult) -> None:
    for constraint in graph.constraints:
        if not constraint.locked:
            continue
        if constraint.kind == "position":
            for target in constraint.target_ids:
                if target in before.nodes and target in after.nodes:
                    old, new = before.nodes[target], after.nodes[target]
                    if abs(old.x - new.x) > 1e-6 or abs(old.y - new.y) > 1e-6:
                        raise RuntimeError(f"Optimizer attempted to move locked node {target}")
        if constraint.kind == "edge-route":
            for target in constraint.target_ids:
                if (
                    target in before.edges
                    and target in after.edges
                    and before.edges[target].points[1:-1] != after.edges[target].points[1:-1]
                ):
                    raise RuntimeError(f"Optimizer attempted to overwrite manual route {target}")


def _score(metrics: PaperMetrics) -> float:
    return (
        40 * metrics.node_overlap
        + 32 * metrics.edge_node_collision
        + 8 * metrics.crossing
        + 1.5 * metrics.bend_count
        + 0.002 * metrics.path_length
        + 0.08 * metrics.symmetry
        + 12 * metrics.whitespace_balance
        + 24 * metrics.label_overflow
        + 25 * max(0.0, 7.0 - metrics.minimum_font)
        + 20 * (1.0 - metrics.critical_edge_salience)
    )


def _rationale(before: PaperMetrics, after: PaperMetrics) -> str:
    improvements = []
    for key in ("node_overlap", "edge_node_collision", "crossing", "bend_count", "label_overflow"):
        old, new = getattr(before, key), getattr(after, key)
        if new < old:
            improvements.append(f"{key} {old}→{new}")
    if after.minimum_font > before.minimum_font + 1e-6:
        improvements.append(f"minimum_font {before.minimum_font:.2f}→{after.minimum_font:.2f} pt")
    return "; ".join(improvements) if improvements else "Alternative geometry for visual comparison; protected edits are unchanged."


def _page_alias(page: str) -> str:
    return page


def _page_config(page: str, fallback: dict[str, Any]) -> dict[str, Any]:
    return dict(LayoutEngine.PAPER_PAGES.get(page, fallback))


def _segments_cross(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float], d: tuple[float, float]) -> bool:
    if len({a, b, c, d}) < 4:
        return False

    def orientation(p: tuple[float, float], q: tuple[float, float], r: tuple[float, float]) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    first = orientation(a, b, c)
    second = orientation(a, b, d)
    third = orientation(c, d, a)
    fourth = orientation(c, d, b)
    return first * second < -1e-9 and third * fourth < -1e-9


def _segment_intersects_rect(
    start: tuple[float, float], end: tuple[float, float], x: float, y: float, width: float, height: float,
) -> bool:
    if max(start[0], end[0]) < x or min(start[0], end[0]) > x + width or max(start[1], end[1]) < y or min(start[1], end[1]) > y + height:
        return False
    corners = [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]
    if x < start[0] < x + width and y < start[1] < y + height:
        return True
    return any(_segments_cross(start, end, corners[index], corners[(index + 1) % 4]) for index in range(4))


__all__ = [
    "OPTIMIZER_VERSION",
    "PAPER_PRESETS",
    "LayoutDiff",
    "PaperMetrics",
    "PaperOptimizer",
    "PaperSuggestion",
    "apply_suggestion",
    "assess_paper_metrics",
    "proof_preview",
]
