"""Versioned, deterministic IR for scientific-figure presentation.

Figure IR is deliberately separate from :mod:`nn_davinci.ir`.  Graph IR is
the model-evidence record; Figure IR is an editable visual document.  Visual
objects therefore carry either source provenance or an explicit
``author_annotation`` marker and can never silently become model facts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
import math
from typing import Any, Iterable, Iterator

from .errors import ValidationError
from .ir import GraphIR, TensorSpec, stable_id


FIGURE_IR_VERSION = "1.0"
PANEL_MODES = frozenset({"schematic", "tensor-geometry", "mixed"})
LAYER_ROLES = frozenset({
    "model-data", "semantic-annotation", "author-annotation", "legend-caption",
})
OBJECT_KINDS = frozenset({
    "node-glyph", "tensor-glyph", "operator-glyph", "edge", "annotation",
    "title", "caption", "legend", "equation", "image", "callout", "guide",
    "bracket", "region", "inset", "panel-label", "external-vector-group",
})
PROVENANCE_KINDS = frozenset({
    "graph_ir", "semantic_view", "source", "template", "author_annotation",
    "external_vector", "unknown",
})
CONSTRAINT_KINDS = frozenset({
    "align-left", "align-center-x", "align-right", "align-top",
    "align-center-y", "align-bottom", "equal-gap-x", "equal-gap-y",
    "snap-page", "snap-column", "snap-baseline", "snap-object", "pin",
})

PAGE_PRESETS_MM: dict[str, tuple[float, float]] = {
    "single-column": (88.0, 118.0),
    "double-column": (178.0, 118.0),
    "178mm": (178.0, 118.0),
    "letter": (215.9, 279.4),
    "a4": (210.0, 297.0),
    "widescreen": (338.67, 190.5),
}

DEFAULT_DESIGN_TOKENS: dict[str, Any] = {
    "font.family": "DejaVu Sans, Arial, sans-serif",
    "font.size.pt": 9.0,
    "font.minimum.pt": 7.0,
    "font.weight": 500,
    "line.width.pt": 0.8,
    "line.data.color": "#334155",
    "line.annotation.color": "#7c3aed",
    "line.annotation.dash": "4 3",
    "corner.radius.pt": 3.0,
    "arrow.kind": "end",
    "arrow.size.pt": 4.0,
    "color.background": "#ffffff",
    "color.foreground": "#0f172a",
    "color.tensor.front": "#dbeafe",
    "color.tensor.top": "#bfdbfe",
    "color.tensor.side": "#93c5fd",
    "color.operator": "#f8fafc",
    "opacity": 1.0,
    "guide.margin.color": "#94a3b8",
    "guide.column.color": "#cbd5e1",
    "guide.baseline.color": "#e2e8f0",
}


def _finite(value: Any, *, name: str, minimum: float | None = None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"Figure IR {name} must be numeric") from exc
    if not math.isfinite(number) or (minimum is not None and number < minimum):
        raise ValidationError(f"Figure IR {name} must be finite and >= {minimum}")
    return number


def _ordered(items: Iterable[Any]) -> list[Any]:
    return sorted(items, key=lambda item: (int(getattr(item, "order", 0)), str(getattr(item, "id", ""))))


@dataclass(slots=True)
class FigureProvenance:
    kind: str
    source_id: str = ""
    graph_ir_ids: list[str] = field(default_factory=list)
    source_locator: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    author_annotation: bool = False

    @classmethod
    def author(cls, reason: str = "Author-created visual annotation.") -> "FigureProvenance":
        return cls("author_annotation", reason=reason, author_annotation=True)

    @classmethod
    def unknown(cls, reason: str) -> "FigureProvenance":
        return cls("unknown", reason=reason)

    def validate(self) -> "FigureProvenance":
        if self.kind not in PROVENANCE_KINDS:
            raise ValidationError(f"Unsupported Figure IR provenance kind {self.kind!r}")
        if self.author_annotation != (self.kind == "author_annotation"):
            raise ValidationError("author_annotation must be explicit and may only accompany author_annotation provenance")
        if self.kind in {"unknown", "author_annotation", "external_vector"} and not self.reason.strip():
            raise ValidationError(f"Figure provenance {self.kind!r} requires a reason")
        if self.kind in {"graph_ir", "semantic_view"} and not (self.graph_ir_ids or self.source_id):
            raise ValidationError(f"Figure provenance {self.kind!r} requires Graph IR evidence IDs")
        return self


@dataclass(slots=True)
class FigureStyle:
    token_refs: dict[str, str] = field(default_factory=dict)
    overrides: dict[str, Any] = field(default_factory=dict)

    def resolved(self, tokens: dict[str, Any]) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for property_name, token_name in sorted(self.token_refs.items()):
            if token_name not in tokens:
                raise ValidationError(f"Figure style references missing token {token_name!r}")
            values[property_name] = tokens[token_name]
        values.update(self.overrides)
        return values


@dataclass(slots=True)
class FigureConstraint:
    kind: str
    target_ids: list[str]
    value: Any = None
    locked: bool = False

    def validate(self) -> "FigureConstraint":
        if self.kind not in CONSTRAINT_KINDS:
            raise ValidationError(f"Unsupported Figure IR constraint {self.kind!r}")
        if not self.target_ids:
            raise ValidationError("Figure IR constraints require at least one target")
        return self


@dataclass(slots=True)
class FigureObject:
    id: str
    kind: str
    name: str
    geometry: dict[str, Any]
    provenance: FigureProvenance
    style: FigureStyle = field(default_factory=FigureStyle)
    locked: bool = False
    visible: bool = True
    manual_route: list[list[float]] = field(default_factory=list)
    constraints: list[FigureConstraint] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    order: int = 0

    @classmethod
    def create(
        cls,
        kind: str,
        name: str,
        geometry: dict[str, Any],
        provenance: FigureProvenance,
        **kwargs: Any,
    ) -> "FigureObject":
        identity = str(kwargs.pop("identity", f"{kind}:{name}:{json.dumps(geometry, sort_keys=True)}"))
        return cls(stable_id("figure_object", identity), kind, name, geometry, provenance, **kwargs)

    def validate(self) -> "FigureObject":
        if self.kind not in OBJECT_KINDS:
            raise ValidationError(f"Unsupported Figure IR object kind {self.kind!r}")
        if not self.id or not self.name:
            raise ValidationError("Figure IR objects require non-empty IDs and names")
        self.provenance.validate()
        for key in ("x", "y", "width", "height"):
            if key in self.geometry:
                self.geometry[key] = _finite(self.geometry[key], name=f"object {self.id} geometry.{key}", minimum=0.0 if key in {"width", "height"} else None)
        if self.manual_route:
            if self.kind not in {"edge", "annotation", "callout", "guide"}:
                raise ValidationError(f"Object {self.id!r} cannot carry a manual route")
            for point in self.manual_route:
                if not isinstance(point, list) or len(point) != 2:
                    raise ValidationError(f"Object {self.id!r} has a malformed manual route")
                _finite(point[0], name="manual route x")
                _finite(point[1], name="manual route y")
        for constraint in self.constraints:
            constraint.validate()
        for shape_key in ("tensor_shape", "author_shape_override"):
            shape = self.metadata.get(shape_key)
            if shape is None:
                continue
            if self.kind != "tensor-glyph" or not isinstance(shape, list):
                raise ValidationError(f"{shape_key} metadata is only valid on tensor glyphs")
            if any(not (isinstance(dim, int) or isinstance(dim, str) or dim is None) for dim in shape):
                raise ValidationError("Tensor glyph dimensions must be integers, symbols, or null")
        author_shape = self.metadata.get("author_shape_override")
        if author_shape is not None:
            expected_label = "[" + ", ".join("?" if dim is None else str(dim) for dim in author_shape) + "]"
            if self.metadata.get("author_shape_override_label") != expected_label:
                raise ValidationError("Tensor author shape override label must exactly match its dimensions")
            if self.metadata.get("shape_label_origin") != "author_override":
                raise ValidationError("Tensor author shape override must declare shape_label_origin=author_override")
        return self


@dataclass(slots=True)
class FigureGroup:
    id: str
    name: str
    object_ids: list[str] = field(default_factory=list)
    provenance: FigureProvenance = field(default_factory=FigureProvenance.author)
    locked: bool = False
    visible: bool = True
    order: int = 0

    def validate(self, known_objects: set[str]) -> "FigureGroup":
        self.provenance.validate()
        missing = set(self.object_ids) - known_objects
        if missing:
            raise ValidationError(f"Figure group {self.id!r} references missing objects {sorted(missing)!r}")
        return self


@dataclass(slots=True)
class FigureLayer:
    id: str
    name: str
    role: str
    objects: list[FigureObject] = field(default_factory=list)
    groups: list[FigureGroup] = field(default_factory=list)
    visible: bool = True
    locked: bool = False
    order: int = 0

    def validate(self) -> "FigureLayer":
        if self.role not in LAYER_ROLES:
            raise ValidationError(f"Unsupported Figure IR layer role {self.role!r}")
        ids = [item.id for item in self.objects]
        if len(ids) != len(set(ids)):
            raise ValidationError(f"Figure layer {self.id!r} has duplicate object IDs")
        for item in self.objects:
            item.validate()
        group_ids = [item.id for item in self.groups]
        if len(group_ids) != len(set(group_ids)):
            raise ValidationError(f"Figure layer {self.id!r} has duplicate group IDs")
        known = set(ids)
        claimed: set[str] = set()
        for group in self.groups:
            group.validate(known)
            overlap = claimed.intersection(group.object_ids)
            if overlap:
                raise ValidationError(f"Figure objects may belong to only one group: {sorted(overlap)!r}")
            claimed.update(group.object_ids)
        return self


@dataclass(slots=True)
class FigurePanel:
    id: str
    label: str
    title: str
    mode: str
    geometry: dict[str, float]
    layers: list[FigureLayer] = field(default_factory=list)
    constraints: list[FigureConstraint] = field(default_factory=list)
    locked: bool = False
    layout_mode: str = "grid"
    order: int = 0

    def validate(self) -> "FigurePanel":
        if self.mode not in PANEL_MODES:
            raise ValidationError(f"Unsupported Figure IR panel mode {self.mode!r}")
        if self.label not in tuple("ABCDEFGH"):
            raise ValidationError("Figure IR panel labels must be A through H")
        for key in ("x", "y", "width", "height"):
            if key not in self.geometry:
                raise ValidationError(f"Figure panel {self.id!r} is missing geometry.{key}")
            self.geometry[key] = _finite(self.geometry[key], name=f"panel {self.id} geometry.{key}", minimum=0.0 if key in {"width", "height"} else None)
        layer_ids = [item.id for item in self.layers]
        if len(layer_ids) != len(set(layer_ids)):
            raise ValidationError(f"Figure panel {self.id!r} has duplicate layer IDs")
        for layer in self.layers:
            layer.validate()
        for constraint in self.constraints:
            constraint.validate()
        return self


@dataclass(slots=True)
class FigurePage:
    id: str
    title: str
    width_mm: float
    height_mm: float
    panels: list[FigurePanel] = field(default_factory=list)
    margin_mm: float = 4.0
    columns: int = 2
    column_gap_mm: float = 4.0
    baseline_grid_pt: float = 4.0
    order: int = 0

    def validate(self) -> "FigurePage":
        self.width_mm = _finite(self.width_mm, name="page width_mm", minimum=1.0)
        self.height_mm = _finite(self.height_mm, name="page height_mm", minimum=1.0)
        self.margin_mm = _finite(self.margin_mm, name="page margin_mm", minimum=0.0)
        self.column_gap_mm = _finite(self.column_gap_mm, name="page column_gap_mm", minimum=0.0)
        self.baseline_grid_pt = _finite(self.baseline_grid_pt, name="page baseline_grid_pt", minimum=1.0)
        if not 1 <= int(self.columns) <= 12:
            raise ValidationError("Figure page columns must be between 1 and 12")
        if not 1 <= len(self.panels) <= 8:
            raise ValidationError("Figure pages require between one and eight panels")
        labels = [panel.label for panel in self.panels]
        ids = [panel.id for panel in self.panels]
        if len(labels) != len(set(labels)) or len(ids) != len(set(ids)):
            raise ValidationError("Figure page panel IDs and labels must be unique")
        for panel in self.panels:
            panel.validate()
        return self


@dataclass(slots=True)
class FigureIR:
    name: str
    pages: list[FigurePage]
    design_tokens: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_DESIGN_TOKENS))
    theme: str = "neurips"
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = FIGURE_IR_VERSION

    def validate(self) -> "FigureIR":
        if str(self.schema_version).split(".", 1)[0] != FIGURE_IR_VERSION.split(".", 1)[0]:
            raise ValidationError(
                f"Figure IR major version {self.schema_version!r} is incompatible with {FIGURE_IR_VERSION!r}"
            )
        if not self.name.strip() or not self.pages:
            raise ValidationError("Figure IR requires a name and at least one page")
        required_tokens = set(DEFAULT_DESIGN_TOKENS)
        missing_tokens = required_tokens - set(self.design_tokens)
        if missing_tokens:
            raise ValidationError(f"Figure IR is missing design tokens {sorted(missing_tokens)!r}")
        minimum_font = _finite(self.design_tokens["font.minimum.pt"], name="minimum font", minimum=7.0)
        font_size = _finite(self.design_tokens["font.size.pt"], name="font size", minimum=minimum_font)
        self.design_tokens["font.minimum.pt"] = minimum_font
        self.design_tokens["font.size.pt"] = font_size
        _finite(self.design_tokens["line.width.pt"], name="line width", minimum=0.1)
        _finite(self.design_tokens["corner.radius.pt"], name="corner radius", minimum=0.0)
        _finite(self.design_tokens["arrow.size.pt"], name="arrow size", minimum=0.5)
        page_ids = [item.id for item in self.pages]
        if len(page_ids) != len(set(page_ids)):
            raise ValidationError("Figure IR page IDs must be unique")
        all_ids: list[str] = []
        for page in self.pages:
            page.validate()
            all_ids.append(page.id)
            for panel in page.panels:
                all_ids.append(panel.id)
                for layer in panel.layers:
                    all_ids.append(layer.id)
                    all_ids.extend(group.id for group in layer.groups)
                    all_ids.extend(item.id for item in layer.objects)
        if len(all_ids) != len(set(all_ids)):
            raise ValidationError("Figure IR IDs must be globally unique")
        known_ids = set(all_ids)
        for constraint in self.iter_constraints():
            missing = set(constraint.target_ids) - known_ids
            if missing:
                raise ValidationError(f"Figure constraint references missing IDs {sorted(missing)!r}")
        return self

    def iter_panels(self) -> Iterator[FigurePanel]:
        for page in _ordered(self.pages):
            yield from _ordered(page.panels)

    def iter_layers(self) -> Iterator[FigureLayer]:
        for panel in self.iter_panels():
            yield from _ordered(panel.layers)

    def iter_objects(self, *, visible_only: bool = False) -> Iterator[FigureObject]:
        for layer in self.iter_layers():
            if visible_only and not layer.visible:
                continue
            for item in _ordered(layer.objects):
                if not visible_only or item.visible:
                    yield item

    def iter_constraints(self) -> Iterator[FigureConstraint]:
        for panel in self.iter_panels():
            yield from panel.constraints
            for layer in panel.layers:
                for item in layer.objects:
                    yield from item.constraints

    def find_object(self, object_id: str) -> tuple[FigurePanel, FigureLayer, FigureObject]:
        for panel in self.iter_panels():
            for layer in panel.layers:
                for item in layer.objects:
                    if item.id == object_id:
                        return panel, layer, item
        raise ValidationError(f"Figure object {object_id!r} does not exist")

    def move_object(self, object_id: str, target_layer_id: str, *, order: int | None = None) -> None:
        source_panel, source_layer, item = self.find_object(object_id)
        destination: FigureLayer | None = None
        destination_panel: FigurePanel | None = None
        for panel in self.iter_panels():
            for layer in panel.layers:
                if layer.id == target_layer_id:
                    destination, destination_panel = layer, panel
        if destination is None or destination_panel is None:
            raise ValidationError(f"Target Figure layer {target_layer_id!r} does not exist")
        if source_layer.locked or destination.locked or item.locked:
            raise ValidationError("Locked Figure objects or layers cannot be moved")
        if source_panel.id != destination_panel.id:
            raise ValidationError("Objects cannot cross panels by changing layer; move the panel object explicitly")
        for group in source_layer.groups:
            if object_id in group.object_ids:
                group.object_ids.remove(object_id)
        source_layer.objects.remove(item)
        item.order = int(order if order is not None else len(destination.objects))
        destination.objects.append(item)
        self.validate()

    def to_dict(self) -> dict[str, Any]:
        def object_dict(item: FigureObject) -> dict[str, Any]:
            return asdict(item)

        def layer_dict(layer: FigureLayer) -> dict[str, Any]:
            result = asdict(layer)
            result["objects"] = [object_dict(item) for item in _ordered(layer.objects)]
            result["groups"] = [asdict(item) for item in _ordered(layer.groups)]
            return result

        def panel_dict(panel: FigurePanel) -> dict[str, Any]:
            result = asdict(panel)
            result["layers"] = [layer_dict(item) for item in _ordered(panel.layers)]
            return result

        def page_dict(page: FigurePage) -> dict[str, Any]:
            result = asdict(page)
            result["panels"] = [panel_dict(item) for item in _ordered(page.panels)]
            return result

        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "pages": [page_dict(item) for item in _ordered(self.pages)],
            "design_tokens": {key: self.design_tokens[key] for key in sorted(self.design_tokens)},
            "theme": self.theme,
            "metadata": self.metadata,
        }

    def canonical_json(self) -> str:
        self.validate()
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FigureIR":
        def provenance(value: dict[str, Any]) -> FigureProvenance:
            return FigureProvenance(**value)

        def style(value: dict[str, Any] | None) -> FigureStyle:
            return FigureStyle(**(value or {}))

        def constraint(value: dict[str, Any]) -> FigureConstraint:
            return FigureConstraint(**value)

        def object_from(value: dict[str, Any]) -> FigureObject:
            payload = dict(value)
            payload["provenance"] = provenance(payload["provenance"])
            payload["style"] = style(payload.get("style"))
            payload["constraints"] = [constraint(item) for item in payload.get("constraints", [])]
            return FigureObject(**payload)

        def group_from(value: dict[str, Any]) -> FigureGroup:
            payload = dict(value)
            payload["provenance"] = provenance(payload.get("provenance", asdict(FigureProvenance.author())))
            return FigureGroup(**payload)

        def layer_from(value: dict[str, Any]) -> FigureLayer:
            payload = dict(value)
            payload["objects"] = [object_from(item) for item in payload.get("objects", [])]
            payload["groups"] = [group_from(item) for item in payload.get("groups", [])]
            return FigureLayer(**payload)

        def panel_from(value: dict[str, Any]) -> FigurePanel:
            payload = dict(value)
            payload["layers"] = [layer_from(item) for item in payload.get("layers", [])]
            payload["constraints"] = [constraint(item) for item in payload.get("constraints", [])]
            return FigurePanel(**payload)

        def page_from(value: dict[str, Any]) -> FigurePage:
            payload = dict(value)
            payload["panels"] = [panel_from(item) for item in payload.get("panels", [])]
            return FigurePage(**payload)

        payload = dict(data)
        version = str(payload.get("schema_version", FIGURE_IR_VERSION))
        if version.split(".", 1)[0] != FIGURE_IR_VERSION.split(".", 1)[0]:
            raise ValidationError(f"Unsupported Figure IR schema {version!r}")
        payload["schema_version"] = FIGURE_IR_VERSION
        payload["pages"] = [page_from(item) for item in payload.get("pages", [])]
        tokens = dict(DEFAULT_DESIGN_TOKENS)
        tokens.update(payload.get("design_tokens", {}))
        payload["design_tokens"] = tokens
        return cls(**payload).validate()


def default_layers(panel_id: str) -> list[FigureLayer]:
    definitions = (
        ("model-data", "Model data"),
        ("semantic-annotation", "Semantic annotation"),
        ("author-annotation", "Author annotation"),
        ("legend-caption", "Legend / Caption"),
    )
    return [
        FigureLayer(stable_id("figure_layer", f"{panel_id}:{role}"), name, role, order=index)
        for index, (role, name) in enumerate(definitions)
    ]


def new_figure(
    name: str,
    *,
    page_preset: str = "double-column",
    panel_modes: Iterable[str] = ("schematic",),
) -> FigureIR:
    if page_preset not in PAGE_PRESETS_MM:
        raise ValidationError(f"Unknown Figure page preset {page_preset!r}")
    width, height = PAGE_PRESETS_MM[page_preset]
    modes = list(panel_modes)
    if not 1 <= len(modes) <= 8:
        raise ValidationError("New figures require between one and eight panels")
    columns = 1 if len(modes) == 1 else min(4, math.ceil(math.sqrt(len(modes))))
    rows = math.ceil(len(modes) / columns)
    margin, gap = 4.0, 4.0
    panel_width = (width - 2 * margin - (columns - 1) * gap) / columns
    panel_height = (height - 2 * margin - (rows - 1) * gap) / rows
    panels: list[FigurePanel] = []
    for index, mode in enumerate(modes):
        row, column = divmod(index, columns)
        label = tuple("ABCDEFGH")[index]
        panel_id = stable_id("figure_panel", f"{name}:{label}")
        panels.append(FigurePanel(
            panel_id, label, f"Panel {label}", mode,
            {
                "x": margin + column * (panel_width + gap),
                "y": margin + row * (panel_height + gap),
                "width": panel_width,
                "height": panel_height,
            },
            default_layers(panel_id), order=index,
        ))
    page = FigurePage(stable_id("figure_page", name), name, width, height, panels, columns=columns)
    return FigureIR(name, [page], metadata={"page_preset": page_preset, "authoring_mode": "figure-studio"}).validate()


def _shape_label(tensor: TensorSpec | None) -> tuple[list[int | str | None], str]:
    shape = list(tensor.shape) if tensor else []
    label = "[" + ", ".join("?" if dim is None else str(dim) for dim in shape) + "]"
    return shape, label


def figure_from_graph(
    graph: GraphIR,
    *,
    mode: str = "schematic",
    page_preset: str = "double-column",
    **options: Any,
) -> FigureIR:
    """Build a Graph → Semantic → Figure draft via the evidence pipeline."""

    from .model_figure import model_figure_from_graph

    return model_figure_from_graph(graph, mode=mode, page_preset=page_preset, **options)


__all__ = [
    "CONSTRAINT_KINDS", "DEFAULT_DESIGN_TOKENS", "FIGURE_IR_VERSION", "LAYER_ROLES",
    "OBJECT_KINDS", "PAGE_PRESETS_MM", "PANEL_MODES", "FigureConstraint", "FigureGroup",
    "FigureIR", "FigureLayer", "FigureObject", "FigurePage", "FigurePanel", "FigureProvenance",
    "FigureStyle", "default_layers", "figure_from_graph", "new_figure",
]
