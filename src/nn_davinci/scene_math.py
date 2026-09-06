"""Small, deterministic 3D math primitives used by Scene IR.

The module intentionally has no third-party dependency.  Matrices are
row-major 4 x 4 tuples and act on column vectors.  Scene rotations use XYZ
Euler angles in degrees; the helpers also expose the lower-level operations
needed by the CPU projector and browser-compatible ray picking tests.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Iterator, Sequence


EPSILON = 1.0e-10
Vec3 = tuple[float, float, float]
Vec4 = tuple[float, float, float, float]
Mat4 = tuple[
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
]


def _number(value: object, name: str = "value") -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def vec3(value: Sequence[object], *, name: str = "vector") -> Vec3:
    if isinstance(value, (str, bytes)) or len(value) != 3:
        raise ValueError(f"{name} must contain exactly three finite numbers")
    return (
        _number(value[0], f"{name}[0]"),
        _number(value[1], f"{name}[1]"),
        _number(value[2], f"{name}[2]"),
    )


def add(a: Sequence[object], b: Sequence[object]) -> Vec3:
    av, bv = vec3(a, name="a"), vec3(b, name="b")
    return (av[0] + bv[0], av[1] + bv[1], av[2] + bv[2])


def subtract(a: Sequence[object], b: Sequence[object]) -> Vec3:
    av, bv = vec3(a, name="a"), vec3(b, name="b")
    return (av[0] - bv[0], av[1] - bv[1], av[2] - bv[2])


def multiply_scalar(value: Sequence[object], factor: object) -> Vec3:
    vector, scalar = vec3(value), _number(factor, "factor")
    return (vector[0] * scalar, vector[1] * scalar, vector[2] * scalar)


def dot(a: Sequence[object], b: Sequence[object]) -> float:
    av, bv = vec3(a, name="a"), vec3(b, name="b")
    return av[0] * bv[0] + av[1] * bv[1] + av[2] * bv[2]


def cross(a: Sequence[object], b: Sequence[object]) -> Vec3:
    av, bv = vec3(a, name="a"), vec3(b, name="b")
    return (
        av[1] * bv[2] - av[2] * bv[1],
        av[2] * bv[0] - av[0] * bv[2],
        av[0] * bv[1] - av[1] * bv[0],
    )


def length(value: Sequence[object]) -> float:
    vector = vec3(value)
    return math.sqrt(dot(vector, vector))


def normalize(value: Sequence[object], *, name: str = "vector") -> Vec3:
    vector = vec3(value, name=name)
    magnitude = length(vector)
    if magnitude <= EPSILON:
        raise ValueError(f"{name} must not be the zero vector")
    return multiply_scalar(vector, 1.0 / magnitude)


def identity_matrix() -> Mat4:
    return (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )


def matrix4(value: Sequence[Sequence[object]], *, name: str = "matrix") -> Mat4:
    if isinstance(value, (str, bytes)) or len(value) != 4 or any(len(row) != 4 for row in value):
        raise ValueError(f"{name} must be a 4 x 4 matrix")
    rows = tuple(tuple(_number(cell, f"{name}[{row_index}][{column_index}]") for column_index, cell in enumerate(row)) for row_index, row in enumerate(value))
    return rows  # type: ignore[return-value]


def matrix_multiply(a: Sequence[Sequence[object]], b: Sequence[Sequence[object]]) -> Mat4:
    left, right = matrix4(a, name="left matrix"), matrix4(b, name="right matrix")
    return tuple(tuple(sum(left[row][index] * right[index][column] for index in range(4)) for column in range(4)) for row in range(4))  # type: ignore[return-value]


# Public spelling used by callers that prefer the explicit dimension.
mat4_multiply = matrix_multiply


def translation_matrix(position: Sequence[object]) -> Mat4:
    x, y, z = vec3(position, name="position")
    return (
        (1.0, 0.0, 0.0, x),
        (0.0, 1.0, 0.0, y),
        (0.0, 0.0, 1.0, z),
        (0.0, 0.0, 0.0, 1.0),
    )


def scale_matrix(scale: Sequence[object]) -> Mat4:
    x, y, z = vec3(scale, name="scale")
    return (
        (x, 0.0, 0.0, 0.0),
        (0.0, y, 0.0, 0.0),
        (0.0, 0.0, z, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )


def rotation_x_matrix(angle: object, *, degrees: bool = True) -> Mat4:
    radians = math.radians(_number(angle, "x rotation")) if degrees else _number(angle, "x rotation")
    cosine, sine = math.cos(radians), math.sin(radians)
    return (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, cosine, -sine, 0.0),
        (0.0, sine, cosine, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )


def rotation_y_matrix(angle: object, *, degrees: bool = True) -> Mat4:
    radians = math.radians(_number(angle, "y rotation")) if degrees else _number(angle, "y rotation")
    cosine, sine = math.cos(radians), math.sin(radians)
    return (
        (cosine, 0.0, sine, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (-sine, 0.0, cosine, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )


def rotation_z_matrix(angle: object, *, degrees: bool = True) -> Mat4:
    radians = math.radians(_number(angle, "z rotation")) if degrees else _number(angle, "z rotation")
    cosine, sine = math.cos(radians), math.sin(radians)
    return (
        (cosine, -sine, 0.0, 0.0),
        (sine, cosine, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )


def rotation_matrix_xyz(rotation: Sequence[object], *, degrees: bool = True) -> Mat4:
    """Return an XYZ Euler rotation (X first, then Y, then Z)."""

    x, y, z = vec3(rotation, name="rotation")
    return matrix_multiply(
        rotation_z_matrix(z, degrees=degrees),
        matrix_multiply(rotation_y_matrix(y, degrees=degrees), rotation_x_matrix(x, degrees=degrees)),
    )


def compose_matrix(
    position: Sequence[object] = (0.0, 0.0, 0.0),
    rotation: Sequence[object] = (0.0, 0.0, 0.0),
    scale: Sequence[object] = (1.0, 1.0, 1.0),
    *,
    degrees: bool = True,
) -> Mat4:
    """Compose a transform as translation * rotation * scale."""

    return matrix_multiply(
        translation_matrix(position),
        matrix_multiply(rotation_matrix_xyz(rotation, degrees=degrees), scale_matrix(scale)),
    )


compose_transform = compose_matrix


def _transform_homogeneous(matrix: Sequence[Sequence[object]], vector: Vec4) -> Vec4:
    transform = matrix4(matrix)
    return tuple(sum(transform[row][index] * vector[index] for index in range(4)) for row in range(4))  # type: ignore[return-value]


def transform_point(matrix: Sequence[Sequence[object]], point: Sequence[object]) -> Vec3:
    x, y, z = vec3(point, name="point")
    tx, ty, tz, tw = _transform_homogeneous(matrix, (x, y, z, 1.0))
    if abs(tw) <= EPSILON:
        raise ValueError("point transforms to an invalid homogeneous coordinate")
    return (tx / tw, ty / tw, tz / tw)


def transform_direction(matrix: Sequence[Sequence[object]], direction: Sequence[object]) -> Vec3:
    x, y, z = vec3(direction, name="direction")
    tx, ty, tz, _ = _transform_homogeneous(matrix, (x, y, z, 0.0))
    return (tx, ty, tz)


def inverse_matrix(matrix: Sequence[Sequence[object]]) -> Mat4:
    """Invert a finite 4 x 4 matrix with deterministic Gauss-Jordan steps."""

    source = matrix4(matrix)
    augmented = [list(source[row]) + list(identity_matrix()[row]) for row in range(4)]
    for column in range(4):
        pivot = max(range(column, 4), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) <= EPSILON:
            raise ValueError("matrix is singular")
        if pivot != column:
            augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(4):
            if row == column:
                continue
            factor = augmented[row][column]
            if abs(factor) <= EPSILON:
                continue
            augmented[row] = [augmented[row][index] - factor * augmented[column][index] for index in range(8)]
    return tuple(tuple(augmented[row][4:8]) for row in range(4))  # type: ignore[return-value]


def look_at_matrix(
    eye: Sequence[object],
    target: Sequence[object],
    up: Sequence[object] = (0.0, 1.0, 0.0),
) -> Mat4:
    """Return a right-handed OpenGL-style view matrix looking down -Z."""

    eye_value = vec3(eye, name="eye")
    forward = normalize(subtract(target, eye_value), name="camera forward")
    side = normalize(cross(forward, up), name="camera side")
    camera_up = cross(side, forward)
    return (
        (side[0], side[1], side[2], -dot(side, eye_value)),
        (camera_up[0], camera_up[1], camera_up[2], -dot(camera_up, eye_value)),
        (-forward[0], -forward[1], -forward[2], dot(forward, eye_value)),
        (0.0, 0.0, 0.0, 1.0),
    )


def perspective_matrix(
    fov_y_degrees: object,
    aspect: object,
    near: object,
    far: object,
) -> Mat4:
    fov = _number(fov_y_degrees, "field of view")
    ratio = _number(aspect, "aspect")
    near_value, far_value = _number(near, "near"), _number(far, "far")
    if not 0.01 <= fov < 179.0:
        raise ValueError("field of view must be in [0.01, 179) degrees")
    if ratio <= EPSILON or near_value <= EPSILON or far_value <= near_value:
        raise ValueError("perspective aspect and clipping planes are invalid")
    factor = 1.0 / math.tan(math.radians(fov) / 2.0)
    return (
        (factor / ratio, 0.0, 0.0, 0.0),
        (0.0, factor, 0.0, 0.0),
        (0.0, 0.0, (far_value + near_value) / (near_value - far_value), (2.0 * far_value * near_value) / (near_value - far_value)),
        (0.0, 0.0, -1.0, 0.0),
    )


def orthographic_matrix(
    height: object,
    aspect: object,
    near: object,
    far: object,
) -> Mat4:
    height_value, ratio = _number(height, "orthographic height"), _number(aspect, "aspect")
    near_value, far_value = _number(near, "near"), _number(far, "far")
    if height_value <= EPSILON or ratio <= EPSILON or near_value < 0.0 or far_value <= near_value:
        raise ValueError("orthographic dimensions and clipping planes are invalid")
    half_height = height_value / 2.0
    half_width = half_height * ratio
    left, right = -half_width, half_width
    bottom, top = -half_height, half_height
    return (
        (2.0 / (right - left), 0.0, 0.0, -(right + left) / (right - left)),
        (0.0, 2.0 / (top - bottom), 0.0, -(top + bottom) / (top - bottom)),
        (0.0, 0.0, -2.0 / (far_value - near_value), -(far_value + near_value) / (far_value - near_value)),
        (0.0, 0.0, 0.0, 1.0),
    )


@dataclass(frozen=True, slots=True)
class ProjectedPoint:
    x: float
    y: float
    depth: float
    ndc: Vec3
    visible: bool

    def __iter__(self) -> Iterator[float]:
        yield self.x
        yield self.y
        yield self.depth


def _viewport_dimensions(viewport: Sequence[object]) -> tuple[float, float]:
    if isinstance(viewport, (str, bytes)) or len(viewport) != 2:
        raise ValueError("viewport must contain width and height")
    width, height = _number(viewport[0], "viewport width"), _number(viewport[1], "viewport height")
    if width <= 0.0 or height <= 0.0:
        raise ValueError("viewport dimensions must be positive")
    return width, height


def _project_point_with_clip_matrix(point: Sequence[object], clip_matrix: Mat4, width: float, height: float) -> ProjectedPoint:
    """Project one point with a validated, frame-stable clip matrix."""

    x, y, z = vec3(point, name="world point")
    vector = (x, y, z, 1.0)
    cx, cy, cz, cw = (sum(clip_matrix[row][index] * vector[index] for index in range(4)) for row in range(4))
    if abs(cw) <= EPSILON:
        # Projection is undefined on the camera plane.  Persist a finite,
        # explicitly clipped sentinel instead of contaminating Scene JSON
        # with NaN/Infinity or making an otherwise editable scene unloadable.
        return ProjectedPoint(width / 2.0, height / 2.0, 2.0, (0.0, 0.0, 2.0), False)
    ndc = (cx / cw, cy / cw, cz / cw)
    screen_x = (ndc[0] + 1.0) * 0.5 * width
    screen_y = (1.0 - ndc[1]) * 0.5 * height
    visible = cw > 0.0 and -1.0 <= ndc[0] <= 1.0 and -1.0 <= ndc[1] <= 1.0 and -1.0 <= ndc[2] <= 1.0
    return ProjectedPoint(screen_x, screen_y, ndc[2], ndc, visible)


def project_point(
    point: Sequence[object],
    view_matrix: Sequence[Sequence[object]],
    projection_matrix: Sequence[Sequence[object]],
    viewport: Sequence[object] = (1.0, 1.0),
) -> ProjectedPoint:
    width, height = _viewport_dimensions(viewport)
    clip_matrix = matrix_multiply(projection_matrix, view_matrix)
    return _project_point_with_clip_matrix(point, clip_matrix, width, height)


def project_points(
    points: Iterable[Sequence[object]],
    view_matrix: Sequence[Sequence[object]],
    projection_matrix: Sequence[Sequence[object]],
    viewport: Sequence[object] = (1.0, 1.0),
) -> tuple[ProjectedPoint, ...]:
    """Project a frame's points while composing its clip matrix only once.

    Interactive renderers keep view and projection matrices stable for all
    objects in one frame.  This batch path preserves :func:`project_point`
    semantics while avoiding redundant matrix validation and multiplication.
    """

    width, height = _viewport_dimensions(viewport)
    clip_matrix = matrix_multiply(projection_matrix, view_matrix)
    return tuple(_project_point_with_clip_matrix(point, clip_matrix, width, height) for point in points)


def unproject_point(
    screen_x: object,
    screen_y: object,
    depth_ndc: object,
    view_matrix: Sequence[Sequence[object]],
    projection_matrix: Sequence[Sequence[object]],
    viewport: Sequence[object],
) -> Vec3:
    if isinstance(viewport, (str, bytes)) or len(viewport) != 2:
        raise ValueError("viewport must contain width and height")
    width, height = _number(viewport[0], "viewport width"), _number(viewport[1], "viewport height")
    if width <= 0.0 or height <= 0.0:
        raise ValueError("viewport dimensions must be positive")
    x = 2.0 * _number(screen_x, "screen x") / width - 1.0
    y = 1.0 - 2.0 * _number(screen_y, "screen y") / height
    z = _number(depth_ndc, "NDC depth")
    inverse = inverse_matrix(matrix_multiply(projection_matrix, view_matrix))
    wx, wy, wz, ww = _transform_homogeneous(inverse, (x, y, z, 1.0))
    if abs(ww) <= EPSILON:
        raise ValueError("screen point unprojects to an invalid homogeneous coordinate")
    return (wx / ww, wy / ww, wz / ww)


@dataclass(frozen=True, slots=True)
class Ray:
    origin: Vec3
    direction: Vec3

    def point_at(self, distance: object) -> Vec3:
        return add(self.origin, multiply_scalar(self.direction, distance))


def screen_ray(
    screen_x: object,
    screen_y: object,
    view_matrix: Sequence[Sequence[object]],
    projection_matrix: Sequence[Sequence[object]],
    viewport: Sequence[object],
) -> Ray:
    near_point = unproject_point(screen_x, screen_y, -1.0, view_matrix, projection_matrix, viewport)
    far_point = unproject_point(screen_x, screen_y, 1.0, view_matrix, projection_matrix, viewport)
    return Ray(near_point, normalize(subtract(far_point, near_point), name="ray direction"))


def ray_aabb_intersection(
    ray: Ray,
    bounds_min: Sequence[object],
    bounds_max: Sequence[object],
) -> float | None:
    minimum, maximum = vec3(bounds_min, name="bounds minimum"), vec3(bounds_max, name="bounds maximum")
    if any(minimum[index] > maximum[index] for index in range(3)):
        raise ValueError("AABB minimum must not exceed maximum")
    near, far = -math.inf, math.inf
    for axis in range(3):
        origin, direction = ray.origin[axis], ray.direction[axis]
        if abs(direction) <= EPSILON:
            if origin < minimum[axis] or origin > maximum[axis]:
                return None
            continue
        first = (minimum[axis] - origin) / direction
        second = (maximum[axis] - origin) / direction
        if first > second:
            first, second = second, first
        near = max(near, first)
        far = min(far, second)
        if near > far:
            return None
    if far < 0.0:
        return None
    return max(0.0, near)


def transformed_bounds(
    matrix: Sequence[Sequence[object]],
    bounds_min: Sequence[object],
    bounds_max: Sequence[object],
) -> tuple[Vec3, Vec3]:
    minimum, maximum = vec3(bounds_min), vec3(bounds_max)
    corners = [transform_point(matrix, (x, y, z)) for x in (minimum[0], maximum[0]) for y in (minimum[1], maximum[1]) for z in (minimum[2], maximum[2])]
    return (
        tuple(min(point[axis] for point in corners) for axis in range(3)),
        tuple(max(point[axis] for point in corners) for axis in range(3)),
    )  # type: ignore[return-value]


def pick_aabbs(
    ray: Ray,
    boxes: Iterable[tuple[str, Sequence[object], Sequence[object]]],
) -> list[tuple[str, float]]:
    """Return all axis-aligned ray hits from nearest to farthest."""

    hits = []
    for identifier, minimum, maximum in boxes:
        distance = ray_aabb_intersection(ray, minimum, maximum)
        if distance is not None:
            hits.append((str(identifier), distance))
    return sorted(hits, key=lambda item: (item[1], item[0]))


__all__ = [
    "EPSILON",
    "Mat4",
    "ProjectedPoint",
    "Ray",
    "Vec3",
    "Vec4",
    "add",
    "compose_matrix",
    "compose_transform",
    "cross",
    "dot",
    "identity_matrix",
    "inverse_matrix",
    "length",
    "look_at_matrix",
    "mat4_multiply",
    "matrix4",
    "matrix_multiply",
    "multiply_scalar",
    "normalize",
    "orthographic_matrix",
    "perspective_matrix",
    "pick_aabbs",
    "project_point",
    "ray_aabb_intersection",
    "rotation_matrix_xyz",
    "rotation_x_matrix",
    "rotation_y_matrix",
    "rotation_z_matrix",
    "scale_matrix",
    "screen_ray",
    "subtract",
    "transform_direction",
    "transform_point",
    "transformed_bounds",
    "translation_matrix",
    "unproject_point",
    "vec3",
]
