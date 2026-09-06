"""Deterministic, dependency-free CPU projection for :mod:`scene_ir`.

The browser renderer is deliberately not involved here.  This module turns a
validated three-dimensional scene into a small set of physical, vector-first
primitives that can be consumed by SVG, PDF, TikZ, PowerPoint and print proof
exporters.  Matrices are row-major and act on column vectors, matching Scene
IR 1.0.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
import hashlib
import json
import math
import re
from typing import Any, Mapping, Sequence, cast

from .errors import ValidationError


SCENE_PROJECTION_VERSION = "nndv-scene-projection-1"
PT_TO_MM = 25.4 / 72.0
_EPSILON = 1.0e-9

Vec3 = tuple[float, float, float]
Vec4 = tuple[float, float, float, float]
Mat4 = tuple[tuple[float, float, float, float], ...]


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _plain(value: Any) -> Any:
    """Return deterministic JSON-compatible metadata without object reprs."""

    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return round(value, 9) if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return _plain(asdict(cast(Any, value)))
    if hasattr(value, "to_dict"):
        return _plain(value.to_dict())
    return str(value)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(result):
        raise ValidationError("Scene projection received a non-finite numeric value")
    return result


def _vec3(value: Any, default: Vec3 = (0.0, 0.0, 0.0)) -> Vec3:
    if value is None:
        return default
    if isinstance(value, Mapping):
        return (_number(value.get("x"), default[0]), _number(value.get("y"), default[1]), _number(value.get("z"), default[2]))
    if hasattr(value, "x") and hasattr(value, "y") and hasattr(value, "z"):
        return (_number(value.x), _number(value.y), _number(value.z))
    try:
        items = list(value)
    except TypeError:
        return default
    if len(items) < 3:
        return default
    return (_number(items[0]), _number(items[1]), _number(items[2]))


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(value: Vec3, scalar: float) -> Vec3:
    return (value[0] * scalar, value[1] * scalar, value[2] * scalar)


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _length(value: Vec3) -> float:
    return math.sqrt(_dot(value, value))


def _normalize(value: Vec3, *, name: str = "vector") -> Vec3:
    length = _length(value)
    if length <= _EPSILON:
        raise ValidationError(f"Scene camera {name} must not be a zero vector")
    return _mul(value, 1.0 / length)


def identity_matrix() -> Mat4:
    return (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )


def mat4_multiply(left: Sequence[Sequence[float]], right: Sequence[Sequence[float]]) -> Mat4:
    """Multiply two row-major 4x4 matrices."""

    if len(left) != 4 or len(right) != 4 or any(len(row) != 4 for row in left) or any(len(row) != 4 for row in right):
        raise ValidationError("Scene projection matrices must be 4x4")
    return cast(
        Mat4,
        tuple(tuple(sum(_number(left[row][inner]) * _number(right[inner][column]) for inner in range(4)) for column in range(4)) for row in range(4)),
    )


def _mat4_vec4(matrix: Sequence[Sequence[float]], value: Vec4) -> Vec4:
    return tuple(sum(_number(matrix[row][column]) * value[column] for column in range(4)) for row in range(4))  # type: ignore[return-value]


def transform_point(matrix: Sequence[Sequence[float]], point: Sequence[float]) -> Vec3:
    x, y, z = _vec3(point)
    result = _mat4_vec4(matrix, (x, y, z, 1.0))
    if abs(result[3]) > _EPSILON and abs(result[3] - 1.0) > _EPSILON:
        return (result[0] / result[3], result[1] / result[3], result[2] / result[3])
    return (result[0], result[1], result[2])


def look_at_matrix(eye: Sequence[float], target: Sequence[float], up: Sequence[float] = (0.0, 1.0, 0.0)) -> Mat4:
    """Return a right-handed OpenGL look-at view matrix.

    The camera looks down its local negative Z axis.  Degenerate up vectors are
    rejected instead of silently producing a camera-dependent NaN.
    """

    eye_value, target_value = _vec3(eye), _vec3(target)
    forward = _normalize(_sub(target_value, eye_value), name="eye/target direction")
    side_raw = _cross(forward, _vec3(up, (0.0, 1.0, 0.0)))
    if _length(side_raw) <= _EPSILON:
        raise ValidationError("Scene camera up vector must not be parallel to its viewing direction")
    side = _normalize(side_raw, name="side direction")
    camera_up = _cross(side, forward)
    return (
        (side[0], side[1], side[2], -_dot(side, eye_value)),
        (camera_up[0], camera_up[1], camera_up[2], -_dot(camera_up, eye_value)),
        (-forward[0], -forward[1], -forward[2], _dot(forward, eye_value)),
        (0.0, 0.0, 0.0, 1.0),
    )


def perspective_matrix(fov_y_deg: float, aspect: float, near: float, far: float) -> Mat4:
    """Return a right-handed finite OpenGL perspective projection matrix."""

    fov, ratio, near_value, far_value = map(_number, (fov_y_deg, aspect, near, far))
    if not 0.0 < fov < 179.0:
        raise ValidationError("Perspective camera fov_y_deg must be between 0 and 179")
    if ratio <= 0.0 or near_value <= 0.0 or far_value <= near_value:
        raise ValidationError("Perspective camera requires aspect > 0 and 0 < near < far")
    factor = 1.0 / math.tan(math.radians(fov) / 2.0)
    return (
        (factor / ratio, 0.0, 0.0, 0.0),
        (0.0, factor, 0.0, 0.0),
        (0.0, 0.0, (far_value + near_value) / (near_value - far_value), (2.0 * far_value * near_value) / (near_value - far_value)),
        (0.0, 0.0, -1.0, 0.0),
    )


def orthographic_matrix(
    left: float,
    right: float,
    bottom: float,
    top: float,
    near: float,
    far: float,
) -> Mat4:
    """Return a right-handed finite OpenGL orthographic projection matrix."""

    left_value, right_value, bottom_value, top_value, near_value, far_value = map(_number, (left, right, bottom, top, near, far))
    if right_value <= left_value or top_value <= bottom_value or near_value < 0.0 or far_value <= near_value:
        raise ValidationError("Orthographic camera requires ordered extents and 0 <= near < far")
    return (
        (2.0 / (right_value - left_value), 0.0, 0.0, -(right_value + left_value) / (right_value - left_value)),
        (0.0, 2.0 / (top_value - bottom_value), 0.0, -(top_value + bottom_value) / (top_value - bottom_value)),
        (0.0, 0.0, -2.0 / (far_value - near_value), -(far_value + near_value) / (far_value - near_value)),
        (0.0, 0.0, 0.0, 1.0),
    )


def project_point(
    point: Sequence[float],
    view_matrix: Sequence[Sequence[float]],
    projection_matrix: Sequence[Sequence[float]],
    *,
    width_mm: float = 180.0,
    height_mm: float = 120.0,
    margin_mm: float = 8.0,
) -> tuple[float, float, float] | None:
    """Project one world point to physical page coordinates and view depth.

    ``None`` is returned for points on or behind the camera plane.  Depth is a
    positive camera-space distance, making smaller values nearer.
    """

    page_width, page_height, margin = map(_number, (width_mm, height_mm, margin_mm))
    if page_width <= margin * 2.0 or page_height <= margin * 2.0:
        raise ValidationError("Projection page must be larger than twice its margin")
    world = (*_vec3(point), 1.0)
    view = _mat4_vec4(view_matrix, world)
    if view[2] >= -_EPSILON:
        return None
    clip = _mat4_vec4(projection_matrix, view)
    if abs(clip[3]) <= _EPSILON:
        return None
    ndc_x, ndc_y, ndc_z = clip[0] / clip[3], clip[1] / clip[3], clip[2] / clip[3]
    if ndc_z < -1.0 - 1.0e-7 or ndc_z > 1.0 + 1.0e-7:
        return None
    drawable_width, drawable_height = page_width - margin * 2.0, page_height - margin * 2.0
    x = margin + (ndc_x + 1.0) * 0.5 * drawable_width
    y = margin + (1.0 - ndc_y) * 0.5 * drawable_height
    return (round(x, 7), round(y, 7), round(-view[2], 7))


@dataclass(frozen=True, slots=True)
class ProjectionOptions:
    """Physical and visibility policy for deterministic paper projections.

    ``hidden_edges=True`` means that occluded/back-facing edges are omitted.
    Set it to ``False`` for a transparent technical line view.
    """

    width_mm: float = 180.0
    height_mm: float = 120.0
    margin_mm: float = 8.0
    hidden_edges: bool = True
    backface_culling: bool = True
    stroke_width_pt: float = 0.75
    min_label_pt: float = 7.0
    font_family: str = "Arial, Helvetica, sans-serif"
    background: str = "#ffffff"
    label_padding_mm: float = 1.2
    occlusion_samples: int = 32
    density: str = "paper"
    auto_frame: bool = False
    target_occupancy: float = 0.72
    label_budget: int | None = None
    max_leader_mm: float = 18.0

    def __post_init__(self) -> None:
        for name in (
            "width_mm",
            "height_mm",
            "margin_mm",
            "stroke_width_pt",
            "min_label_pt",
            "label_padding_mm",
            "max_leader_mm",
        ):
            value = _number(getattr(self, name))
            if value < 0.0:
                raise ValidationError(f"Projection option {name} must not be negative")
        if self.width_mm <= self.margin_mm * 2.0 or self.height_mm <= self.margin_mm * 2.0:
            raise ValidationError("Projection page must be larger than twice its margin")
        if self.stroke_width_pt <= 0.0:
            raise ValidationError("Projection stroke width must be positive")
        if self.min_label_pt < 7.0:
            raise ValidationError("Scene publication labels must be at least 7 pt")
        if self.occlusion_samples < 4 or self.occlusion_samples > 256:
            raise ValidationError("Projection occlusion_samples must be between 4 and 256")
        if self.density not in {"compact", "paper", "detailed"}:
            raise ValidationError("Scene density must be compact, paper, or detailed")
        if not isinstance(self.auto_frame, bool):
            raise ValidationError("Scene auto_frame must be boolean")
        if not 0.55 <= self.target_occupancy <= 0.9:
            raise ValidationError("Scene target_occupancy must be between 0.55 and 0.90")
        if self.label_budget is not None and (isinstance(self.label_budget, bool) or not 1 <= self.label_budget <= 128):
            raise ValidationError("Scene label_budget must be an integer between 1 and 128")
        if self.max_leader_mm < 4.0 or self.max_leader_mm > 80.0:
            raise ValidationError("Scene max_leader_mm must be between 4 and 80 mm")

    @classmethod
    def coerce(cls, value: "ProjectionOptions | Mapping[str, Any] | None") -> "ProjectionOptions":
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        if isinstance(value, Mapping):
            allowed = set(cls.__dataclass_fields__)
            unknown = sorted(set(map(str, value)) - allowed)
            if unknown:
                raise ValidationError(f"Unknown scene projection options: {unknown!r}")
            return cls(**dict(value))
        raise ValidationError("Scene projection options must be ProjectionOptions or a mapping")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ProjectedPrimitive:
    kind: str
    object_id: str
    depth: float
    points: list[tuple[float, float]] = field(default_factory=list)
    style: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind,
            "object_id": self.object_id,
            "depth": round(float(self.depth), 7),
            "points": [[round(x, 7), round(y, 7)] for x, y in self.points],
            "style": _plain(self.style),
            "metadata": _plain(self.metadata),
        }
        if self.text:
            payload["text"] = self.text
        return payload


@dataclass(slots=True)
class ProjectedScene:
    scene_id: str
    camera_id: str
    width_mm: float
    height_mm: float
    view_matrix: Mat4
    projection_matrix: Mat4
    primitives: list[ProjectedPrimitive]
    options: ProjectionOptions
    source_digest: str
    framing: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.width_mm <= 0.0 or self.height_mm <= 0.0:
            raise ValidationError("Projected scene dimensions must be positive")
        if not self.camera_id:
            raise ValidationError("Projected scene must identify its camera")
        for primitive in self.primitives:
            if primitive.kind not in {"face", "edge", "polyline", "bezier", "arrow", "label", "leader"}:
                raise ValidationError(f"Unsupported projected primitive kind {primitive.kind!r}")
            if not primitive.object_id:
                raise ValidationError("Every projected primitive must retain an object ID")
            if primitive.kind == "label" and _number(primitive.style.get("font_size_pt")) < 7.0:
                raise ValidationError("Projected labels must be at least 7 pt")
            if _number(primitive.style.get("stroke_width_pt"), self.options.stroke_width_pt) <= 0.0:
                raise ValidationError("Projected vector strokes must use a positive physical width")
            for point in primitive.points:
                if len(point) != 2 or not all(math.isfinite(float(value)) for value in point):
                    raise ValidationError("Projected primitive contains an invalid point")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": SCENE_PROJECTION_VERSION,
            "scene_id": self.scene_id,
            "camera_id": self.camera_id,
            "source_digest": self.source_digest,
            "width_mm": self.width_mm,
            "height_mm": self.height_mm,
            "view_matrix": [list(row) for row in self.view_matrix],
            "projection_matrix": [list(row) for row in self.projection_matrix],
            "options": self.options.to_dict(),
            "framing": _plain(self.framing),
            "primitives": [primitive.to_dict() for primitive in self.primitives],
        }


@dataclass(slots=True)
class _Face:
    object_id: str
    index: int
    world: list[Vec3]
    projected: list[tuple[float, float, float]]
    style: dict[str, Any]
    front: bool
    metadata: dict[str, Any]

    @property
    def depth(self) -> float:
        return sum(point[2] for point in self.projected) / len(self.projected)


@dataclass(slots=True)
class _Line:
    kind: str
    object_id: str
    projected: list[tuple[float, float, float]]
    style: dict[str, Any]
    metadata: dict[str, Any]


@dataclass(slots=True)
class _LabelCandidate:
    object_id: str
    text: str
    anchor: tuple[float, float, float]
    style: dict[str, Any]
    metadata: dict[str, Any]
    priority: float


_BOX_KINDS = {
    "cuboid",
    "tensor-volume",
    "tensor-stack",
    "feature-map-stack",
    "layer-plane",
    "operation-block",
    "convolution-window",
    "conv-window",
    "pooling",
    "downsample",
    "upsample",
    "attention-head",
    "token-sequence",
    "moe-router",
    "merge",
    "fusion",
    "timestep-conditioning",
    "group-frame",
    "unknown",
}
_ROUTE_KINDS = {
    "residual-skip",
    "unet-skip",
    "attention-ribbon",
    "qkv-branch",
    "expert-branch",
    "multimodal-stream",
    "arrow",
    "tube",
    "polyline",
    "bezier-route",
}


def _object_id(item: Any, fallback: str) -> str:
    return str(_get(item, "id", _get(item, "object_id", fallback)))


def _objects(scene: Any, *, visible_only: bool = False) -> list[Any]:
    if hasattr(scene, "iter_objects"):
        try:
            return sorted(list(scene.iter_objects(visible_only=visible_only)), key=lambda item: _object_id(item, ""))
        except TypeError:
            return sorted(list(scene.iter_objects()), key=lambda item: _object_id(item, ""))
    direct = _get(scene, "objects")
    if direct is not None:
        values = list(direct.values()) if isinstance(direct, Mapping) else list(direct)
        return sorted(values, key=lambda item: _object_id(item, ""))
    result: list[Any] = []
    for layer in _get(scene, "layers", []) or []:
        values = _get(layer, "objects", []) or []
        result.extend(values.values() if isinstance(values, Mapping) else values)
        for group in _get(layer, "groups", []) or []:
            grouped = _get(group, "objects", _get(group, "children", [])) or []
            result.extend(grouped.values() if isinstance(grouped, Mapping) else grouped)
    return sorted(result, key=lambda item: _object_id(item, ""))


def _camera(scene: Any, camera_id: str | None) -> Any:
    cameras_value = _get(scene, "cameras", []) or []
    cameras = list(cameras_value.values()) if isinstance(cameras_value, Mapping) else list(cameras_value)
    selected_id = camera_id or _get(scene, "active_camera_id")
    if selected_id is None and hasattr(scene, "active_camera"):
        try:
            active = scene.active_camera()
            if active is not None:
                return active
        except (TypeError, ValueError):
            pass
    if selected_id is not None:
        for item in cameras:
            if str(_get(item, "id", "")) == str(selected_id):
                return item
        raise ValidationError(f"Scene camera {selected_id!r} does not exist")
    if cameras:
        return sorted(cameras, key=lambda item: str(_get(item, "id", "")))[0]
    return {
        "id": "camera:auto-isometric",
        "projection": "orthographic",
        "position": [8.0, 6.0, 8.0],
        "target": [0.0, 0.0, 0.0],
        "up": [0.0, 1.0, 0.0],
        "ortho_height": 12.0,
        "near": 0.01,
        "far": 1000.0,
    }


def _camera_matrices(camera: Any, options: ProjectionOptions) -> tuple[Mat4, Mat4]:
    if hasattr(camera, "view_matrix") and hasattr(camera, "projection_matrix"):
        view_value, projection_value = camera.view_matrix(), camera.projection_matrix()
        view = tuple(tuple(_number(value) for value in row) for row in view_value)
        projection = tuple(tuple(_number(value) for value in row) for row in projection_value)
        if len(view) != 4 or len(projection) != 4 or any(len(row) != 4 for row in (*view, *projection)):
            raise ValidationError("Scene camera returned a malformed projection matrix")
        return view, projection  # type: ignore[return-value]
    eye = _vec3(_get(camera, "position"), (8.0, 6.0, 8.0))
    target = _vec3(_get(camera, "target"), (0.0, 0.0, 0.0))
    up = _vec3(_get(camera, "up"), (0.0, 1.0, 0.0))
    view = look_at_matrix(eye, target, up)
    aspect = _number(_get(camera, "aspect"), options.width_mm / options.height_mm)
    if aspect <= 0.0:
        aspect = options.width_mm / options.height_mm
    near = _number(_get(camera, "near"), 0.01)
    far = _number(_get(camera, "far"), 1000.0)
    projection_kind = str(_get(camera, "projection", _get(camera, "projection_type", "orthographic"))).lower()
    if projection_kind == "perspective":
        projection = perspective_matrix(_number(_get(camera, "fov_y_deg", _get(camera, "fov", 45.0))), aspect, near, far)
    elif projection_kind == "orthographic":
        height = _number(_get(camera, "ortho_height", _get(camera, "orthographic_scale", 12.0)), 12.0)
        if height <= 0.0:
            raise ValidationError("Orthographic camera ortho_height must be positive")
        width = height * aspect
        projection = orthographic_matrix(-width / 2.0, width / 2.0, -height / 2.0, height / 2.0, near, far)
    else:
        raise ValidationError(f"Unsupported Scene camera projection {projection_kind!r}")
    return view, projection


def _world_matrix(scene: Any, item: Any) -> Mat4:
    if hasattr(scene, "world_matrix"):
        try:
            matrix = scene.world_matrix(item)
        except (TypeError, KeyError):
            matrix = scene.world_matrix(_object_id(item, ""))
        if matrix is not None:
            return cast(Mat4, tuple(tuple(_number(value) for value in row) for row in matrix))
    world = _get(item, "world")
    matrix = _get(world, "matrix") if world is not None else None
    if matrix is not None:
        return cast(Mat4, tuple(tuple(_number(value) for value in row) for row in matrix))
    transform = _get(item, "transform", {}) or {}
    position = _vec3(_get(transform, "position"), _vec3(_get(item, "position")))
    rotation = _vec3(_get(transform, "rotation"), _vec3(_get(item, "rotation")))
    scale = _vec3(_get(transform, "scale"), _vec3(_get(item, "scale"), (1.0, 1.0, 1.0)))
    rx, ry, rz = map(math.radians, rotation)
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    scale_matrix: Mat4 = ((scale[0], 0.0, 0.0, 0.0), (0.0, scale[1], 0.0, 0.0), (0.0, 0.0, scale[2], 0.0), (0.0, 0.0, 0.0, 1.0))
    rotate_x: Mat4 = ((1.0, 0.0, 0.0, 0.0), (0.0, cx, -sx, 0.0), (0.0, sx, cx, 0.0), (0.0, 0.0, 0.0, 1.0))
    rotate_y: Mat4 = ((cy, 0.0, sy, 0.0), (0.0, 1.0, 0.0, 0.0), (-sy, 0.0, cy, 0.0), (0.0, 0.0, 0.0, 1.0))
    rotate_z: Mat4 = ((cz, -sz, 0.0, 0.0), (sz, cz, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0))
    translation: Mat4 = ((1.0, 0.0, 0.0, position[0]), (0.0, 1.0, 0.0, position[1]), (0.0, 0.0, 1.0, position[2]), (0.0, 0.0, 0.0, 1.0))
    return mat4_multiply(translation, mat4_multiply(rotate_z, mat4_multiply(rotate_y, mat4_multiply(rotate_x, scale_matrix))))


def _hex_colour(value: Any, fallback: str) -> str:
    text = str(value or fallback).strip()
    if len(text) in {7, 9} and text.startswith("#") and all(character in "0123456789abcdefABCDEF" for character in text[1:]):
        return text.lower()
    return fallback


def _style(item: Any, options: ProjectionOptions) -> dict[str, Any]:
    material = _get(item, "material", {}) or {}
    base = _hex_colour(_get(material, "base_color", _get(material, "fill", "#dbeafe")), "#dbeafe")
    opacity = max(0.0, min(1.0, _number(_get(material, "opacity"), 1.0)))
    if len(base) == 9:
        opacity *= int(base[7:9], 16) / 255.0
        base = base[:7]
    return {
        "fill": base,
        "stroke": _hex_colour(_get(material, "stroke_color", _get(material, "stroke", "#334155")), "#334155"),
        # One physical stroke policy across all vector backends.  Per-object
        # pixel widths are intentionally ignored.
        "stroke_width_pt": round(options.stroke_width_pt, 5),
        "opacity": round(opacity, 5),
        "font_size_pt": max(options.min_label_pt, _number(_get(material, "font_size_pt"), options.min_label_pt)),
        "font_family": options.font_family,
        "dash": str(_get(material, "dash", "")),
        "double_sided": bool(_get(material, "double_sided", False)),
    }


def _box_mesh(size: Vec3) -> tuple[list[Vec3], list[list[int]], list[str]]:
    x, y, z = (max(abs(value), 1.0e-5) / 2.0 for value in size)
    vertices = [(-x, -y, -z), (x, -y, -z), (x, y, -z), (-x, y, -z), (-x, -y, z), (x, -y, z), (x, y, z), (-x, y, z)]
    faces = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [3, 7, 6, 2], [0, 4, 7, 3]]
    return vertices, faces, ["back", "front", "bottom", "right", "top", "left"]


def _mesh(item: Any) -> tuple[list[Vec3], list[list[int]], list[str]] | None:
    geometry = _get(item, "geometry", {}) or {}
    vertices_value = _get(geometry, "vertices")
    faces_value = _get(geometry, "faces")
    if vertices_value is not None and faces_value is not None:
        vertices = [_vec3(point) for point in vertices_value]
        faces: list[list[int]] = []
        for face in faces_value:
            indices = [int(value) for value in face]
            if len(indices) < 3 or min(indices) < 0 or max(indices) >= len(vertices):
                raise ValidationError(f"Scene object {_object_id(item, '')!r} contains an invalid mesh face")
            faces.append(indices)
        return vertices, faces, [str(index) for index in range(len(faces))]
    kind = str(_get(item, "kind", "unknown")).lower()
    if kind not in _BOX_KINDS:
        return None
    default_size = (2.0, 1.2, 0.6)
    if kind in {"layer-plane", "conv-window", "group-frame"}:
        default_size = (2.5, 2.0, 0.08)
    size = _vec3(_get(geometry, "size", _get(geometry, "dimensions")), default_size)
    center = _vec3(_get(geometry, "center"), (0.0, 0.0, 0.0))
    vertices, faces, names = _box_mesh(size)
    if center != (0.0, 0.0, 0.0):
        vertices = [_add(point, center) for point in vertices]
    return vertices, faces, names


def _route(item: Any) -> tuple[str, list[Vec3]] | None:
    kind = str(_get(item, "kind", "")).lower()
    geometry = _get(item, "geometry", {}) or {}
    values = _get(geometry, "points")
    if values is None:
        start, end = _get(geometry, "start"), _get(geometry, "end")
        if start is not None and end is not None:
            controls = _get(geometry, "controls", []) or []
            values = [start, *controls, end]
    if values is None or kind not in _ROUTE_KINDS:
        return None
    points = [_vec3(point) for point in values]
    if len(points) < 2:
        raise ValidationError(f"Scene route {_object_id(item, '')!r} requires at least two points")
    if kind == "bezier-route" and len(points) != 4:
        raise ValidationError(f"Scene bezier route {_object_id(item, '')!r} requires exactly four points")
    metadata = _item_metadata(item)
    directional_critical_route = bool(metadata.get("architecture_route_id"))
    projected_kind = (
        "bezier"
        if kind == "bezier-route"
        else (
            "arrow"
            if directional_critical_route
            or kind in {"arrow", "residual-skip", "unet-skip", "qkv-branch", "expert-branch"}
            else "polyline"
        )
    )
    return projected_kind, points


def _front_facing(projected: Sequence[tuple[float, float, float]]) -> bool:
    if len(projected) < 3:
        return False
    # Screen Y points down, so outward CCW faces are front-facing when their
    # projected signed area is negative.  This matches GPU winding after the
    # viewport transform for perspective and orthographic cameras alike.
    area = sum(
        projected[index][0] * projected[(index + 1) % len(projected)][1] - projected[(index + 1) % len(projected)][0] * projected[index][1]
        for index in range(len(projected))
    )
    return area < -_EPSILON


def _edges(faces: Sequence[Sequence[int]]) -> dict[tuple[int, int], set[int]]:
    result: dict[tuple[int, int], set[int]] = {}
    for face_index, face in enumerate(faces):
        for index, start in enumerate(face):
            end = face[(index + 1) % len(face)]
            edge = (min(start, end), max(start, end))
            result.setdefault(edge, set()).add(face_index)
    return result


def _point_in_triangle(point: tuple[float, float], triangle: Sequence[tuple[float, float, float]]) -> tuple[float, float, float] | None:
    (px, py), (a, b, c) = point, triangle
    denominator = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
    if abs(denominator) <= _EPSILON:
        return None
    first = ((b[1] - c[1]) * (px - c[0]) + (c[0] - b[0]) * (py - c[1])) / denominator
    second = ((c[1] - a[1]) * (px - c[0]) + (a[0] - c[0]) * (py - c[1])) / denominator
    third = 1.0 - first - second
    tolerance = 1.0e-6
    if first < -tolerance or second < -tolerance or third < -tolerance:
        return None
    return first, second, third


def _occluded(point: tuple[float, float, float], object_id: str, faces: Sequence[_Face]) -> bool:
    for face in faces:
        if face.object_id == object_id or face.style.get("opacity", 1.0) < 0.98:
            continue
        polygon = face.projected
        for index in range(1, len(polygon) - 1):
            triangle = [polygon[0], polygon[index], polygon[index + 1]]
            weights = _point_in_triangle((point[0], point[1]), triangle)
            if weights is None:
                continue
            surface_depth = sum(weight * vertex[2] for weight, vertex in zip(weights, triangle))
            if surface_depth < point[2] - 1.0e-5:
                return True
    return False


def _visible_line_chunks(line: _Line, faces: Sequence[_Face], options: ProjectionOptions) -> list[list[tuple[float, float, float]]]:
    if not options.hidden_edges or len(line.projected) != 2:
        return [line.projected]
    start, end = line.projected
    samples: list[tuple[tuple[float, float, float], bool]] = []
    for index in range(options.occlusion_samples + 1):
        amount = index / options.occlusion_samples
        point = (
            start[0] + (end[0] - start[0]) * amount,
            start[1] + (end[1] - start[1]) * amount,
            start[2] + (end[2] - start[2]) * amount,
        )
        samples.append((point, not _occluded(point, line.object_id, faces)))
    chunks: list[list[tuple[float, float, float]]] = []
    current: list[tuple[float, float, float]] = []
    for point, visible in samples:
        if visible:
            current.append(point)
        elif current:
            if len(current) >= 2:
                chunks.append([current[0], current[-1]])
            current = []
    if len(current) >= 2:
        chunks.append([current[0], current[-1]])
    return chunks


def _label_text(item: Any) -> str:
    geometry, metadata = _get(item, "geometry", {}) or {}, _get(item, "metadata", {}) or {}
    value = _get(geometry, "text", _get(metadata, "label", _get(item, "label", _get(item, "name", ""))))
    return str(value or "").strip()


def _label_anchor(item: Any, matrix: Mat4, vertices: Sequence[Vec3]) -> Vec3:
    geometry = _get(item, "geometry", {}) or {}
    anchor = _get(geometry, "label_position", _get(geometry, "anchor"))
    if anchor is not None:
        return transform_point(matrix, _vec3(anchor))
    if vertices:
        local = (
            sum(point[0] for point in vertices) / len(vertices),
            sum(point[1] for point in vertices) / len(vertices),
            sum(point[2] for point in vertices) / len(vertices),
        )
        return transform_point(matrix, local)
    return transform_point(matrix, (0.0, 0.0, 0.0))


def _boxes_overlap(first: tuple[float, float, float, float], second: tuple[float, float, float, float], padding: float) -> bool:
    return not (first[2] + padding <= second[0] or second[2] + padding <= first[0] or first[3] + padding <= second[1] or second[3] + padding <= first[1])


def _item_metadata(item: Any) -> Mapping[str, Any]:
    metadata = _get(item, "metadata", {}) or {}
    return metadata if isinstance(metadata, Mapping) else {}


def _is_decorative(item: Any) -> bool:
    kind = str(_get(item, "kind", "")).lower()
    metadata = _item_metadata(item)
    return bool(kind == "group-frame" or metadata.get("decorative") or metadata.get("frame_role"))


def _exclude_from_framing(item: Any) -> bool:
    return _is_decorative(item) or bool(_item_metadata(item).get("exclude_from_framing"))


def _publication_visible(item: Any, options: ProjectionOptions) -> bool:
    if not _is_decorative(item):
        return True
    if options.density != "detailed":
        return False
    return not bool(_item_metadata(item).get("hidden_in_detailed"))


def _world_geometry_points(scene: Any, item: Any) -> list[Vec3]:
    matrix = _world_matrix(scene, item)
    mesh = _mesh(item)
    if mesh is not None:
        return [transform_point(matrix, point) for point in mesh[0]]
    route = _route(item)
    if route is not None:
        return [transform_point(matrix, point) for point in route[1]]
    return [transform_point(matrix, (0.0, 0.0, 0.0))]


def _fit_projection(
    scene: Any,
    camera: Any,
    objects: Sequence[Any],
    options: ProjectionOptions,
) -> tuple[Mat4, Mat4, dict[str, Any]]:
    """Return a camera-consistent clip transform fitted to substantive content.

    The fit is applied as a projection-matrix crop, so every paper backend uses
    exactly the same camera result. Decorative frames never enter the bounds.
    """

    view, projection = _camera_matrices(camera, options)
    included = [item for item in objects if not _exclude_from_framing(item)]
    excluded_ids = [_object_id(item, "") for item in objects if _exclude_from_framing(item)]
    if not options.auto_frame or not included:
        return (
            view,
            projection,
            {
                "applied": False,
                "target_occupancy": options.target_occupancy,
                "included_object_ids": [_object_id(item, "") for item in included],
                "excluded_decorative_object_ids": excluded_ids,
            },
        )

    ndc_points: list[tuple[float, float]] = []
    for item in included:
        for point in _world_geometry_points(scene, item):
            camera_point = _mat4_vec4(view, (*point, 1.0))
            if camera_point[2] >= -_EPSILON:
                continue
            clip = _mat4_vec4(projection, camera_point)
            if abs(clip[3]) <= _EPSILON:
                continue
            ndc_points.append((clip[0] / clip[3], clip[1] / clip[3]))
    if not ndc_points:
        return (
            view,
            projection,
            {
                "applied": False,
                "target_occupancy": options.target_occupancy,
                "included_object_ids": [_object_id(item, "") for item in included],
                "excluded_decorative_object_ids": excluded_ids,
                "reason": "no projectable substantive geometry",
            },
        )

    minimum_x = min(point[0] for point in ndc_points)
    maximum_x = max(point[0] for point in ndc_points)
    minimum_y = min(point[1] for point in ndc_points)
    maximum_y = max(point[1] for point in ndc_points)
    span_x = max(maximum_x - minimum_x, 1.0e-5)
    span_y = max(maximum_y - minimum_y, 1.0e-5)
    scale = min(2.0 * options.target_occupancy / span_x, 2.0 * options.target_occupancy / span_y)
    scale = min(max(scale, 0.01), 100.0)
    centre_x = (minimum_x + maximum_x) / 2.0
    centre_y = (minimum_y + maximum_y) / 2.0
    crop: Mat4 = (
        (scale, 0.0, 0.0, -scale * centre_x),
        (0.0, scale, 0.0, -scale * centre_y),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )
    fitted = mat4_multiply(crop, projection)
    return (
        view,
        fitted,
        {
            "applied": True,
            "method": "camera-projection-crop",
            "target_occupancy": options.target_occupancy,
            "raw_ndc_bounds": [minimum_x, minimum_y, maximum_x, maximum_y],
            "projection_scale": scale,
            "included_object_ids": [_object_id(item, "") for item in included],
            "excluded_decorative_object_ids": excluded_ids,
        },
    )


def _label_priority(item: Any, text: str) -> float:
    kind = str(_get(item, "kind", "unknown")).lower()
    metadata = _item_metadata(item)
    role = str(metadata.get("architecture_role", "")).lower()
    lowered = text.casefold()
    if kind in {"legend", "caption"} or metadata.get("caption"):
        return 110.0
    if any(token in lowered for token in ("input", "output", "stem", "head")):
        return 100.0
    if kind in _ROUTE_KINDS:
        return 72.0 if metadata.get("template_only") else 8.0
    if role and role not in {"unknown", "summary", "operation"}:
        return 82.0
    if kind in {"attention-head", "moe-router", "merge", "fusion", "timestep-conditioning"}:
        return 78.0
    if re.search(r"\bsummary\s+\d+", lowered):
        return 30.0
    return 58.0


def _abbreviate_label(text: str, density: str) -> str:
    value = " ".join(str(text).split())
    if value.startswith("3D depth and thickness are editable visual mappings"):
        value = "Depth/thickness are visual."
    summary = re.fullmatch(r"Summary\s+(\d+)\s*\([^)]*\)", value, flags=re.IGNORECASE)
    if summary:
        value = f"Summary {summary.group(1)}"
    value = re.sub(r"\s+to\s+Summary\s+\d+.*$", " flow", value, flags=re.IGNORECASE)
    limits = {"compact": 18, "paper": 40, "detailed": 56}
    limit = limits[density]
    if len(value) <= limit:
        return value
    clipped = value[: limit - 1].rsplit(" ", 1)[0]
    return (clipped or value[: limit - 1]) + "…"


def _select_labels(pending: Sequence[_LabelCandidate], options: ProjectionOptions) -> list[_LabelCandidate]:
    budget = options.label_budget or {"compact": 5, "paper": 9, "detailed": 36}[options.density]
    prepared: list[_LabelCandidate] = []
    route_groups: dict[tuple[str, str], list[_LabelCandidate]] = {}
    for candidate in pending:
        kind = str(candidate.metadata.get("source_kind", "unknown")).lower()
        if candidate.metadata.get("decorative"):
            continue
        if candidate.metadata.get("architecture_role_id"):
            prepared.append(
                _LabelCandidate(
                    candidate.object_id,
                    candidate.text,
                    candidate.anchor,
                    candidate.style,
                    {**candidate.metadata, "reader_visible_required": True},
                    candidate.priority,
                )
            )
            continue
        if kind in _ROUTE_KINDS:
            if options.density != "detailed":
                continue
            key = (kind, _abbreviate_label(candidate.text, options.density))
            route_groups.setdefault(key, []).append(candidate)
            continue
        prepared.append(candidate)
    for (_kind, short_text), group in sorted(route_groups.items()):
        anchor = tuple(sum(item.anchor[axis] for item in group) / len(group) for axis in range(3))
        first = min(group, key=lambda item: item.object_id)
        prepared.append(
            _LabelCandidate(
                first.object_id,
                f"{short_text} ×{len(group)}" if len(group) > 1 else short_text,
                cast(tuple[float, float, float], anchor),
                first.style,
                {**first.metadata, "aggregated_object_ids": sorted(item.object_id for item in group)},
                first.priority,
            )
        )

    prepared = [
        _LabelCandidate(
            item.object_id,
            item.text if item.metadata.get("reader_visible_required") else _abbreviate_label(item.text, options.density),
            item.anchor,
            item.style,
            item.metadata,
            item.priority,
        )
        for item in prepared
    ]
    captions = sorted(
        [item for item in prepared if item.metadata.get("caption")],
        key=lambda item: (-item.priority, item.object_id),
    )
    pool = [item for item in prepared if not item.metadata.get("caption")]
    required = sorted(
        [item for item in pool if item.metadata.get("reader_visible_required")],
        key=lambda item: (str(item.metadata.get("architecture_role_id")), item.object_id),
    )
    required_role_ids = {
        str(item.metadata.get("architecture_role_id")) for item in required
    }
    if len(required_role_ids) <= 12:
        if len(required_role_ids) != len(required):
            raise ValidationError("Each required Architecture Role must have exactly one direct label candidate")
        selected: list[_LabelCandidate] = list(required)
        budget = max(budget, len(selected) + min(1, len(captions)))
        pool = [item for item in pool if not item.metadata.get("reader_visible_required")]
    else:
        selected = []
    while pool and len(selected) < max(0, budget - len(captions)):

        def score(item: _LabelCandidate) -> tuple[float, str]:
            if not selected:
                spread = 0.0
            else:
                spread = min(math.hypot(item.anchor[0] - other.anchor[0], item.anchor[1] - other.anchor[1]) for other in selected)
            return (item.priority * 10.0 + spread, item.object_id)

        chosen = max(pool, key=score)
        selected.append(chosen)
        pool.remove(chosen)
    return sorted([*selected, *captions[:1]], key=lambda item: (-item.priority, item.anchor[0], item.object_id))


def _box_for_points(points: Sequence[tuple[float, float]], padding: float = 0.0) -> tuple[float, float, float, float]:
    return (
        min(point[0] for point in points) - padding,
        min(point[1] for point in points) - padding,
        max(point[0] for point in points) + padding,
        max(point[1] for point in points) + padding,
    )


def _segment_box_intersection(
    start: tuple[float, float],
    end: tuple[float, float],
    box: tuple[float, float, float, float],
) -> bool:
    """Liang-Barsky segment/axis-aligned-box intersection."""

    dx, dy = end[0] - start[0], end[1] - start[1]
    p = (-dx, dx, -dy, dy)
    q = (start[0] - box[0], box[2] - start[0], start[1] - box[1], box[3] - start[1])
    lower, upper = 0.0, 1.0
    for direction, distance in zip(p, q):
        if abs(direction) <= _EPSILON:
            if distance < 0.0:
                return False
            continue
        amount = distance / direction
        if direction < 0.0:
            lower = max(lower, amount)
        else:
            upper = min(upper, amount)
        if lower > upper:
            return False
    return True


def _layout_labels(
    pending: Sequence[_LabelCandidate],
    options: ProjectionOptions,
    object_boxes: Mapping[str, tuple[float, float, float, float]],
    route_segments: Sequence[tuple[str, tuple[float, float], tuple[float, float], frozenset[str]]],
) -> list[ProjectedPrimitive]:
    result: list[ProjectedPrimitive] = []
    occupied: list[tuple[float, float, float, float]] = []
    selected_candidates = _select_labels(pending, options)
    for candidate in selected_candidates:
        object_id, label, anchor = candidate.object_id, candidate.text, candidate.anchor
        style, source_metadata = candidate.style, candidate.metadata
        font_pt = max(options.min_label_pt, _number(style.get("font_size_pt"), options.min_label_pt))
        height = font_pt * PT_TO_MM * 1.25
        character_width = font_pt * PT_TO_MM * 0.62
        available_width = options.width_mm - options.margin_mm * 2.0
        maximum_characters = max(4, int(available_width / max(character_width, _EPSILON)))
        display_text = label if len(label) <= maximum_characters else label[: maximum_characters - 1] + "…"
        width = min(available_width, max(height, len(display_text) * character_width))
        step = options.label_padding_mm
        own = object_boxes.get(object_id)
        if source_metadata.get("caption"):
            offsets = [(options.width_mm / 2.0, options.height_mm - options.margin_mm - height / 2.0)]
        elif own is not None:
            offsets = [
                ((own[0] + own[2]) / 2.0, own[1] - step - height / 2.0),
                ((own[0] + own[2]) / 2.0, own[3] + step + height / 2.0),
                (own[0] - step - width / 2.0, (own[1] + own[3]) / 2.0),
                (own[2] + step + width / 2.0, (own[1] + own[3]) / 2.0),
                (own[0] - step - width / 2.0, own[1] - step - height / 2.0),
                (own[2] + step + width / 2.0, own[1] - step - height / 2.0),
                (own[0] - step - width / 2.0, own[3] + step + height / 2.0),
                (own[2] + step + width / 2.0, own[3] + step + height / 2.0),
            ]
        else:
            offsets = [
                (anchor[0], anchor[1] - height - step),
                (anchor[0], anchor[1] + height + step),
                (anchor[0] - width / 2.0 - step, anchor[1]),
                (anchor[0] + width / 2.0 + step, anchor[1]),
            ]
        selected: tuple[float, float, float, float] | None = None
        if source_metadata.get("caption"):
            selected = (
                options.margin_mm,
                options.height_mm - options.margin_mm - height,
                min(options.width_mm - options.margin_mm, options.margin_mm + width),
                options.height_mm - options.margin_mm,
            )
        for centre_x, centre_y in offsets:
            if selected is not None:
                break
            left = centre_x - width / 2.0
            top = centre_y - height / 2.0
            candidate_box = (left, top, left + width, top + height)
            inside_page = (
                candidate_box[0] >= options.margin_mm
                and candidate_box[1] >= options.margin_mm
                and candidate_box[2] <= options.width_mm - options.margin_mm
                and candidate_box[3] <= options.height_mm - options.margin_mm
            )
            blocked_by_object = any(
                other_id != object_id and _boxes_overlap(candidate_box, other, options.label_padding_mm * 0.35) for other_id, other in object_boxes.items()
            )
            blocked_by_route = any(
                route_id != object_id and _segment_box_intersection(start, end, candidate_box)
                for route_id, start, end, _endpoint_ids in route_segments
            )
            if (
                inside_page
                and not blocked_by_object
                and not blocked_by_route
                and not any(_boxes_overlap(candidate_box, other, options.label_padding_mm) for other in occupied)
            ):
                selected = candidate_box
                break
        if selected is None:
            # Deterministic external label lanes. Low-priority labels are
            # suppressed when no collision-free physical slot exists.
            maximum_left = options.width_mm - options.margin_mm - width
            lane_tops = [options.margin_mm, options.height_mm - options.margin_mm - height]
            lane_candidates: list[tuple[float, float, float, float]] = []

            def distance_to_source(
                box: tuple[float, float, float, float],
                source_box: tuple[float, float, float, float] | None = own,
                source_anchor: tuple[float, float, float] = anchor,
            ) -> tuple[float, float, float]:
                if source_box is not None:
                    dx = max(source_box[0] - box[2], box[0] - source_box[2], 0.0)
                    dy = max(source_box[1] - box[3], box[1] - source_box[3], 0.0)
                else:
                    dx = max(box[0] - source_anchor[0], source_anchor[0] - box[2], 0.0)
                    dy = max(box[1] - source_anchor[1], source_anchor[1] - box[3], 0.0)
                return (math.hypot(dx, dy), box[1], box[0])

            for top in lane_tops:
                left = options.margin_mm
                while left <= maximum_left + _EPSILON:
                    candidate_box = (left, top, left + width, top + height)
                    blocked_by_object = any(
                        other_id != object_id and _boxes_overlap(candidate_box, other, options.label_padding_mm * 0.35)
                        for other_id, other in object_boxes.items()
                    )
                    blocked_by_route = any(
                        route_id != object_id and _segment_box_intersection(start, end, candidate_box)
                        for route_id, start, end, _endpoint_ids in route_segments
                    )
                    if (
                        not blocked_by_object
                        and not blocked_by_route
                        and not any(_boxes_overlap(candidate_box, other, options.label_padding_mm) for other in occupied)
                    ):
                        lane_candidates.append(candidate_box)
                    left += width + options.label_padding_mm
            if lane_candidates:
                selected = min(lane_candidates, key=distance_to_source)
        if selected is None and source_metadata.get("reader_visible_required"):
            maximum_left = options.width_mm - options.margin_mm - width
            maximum_top = options.height_mm - options.margin_mm - height
            top = options.margin_mm
            grid_candidates: list[tuple[float, float, float, float]] = []
            while top <= maximum_top + _EPSILON:
                left = options.margin_mm
                while left <= maximum_left + _EPSILON:
                    candidate_box = (left, top, left + width, top + height)
                    blocked_by_object = any(
                        other_id != object_id
                        and _boxes_overlap(candidate_box, other, options.label_padding_mm * 0.35)
                        for other_id, other in object_boxes.items()
                    )
                    blocked_by_route = any(
                        route_id != object_id
                        and _segment_box_intersection(start, end, candidate_box)
                        for route_id, start, end, _endpoint_ids in route_segments
                    )
                    if (
                        not blocked_by_object
                        and not blocked_by_route
                        and not any(
                            _boxes_overlap(candidate_box, other, options.label_padding_mm)
                            for other in occupied
                        )
                    ):
                        grid_candidates.append(candidate_box)
                    left += max(options.label_padding_mm, width * 0.5)
                top += max(options.label_padding_mm, height * 0.75)
            if grid_candidates:
                selected = min(grid_candidates, key=distance_to_source)
        if selected is None:
            if source_metadata.get("reader_visible_required"):
                raise ValidationError(
                    f"Required Architecture Role label {source_metadata.get('architecture_role_id')!r} has no collision-free page position",
                    hint="Increase page area or adjust the architecture camera/layout; protected reader-visible labels cannot be hidden.",
                )
            continue
        occupied.append(selected)
        centre = ((selected[0] + selected[2]) / 2.0, (selected[1] + selected[3]) / 2.0)
        if not source_metadata.get("caption") and math.hypot(centre[0] - anchor[0], centre[1] - anchor[1]) > height:
            if own is not None:
                target = (
                    min(max(centre[0], own[0]), own[2]),
                    min(max(centre[1], own[1]), own[3]),
                )
            else:
                target = (anchor[0], anchor[1])
            start = (
                min(max(target[0], selected[0]), selected[2]),
                min(max(target[1], selected[1]), selected[3]),
            )
            if (
                options.auto_frame
                and options.density != "detailed"
                and not source_metadata.get("reader_visible_required")
                and math.hypot(start[0] - target[0], start[1] - target[1]) > options.max_leader_mm
            ):
                occupied.pop()
                continue
            result.append(
                ProjectedPrimitive(
                    "leader",
                    object_id,
                    anchor[2],
                    [start, target],
                    {**style, "fill": "none", "opacity": min(0.55, style.get("opacity", 1.0))},
                    metadata={**source_metadata, "label_for": object_id, "routing": "shortest-box-normal"},
                )
            )
        result.append(
            ProjectedPrimitive(
                "label",
                object_id,
                anchor[2],
                [(selected[0], selected[1])],
                {**style, "font_size_pt": font_pt, "fill": "#0f172a", "text_bbox_mm": list(selected)},
                text=display_text,
                metadata={
                    **source_metadata,
                    "anchor": [anchor[0], anchor[1]],
                    "collision_avoided": True,
                    "billboard": True,
                    "full_text": candidate.text,
                    "abbreviated": display_text != candidate.text,
                    "priority": candidate.priority,
                },
            )
        )
    return result


def _scene_digest(scene: Any) -> str:
    if hasattr(scene, "digest"):
        try:
            return str(scene.digest())
        except TypeError:
            pass
    document = scene.to_dict() if hasattr(scene, "to_dict") else _plain(scene)
    encoded = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def project_scene(
    scene: Any,
    *,
    camera_id: str | None = None,
    options: ProjectionOptions | Mapping[str, Any] | None = None,
) -> ProjectedScene:
    """Project Scene IR into deterministic, format-neutral vector primitives."""

    if hasattr(scene, "validate"):
        scene.validate()
    resolved = ProjectionOptions.coerce(options)
    camera = _camera(scene, camera_id)
    visible_objects = [item for item in _objects(scene, visible_only=True) if bool(_get(item, "visible", True))]
    view, projection, framing = _fit_projection(scene, camera, visible_objects, resolved)
    render_objects = [item for item in visible_objects if _publication_visible(item, resolved)]
    faces: list[_Face] = []
    lines: list[_Line] = []
    labels: list[_LabelCandidate] = []

    for ordinal, item in enumerate(render_objects):
        object_id = _object_id(item, f"object:{ordinal:04d}")
        matrix = _world_matrix(scene, item)
        style = _style(item, resolved)
        item_metadata = _item_metadata(item)
        source_metadata = {
            "source_kind": str(_get(item, "kind", "unknown")),
            "provenance": _plain(_get(item, "provenance", {})),
            "locked": bool(_get(item, "locked", False)),
            "selected": bool(_get(item, "selected", False)),
            "decorative": _is_decorative(item),
            "caption": bool(item_metadata.get("caption") or str(_get(item, "kind", "")).lower() in {"legend", "caption"}),
            "template_only": bool(item_metadata.get("template_only")),
            "architecture_role": str(item_metadata.get("architecture_role", "")),
            "architecture_role_id": item_metadata.get("architecture_role_id"),
            "architecture_route_id": item_metadata.get("architecture_route_id"),
            "architecture_route_role": item_metadata.get("architecture_route_role"),
            "architecture_role_graph_edge_id": item_metadata.get("architecture_role_graph_edge_id"),
            "architecture_direction": item_metadata.get("architecture_direction"),
            "architecture_evidence_digest": item_metadata.get("architecture_evidence_digest"),
            "architecture_role_graph_digest": item_metadata.get("architecture_role_graph_digest"),
            "repeat_count": int(item_metadata.get("repeat_count", 1) or 1),
            "bundled_edge_count": int(item_metadata.get("bundled_edge_count", 1) or 1),
            "endpoint_object_ids": _plain(item_metadata.get("endpoint_object_ids", [])),
            "endpoint_role_ids": _plain(item_metadata.get("endpoint_role_ids", [])),
        }
        mesh = _mesh(item)
        local_vertices: list[Vec3] = []
        if mesh is not None:
            local_vertices, mesh_faces, face_names = mesh
            world_vertices = [transform_point(matrix, point) for point in local_vertices]
            projected_vertices = [
                project_point(point, view, projection, width_mm=resolved.width_mm, height_mm=resolved.height_mm, margin_mm=resolved.margin_mm)
                for point in world_vertices
            ]
            material = _get(item, "material", {}) or {}
            face_colours = _get(material, "face_colors", {}) or {}
            front_indices: set[int] = set()
            for face_index, indices in enumerate(mesh_faces):
                if any(projected_vertices[index] is None for index in indices):
                    continue
                world_face = [world_vertices[index] for index in indices]
                projected_face = [projected_vertices[index] for index in indices if projected_vertices[index] is not None]
                front = _front_facing(projected_face)  # type: ignore[arg-type]
                face_style = dict(style)
                named_colour = face_colours.get(face_names[face_index]) if isinstance(face_colours, Mapping) else None
                if named_colour:
                    face_style["fill"] = _hex_colour(named_colour, style["fill"])
                if front:
                    front_indices.add(face_index)
                if resolved.backface_culling and not front and not style.get("double_sided"):
                    continue
                faces.append(
                    _Face(
                        object_id,
                        face_index,
                        world_face,
                        projected_face,  # type: ignore[arg-type]
                        face_style,
                        front,
                        source_metadata,
                    )
                )
            for edge, adjacent_faces in sorted(_edges(mesh_faces).items()):
                if resolved.hidden_edges and adjacent_faces and not (adjacent_faces & front_indices):
                    continue
                projected_edge = [projected_vertices[index] for index in edge]
                if any(point is None for point in projected_edge):
                    continue
                projected_edge_values = cast(list[tuple[float, float, float]], projected_edge)
                lines.append(
                    _Line(
                        "edge",
                        object_id,
                        projected_edge_values,
                        {**style, "fill": "none"},
                        {**source_metadata, "vertex_indices": list(edge)},
                    )
                )

        route = _route(item)
        if route is not None:
            route_kind, local_points = route
            projected_route = [
                project_point(
                    transform_point(matrix, point), view, projection, width_mm=resolved.width_mm, height_mm=resolved.height_mm, margin_mm=resolved.margin_mm
                )
                for point in local_points
            ]
            if all(point is not None for point in projected_route):
                lines.append(_Line(route_kind, object_id, projected_route, {**style, "fill": "none"}, source_metadata))  # type: ignore[arg-type]

        label = _label_text(item)
        if label:
            projected_anchor = project_point(
                _label_anchor(item, matrix, local_vertices),
                view,
                projection,
                width_mm=resolved.width_mm,
                height_mm=resolved.height_mm,
                margin_mm=resolved.margin_mm,
            )
            if projected_anchor is not None:
                labels.append(
                    _LabelCandidate(
                        object_id,
                        label,
                        projected_anchor,
                        style,
                        source_metadata,
                        _label_priority(item, label),
                    )
                )

    primitives: list[ProjectedPrimitive] = []
    # Painter's algorithm for opaque vector faces: far to near, with stable
    # object/face tiebreakers.  This order changes correctly with the camera.
    visible_faces = sorted(faces, key=lambda face: (-face.depth, face.object_id, face.index))
    for face in visible_faces:
        primitives.append(
            ProjectedPrimitive(
                "face",
                face.object_id,
                face.depth,
                [(point[0], point[1]) for point in face.projected],
                face.style,
                metadata={**face.metadata, "face_index": face.index, "front_facing": face.front},
            )
        )

    # Edges/routes sit above filled faces, but occluded spans are removed by a
    # small deterministic software visibility pass rather than hidden by DOM
    # ordering alone.
    for line in sorted(lines, key=lambda item: (-sum(point[2] for point in item.projected) / len(item.projected), item.object_id, item.kind)):
        if line.kind == "bezier":
            primitives.append(
                ProjectedPrimitive(
                    "bezier",
                    line.object_id,
                    sum(point[2] for point in line.projected) / len(line.projected),
                    [(point[0], point[1]) for point in line.projected],
                    line.style,
                    metadata=line.metadata,
                )
            )
            continue
        if len(line.projected) > 2 and resolved.hidden_edges:
            chunks = []
            for start, end in zip(line.projected, line.projected[1:]):
                segment = _Line(line.kind, line.object_id, [start, end], line.style, line.metadata)
                chunks.extend(_visible_line_chunks(segment, visible_faces, resolved))
        elif len(line.projected) > 2:
            chunks = [line.projected]
        else:
            chunks = _visible_line_chunks(line, visible_faces, resolved)
        for chunk_index, chunk in enumerate(chunks):
            ends_at_route_tip = all(abs(chunk[-1][axis] - line.projected[-1][axis]) <= 1.0e-7 for axis in range(3))
            # Route tips usually terminate inside the target volume.  Hidden
            # line removal therefore clips the literal tip at the visible
            # target boundary; the last surviving chunk must still carry the
            # arrowhead or every publication backend silently loses direction.
            if line.kind == "arrow" and (ends_at_route_tip or chunk_index == len(chunks) - 1):
                kind = "arrow"
            elif line.kind in {"arrow", "polyline"}:
                kind = "polyline"
            else:
                kind = "edge"
            primitives.append(
                ProjectedPrimitive(
                    kind,
                    line.object_id,
                    sum(point[2] for point in chunk) / len(chunk),
                    [(point[0], point[1]) for point in chunk],
                    line.style,
                    metadata={**line.metadata, "visible_chunk": chunk_index},
                )
            )

    object_box_points: dict[str, list[tuple[float, float]]] = {}
    for face in visible_faces:
        if face.metadata.get("decorative"):
            continue
        object_box_points.setdefault(face.object_id, []).extend((point[0], point[1]) for point in face.projected)
    object_boxes = {object_id: _box_for_points(points, 0.35) for object_id, points in object_box_points.items() if points}
    route_segments = [
        (
            line.object_id,
            (start[0], start[1]),
            (end[0], end[1]),
            frozenset(str(item) for item in line.metadata.get("endpoint_object_ids", [])),
        )
        for line in lines
        if str(line.metadata.get("source_kind", "")).lower() in _ROUTE_KINDS
        for start, end in zip(line.projected, line.projected[1:])
    ]
    label_primitives = _layout_labels(labels, resolved, object_boxes, route_segments)
    primitives.extend(label_primitives)
    if object_boxes:
        content_box = (
            min(box[0] for box in object_boxes.values()),
            min(box[1] for box in object_boxes.values()),
            max(box[2] for box in object_boxes.values()),
            max(box[3] for box in object_boxes.values()),
        )
        drawable_width = resolved.width_mm - 2.0 * resolved.margin_mm
        drawable_height = resolved.height_mm - 2.0 * resolved.margin_mm
        framing["content_bbox_mm"] = list(content_box)
        framing["content_occupancy"] = {
            "width": min(1.0, (content_box[2] - content_box[0]) / drawable_width),
            "height": min(1.0, (content_box[3] - content_box[1]) / drawable_height),
            "max_axis": min(
                1.0,
                max(
                    (content_box[2] - content_box[0]) / drawable_width,
                    (content_box[3] - content_box[1]) / drawable_height,
                ),
            ),
        }
    framing["density"] = resolved.density
    framing["label_candidates"] = len(labels)
    framing["visible_labels"] = sum(item.kind == "label" for item in label_primitives)
    framing["suppressed_labels"] = len(labels) - framing["visible_labels"]
    expected_role_ids = {
        str(item.metadata.get("architecture_role_id"))
        for item in labels
        if item.metadata.get("architecture_role_id")
    }
    visible_role_ids = {
        str(item.metadata.get("architecture_role_id"))
        for item in label_primitives
        if item.kind == "label" and item.metadata.get("architecture_role_id")
    }
    framing["expected_role_ids"] = sorted(expected_role_ids)
    framing["visible_role_ids"] = sorted(visible_role_ids)
    framing["expected_role_count"] = len(expected_role_ids)
    framing["visible_role_count"] = len(visible_role_ids)
    if len(expected_role_ids) <= 12 and visible_role_ids != expected_role_ids:
        raise ValidationError(
            "Scene projection did not land every required Architecture Role label",
            details={
                "missing_role_ids": sorted(expected_role_ids - visible_role_ids),
                "extra_role_ids": sorted(visible_role_ids - expected_role_ids),
            },
        )
    projected = ProjectedScene(
        scene_id=str(_get(scene, "id", _get(scene, "name", "scene"))),
        camera_id=str(_get(camera, "id", "camera:auto-isometric")),
        width_mm=resolved.width_mm,
        height_mm=resolved.height_mm,
        view_matrix=view,
        projection_matrix=projection,
        primitives=primitives,
        options=resolved,
        source_digest=_scene_digest(scene),
        framing=framing,
    )
    projected.validate()
    return projected


__all__ = [
    "Mat4",
    "ProjectedPrimitive",
    "ProjectedScene",
    "ProjectionOptions",
    "SCENE_PROJECTION_VERSION",
    "identity_matrix",
    "look_at_matrix",
    "mat4_multiply",
    "orthographic_matrix",
    "perspective_matrix",
    "project_point",
    "project_scene",
    "transform_point",
]
