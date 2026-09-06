"""Shape-faithful 2-D/isometric tensor geometry for Figure IR.

The module emits explicit polygon coordinates.  It never relies on CSS
perspective and never substitutes visual dimensions for the displayed tensor
shape.  Scaling choices are retained as metadata for legends and proof files.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import html
import math
from typing import Any, Iterable, Sequence

from .errors import ValidationError


TENSOR_GEOMETRY_VERSION = "1.0"
SCALE_MODES = frozenset({"linear", "sqrt", "log", "normalized", "manual"})
TENSOR_LAYOUTS = frozenset({"auto", "NCHW", "NHWC", "BTD", "matrix", "vector", "scalar"})
OPERATOR_FAMILIES = frozenset({
    "convolution", "pooling", "upsample", "concatenate", "addition", "attention",
    "normalization", "routing", "expert", "generic",
})


@dataclass(slots=True)
class TensorGeometrySpec:
    shape: list[int | str | None]
    layout: str = "auto"
    scale_mode: str = "normalized"
    manual_size: list[float] | None = None
    origin: tuple[float, float] = (0.0, 0.0)
    maximum_extent: float = 42.0
    minimum_extent: float = 8.0
    depth_skew: float = 0.45
    label: str = ""
    dtype: str = "unknown"

    def validate(self) -> "TensorGeometrySpec":
        if self.layout not in TENSOR_LAYOUTS:
            raise ValidationError(f"Unsupported tensor layout {self.layout!r}")
        if self.scale_mode not in SCALE_MODES:
            raise ValidationError(f"Unsupported tensor geometry scale {self.scale_mode!r}")
        if any(
            not (isinstance(dim, int) and not isinstance(dim, bool) or isinstance(dim, str) or dim is None)
            for dim in self.shape
        ):
            raise ValidationError("Tensor dimensions must be integers, symbols, or null")
        if any(isinstance(dim, int) and dim < 0 for dim in self.shape):
            raise ValidationError("Negative dimensions must be represented as a symbol or unknown, not guessed")
        if self.scale_mode == "manual":
            if self.manual_size is None or len(self.manual_size) != 3:
                raise ValidationError("Manual tensor geometry requires [width, height, depth]")
            if any(not math.isfinite(float(item)) or float(item) <= 0 for item in self.manual_size):
                raise ValidationError("Manual tensor geometry sizes must be positive finite values")
        for name, value in (("maximum_extent", self.maximum_extent), ("minimum_extent", self.minimum_extent)):
            if not math.isfinite(float(value)) or float(value) <= 0:
                raise ValidationError(f"Tensor geometry {name} must be positive and finite")
        if self.maximum_extent < self.minimum_extent:
            raise ValidationError("Tensor geometry maximum_extent cannot be smaller than minimum_extent")
        if not 0.1 <= float(self.depth_skew) <= 1.0:
            raise ValidationError("Tensor geometry depth_skew must be between 0.1 and 1")
        return self


@dataclass(slots=True)
class TensorVectorGeometry:
    shape: list[int | str | None]
    shape_label: str
    layout: str
    faces: dict[str, list[list[float]]]
    bounds: dict[str, float]
    visual_size: dict[str, float]
    draw_order: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)
    version: str = TENSOR_GEOMETRY_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def svg_group(
        self,
        object_id: str,
        *,
        front: str = "#dbeafe",
        top: str = "#bfdbfe",
        side: str = "#93c5fd",
        stroke: str = "#334155",
        font_family: str = "DejaVu Sans, Arial, sans-serif",
        font_size_pt: float = 7.0,
        opacity: float = 1.0,
    ) -> str:
        fills = {"front": front, "top": top, "side": side}
        pieces = [
            f'<g id="{html.escape(object_id, quote=True)}" class="tensor-glyph" '
            f'data-figure-object-id="{html.escape(object_id, quote=True)}" '
            f'data-shape="{html.escape(self.shape_label, quote=True)}" '
            f'data-scale-mode="{html.escape(str(self.metadata["scale_mode"]), quote=True)}">'
        ]
        for face in self.draw_order:
            points = " ".join(f"{x:.4f},{y:.4f}" for x, y in self.faces[face])
            pieces.append(
                f'<polygon class="tensor-face tensor-{face}" data-tensor-face="{face}" '
                f'points="{points}" fill="{fills[face]}" fill-opacity="{opacity:g}" '
                f'stroke="{stroke}" stroke-width="0.8" vector-effect="non-scaling-stroke"/>'
            )
        center_x = self.bounds["x"] + self.bounds["width"] / 2
        label_y = self.bounds["y"] + self.bounds["height"] + max(3.0, font_size_pt * 0.5)
        pieces.append(
            f'<text class="tensor-shape-label" x="{center_x:.4f}" y="{label_y:.4f}" '
            f'text-anchor="middle" font-family="{html.escape(font_family, quote=True)}" '
            f'font-size="{max(7.0, float(font_size_pt)):g}pt" data-real-shape="true">'
            f'{html.escape(self.shape_label)}</text>'
        )
        pieces.append("</g>")
        return "".join(pieces)


def shape_label(shape: Sequence[int | str | None]) -> str:
    return "[" + ", ".join("?" if dim is None or dim == "" else str(dim) for dim in shape) + "]"


def resolve_layout(shape: Sequence[int | str | None], requested: str) -> str:
    if requested != "auto":
        expected = {"NCHW": 4, "NHWC": 4, "BTD": 3, "matrix": 2, "vector": 1, "scalar": 0}
        if len(shape) != expected[requested]:
            raise ValidationError(f"Layout {requested!r} requires rank {expected[requested]}, received rank {len(shape)}")
        return requested
    return {4: "NCHW", 3: "BTD", 2: "matrix", 1: "vector", 0: "scalar"}.get(len(shape), "vector")


def _axis_values(shape: Sequence[int | str | None], layout: str) -> tuple[Any, Any, Any, dict[str, Any]]:
    if layout == "NCHW":
        batch, channels, height, width = shape
        return width, height, channels, {"batch": batch, "axes": ["W", "H", "C"]}
    if layout == "NHWC":
        batch, height, width, channels = shape
        return width, height, channels, {"batch": batch, "axes": ["W", "H", "C"]}
    if layout == "BTD":
        batch, tokens, dimension = shape
        return tokens, dimension, batch, {"batch": batch, "axes": ["T", "D", "B"]}
    if layout == "matrix":
        rows, columns = shape
        return columns, rows, 1, {"axes": ["columns", "rows", "depth"]}
    if layout == "vector":
        value = shape[0] if shape else None
        return value, 1, 1, {"axes": ["length", "height", "depth"]}
    return 1, 1, 1, {"axes": ["scalar", "height", "depth"]}


def _map_value(value: Any, mode: str, known_max: float, minimum: float, maximum: float) -> tuple[float, bool]:
    if not isinstance(value, int) or isinstance(value, bool):
        return max(minimum, maximum * 0.38), True
    if value == 0:
        return minimum, False
    ratio = max(0.0, float(value)) / max(known_max, 1.0)
    if mode == "sqrt":
        ratio = math.sqrt(ratio)
    elif mode == "log":
        ratio = math.log1p(float(value)) / math.log1p(max(known_max, 1.0))
    elif mode == "normalized":
        ratio = 0.22 + 0.78 * ratio
    return minimum + (maximum - minimum) * min(1.0, ratio), False


def tensor_geometry(spec: TensorGeometrySpec) -> TensorVectorGeometry:
    spec.validate()
    layout = resolve_layout(spec.shape, spec.layout)
    width_value, height_value, depth_value, axes = _axis_values(spec.shape, layout)
    raw_values = [width_value, height_value, depth_value]
    known = [float(item) for item in raw_values if isinstance(item, int) and not isinstance(item, bool)]
    known_max = max(known, default=1.0)
    unknown_axes: list[str] = []
    if spec.scale_mode == "manual":
        width, height, depth = [float(item) for item in spec.manual_size or []]
    else:
        mapped = [
            _map_value(item, spec.scale_mode, known_max, spec.minimum_extent, spec.maximum_extent)
            for item in raw_values
        ]
        width, height, depth = (item[0] for item in mapped)
        unknown_axes = [axes["axes"][index] for index, item in enumerate(mapped) if item[1]]
    # Isometric offset is bounded independently so channel or batch count cannot
    # obscure the true front-face label.
    depth_visible = max(3.0, min(depth * 0.38, spec.maximum_extent * 0.42))
    dx = depth_visible
    dy = depth_visible * float(spec.depth_skew)
    x, y = float(spec.origin[0]), float(spec.origin[1]) + dy
    faces = {
        "top": [[x, y], [x + width, y], [x + width + dx, y - dy], [x + dx, y - dy]],
        "side": [[x + width, y], [x + width, y + height], [x + width + dx, y + height - dy], [x + width + dx, y - dy]],
        "front": [[x + dx, y - dy], [x + width + dx, y - dy], [x + width + dx, y + height - dy], [x + dx, y + height - dy]],
    }
    label = spec.label or shape_label(spec.shape)
    metadata = {
        "scale_mode": spec.scale_mode,
        "scale_is_visual_only": True,
        "real_shape_label": label,
        "layout": layout,
        "axis_mapping": axes,
        "unknown_visual_axes": unknown_axes,
        "manual_size": list(spec.manual_size) if spec.manual_size else None,
        "legend_note": (
            f"Tensor geometry uses {spec.scale_mode} visual scaling; numeric labels are the authoritative shape."
        ),
        "css_perspective_used": False,
    }
    return TensorVectorGeometry(
        list(spec.shape), label, layout, faces,
        {"x": x, "y": y - dy, "width": width + dx, "height": height + dy},
        {"width": width, "height": height, "depth": depth, "visible_depth": depth_visible},
        ["top", "side", "front"], metadata,
    )


def tensor_geometry_many(
    shapes: Iterable[Sequence[int | str | None]],
    *,
    layout: str = "auto",
    scale_mode: str = "normalized",
    origin: tuple[float, float] = (0.0, 0.0),
    gap: float = 12.0,
) -> list[TensorVectorGeometry]:
    result: list[TensorVectorGeometry] = []
    cursor = float(origin[0])
    for shape in shapes:
        geometry = tensor_geometry(TensorGeometrySpec(list(shape), layout=layout, scale_mode=scale_mode, origin=(cursor, origin[1])))
        result.append(geometry)
        cursor = geometry.bounds["x"] + geometry.bounds["width"] + gap
    return result


def operator_symbol(family: str, x: float, y: float, size: float = 10.0) -> dict[str, Any]:
    """Return editable vector primitives for common scientific operators."""
    normalized = family.lower().replace("_", "-")
    aliases = {
        "conv": "convolution", "conv2d": "convolution", "pool": "pooling",
        "upsampling": "upsample", "concat": "concatenate", "add": "addition",
        "multiheadattention": "attention", "layernorm": "normalization", "router": "routing",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in OPERATOR_FAMILIES:
        normalized = "generic"
    primitives: list[dict[str, Any]]
    if normalized == "addition":
        primitives = [
            {"kind": "circle", "cx": x, "cy": y, "r": size / 2},
            {"kind": "line", "x1": x - size / 4, "y1": y, "x2": x + size / 4, "y2": y},
            {"kind": "line", "x1": x, "y1": y - size / 4, "x2": x, "y2": y + size / 4},
        ]
    elif normalized == "concatenate":
        primitives = [
            {"kind": "path", "d": f"M{x-size/2},{y-size/2} L{x},{y} L{x-size/2},{y+size/2}"},
            {"kind": "path", "d": f"M{x+size/2},{y-size/2} L{x},{y} L{x+size/2},{y+size/2}"},
        ]
    elif normalized == "attention":
        primitives = [
            {"kind": "polygon", "points": [[x, y-size/2], [x+size/2, y], [x, y+size/2], [x-size/2, y]]},
            {"kind": "text", "x": x, "y": y, "text": "A"},
        ]
    elif normalized in {"routing", "expert"}:
        primitives = [
            {"kind": "polygon", "points": [[x-size/2, y-size/2], [x+size/2, y], [x-size/2, y+size/2]]},
            {"kind": "text", "x": x-size/6, "y": y, "text": "R" if normalized == "routing" else "E"},
        ]
    elif normalized == "upsample":
        primitives = [{"kind": "polygon", "points": [[x-size/2, y+size/2], [x+size/2, y+size/2], [x+size/3, y-size/2], [x-size/3, y-size/2]]}]
    elif normalized == "pooling":
        primitives = [{"kind": "polygon", "points": [[x-size/3, y-size/2], [x+size/3, y-size/2], [x+size/2, y+size/2], [x-size/2, y+size/2]]}]
    else:
        primitives = [
            {"kind": "rect", "x": x-size/2, "y": y-size/2, "width": size, "height": size, "rx": size/6},
            {"kind": "text", "x": x, "y": y, "text": {"convolution": "Conv", "normalization": "Norm"}.get(normalized, "Op")},
        ]
    return {"family": normalized, "primitives": primitives, "editable": True}


def route_around(
    start: tuple[float, float],
    end: tuple[float, float],
    obstacles: Iterable[dict[str, float]] = (),
    *,
    branch_index: int = 0,
    residual: bool = False,
) -> list[list[float]]:
    """Bounded orthogonal routing for skips and branch merges."""
    sx, sy = map(float, start)
    ex, ey = map(float, end)
    boxes = list(obstacles)
    direct_y = sy
    intersects = any(
        min(sx, ex) <= float(box["x"]) + float(box["width"])
        and max(sx, ex) >= float(box["x"])
        and float(box["y"]) <= direct_y <= float(box["y"]) + float(box["height"])
        for box in boxes
    )
    if residual or intersects:
        top = min([sy, ey, *(float(box["y"]) for box in boxes)] or [sy, ey])
        detour = top - 8.0 - branch_index * 5.0
        return [[sx, sy], [sx + 4.0, sy], [sx + 4.0, detour], [ex - 4.0, detour], [ex - 4.0, ey], [ex, ey]]
    middle = (sx + ex) / 2
    return [[sx, sy], [middle, sy], [middle, ey], [ex, ey]]


def shape_transition(
    source: Sequence[int | str | None], target: Sequence[int | str | None]
) -> dict[str, Any]:
    source_label, target_label = shape_label(source), shape_label(target)
    if len(source) != len(target):
        status = "rank-change"
    elif any(a is None or b is None or isinstance(a, str) or isinstance(b, str) for a, b in zip(source, target)):
        status = "unknown"
    elif list(source) == list(target):
        status = "unchanged"
    else:
        status = "shape-change"
    return {
        "source": source_label, "target": target_label, "status": status,
        "proven": status != "unknown", "label": f"{source_label} → {target_label}",
    }


def relative_luminance(color: str) -> float:
    value = color.lstrip("#")
    if len(value) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in value):
        raise ValidationError(f"Expected a six-digit hex color, received {color!r}")
    channels = [int(value[index:index+2], 16) / 255 for index in (0, 2, 4)]
    linear = [item / 12.92 if item <= 0.04045 else ((item + 0.055) / 1.055) ** 2.4 for item in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(first: str, second: str) -> float:
    light, dark = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


__all__ = [
    "OPERATOR_FAMILIES", "SCALE_MODES", "TENSOR_GEOMETRY_VERSION", "TENSOR_LAYOUTS",
    "TensorGeometrySpec", "TensorVectorGeometry", "contrast_ratio", "operator_symbol",
    "relative_luminance", "resolve_layout", "route_around", "shape_label", "shape_transition",
    "tensor_geometry", "tensor_geometry_many",
]
