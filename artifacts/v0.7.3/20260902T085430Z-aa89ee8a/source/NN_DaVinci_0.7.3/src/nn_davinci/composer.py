"""Multi-panel paper figure composition with independent panel state."""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Iterable

from .errors import ValidationError
from .ir import Annotation, Edge, GraphIR, stable_id
from .layout import EdgeRoute, LayoutEngine, LayoutResult, NodePlacement
from .render import export_graph
from .semantic import SEMANTIC_LEVELS, VIEW_MODES, derive_semantic_view
from .themes import PAGE_PRESETS, get_theme

FIGURE_COMPOSER_VERSION = "1.2"
PANEL_IDS = tuple("ABCDEFGH")
COMPOSER_PAGE_MM = {
    "single-column": (88.0, 118.0),
    "double-column": (178.0, 118.0),
    "wide-two-column": (183.0, 111.0),
    "slide": (338.7, 190.5),
    "widescreen": (338.7, 190.5),
}


@dataclass(slots=True)
class FigurePanel:
    id: str
    title: str
    graph: GraphIR
    semantic_level: str = "block"
    semantic_view: str = "paper"
    layout: dict[str, Any] = field(default_factory=dict)
    layout_algorithm: str = "auto"
    label_density: str = "paper"
    locked_node_ids: list[str] = field(default_factory=list)
    manual_routes: dict[str, list[list[float]]] = field(default_factory=dict)
    annotations: list[dict[str, Any]] = field(default_factory=list)
    source_reference: dict[str, Any] = field(default_factory=dict)
    width_weight: float = 1.0
    mode: str = "schematic"
    locked: bool = False
    geometry: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.id not in PANEL_IDS:
            raise ValidationError(f"Panel ID {self.id!r} is invalid", hint="Use A through H.")
        if self.semantic_level not in SEMANTIC_LEVELS:
            raise ValidationError(f"Panel semantic level {self.semantic_level!r} is invalid")
        if self.semantic_view not in VIEW_MODES:
            raise ValidationError(f"Panel semantic view {self.semantic_view!r} is invalid")
        if not math.isfinite(self.width_weight) or self.width_weight <= 0:
            raise ValidationError("Panel width weight must be a positive finite number")
        if self.mode not in {"schematic", "tensor-geometry", "mixed"}:
            raise ValidationError(f"Panel mode {self.mode!r} is invalid")

    def resolved_graph(self) -> GraphIR:
        if not self.graph.nodes:
            return self.graph.copy()
        if self.graph.metadata.get("semantic_view"):
            return self.graph.copy()
        semantic = derive_semantic_view(self.graph)
        return semantic.materialize(self.graph, level=self.semantic_level, view=self.semantic_view)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["graph"] = self.graph.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FigurePanel":
        payload = dict(data)
        payload["graph"] = GraphIR.from_dict(payload["graph"])
        return cls(**payload)


@dataclass(slots=True)
class SemanticPanelConnection:
    id: str
    source_panel: str
    source_node: str
    target_panel: str
    target_node: str
    label: str = ""
    reason: str = "Conceptual relationship between figure panels; not a model data edge."

    @classmethod
    def create(
        cls,
        source_panel: str,
        source_node: str,
        target_panel: str,
        target_node: str,
        *,
        label: str = "",
    ) -> "SemanticPanelConnection":
        identity = f"{source_panel}:{source_node}->{target_panel}:{target_node}:{label}"
        return cls(stable_id("panel_connection", identity), source_panel, source_node, target_panel, target_node, label)


@dataclass(slots=True)
class FigureComposer:
    title: str
    panels: list[FigurePanel] = field(default_factory=list)
    page_preset: str = "double-column"
    arrangement: str = "grid"
    alignment: str = "baseline"
    equal_width: bool = True
    equal_height: bool = True
    gap: float = 28.0
    shared_legend: bool = True
    shared_colors: bool = True
    shared_font: str = "Inter, Arial, sans-serif"
    number_format: str = "human"
    theme: str = "neurips"
    connections: list[SemanticPanelConnection] = field(default_factory=list)
    composer_version: str = FIGURE_COMPOSER_VERSION
    paper_ready_required: bool = False
    _panel_layout_digests: dict[str, str] = field(default_factory=dict, repr=False)

    def validate(self) -> "FigureComposer":
        if self.composer_version.split(".", 1)[0] != FIGURE_COMPOSER_VERSION.split(".", 1)[0]:
            raise ValidationError(f"Unsupported Figure Composer version {self.composer_version!r}")
        ids = [panel.id for panel in self.panels]
        if len(ids) != len(set(ids)) or any(item not in PANEL_IDS for item in ids):
            raise ValidationError("Figure Composer panels must have unique IDs from A through H")
        if not 1 <= len(ids) <= 8:
            raise ValidationError("Figure Composer requires between one and eight panels")
        if self.page_preset not in COMPOSER_PAGE_MM:
            raise ValidationError(f"Unknown composer page preset {self.page_preset!r}")
        known = set(ids)
        for connection in self.connections:
            if connection.source_panel not in known or connection.target_panel not in known:
                raise ValidationError(f"Panel connection {connection.id!r} has a missing panel")
            if connection.source_panel == connection.target_panel:
                raise ValidationError("Cross-panel semantic connections must connect distinct panels")
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "composer_version": self.composer_version,
            "title": self.title,
            "panels": [panel.to_dict() for panel in self.panels],
            "page_preset": self.page_preset,
            "arrangement": self.arrangement,
            "alignment": self.alignment,
            "equal_width": self.equal_width,
            "equal_height": self.equal_height,
            "gap": self.gap,
            "shared_legend": self.shared_legend,
            "shared_colors": self.shared_colors,
            "shared_font": self.shared_font,
            "number_format": self.number_format,
            "theme": self.theme,
            "connections": [asdict(item) for item in self.connections],
            "paper_ready_required": self.paper_ready_required,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FigureComposer":
        payload = dict(data)
        payload["panels"] = [FigurePanel.from_dict(item) for item in payload.get("panels", [])]
        payload["connections"] = [SemanticPanelConnection(**item) for item in payload.get("connections", [])]
        return cls(**payload).validate()

    def panel(self, panel_id: str) -> FigurePanel:
        try:
            return next(panel for panel in self.panels if panel.id == panel_id)
        except StopIteration as exc:
            raise ValidationError(f"Figure panel {panel_id!r} does not exist") from exc

    def set_panel_layout(self, panel_id: str, layout: LayoutResult) -> None:
        panel = self.panel(panel_id)
        panel.layout = layout.to_dict()
        self._panel_layout_digests[panel_id] = _layout_digest(layout)

    def layout_panel(self, panel_id: str, *, force: bool = False) -> LayoutResult:
        panel = self.panel(panel_id)
        if panel.layout and not force:
            return LayoutResult.from_dict(panel.layout)
        graph = panel.resolved_graph()
        previous = LayoutResult.from_dict(panel.layout) if panel.layout else None
        layout = LayoutEngine().layout(
            graph,
            algorithm=panel.layout_algorithm,
            previous=previous,
            label_density=panel.label_density,
        )
        for node_id in panel.locked_node_ids:
            if node_id in layout.nodes:
                layout.nodes[node_id].locked = True
        for edge_id, points in panel.manual_routes.items():
            if edge_id in layout.edges:
                layout.edges[edge_id] = EdgeRoute([(float(point[0]), float(point[1])) for point in points])
        self.set_panel_layout(panel_id, layout)
        return layout

    def compose(self, *, relayout_panels: Iterable[str] = ()) -> tuple[GraphIR, LayoutResult, dict[str, Any]]:
        """Combine panels; only explicitly requested panels are re-laid out."""
        self.validate()
        relayout = set(relayout_panels)
        resolved: dict[str, GraphIR] = {}
        layouts: dict[str, LayoutResult] = {}
        for panel in self.panels:
            resolved[panel.id] = panel.resolved_graph()
        rows, columns = _grid(len(self.panels), self.arrangement)
        margin = 28.0
        target = dict(PAGE_PRESETS["widescreen" if self.page_preset == "slide" else self.page_preset])
        physical_width_mm, physical_height_mm = COMPOSER_PAGE_MM[self.page_preset]
        # Make viewBox and declared physical dimensions share one aspect ratio;
        # this prevents anisotropic text transforms in SVG/PDF.
        target["height"] = float(target["width"]) * physical_height_mm / physical_width_mm
        page_width = float(target["width"])
        page_height = float(target["height"])
        title_height = 34.0 if self.title else 0.0
        available_width = page_width - 2 * margin - (columns - 1) * self.gap
        column_weights = _column_weights(self.panels, resolved, rows, columns, self.equal_width)
        column_widths = [available_width * weight / sum(column_weights) for weight in column_weights]
        cell_height = (page_height - 2 * margin - title_height - (rows - 1) * self.gap) / rows
        column_x: list[float] = []
        cursor_x = margin
        for width in column_widths:
            column_x.append(cursor_x)
            cursor_x += width + self.gap
        panel_label_height = 26.0
        panel_inset = 12.0
        for index, panel in enumerate(self.panels):
            _, column = divmod(index, columns)
            content_width = max(80.0, column_widths[column] - 2 * panel_inset)
            content_height = max(80.0, cell_height - panel_label_height - 2 * panel_inset)
            force = panel.id in relayout and not panel.locked
            budget = [round(content_width, 3), round(content_height, 3)]
            cached_budget = panel.layout.get("metadata", {}).get("composer_budget") if panel.layout else None
            if cached_budget != budget and not panel.locked and not panel.locked_node_ids and not panel.manual_routes:
                force = True
            layouts[panel.id] = self._layout_panel_for_cell(
                panel,
                resolved[panel.id],
                content_width,
                content_height,
                force=force,
            )
        combined = GraphIR(name=self.title or "Composed paper figure")
        combined_layout = LayoutResult("figure-composer", "LR", width=page_width, height=page_height)
        panel_maps: dict[str, dict[str, str]] = {}
        panel_scales: dict[str, float] = {}
        panel_transforms: dict[str, dict[str, float]] = {}
        panel_boxes: dict[str, dict[str, float]] = {}
        panel_occupancy: dict[str, float] = {}
        digests_before = dict(self._panel_layout_digests)
        for index, panel in enumerate(self.panels):
            row, column = divmod(index, columns)
            graph, layout = resolved[panel.id], layouts[panel.id]
            cell_width = column_widths[column]
            content_width = max(80.0, cell_width - 2 * panel_inset)
            content_height = max(80.0, cell_height - panel_label_height - 2 * panel_inset)
            bbox = layout.metadata.get("paper", {}).get("content_bbox", [0.0, 0.0, layout.width, layout.height])
            natural_width = max(1.0, float(bbox[2]) - float(bbox[0]))
            natural_height = max(1.0, float(bbox[3]) - float(bbox[1]))
            scale = min(content_width / natural_width, content_height / natural_height, 1.0)
            panel_scales[panel.id] = scale
            used_width, used_height = natural_width * scale, natural_height * scale
            target_x = column_x[column] + panel_inset + (content_width - used_width) / 2
            target_y = margin + title_height + row * (cell_height + self.gap) + panel_label_height + panel_inset
            if self.alignment == "center":
                target_y += (content_height - used_height) / 2
            elif self.alignment == "bottom":
                target_y += content_height - used_height
            x = target_x - float(bbox[0]) * scale
            y = target_y - float(bbox[1]) * scale
            panel_transforms[panel.id] = {"x": x, "y": y, "scale": scale}
            mapping = _append_panel(combined, combined_layout, graph, layout, panel, x, y, scale)
            panel_maps[panel.id] = mapping
            label = f"{panel.id} — {panel.title}" if panel.title else panel.id
            panel_boxes[label] = {"x": column_x[column], "y": margin + title_height + row * (cell_height + self.gap), "width": cell_width, "height": cell_height}
            panel_occupancy[panel.id] = round(
                used_width * used_height / max(content_width * content_height, 1.0), 4
            )
        for connection in self.connections:
            source = panel_maps[connection.source_panel].get(connection.source_node)
            target_id = panel_maps[connection.target_panel].get(connection.target_node)
            if source is None or target_id is None:
                raise ValidationError(
                    f"Panel connection {connection.id!r} cannot resolve its node endpoints",
                    hint="Use node IDs from each panel's resolved semantic graph.",
                )
            edge = Edge.create(source, target_id, kind="semantic-connection", label=connection.label)
            edge.id = connection.id
            edge.attributes = {
                "dashed": True,
                "dash": "3 3",
                "semantic_connection": True,
                "not_model_data_edge": True,
                "reason": connection.reason,
            }
            combined.edges.append(edge)
            source_box, target_box = combined_layout.nodes[source], combined_layout.nodes[target_id]
            combined_layout.edges[edge.id] = EdgeRoute([
                (source_box.x + source_box.width, source_box.y + source_box.height / 2),
                (target_box.x, target_box.y + target_box.height / 2),
            ])
        combined.metadata["figure_composer"] = {
            "version": self.composer_version,
            "panel_count": len(self.panels),
            "page_preset": self.page_preset,
            "semantic_connections_are_data_edges": False,
            "paper_ready_required": self.paper_ready_required,
            "panel_modes": {panel.id: panel.mode for panel in self.panels},
            "maximum_panels": 8,
        }
        combined_layout.metadata.update({
            "panels": panel_boxes,
            "panel_scales": panel_scales,
            "panel_transforms": panel_transforms,
            "panel_content_occupancy": panel_occupancy,
            "panel_layout_digests": {panel.id: _layout_digest(layouts[panel.id]) for panel in self.panels},
            "unmodified_panel_layouts_stable": all(
                panel.id in relayout or panel.id not in digests_before or digests_before[panel.id] == _layout_digest(layouts[panel.id])
                for panel in self.panels
            ),
            "paper": {
                "selected_page": "widescreen" if self.page_preset == "slide" else self.page_preset,
                "page": target,
                "content_bbox": [margin, margin + title_height, page_width - margin, page_height - margin],
                "content_width": page_width - 2 * margin,
                "content_height": page_height - 2 * margin - title_height,
                "content_occupancy": round(
                    (page_width - 2 * margin) * (page_height - 2 * margin - title_height)
                    / max((page_width - 2 * margin) * (page_height - 2 * margin), 1.0),
                    4,
                ),
                "minimum_body_font_pt": 7.0,
                "body_font_px": self._publication_font_px() * min(
                    0.78 if panel.label_density == "detailed" else 0.84 for panel in self.panels
                ),
                "physical_width_mm": physical_width_mm,
                "physical_height_mm": physical_height_mm,
                "physical_scale": physical_width_mm / 25.4 * 96.0 / page_width,
                "final_body_font_pt": round(
                    self._publication_font_px()
                    * min(0.78 if panel.label_density == "detailed" else 0.84 for panel in self.panels)
                    * 0.75
                    * (physical_width_mm / 25.4 * 96.0 / page_width),
                    3,
                ),
                "readable": (
                    self._publication_font_px()
                    * min(0.78 if panel.label_density == "detailed" else 0.84 for panel in self.panels)
                    * 0.75
                    * (physical_width_mm / 25.4 * 96.0 / page_width) >= 7.0
                ),
                "precomposed_page": True,
                "warnings": [],
            },
        })
        proof = self.proof_preview(combined_layout)
        combined_layout.metadata["composer_proof"] = proof
        if self.paper_ready_required and not proof["paper_ready"]:
            raise ValidationError(
                "The composed figure cannot be marked paper-ready at 7 pt",
                hint="Use a coarser semantic level, abbreviate labels, or split the dense panel before export.",
                details={"proof": proof},
            )
        combined.validate()
        return combined, combined_layout, proof

    def _publication_font_px(self) -> float:
        target = PAGE_PRESETS["widescreen" if self.page_preset == "slide" else self.page_preset]
        physical_width_mm = COMPOSER_PAGE_MM[self.page_preset][0]
        root_scale = physical_width_mm / 25.4 * 96.0 / float(target["width"])
        smallest = min(0.78 if panel.label_density == "detailed" else 0.84 for panel in self.panels)
        required = 7.08 / max(0.75 * root_scale * smallest, 0.01)
        return round(max(float(get_theme(self.theme)["font_size"]), required), 2)

    def _layout_panel_for_cell(
        self,
        panel: FigurePanel,
        graph: GraphIR,
        width: float,
        height: float,
        *,
        force: bool,
    ) -> LayoutResult:
        if panel.layout and (not force or panel.locked):
            return LayoutResult.from_dict(panel.layout)
        theme = get_theme(self.theme, {"font_size": self._publication_font_px()})
        # Three compact operation nodes must fit across a half-width paper
        # panel.  The width is still expanded by real glyph wrapping below;
        # it is never made smaller by compressing the text itself.
        if panel.source_reference and len(graph.nodes) <= 7:
            node_width = min(220.0, max(180.0, width / 2.4))
        else:
            node_width = min(128.0, max(112.0, width / 3.55))
        node_height = 64.0 if panel.label_density == "compact" else 88.0
        previous = LayoutResult.from_dict(panel.layout) if panel.layout else None
        layout = LayoutEngine().layout(
            graph,
            algorithm=panel.layout_algorithm,
            previous=previous,
            label_density=panel.label_density,
            node_width=node_width,
            node_height=node_height,
            rank_gap=50.0,
            node_gap=22.0,
            # LayoutEngine subtracts a routing allowance before rank wrapping.
            # Add it to the private panel budget so the resulting node grid,
            # including its routes, targets the actual cell width.
            page={"width": width + 32.0, "height": height, "margin": 8.0},
            page_preset="composer-panel",
            font_size=float(theme["font_size"]),
            minimum_font_pt=7.0,
        )
        if not panel.locked_node_ids and not panel.manual_routes and not layout.groups:
            _balance_panel_whitespace(graph, layout, height)
        layout.metadata["composer_budget"] = [round(width, 3), round(height, 3)]
        for node_id in panel.locked_node_ids:
            if node_id in layout.nodes:
                layout.nodes[node_id].locked = True
        for edge_id, points in panel.manual_routes.items():
            if edge_id in layout.edges:
                layout.edges[edge_id] = EdgeRoute([(float(point[0]), float(point[1])) for point in points])
        self.set_panel_layout(panel.id, layout)
        return layout

    def proof_preview(self, layout: LayoutResult | None = None) -> dict[str, Any]:
        if layout is None:
            _, layout, _ = self.compose()
        width_mm, height_mm = COMPOSER_PAGE_MM[self.page_preset]
        paper = layout.metadata.get("paper", {})
        min_font = float(paper.get("final_body_font_pt", 9.0))
        px_to_mm = width_mm / max(layout.width, 1.0)
        min_line_pt = round(1.2 * px_to_mm * 72.0 / 25.4, 3)
        occupancy = float(paper.get("content_occupancy", 0.0))
        scales = layout.metadata.get("panel_scales", {})
        geometry_scale = min((float(value) for value in scales.values()), default=1.0)
        panel_occupancy = layout.metadata.get("panel_content_occupancy", {})
        # Panel geometry may adapt while SVG glyphs remain unscaled.  Actual
        # label fit is checked from real glyph advances and then independently
        # re-measured in Chrome; geometry scale is diagnostic, not font scale.
        readable = min_font >= 7.0
        whitespace_ok = all(0.28 <= float(value) <= 1.0 for value in panel_occupancy.values())
        warning = None
        if not readable:
            warning = (
                f"The densest panel needs {geometry_scale:.3f}× geometry scaling; "
                "use a coarser semantic level or split the panel instead of shrinking text."
            )
        elif not whitespace_ok:
            warning = "At least one panel has abnormal unused space; adjust panel ratios or split the composition."
        return {
            "page_preset": self.page_preset,
            "width_mm": width_mm,
            "height_mm": height_mm,
            "width_in": round(width_mm / 25.4, 3),
            "height_in": round(height_mm / 25.4, 3),
            "minimum_font_pt": min_font,
            "minimum_line_width_pt": min_line_pt,
            "page_occupancy": occupancy,
            "panel_content_occupancy": panel_occupancy,
            "minimum_geometry_scale": round(geometry_scale, 4),
            "readable_at_7pt": readable,
            "balanced_whitespace": whitespace_ok,
            "paper_ready": warning is None,
            "readability_explanation": warning,
            "panel_count": len(self.panels),
        }

    def export(
        self,
        output: str | Path,
        *,
        formats: Iterable[str] = ("svg", "pdf", "tikz", "png", "eps", "pptx"),
        tikz_panels: bool = False,
    ) -> list[Path]:
        graph, layout, proof = self.compose()
        publication_font = self._publication_font_px()
        theme = get_theme(
            self.theme,
            {
                "font_family": self.shared_font,
                "font_size": publication_font,
                "title_size": max(18.0, publication_font + 3.0),
            },
            page="widescreen" if self.page_preset == "slide" else self.page_preset,
        )
        outputs = export_graph(
            graph,
            layout,
            theme,
            output,
            formats=formats,
            title=self.title,
            show_legend=self.shared_legend,
            publication_manifest={"figure_composer": self.composer_version, "proof": proof},
        )
        if tikz_panels:
            stem = Path(output).with_suffix("")
            for panel in self.panels:
                panel_graph = panel.resolved_graph()
                panel_layout = self.layout_panel(panel.id)
                outputs.extend(export_graph(panel_graph, panel_layout, theme, stem.parent / f"{stem.name}_{panel.id}.tex", formats=["tikz"], title=panel.title))
        return outputs


def _grid(count: int, arrangement: str) -> tuple[int, int]:
    if arrangement in {"horizontal", "overview-detail"}:
        return 1, count
    if arrangement == "vertical":
        return count, 1
    columns = 1 if count == 1 else 2
    return math.ceil(count / columns), columns


def _column_weights(
    panels: list[FigurePanel],
    resolved: dict[str, GraphIR],
    rows: int,
    columns: int,
    equal_width: bool,
) -> list[float]:
    if equal_width or columns == 1:
        return [1.0] * columns
    weights = [1.0] * columns
    for column in range(columns):
        column_panels = [panel for index, panel in enumerate(panels) if index % columns == column]
        complexities = [max(1.0, math.sqrt(len(resolved[panel.id].nodes))) * panel.width_weight for panel in column_panels]
        weights[column] = max(complexities, default=1.0)
    total = sum(weights)
    # Avoid starving an overview merely because a detail panel has more nodes.
    return [min(0.75 * total, max(0.25 * total, value)) for value in weights]


def _balance_panel_whitespace(graph: GraphIR, layout: LayoutResult, target_height: float) -> None:
    """Distribute row gaps without scaling nodes or glyphs.

    Sparse semantic summaries otherwise sit at the top of a full-height panel.
    Only whitespace changes; node dimensions and text transforms remain 1.0.
    """
    if len(layout.nodes) < 2:
        return
    paper = layout.metadata.get("paper", {})
    bbox = paper.get("content_bbox", [0.0, 0.0, layout.width, layout.height])
    natural_height = max(1.0, float(bbox[3]) - float(bbox[1]))
    desired_height = min(target_height, max(natural_height, target_height * 0.78))
    if desired_height <= natural_height + 2.0:
        return
    rows: dict[float, list[NodePlacement]] = {}
    for placement in layout.nodes.values():
        rows.setdefault(round(placement.y, 3), []).append(placement)
    ordered = [rows[key] for key in sorted(rows)]
    if len(ordered) < 2:
        return
    row_heights = [max(item.height for item in row) for row in ordered]
    gap = max(18.0, (desired_height - sum(row_heights)) / (len(ordered) - 1))
    cursor = float(bbox[1])
    for row, row_height in zip(ordered, row_heights):
        for placement in row:
            placement.y = cursor + (row_height - placement.height) / 2
        cursor += row_height + gap
    engine = LayoutEngine()
    layout.edges.clear()
    engine._route_edges_for_paper(graph, layout)
    x_values = [value for placement in layout.nodes.values() for value in (placement.x, placement.x + placement.width)]
    y_values = [value for placement in layout.nodes.values() for value in (placement.y, placement.y + placement.height)]
    for route in layout.edges.values():
        x_values.extend(point[0] for point in route.points)
        y_values.extend(point[1] for point in route.points)
    refreshed = [min(x_values), min(y_values), max(x_values), max(y_values)]
    paper.update({
        "content_bbox": refreshed,
        "content_width": refreshed[2] - refreshed[0],
        "content_height": refreshed[3] - refreshed[1],
    })


def _append_panel(
    destination: GraphIR,
    destination_layout: LayoutResult,
    graph: GraphIR,
    layout: LayoutResult,
    panel: FigurePanel,
    offset_x: float,
    offset_y: float,
    scale: float,
) -> dict[str, str]:
    node_map = {node.id: f"panel_{panel.id.lower()}__{node.id}" for node in graph.nodes}
    port_map: dict[str, str] = {}
    for node in graph.nodes:
        for port in [*node.inputs, *node.outputs]:
            port_map[port.id] = f"panel_{panel.id.lower()}__{port.id}"
    group_map = {group.id: f"panel_{panel.id.lower()}__{group.id}" for group in graph.subgraphs}
    edge_map = {edge.id: f"panel_{panel.id.lower()}__{edge.id}" for edge in graph.edges}
    for source_node in graph.nodes:
        node = copy.deepcopy(source_node)
        node.id = node_map[source_node.id]
        if node.parent is not None:
            node.parent = group_map.get(node.parent, node_map.get(node.parent, node.parent))
        node.inputs = [copy.deepcopy(port) for port in source_node.inputs]
        node.outputs = [copy.deepcopy(port) for port in source_node.outputs]
        for port in [*node.inputs, *node.outputs]:
            port.id = port_map[port.id]
        node.attributes = {
            **node.attributes,
            "figure_panel": panel.id,
            "panel_source_node": source_node.id,
            "figure_panel_label_density": panel.label_density,
        }
        node.source = {**node.source, "figure_panel": panel.id, "panel_source_node": source_node.id}
        destination.nodes.append(node)
    for source_edge in graph.edges:
        edge = copy.deepcopy(source_edge)
        edge.id = edge_map[source_edge.id]
        edge.source = node_map[source_edge.source]
        edge.target = node_map[source_edge.target]
        edge.source_port = port_map.get(source_edge.source_port or "")
        edge.target_port = port_map.get(source_edge.target_port or "")
        edge.attributes = {**edge.attributes, "figure_panel": panel.id, "panel_source_edge": source_edge.id}
        destination.edges.append(edge)
    for source_group in graph.subgraphs:
        group = copy.deepcopy(source_group)
        group.id = group_map[source_group.id]
        group.node_ids = [node_map[item] for item in source_group.node_ids]
        group.parent = group_map.get(source_group.parent or "")
        group.attributes = {**group.attributes, "figure_panel": panel.id}
        destination.subgraphs.append(group)
    for source_annotation in graph.annotations:
        annotation = copy.deepcopy(source_annotation)
        annotation.id = f"panel_{panel.id.lower()}__{source_annotation.id}"
        annotation.target_ids = [node_map.get(item, edge_map.get(item, group_map.get(item, item))) for item in source_annotation.target_ids]
        annotation.panel = panel.id
        annotation.geometry = {
            **annotation.geometry,
            "x": offset_x + float(annotation.geometry.get("x", 0.0)) * scale,
            "y": offset_y + float(annotation.geometry.get("y", 0.0)) * scale,
        }
        destination.annotations.append(annotation)
    for item in panel.annotations:
        annotation = Annotation(**item)
        annotation.id = f"panel_{panel.id.lower()}__{annotation.id}"
        annotation.target_ids = [node_map.get(target, edge_map.get(target, group_map.get(target, target))) for target in annotation.target_ids]
        annotation.panel = panel.id
        annotation.geometry = {
            **annotation.geometry,
            "x": offset_x + float(annotation.geometry.get("x", 0.0)) * scale,
            "y": offset_y + float(annotation.geometry.get("y", 0.0)) * scale,
        }
        destination.annotations.append(annotation)
    for node_id, placement in layout.nodes.items():
        destination_layout.nodes[node_map[node_id]] = NodePlacement(
            offset_x + placement.x * scale,
            offset_y + placement.y * scale,
            placement.width * scale,
            placement.height * scale,
            placement.rank,
            placement.order,
            placement.locked,
            panel.id,
        )
    for edge_id, route in layout.edges.items():
        destination_layout.edges[edge_map[edge_id]] = EdgeRoute(
            [(offset_x + x * scale, offset_y + y * scale) for x, y in route.points],
            route.back_edge,
        )
    for group_id, box in layout.groups.items():
        destination_layout.groups[group_map[group_id]] = {
            "x": offset_x + float(box["x"]) * scale,
            "y": offset_y + float(box["y"]) * scale,
            "width": float(box["width"]) * scale,
            "height": float(box["height"]) * scale,
        }
    return node_map


def _layout_digest(layout: LayoutResult) -> str:
    return sha256(json.dumps(layout.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


__all__ = [
    "COMPOSER_PAGE_MM",
    "FIGURE_COMPOSER_VERSION",
    "PANEL_IDS",
    "FigureComposer",
    "FigurePanel",
    "SemanticPanelConnection",
]
