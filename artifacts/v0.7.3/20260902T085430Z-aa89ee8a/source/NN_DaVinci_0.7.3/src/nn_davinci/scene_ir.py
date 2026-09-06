"""Versioned, evidence-aware Scene IR for editable scientific 3D figures.

Scene IR is authoring state, not a source of model facts.  Every generated
object therefore records whether it came from Graph IR, a persisted Semantic
View, Figure IR, an explicit template, an author annotation, an external 3D
asset, or unknown evidence.  World and projection records are deterministic
derivations of transforms and cameras; loading never trusts them as model
evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
import math
import re
from typing import Any, Iterable, Iterator, Mapping, Sequence

from .errors import ValidationError
from .ir import stable_id
from .scene_math import (
    Mat4,
    Ray,
    add,
    compose_matrix,
    identity_matrix,
    inverse_matrix,
    length,
    look_at_matrix,
    matrix_multiply,
    multiply_scalar,
    normalize,
    orthographic_matrix,
    perspective_matrix,
    project_point,
    rotation_matrix_xyz,
    screen_ray,
    subtract,
    transform_direction,
    transform_point,
    transformed_bounds,
    vec3,
)


SCENE_IR_VERSION = "1.0"
MAX_SCENE_OBJECTS = 10_000
MAX_SCENE_LAYERS = 128
MAX_SCENE_GROUPS = 4_096
MAX_SCENE_CAMERAS = 32
MAX_SCENE_LIGHTS = 64
MAX_ROUTE_POINTS = 4_096
MAX_JSON_DEPTH = 32
MAX_JSON_ITEMS = 200_000
MAX_STRING_LENGTH = 16_384
MAX_ABS_COORDINATE = 1_000_000.0
MAX_ABS_ROTATION = 360_000.0
MAX_SCALE = 10_000.0

CAMERA_PROJECTIONS = frozenset({"orthographic", "perspective"})
LIGHT_KINDS = frozenset({"ambient", "directional", "point"})
PROVENANCE_KINDS = frozenset({
    "graph_ir", "semantic_view", "figure_ir", "source", "template",
    "author_annotation", "external_3d", "unknown",
})
OBJECT_KINDS = frozenset({
    "cuboid", "tensor-volume", "tensor-stack", "feature-map-stack",
    "layer-plane", "operation-block", "convolution-window", "conv-window",
    "pooling", "downsample", "upsample", "residual-skip", "unet-skip",
    "attention-head", "attention-ribbon", "qkv-branch", "token-sequence",
    "moe-router", "expert-branch", "merge", "multimodal-stream", "fusion",
    "timestep-conditioning", "group-frame", "annotation", "legend", "arrow",
    "tube", "polyline", "bezier-route", "unknown",
})
ROUTE_KINDS = frozenset({
    "residual-skip", "unet-skip", "attention-ribbon", "qkv-branch",
    "expert-branch", "arrow", "tube", "polyline",
    "bezier-route",
})
TEXT_KINDS = frozenset({"annotation", "legend"})
UNSAFE_KEYS = frozenset({"__proto__", "prototype", "constructor"})
_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?$")


def _fail(message: str, *, hint: str | None = None, details: dict[str, Any] | None = None) -> ValidationError:
    return ValidationError(message, hint=hint, details=details)


def _finite(
    value: Any,
    *,
    name: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool):
        raise _fail(f"Scene IR {name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise _fail(f"Scene IR {name} must be a finite number") from exc
    if not math.isfinite(number):
        raise _fail(f"Scene IR {name} must be a finite number")
    if minimum is not None and number < minimum:
        raise _fail(f"Scene IR {name} must be >= {minimum}")
    if maximum is not None and number > maximum:
        raise _fail(f"Scene IR {name} must be <= {maximum}")
    return number


def _string(value: Any, *, name: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise _fail(f"Scene IR {name} must be a string")
    if not allow_empty and not value.strip():
        raise _fail(f"Scene IR {name} must not be empty")
    if len(value) > MAX_STRING_LENGTH:
        raise _fail(f"Scene IR {name} exceeds the {MAX_STRING_LENGTH}-character safety limit")
    if "\x00" in value:
        raise _fail(f"Scene IR {name} contains a NUL character")
    return value


def _identifier(value: Any, *, name: str) -> str:
    identifier = _string(value, name=name)
    if any(character.isspace() for character in identifier):
        raise _fail(f"Scene IR {name} must not contain whitespace")
    return identifier


def _vector(
    value: Any,
    *,
    name: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise _fail(f"Scene IR {name} must contain exactly three numbers")
    return [
        _finite(item, name=f"{name}[{index}]", minimum=minimum, maximum=maximum)
        for index, item in enumerate(value)
    ]


def _matrix(value: Any, *, name: str) -> list[list[float]]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise _fail(f"Scene IR {name} must be a 4 x 4 matrix")
    rows: list[list[float]] = []
    for row_index, row in enumerate(value):
        if not isinstance(row, (list, tuple)) or len(row) != 4:
            raise _fail(f"Scene IR {name} must be a 4 x 4 matrix")
        rows.append([
            _finite(cell, name=f"{name}[{row_index}][{column_index}]")
            for column_index, cell in enumerate(row)
        ])
    return rows


def _color(value: Any, *, name: str) -> str:
    color = _string(value, name=name)
    if not _COLOR_PATTERN.fullmatch(color):
        raise _fail(f"Scene IR {name} must be #RRGGBB or #RRGGBBAA")
    return color.lower()


def _strict_mapping(
    value: Any,
    *,
    path: str,
    allowed: set[str] | frozenset[str],
    required: set[str] | frozenset[str] = frozenset(),
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _fail(f"Scene IR {path} must be an object")
    payload = dict(value)
    keys = set(payload)
    if not all(isinstance(key, str) for key in payload):
        raise _fail(f"Scene IR {path} keys must be strings")
    unsafe = keys.intersection(UNSAFE_KEYS)
    if unsafe:
        raise _fail(f"Scene IR {path} contains unsafe keys {sorted(unsafe)!r}")
    unknown = keys - set(allowed)
    if unknown:
        raise _fail(f"Scene IR {path} contains unsupported fields {sorted(unknown)!r}")
    missing = set(required) - keys
    if missing:
        raise _fail(f"Scene IR {path} is missing required fields {sorted(missing)!r}")
    return payload


def _safe_json(value: Any, *, path: str, depth: int = 0, counter: list[int] | None = None) -> Any:
    """Validate arbitrary metadata without evaluating or coercing payloads."""

    if counter is None:
        counter = [0]
    counter[0] += 1
    if counter[0] > MAX_JSON_ITEMS:
        raise _fail(f"Scene IR {path} exceeds the {MAX_JSON_ITEMS}-item safety budget")
    if depth > MAX_JSON_DEPTH:
        raise _fail(f"Scene IR {path} exceeds the maximum nesting depth of {MAX_JSON_DEPTH}")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        # Preserve exact integer tensor dimensions and counters.  JSON has no
        # arbitrary executable numeric types, but absurd integers can still
        # be used for memory/CPU abuse downstream, so keep them bounded.
        if abs(value) > 10**18:
            raise _fail(f"Scene IR {path} integer exceeds the safety bound")
        return value
    if isinstance(value, float):
        return _finite(value, name=path)
    if isinstance(value, str):
        return _string(value, name=path, allow_empty=True)
    if isinstance(value, list):
        return [
            _safe_json(item, path=f"{path}[{index}]", depth=depth + 1, counter=counter)
            for index, item in enumerate(value)
        ]
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            if not isinstance(raw_key, str):
                raise _fail(f"Scene IR {path} metadata keys must be strings")
            key = _string(raw_key, name=f"{path} key")
            if key in UNSAFE_KEYS:
                raise _fail(f"Scene IR {path} contains unsafe key {key!r}")
            result[key] = _safe_json(item, path=f"{path}.{key}", depth=depth + 1, counter=counter)
        return result
    raise _fail(f"Scene IR {path} contains a non-JSON value of type {type(value).__name__}")


def _unique_ids(values: Any, *, name: str) -> list[str]:
    if not isinstance(values, list):
        raise _fail(f"Scene IR {name} must be an array")
    result = [_identifier(value, name=f"{name}[{index}]") for index, value in enumerate(values)]
    if len(result) != len(set(result)):
        raise _fail(f"Scene IR {name} must not repeat IDs")
    return result


def _ordered(items: Iterable[Any]) -> list[Any]:
    return sorted(items, key=lambda item: (int(getattr(item, "order", 0)), str(getattr(item, "id", ""))))


def _matrix_lists(matrix: Mat4) -> list[list[float]]:
    return [list(row) for row in matrix]


@dataclass(slots=True)
class Transform3D:
    position: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    rotation: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    scale: list[float] = field(default_factory=lambda: [1.0, 1.0, 1.0])

    def validate(self) -> "Transform3D":
        self.position = _vector(
            self.position, name="transform.position",
            minimum=-MAX_ABS_COORDINATE, maximum=MAX_ABS_COORDINATE,
        )
        self.rotation = _vector(
            self.rotation, name="transform.rotation",
            minimum=-MAX_ABS_ROTATION, maximum=MAX_ABS_ROTATION,
        )
        self.scale = _vector(self.scale, name="transform.scale", minimum=1.0e-6, maximum=MAX_SCALE)
        return self

    def matrix(self) -> Mat4:
        self.validate()
        return compose_matrix(self.position, self.rotation, self.scale)

    def translate(self, delta: Sequence[object]) -> None:
        self.position = list(add(self.position, vec3(delta, name="translation")))
        self.validate()

    def rotate(self, delta_degrees: Sequence[object]) -> None:
        self.rotation = list(add(self.rotation, vec3(delta_degrees, name="rotation delta")))
        self.validate()

    def scale_by(self, factors: Sequence[object]) -> None:
        values = vec3(factors, name="scale factors")
        self.scale = [self.scale[index] * values[index] for index in range(3)]
        self.validate()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Transform3D":
        payload = _strict_mapping(
            data, path="transform", allowed={"position", "rotation", "scale"},
            required={"position", "rotation", "scale"},
        )
        return cls(**payload).validate()


@dataclass(slots=True)
class Material3D:
    base_color: str = "#dbeafe"
    face_colors: dict[str, str] = field(default_factory=dict)
    stroke_color: str = "#334155"
    stroke_width: float = 0.8
    opacity: float = 1.0
    metallic: float = 0.0
    roughness: float = 0.85
    unlit: bool = False

    def validate(self) -> "Material3D":
        self.base_color = _color(self.base_color, name="material.base_color")
        if not isinstance(self.face_colors, dict) or len(self.face_colors) > 32:
            raise _fail("Scene IR material.face_colors must be an object with at most 32 entries")
        self.face_colors = {
            _string(face, name="material face name"): _color(color, name=f"material.face_colors.{face}")
            for face, color in sorted(self.face_colors.items())
        }
        self.stroke_color = _color(self.stroke_color, name="material.stroke_color")
        self.stroke_width = _finite(self.stroke_width, name="material.stroke_width", minimum=0.0, maximum=100.0)
        self.opacity = _finite(self.opacity, name="material.opacity", minimum=0.0, maximum=1.0)
        self.metallic = _finite(self.metallic, name="material.metallic", minimum=0.0, maximum=1.0)
        self.roughness = _finite(self.roughness, name="material.roughness", minimum=0.0, maximum=1.0)
        if not isinstance(self.unlit, bool):
            raise _fail("Scene IR material.unlit must be boolean")
        return self

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Material3D":
        fields = {
            "base_color", "face_colors", "stroke_color", "stroke_width",
            "opacity", "metallic", "roughness", "unlit",
        }
        payload = _strict_mapping(data, path="material", allowed=fields)
        return cls(**payload).validate()


@dataclass(slots=True)
class SceneProvenance:
    kind: str
    source_id: str = ""
    graph_ir_ids: list[str] = field(default_factory=list)
    semantic_view_ids: list[str] = field(default_factory=list)
    figure_ir_ids: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    author_annotation: bool = False

    @classmethod
    def template(cls, template_id: str, *, reason: str = "Explicit editable Scene template; not model evidence.") -> "SceneProvenance":
        return cls("template", source_id=template_id, reason=reason)

    @classmethod
    def author(cls, reason: str = "Author-created 3D annotation.") -> "SceneProvenance":
        return cls("author_annotation", reason=reason, author_annotation=True)

    @classmethod
    def unknown(cls, reason: str) -> "SceneProvenance":
        return cls("unknown", reason=reason)

    def validate(self) -> "SceneProvenance":
        self.kind = _string(self.kind, name="provenance.kind")
        if self.kind not in PROVENANCE_KINDS:
            raise _fail(f"Unsupported Scene IR provenance kind {self.kind!r}")
        self.source_id = _string(self.source_id, name="provenance.source_id", allow_empty=True)
        self.graph_ir_ids = _unique_ids(self.graph_ir_ids, name="provenance.graph_ir_ids")
        self.semantic_view_ids = _unique_ids(self.semantic_view_ids, name="provenance.semantic_view_ids")
        self.figure_ir_ids = _unique_ids(self.figure_ir_ids, name="provenance.figure_ir_ids")
        self.reason = _string(self.reason, name="provenance.reason", allow_empty=True)
        self.evidence = _safe_json(self.evidence, path="provenance.evidence")
        if not isinstance(self.author_annotation, bool):
            raise _fail("Scene IR provenance.author_annotation must be boolean")
        if self.author_annotation != (self.kind == "author_annotation"):
            raise _fail("Scene IR author_annotation must be explicit and exclusive to author_annotation provenance")
        if self.kind == "graph_ir" and not self.graph_ir_ids:
            raise _fail("Scene Graph IR provenance requires graph_ir_ids")
        if self.kind == "semantic_view" and (not self.semantic_view_ids or not self.graph_ir_ids):
            raise _fail("Scene Semantic View provenance requires semantic_view_ids and graph_ir_ids")
        if self.kind == "figure_ir" and not self.figure_ir_ids:
            raise _fail("Scene Figure IR provenance requires figure_ir_ids")
        if self.kind == "template" and not self.source_id:
            raise _fail("Scene template provenance requires a template source_id")
        if self.kind in {"unknown", "author_annotation", "external_3d", "source"} and not self.reason.strip():
            raise _fail(f"Scene provenance {self.kind!r} requires a reason")
        return self

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SceneProvenance":
        fields = {
            "kind", "source_id", "graph_ir_ids", "semantic_view_ids",
            "figure_ir_ids", "evidence", "reason", "author_annotation",
        }
        payload = _strict_mapping(data, path="provenance", allowed=fields, required={"kind"})
        return cls(**payload).validate()


@dataclass(slots=True)
class WorldRecord:
    matrix: list[list[float]] = field(default_factory=lambda: _matrix_lists(identity_matrix()))
    position: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    bounds_min: list[float] = field(default_factory=lambda: [-0.5, -0.5, -0.5])
    bounds_max: list[float] = field(default_factory=lambda: [0.5, 0.5, 0.5])

    def validate(self) -> "WorldRecord":
        self.matrix = _matrix(self.matrix, name="world.matrix")
        self.position = _vector(self.position, name="world.position")
        self.bounds_min = _vector(self.bounds_min, name="world.bounds_min")
        self.bounds_max = _vector(self.bounds_max, name="world.bounds_max")
        if any(self.bounds_min[index] > self.bounds_max[index] for index in range(3)):
            raise _fail("Scene IR world bounds minimum must not exceed maximum")
        return self

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WorldRecord":
        fields = {"matrix", "position", "bounds_min", "bounds_max"}
        payload = _strict_mapping(data, path="world", allowed=fields, required=fields)
        return cls(**payload).validate()


@dataclass(slots=True)
class ProjectionRecord:
    camera_id: str
    viewport: list[float]
    point: list[float]
    depth: float
    visible: bool
    ndc: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])

    def validate(self) -> "ProjectionRecord":
        self.camera_id = _identifier(self.camera_id, name="projection.camera_id")
        if not isinstance(self.viewport, (list, tuple)) or len(self.viewport) != 2:
            raise _fail("Scene IR projection.viewport must contain width and height")
        self.viewport = [
            _finite(self.viewport[0], name="projection viewport width", minimum=1.0, maximum=1_000_000.0),
            _finite(self.viewport[1], name="projection viewport height", minimum=1.0, maximum=1_000_000.0),
        ]
        if not isinstance(self.point, (list, tuple)) or len(self.point) != 2:
            raise _fail("Scene IR projection.point must contain x and y")
        self.point = [
            _finite(self.point[0], name="projection point x"),
            _finite(self.point[1], name="projection point y"),
        ]
        self.depth = _finite(self.depth, name="projection.depth")
        self.ndc = _vector(self.ndc, name="projection.ndc")
        if not isinstance(self.visible, bool):
            raise _fail("Scene IR projection.visible must be boolean")
        return self

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProjectionRecord":
        fields = {"camera_id", "viewport", "point", "depth", "visible", "ndc"}
        payload = _strict_mapping(
            data, path="projection", allowed=fields,
            required={"camera_id", "viewport", "point", "depth", "visible"},
        )
        return cls(**payload).validate()


@dataclass(slots=True)
class Camera:
    id: str
    name: str
    projection: str = "orthographic"
    position: list[float] = field(default_factory=lambda: [12.0, 10.0, 14.0])
    target: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    up: list[float] = field(default_factory=lambda: [0.0, 1.0, 0.0])
    rotation: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    fov_y_deg: float = 45.0
    ortho_height: float = 18.0
    near: float = 0.1
    far: float = 10_000.0
    aspect: float = 1.5
    locked: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, name: str = "Isometric", **kwargs: Any) -> "Camera":
        identity = str(kwargs.pop("identity", name))
        return cls(stable_id("scene_camera", identity), name, **kwargs).validate()

    def validate(self) -> "Camera":
        self.id = _identifier(self.id, name="camera.id")
        self.name = _string(self.name, name=f"camera {self.id} name")
        self.projection = _string(self.projection, name=f"camera {self.id} projection")
        if self.projection not in CAMERA_PROJECTIONS:
            raise _fail(f"Unsupported Scene camera projection {self.projection!r}")
        self.position = _vector(
            self.position, name=f"camera {self.id} position",
            minimum=-MAX_ABS_COORDINATE, maximum=MAX_ABS_COORDINATE,
        )
        self.target = _vector(
            self.target, name=f"camera {self.id} target",
            minimum=-MAX_ABS_COORDINATE, maximum=MAX_ABS_COORDINATE,
        )
        self.up = _vector(self.up, name=f"camera {self.id} up")
        self.rotation = _vector(
            self.rotation, name=f"camera {self.id} rotation",
            minimum=-MAX_ABS_ROTATION, maximum=MAX_ABS_ROTATION,
        )
        try:
            normalize(subtract(self.target, self.position), name="camera direction")
            normalize(self.up, name="camera up")
        except ValueError as exc:
            raise _fail(f"Scene camera {self.id!r} has an invalid direction or up vector") from exc
        self.fov_y_deg = _finite(self.fov_y_deg, name="camera fov_y_deg", minimum=0.01, maximum=178.999)
        self.ortho_height = _finite(self.ortho_height, name="camera ortho_height", minimum=1.0e-4, maximum=MAX_ABS_COORDINATE)
        self.near = _finite(self.near, name="camera near", minimum=1.0e-6, maximum=MAX_ABS_COORDINATE)
        self.far = _finite(self.far, name="camera far", minimum=self.near + 1.0e-6, maximum=MAX_ABS_COORDINATE * 10.0)
        self.aspect = _finite(self.aspect, name="camera aspect", minimum=1.0e-6, maximum=1_000.0)
        if not isinstance(self.locked, bool):
            raise _fail("Scene IR camera.locked must be boolean")
        self.metadata = _safe_json(self.metadata, path=f"camera {self.id} metadata")
        return self

    def _rotated_basis(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        forward = normalize(subtract(self.target, self.position), name="camera direction")
        rotation = rotation_matrix_xyz(self.rotation)
        rotated_forward = normalize(transform_direction(rotation, forward), name="rotated camera direction")
        rotated_up = normalize(transform_direction(rotation, self.up), name="rotated camera up")
        return rotated_forward, rotated_up

    def view_matrix(self) -> Mat4:
        self.validate()
        forward, rotated_up = self._rotated_basis()
        try:
            return look_at_matrix(self.position, add(self.position, forward), rotated_up)
        except ValueError as exc:
            raise _fail(f"Scene camera {self.id!r} has collinear view and up vectors") from exc

    def projection_matrix(self) -> Mat4:
        self.validate()
        if self.projection == "perspective":
            return perspective_matrix(self.fov_y_deg, self.aspect, self.near, self.far)
        return orthographic_matrix(self.ortho_height, self.aspect, self.near, self.far)

    def project(self, world_point: Sequence[object], viewport: Sequence[object]) -> Any:
        return project_point(world_point, self.view_matrix(), self.projection_matrix(), viewport)

    def ray(self, screen_x: object, screen_y: object, viewport: Sequence[object]) -> Ray:
        return screen_ray(screen_x, screen_y, self.view_matrix(), self.projection_matrix(), viewport)

    def orbit(self, yaw_degrees: float, pitch_degrees: float) -> None:
        if self.locked:
            raise _fail(f"Scene camera {self.id!r} is locked")
        offset = subtract(self.position, self.target)
        rotated = transform_direction(rotation_matrix_xyz((pitch_degrees, yaw_degrees, 0.0)), offset)
        self.position = list(add(self.target, rotated))
        self.validate()

    def zoom(self, factor: float) -> None:
        if self.locked:
            raise _fail(f"Scene camera {self.id!r} is locked")
        amount = _finite(factor, name="camera zoom factor", minimum=1.0e-4, maximum=10_000.0)
        if self.projection == "orthographic":
            self.ortho_height /= amount
        else:
            offset = subtract(self.position, self.target)
            self.position = list(add(self.target, multiply_scalar(offset, 1.0 / amount)))
        self.validate()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Camera":
        fields = {
            "id", "name", "projection", "position", "target", "up", "rotation",
            "fov_y_deg", "ortho_height", "near", "far", "aspect", "locked", "metadata",
        }
        payload = _strict_mapping(data, path="camera", allowed=fields, required={"id", "name", "projection"})
        return cls(**payload).validate()


@dataclass(slots=True)
class Light:
    id: str
    name: str
    kind: str = "directional"
    color: str = "#ffffff"
    intensity: float = 1.0
    position: list[float] = field(default_factory=lambda: [8.0, 10.0, 12.0])
    direction: list[float] = field(default_factory=lambda: [-1.0, -1.0, -1.0])
    visible: bool = True
    locked: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, name: str = "Key light", **kwargs: Any) -> "Light":
        identity = str(kwargs.pop("identity", name))
        return cls(stable_id("scene_light", identity), name, **kwargs).validate()

    def validate(self) -> "Light":
        self.id = _identifier(self.id, name="light.id")
        self.name = _string(self.name, name=f"light {self.id} name")
        self.kind = _string(self.kind, name=f"light {self.id} kind")
        if self.kind not in LIGHT_KINDS:
            raise _fail(f"Unsupported Scene light kind {self.kind!r}")
        self.color = _color(self.color, name=f"light {self.id} color")
        self.intensity = _finite(self.intensity, name=f"light {self.id} intensity", minimum=0.0, maximum=100_000.0)
        self.position = _vector(
            self.position, name=f"light {self.id} position",
            minimum=-MAX_ABS_COORDINATE, maximum=MAX_ABS_COORDINATE,
        )
        self.direction = _vector(self.direction, name=f"light {self.id} direction")
        if self.kind == "directional":
            try:
                normalize(self.direction, name="light direction")
            except ValueError as exc:
                raise _fail(f"Directional light {self.id!r} requires a non-zero direction") from exc
        if not isinstance(self.visible, bool) or not isinstance(self.locked, bool):
            raise _fail("Scene IR light visible and locked fields must be boolean")
        self.metadata = _safe_json(self.metadata, path=f"light {self.id} metadata")
        return self

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Light":
        fields = {"id", "name", "kind", "color", "intensity", "position", "direction", "visible", "locked", "metadata"}
        payload = _strict_mapping(data, path="light", allowed=fields, required={"id", "name", "kind"})
        return cls(**payload).validate()


def _geometry_bounds(kind: str, geometry: dict[str, Any]) -> tuple[list[float], list[float]]:
    if "points" in geometry:
        raw_points = geometry["points"]
        if not isinstance(raw_points, list) or not 2 <= len(raw_points) <= MAX_ROUTE_POINTS:
            raise _fail(f"Scene route geometry.points requires 2..{MAX_ROUTE_POINTS} points")
        points = [_vector(point, name=f"geometry.points[{index}]") for index, point in enumerate(raw_points)]
        geometry["points"] = points
        radius = _finite(geometry.get("radius", 0.05), name="geometry.radius", minimum=0.0, maximum=10_000.0)
        geometry["radius"] = radius
        return (
            [min(point[axis] for point in points) - radius for axis in range(3)],
            [max(point[axis] for point in points) + radius for axis in range(3)],
        )
    if kind in TEXT_KINDS:
        text = _string(geometry.get("text", ""), name="geometry.text")
        geometry["text"] = text
    raw_size = geometry.get("size", [1.0, 1.0, 1.0])
    size = _vector(raw_size, name="geometry.size", minimum=1.0e-6, maximum=MAX_ABS_COORDINATE)
    geometry["size"] = size
    center = _vector(geometry.get("center", [0.0, 0.0, 0.0]), name="geometry.center")
    geometry["center"] = center
    return (
        [center[axis] - size[axis] / 2.0 for axis in range(3)],
        [center[axis] + size[axis] / 2.0 for axis in range(3)],
    )


@dataclass(slots=True)
class Object3D:
    id: str
    kind: str
    name: str
    transform: Transform3D
    geometry: dict[str, Any]
    material: Material3D
    provenance: SceneProvenance
    visible: bool = True
    locked: bool = False
    selected: bool = False
    parent_group_id: str | None = None
    world: WorldRecord = field(default_factory=WorldRecord)
    projections: list[ProjectionRecord] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    order: int = 0

    @classmethod
    def create(
        cls,
        kind: str,
        name: str,
        geometry: dict[str, Any],
        provenance: SceneProvenance,
        *,
        transform: Transform3D | None = None,
        material: Material3D | None = None,
        identity: str | None = None,
        **kwargs: Any,
    ) -> "Object3D":
        identity_value = identity or f"{kind}:{name}:{json.dumps(geometry, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"
        return cls(
            stable_id("scene_object", identity_value), kind, name,
            transform or Transform3D(), dict(geometry), material or Material3D(), provenance,
            **kwargs,
        ).validate()

    def validate(self) -> "Object3D":
        self.id = _identifier(self.id, name="object.id")
        self.kind = _string(self.kind, name=f"object {self.id} kind")
        if self.kind not in OBJECT_KINDS:
            raise _fail(f"Unsupported Scene IR object kind {self.kind!r}")
        self.name = _string(self.name, name=f"object {self.id} name")
        if not isinstance(self.transform, Transform3D):
            raise _fail(f"Scene object {self.id!r} transform must be Transform3D")
        if not isinstance(self.material, Material3D):
            raise _fail(f"Scene object {self.id!r} material must be Material3D")
        if not isinstance(self.provenance, SceneProvenance):
            raise _fail(f"Scene object {self.id!r} provenance must be SceneProvenance")
        self.transform.validate()
        self.material.validate()
        self.provenance.validate()
        if not isinstance(self.geometry, dict):
            raise _fail(f"Scene object {self.id!r} geometry must be an object")
        self.geometry = _safe_json(self.geometry, path=f"object {self.id} geometry")
        if self.kind in ROUTE_KINDS and "points" not in self.geometry:
            raise _fail(f"Scene route object {self.id!r} requires geometry.points")
        _geometry_bounds(self.kind, self.geometry)
        if not all(isinstance(value, bool) for value in (self.visible, self.locked, self.selected)):
            raise _fail(f"Scene object {self.id!r} visibility, lock, and selection fields must be boolean")
        if self.parent_group_id is not None:
            self.parent_group_id = _identifier(self.parent_group_id, name=f"object {self.id} parent_group_id")
        if not isinstance(self.world, WorldRecord):
            raise _fail(f"Scene object {self.id!r} world record must be WorldRecord")
        self.world.validate()
        if not isinstance(self.projections, list) or len(self.projections) > MAX_SCENE_CAMERAS:
            raise _fail(f"Scene object {self.id!r} has too many projection records")
        for record in self.projections:
            if not isinstance(record, ProjectionRecord):
                raise _fail(f"Scene object {self.id!r} projection must be ProjectionRecord")
            record.validate()
        projection_camera_ids = [record.camera_id for record in self.projections]
        if len(projection_camera_ids) != len(set(projection_camera_ids)):
            raise _fail(f"Scene object {self.id!r} repeats camera projection records")
        self.metadata = _safe_json(self.metadata, path=f"object {self.id} metadata")
        if isinstance(self.order, bool) or not isinstance(self.order, int) or abs(self.order) > 1_000_000_000:
            raise _fail(f"Scene object {self.id!r} order must be a bounded integer")
        return self

    def local_bounds(self) -> tuple[list[float], list[float]]:
        return _geometry_bounds(self.kind, self.geometry)

    def translate(self, delta: Sequence[object]) -> None:
        if self.locked:
            raise _fail(f"Scene object {self.id!r} is locked")
        self.transform.translate(delta)

    def rotate(self, delta_degrees: Sequence[object]) -> None:
        if self.locked:
            raise _fail(f"Scene object {self.id!r} is locked")
        self.transform.rotate(delta_degrees)

    def scale_by(self, factors: Sequence[object]) -> None:
        if self.locked:
            raise _fail(f"Scene object {self.id!r} is locked")
        self.transform.scale_by(factors)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Object3D":
        fields = {
            "id", "kind", "name", "transform", "geometry", "material",
            "provenance", "visible", "locked", "selected", "parent_group_id",
            "world", "projections", "metadata", "order",
        }
        required = {"id", "kind", "name", "transform", "geometry", "material", "provenance"}
        payload = _strict_mapping(data, path="object", allowed=fields, required=required)
        payload["transform"] = Transform3D.from_dict(payload["transform"])
        payload["material"] = Material3D.from_dict(payload["material"])
        payload["provenance"] = SceneProvenance.from_dict(payload["provenance"])
        payload["world"] = WorldRecord.from_dict(payload["world"]) if "world" in payload else WorldRecord()
        raw_projections = payload.get("projections", [])
        if not isinstance(raw_projections, list):
            raise _fail("Scene IR object.projections must be an array")
        payload["projections"] = [ProjectionRecord.from_dict(item) for item in raw_projections]
        return cls(**payload).validate()


@dataclass(slots=True)
class Group3D:
    id: str
    name: str
    object_ids: list[str] = field(default_factory=list)
    transform: Transform3D = field(default_factory=Transform3D)
    provenance: SceneProvenance = field(default_factory=SceneProvenance.author)
    parent_group_id: str | None = None
    visible: bool = True
    locked: bool = False
    selected: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    order: int = 0

    @classmethod
    def create(cls, name: str, *, identity: str | None = None, **kwargs: Any) -> "Group3D":
        return cls(stable_id("scene_group", identity or name), name, **kwargs).validate()

    def validate(self) -> "Group3D":
        self.id = _identifier(self.id, name="group.id")
        self.name = _string(self.name, name=f"group {self.id} name")
        self.object_ids = _unique_ids(self.object_ids, name=f"group {self.id} object_ids")
        if not isinstance(self.transform, Transform3D) or not isinstance(self.provenance, SceneProvenance):
            raise _fail(f"Scene group {self.id!r} has malformed transform or provenance")
        self.transform.validate()
        self.provenance.validate()
        if self.parent_group_id is not None:
            self.parent_group_id = _identifier(self.parent_group_id, name=f"group {self.id} parent_group_id")
            if self.parent_group_id == self.id:
                raise _fail(f"Scene group {self.id!r} cannot parent itself")
        if not all(isinstance(value, bool) for value in (self.visible, self.locked, self.selected)):
            raise _fail(f"Scene group {self.id!r} visibility, lock, and selection fields must be boolean")
        self.metadata = _safe_json(self.metadata, path=f"group {self.id} metadata")
        if isinstance(self.order, bool) or not isinstance(self.order, int):
            raise _fail(f"Scene group {self.id!r} order must be an integer")
        return self

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Group3D":
        fields = {
            "id", "name", "object_ids", "transform", "provenance",
            "parent_group_id", "visible", "locked", "selected", "metadata", "order",
        }
        payload = _strict_mapping(data, path="group", allowed=fields, required={"id", "name"})
        if "transform" in payload:
            payload["transform"] = Transform3D.from_dict(payload["transform"])
        if "provenance" in payload:
            payload["provenance"] = SceneProvenance.from_dict(payload["provenance"])
        return cls(**payload).validate()


@dataclass(slots=True)
class Layer3D:
    id: str
    name: str
    objects: list[Object3D] = field(default_factory=list)
    groups: list[Group3D] = field(default_factory=list)
    visible: bool = True
    locked: bool = False
    order: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, name: str, *, identity: str | None = None, **kwargs: Any) -> "Layer3D":
        return cls(stable_id("scene_layer", identity or name), name, **kwargs).validate()

    def validate(self) -> "Layer3D":
        self.id = _identifier(self.id, name="layer.id")
        self.name = _string(self.name, name=f"layer {self.id} name")
        if not isinstance(self.objects, list) or not isinstance(self.groups, list):
            raise _fail(f"Scene layer {self.id!r} objects and groups must be arrays")
        object_ids = []
        for item in self.objects:
            if not isinstance(item, Object3D):
                raise _fail(f"Scene layer {self.id!r} contains a malformed object")
            item.validate()
            object_ids.append(item.id)
        group_ids = []
        for group in self.groups:
            if not isinstance(group, Group3D):
                raise _fail(f"Scene layer {self.id!r} contains a malformed group")
            group.validate()
            group_ids.append(group.id)
        if len(object_ids) != len(set(object_ids)) or len(group_ids) != len(set(group_ids)):
            raise _fail(f"Scene layer {self.id!r} has duplicate object or group IDs")
        known_objects, known_groups = set(object_ids), set(group_ids)
        claimed: set[str] = set()
        for group in self.groups:
            missing = set(group.object_ids) - known_objects
            if missing:
                raise _fail(f"Scene group {group.id!r} references missing objects {sorted(missing)!r}")
            overlap = claimed.intersection(group.object_ids)
            if overlap:
                raise _fail(f"Scene objects may belong to only one group: {sorted(overlap)!r}")
            claimed.update(group.object_ids)
            if group.parent_group_id and group.parent_group_id not in known_groups:
                raise _fail(f"Scene group {group.id!r} references missing parent group {group.parent_group_id!r}")
        for item in self.objects:
            if item.parent_group_id:
                if item.parent_group_id not in known_groups:
                    raise _fail(f"Scene object {item.id!r} references missing group {item.parent_group_id!r}")
                group = next(group for group in self.groups if group.id == item.parent_group_id)
                if item.id not in group.object_ids:
                    raise _fail(f"Scene object {item.id!r} and group {group.id!r} membership is not reciprocal")
            elif item.id in claimed:
                group = next(group for group in self.groups if item.id in group.object_ids)
                item.parent_group_id = group.id
        for group in self.groups:
            visited = {group.id}
            parent_id = group.parent_group_id
            while parent_id:
                if parent_id in visited:
                    raise _fail(f"Scene group hierarchy contains a cycle at {group.id!r}")
                visited.add(parent_id)
                parent = next((candidate for candidate in self.groups if candidate.id == parent_id), None)
                parent_id = parent.parent_group_id if parent else None
        if not isinstance(self.visible, bool) or not isinstance(self.locked, bool):
            raise _fail(f"Scene layer {self.id!r} visible and locked fields must be boolean")
        if isinstance(self.order, bool) or not isinstance(self.order, int):
            raise _fail(f"Scene layer {self.id!r} order must be an integer")
        self.metadata = _safe_json(self.metadata, path=f"layer {self.id} metadata")
        return self

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Layer3D":
        fields = {"id", "name", "objects", "groups", "visible", "locked", "order", "metadata"}
        payload = _strict_mapping(data, path="layer", allowed=fields, required={"id", "name"})
        raw_objects, raw_groups = payload.get("objects", []), payload.get("groups", [])
        if not isinstance(raw_objects, list) or not isinstance(raw_groups, list):
            raise _fail("Scene layer objects and groups must be arrays")
        payload["objects"] = [Object3D.from_dict(item) for item in raw_objects]
        payload["groups"] = [Group3D.from_dict(item) for item in raw_groups]
        return cls(**payload).validate()


@dataclass(frozen=True, slots=True)
class PickHit:
    object_id: str
    distance: float
    point: tuple[float, float, float]


@dataclass(slots=True)
class Scene:
    name: str
    id: str = ""
    cameras: list[Camera] = field(default_factory=list)
    active_camera_id: str = ""
    lights: list[Light] = field(default_factory=list)
    layers: list[Layer3D] = field(default_factory=list)
    selection_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    migrations: list[dict[str, Any]] = field(default_factory=list)
    schema_version: str = SCENE_IR_VERSION

    def __post_init__(self) -> None:
        if not self.id and self.name:
            self.id = stable_id("scene", self.name)

    @classmethod
    def create(cls, name: str, **kwargs: Any) -> "Scene":
        return cls(name, id=str(kwargs.pop("id", stable_id("scene", name))), **kwargs).validate()

    def validate(self) -> "Scene":
        version = _string(str(self.schema_version), name="schema_version")
        if version != SCENE_IR_VERSION:
            if version.split(".", 1)[0] != SCENE_IR_VERSION.split(".", 1)[0]:
                raise _fail(f"Scene IR major version {version!r} is incompatible with {SCENE_IR_VERSION!r}")
            raise _fail(f"Unsupported Scene IR schema version {version!r}; expected {SCENE_IR_VERSION!r}")
        self.schema_version = SCENE_IR_VERSION
        self.id = _identifier(self.id, name="scene.id")
        self.name = _string(self.name, name="scene.name")
        if not isinstance(self.cameras, list) or not 1 <= len(self.cameras) <= MAX_SCENE_CAMERAS:
            raise _fail(f"Scene IR requires 1..{MAX_SCENE_CAMERAS} cameras")
        if not isinstance(self.lights, list) or len(self.lights) > MAX_SCENE_LIGHTS:
            raise _fail(f"Scene IR supports at most {MAX_SCENE_LIGHTS} lights")
        if not isinstance(self.layers, list) or len(self.layers) > MAX_SCENE_LAYERS:
            raise _fail(f"Scene IR supports at most {MAX_SCENE_LAYERS} layers")
        for camera in self.cameras:
            if not isinstance(camera, Camera):
                raise _fail("Scene IR contains a malformed camera")
            camera.validate()
        for light in self.lights:
            if not isinstance(light, Light):
                raise _fail("Scene IR contains a malformed light")
            light.validate()
        for layer in self.layers:
            if not isinstance(layer, Layer3D):
                raise _fail("Scene IR contains a malformed layer")
            layer.validate()
        object_count = sum(len(layer.objects) for layer in self.layers)
        group_count = sum(len(layer.groups) for layer in self.layers)
        if object_count > MAX_SCENE_OBJECTS:
            raise _fail(
                f"Scene IR contains {object_count} objects, above the safe limit of {MAX_SCENE_OBJECTS}",
                hint="Use summary/focus generation instead of materializing the full model.",
            )
        if group_count > MAX_SCENE_GROUPS:
            raise _fail(f"Scene IR contains {group_count} groups, above the safe limit of {MAX_SCENE_GROUPS}")
        all_ids = [self.id]
        all_ids.extend(camera.id for camera in self.cameras)
        all_ids.extend(light.id for light in self.lights)
        for layer in self.layers:
            all_ids.append(layer.id)
            all_ids.extend(group.id for group in layer.groups)
            all_ids.extend(item.id for item in layer.objects)
        if len(all_ids) != len(set(all_ids)):
            raise _fail("Scene IR IDs must be globally unique")
        camera_ids = {camera.id for camera in self.cameras}
        self.active_camera_id = _identifier(self.active_camera_id, name="active_camera_id")
        if self.active_camera_id not in camera_ids:
            raise _fail(f"Scene active camera {self.active_camera_id!r} does not exist")
        selectable = {
            identifier
            for layer in self.layers
            for identifier in [*(item.id for item in layer.objects), *(group.id for group in layer.groups)]
        }
        self.selection_ids = _unique_ids(self.selection_ids, name="selection_ids")
        missing_selection = set(self.selection_ids) - selectable
        if missing_selection:
            raise _fail(f"Scene selection references missing IDs {sorted(missing_selection)!r}")
        selected_flags = {
            identifier
            for layer in self.layers
            for identifier, selected in [
                *((item.id, item.selected) for item in layer.objects),
                *((group.id, group.selected) for group in layer.groups),
            ]
            if selected
        }
        if selected_flags != set(self.selection_ids):
            raise _fail("Scene selection_ids must exactly match object/group selected flags")
        self.metadata = _safe_json(self.metadata, path="scene.metadata")
        if not isinstance(self.migrations, list) or len(self.migrations) > 128:
            raise _fail("Scene IR migrations must be an array with at most 128 records")
        self.migrations = [_safe_json(item, path=f"scene.migrations[{index}]") for index, item in enumerate(self.migrations)]
        if any(not isinstance(item, dict) for item in self.migrations):
            raise _fail("Scene IR migration records must be objects")
        self.refresh_records()
        return self

    def active_camera(self) -> Camera:
        for camera in self.cameras:
            if camera.id == self.active_camera_id:
                return camera
        raise _fail(f"Scene active camera {self.active_camera_id!r} does not exist")

    def iter_layers(self, *, visible_only: bool = False) -> Iterator[Layer3D]:
        for layer in _ordered(self.layers):
            if not visible_only or layer.visible:
                yield layer

    def iter_groups(self, *, visible_only: bool = False) -> Iterator[Group3D]:
        for layer in self.iter_layers(visible_only=visible_only):
            for group in _ordered(layer.groups):
                if not visible_only or group.visible:
                    yield group

    def iter_objects(self, *, visible_only: bool = False) -> Iterator[Object3D]:
        for layer in self.iter_layers(visible_only=visible_only):
            groups = {group.id: group for group in layer.groups}
            for item in _ordered(layer.objects):
                if visible_only and not item.visible:
                    continue
                parent_id = item.parent_group_id
                hidden = False
                while parent_id:
                    group = groups.get(parent_id)
                    if group is None:
                        break
                    hidden = hidden or not group.visible
                    parent_id = group.parent_group_id
                if not visible_only or not hidden:
                    yield item

    def find_object(self, object_id: str) -> tuple[Layer3D, Object3D]:
        for layer in self.layers:
            for item in layer.objects:
                if item.id == object_id:
                    return layer, item
        raise _fail(f"Scene object {object_id!r} does not exist")

    def find_group(self, group_id: str) -> tuple[Layer3D, Group3D]:
        for layer in self.layers:
            for group in layer.groups:
                if group.id == group_id:
                    return layer, group
        raise _fail(f"Scene group {group_id!r} does not exist")

    def _group_world_matrix(self, layer: Layer3D, group_id: str, visited: set[str] | None = None) -> Mat4:
        groups = {group.id: group for group in layer.groups}
        group = groups.get(group_id)
        if group is None:
            raise _fail(f"Scene group {group_id!r} does not exist")
        path = set(visited or ())
        if group_id in path:
            raise _fail(f"Scene group hierarchy contains a cycle at {group_id!r}")
        path.add(group_id)
        local = group.transform.matrix()
        if not group.parent_group_id:
            return local
        return matrix_multiply(self._group_world_matrix(layer, group.parent_group_id, path), local)

    def world_matrix(self, object_or_id: Object3D | str) -> Mat4:
        if isinstance(object_or_id, Object3D):
            item = object_or_id
            layer = next((candidate for candidate in self.layers if item in candidate.objects), None)
            if layer is None:
                raise _fail(f"Scene object {item.id!r} does not belong to this scene")
        else:
            layer, item = self.find_object(str(object_or_id))
        local = item.transform.matrix()
        if not item.parent_group_id:
            return local
        return matrix_multiply(self._group_world_matrix(layer, item.parent_group_id), local)

    def refresh_records(self, viewport: Sequence[object] | None = None) -> None:
        raw_viewport = viewport or self.metadata.get("viewport", [1200.0, 800.0])
        if not isinstance(raw_viewport, (list, tuple)) or len(raw_viewport) != 2:
            raise _fail("Scene viewport must contain width and height")
        width = _finite(raw_viewport[0], name="viewport width", minimum=1.0, maximum=1_000_000.0)
        height = _finite(raw_viewport[1], name="viewport height", minimum=1.0, maximum=1_000_000.0)
        viewport_value = [width, height]
        if viewport is not None:
            self.metadata["viewport"] = list(viewport_value)
        for camera in self.cameras:
            camera.aspect = width / height
        for item in self.iter_objects():
            world_matrix = self.world_matrix(item)
            local_minimum, local_maximum = item.local_bounds()
            world_minimum, world_maximum = transformed_bounds(world_matrix, local_minimum, local_maximum)
            world_position = transform_point(world_matrix, (0.0, 0.0, 0.0))
            item.world = WorldRecord(
                _matrix_lists(world_matrix), list(world_position), list(world_minimum), list(world_maximum),
            ).validate()
            item.projections = []
            for camera in _ordered(self.cameras):
                projected = camera.project(world_position, viewport_value)
                item.projections.append(ProjectionRecord(
                    camera.id, list(viewport_value), [projected.x, projected.y], projected.depth,
                    projected.visible, list(projected.ndc),
                ).validate())

    def set_selection(self, identifiers: Iterable[str]) -> None:
        requested = list(dict.fromkeys(map(str, identifiers)))
        selectable = {item.id for item in self.iter_objects()} | {group.id for group in self.iter_groups()}
        missing = set(requested) - selectable
        if missing:
            raise _fail(f"Scene selection references missing IDs {sorted(missing)!r}")
        self.selection_ids = requested
        selected = set(requested)
        for item in self.iter_objects():
            item.selected = item.id in selected
        for group in self.iter_groups():
            group.selected = group.id in selected
        # Selection does not change transforms, bounds, camera projections or
        # provenance.  A full Scene validation would recompute every world and
        # projection record, turning a single Inspector click into O(objects)
        # matrix work.  The exact selection invariant has already been checked
        # above and is maintained by these flags.

    def add_object(self, layer_id: str, item: Object3D) -> None:
        layer = next((candidate for candidate in self.layers if candidate.id == layer_id), None)
        if layer is None:
            raise _fail(f"Scene layer {layer_id!r} does not exist")
        if layer.locked:
            raise _fail(f"Scene layer {layer_id!r} is locked")
        layer.objects.append(item)
        self.validate()

    def translate_object(self, object_id: str, delta: Sequence[object]) -> None:
        layer, item = self.find_object(object_id)
        if layer.locked or self._object_in_locked_group(layer, item):
            raise _fail(f"Scene object {object_id!r} belongs to a locked layer or group")
        item.translate(delta)
        self.refresh_records()

    def rotate_object(self, object_id: str, delta_degrees: Sequence[object]) -> None:
        layer, item = self.find_object(object_id)
        if layer.locked or self._object_in_locked_group(layer, item):
            raise _fail(f"Scene object {object_id!r} belongs to a locked layer or group")
        item.rotate(delta_degrees)
        self.refresh_records()

    def scale_object(self, object_id: str, factors: Sequence[object]) -> None:
        layer, item = self.find_object(object_id)
        if layer.locked or self._object_in_locked_group(layer, item):
            raise _fail(f"Scene object {object_id!r} belongs to a locked layer or group")
        item.scale_by(factors)
        self.refresh_records()

    @staticmethod
    def _object_in_locked_group(layer: Layer3D, item: Object3D) -> bool:
        groups = {group.id: group for group in layer.groups}
        parent_id = item.parent_group_id
        while parent_id:
            group = groups.get(parent_id)
            if group is None:
                break
            if group.locked:
                return True
            parent_id = group.parent_group_id
        return False

    def pick(
        self,
        screen_x: object,
        screen_y: object,
        viewport: Sequence[object],
        *,
        camera_id: str | None = None,
        include_locked: bool = True,
    ) -> list[PickHit]:
        camera = next((item for item in self.cameras if item.id == (camera_id or self.active_camera_id)), None)
        if camera is None:
            raise _fail(f"Scene camera {camera_id!r} does not exist")
        ray = camera.ray(screen_x, screen_y, viewport)
        hits: list[PickHit] = []
        for item in self.iter_objects(visible_only=True):
            layer, _ = self.find_object(item.id)
            if not include_locked and (item.locked or layer.locked or self._object_in_locked_group(layer, item)):
                continue
            world_matrix = self.world_matrix(item)
            try:
                inverse = inverse_matrix(world_matrix)
                local_origin = transform_point(inverse, ray.origin)
                local_direction = normalize(transform_direction(inverse, ray.direction), name="local pick ray")
            except ValueError:
                continue
            local_minimum, local_maximum = item.local_bounds()
            local_distance = _ray_aabb_distance(local_origin, local_direction, local_minimum, local_maximum)
            if local_distance is None:
                continue
            local_point = add(local_origin, multiply_scalar(local_direction, local_distance))
            world_point = transform_point(world_matrix, local_point)
            hits.append(PickHit(item.id, length(subtract(world_point, ray.origin)), world_point))
        return sorted(hits, key=lambda hit: (hit.distance, hit.object_id))

    def to_dict(self) -> dict[str, Any]:
        self.validate()

        def object_dict(item: Object3D) -> dict[str, Any]:
            return asdict(item)

        def layer_dict(layer: Layer3D) -> dict[str, Any]:
            payload = asdict(layer)
            payload["objects"] = [object_dict(item) for item in _ordered(layer.objects)]
            payload["groups"] = [asdict(group) for group in _ordered(layer.groups)]
            return payload

        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "name": self.name,
            "cameras": [asdict(camera) for camera in _ordered(self.cameras)],
            "active_camera_id": self.active_camera_id,
            "lights": [asdict(light) for light in _ordered(self.lights)],
            "layers": [layer_dict(layer) for layer in _ordered(self.layers)],
            "selection_ids": list(self.selection_ids),
            "metadata": self.metadata,
            "migrations": self.migrations,
        }

    def canonical_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Scene":
        fields = {
            "schema_version", "id", "name", "cameras", "active_camera_id",
            "lights", "layers", "selection_ids", "metadata", "migrations",
        }
        required = {"schema_version", "id", "name", "cameras", "active_camera_id", "lights", "layers"}
        payload = _strict_mapping(data, path="scene", allowed=fields, required=required)
        version = str(payload.get("schema_version", ""))
        if version != SCENE_IR_VERSION:
            raise _fail(f"Unsupported Scene IR schema {version!r}; expected {SCENE_IR_VERSION!r}")
        raw_cameras, raw_lights, raw_layers = payload["cameras"], payload["lights"], payload["layers"]
        if not isinstance(raw_cameras, list) or not isinstance(raw_lights, list) or not isinstance(raw_layers, list):
            raise _fail("Scene cameras, lights, and layers must be arrays")
        payload["cameras"] = [Camera.from_dict(item) for item in raw_cameras]
        payload["lights"] = [Light.from_dict(item) for item in raw_lights]
        payload["layers"] = [Layer3D.from_dict(item) for item in raw_layers]
        return cls(**payload).validate()


def _ray_aabb_distance(
    origin: Sequence[object],
    direction: Sequence[object],
    bounds_min: Sequence[object],
    bounds_max: Sequence[object],
) -> float | None:
    ray = Ray(vec3(origin), normalize(direction))
    minimum, maximum = vec3(bounds_min), vec3(bounds_max)
    near, far = -math.inf, math.inf
    for axis in range(3):
        if abs(ray.direction[axis]) <= 1.0e-10:
            if ray.origin[axis] < minimum[axis] or ray.origin[axis] > maximum[axis]:
                return None
            continue
        first = (minimum[axis] - ray.origin[axis]) / ray.direction[axis]
        second = (maximum[axis] - ray.origin[axis]) / ray.direction[axis]
        if first > second:
            first, second = second, first
        near, far = max(near, first), min(far, second)
        if near > far:
            return None
    if far < 0.0:
        return None
    return max(0.0, near)


def new_scene(
    name: str,
    *,
    projection: str = "orthographic",
    include_default_layer: bool = True,
    include_default_light: bool = True,
) -> Scene:
    camera = Camera.create(f"{name} isometric camera", projection=projection, identity=f"{name}:camera:isometric")
    layers = [Layer3D.create("Model", identity=f"{name}:layer:model")] if include_default_layer else []
    lights = [Light.create("Key light", identity=f"{name}:light:key")] if include_default_light else []
    return Scene.create(
        name,
        cameras=[camera],
        active_camera_id=camera.id,
        lights=lights,
        layers=layers,
        metadata={
            "authoring_mode": "scene-studio",
            "coordinate_system": "right-handed-y-up",
            "rotation_unit": "degrees",
            "matrix_convention": "row-major-column-vector",
            "viewport": [1200.0, 800.0],
        },
    )


def empty_scene(name: str, *, migration_from: str | None = None) -> Scene:
    """Create a valid scene with no layers, groups, objects, or provenance."""

    scene = new_scene(name, include_default_layer=False)
    scene.metadata.update({
        "empty": True,
        "model_geometry_inferred": False,
        "model_semantics_inferred": False,
        "provenance_inferred": False,
    })
    if migration_from is not None:
        scene.migrations.append({
            "from": str(migration_from),
            "to": SCENE_IR_VERSION,
            "reason": "Project migration added an empty Scene IR; no 3D geometry, model semantics, or provenance was inferred.",
        })
    return scene.validate()


__all__ = [
    "CAMERA_PROJECTIONS", "LIGHT_KINDS", "MAX_ROUTE_POINTS", "MAX_SCENE_CAMERAS",
    "MAX_SCENE_GROUPS", "MAX_SCENE_LAYERS", "MAX_SCENE_LIGHTS",
    "MAX_SCENE_OBJECTS", "OBJECT_KINDS", "PROVENANCE_KINDS", "ROUTE_KINDS",
    "SCENE_IR_VERSION", "Camera", "Group3D", "Layer3D", "Light", "Material3D",
    "Object3D", "PickHit", "ProjectionRecord", "Scene", "SceneProvenance",
    "Transform3D", "WorldRecord", "empty_scene", "new_scene",
]
