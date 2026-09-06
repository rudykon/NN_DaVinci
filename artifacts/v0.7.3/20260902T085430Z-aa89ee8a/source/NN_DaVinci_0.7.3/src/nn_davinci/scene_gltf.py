"""Deterministic Scene IR JSON, glTF 2.0 and binary GLB export.

Meshes and routes retain real three-dimensional coordinates.  Object IDs and
provenance live in inert glTF ``extras`` records, while buffers are embedded so
the exports remain offline and relocatable.
"""

from __future__ import annotations

import base64
import copy
import json
import math
from pathlib import Path
import re
import struct
from typing import Any, Iterable, Mapping, Sequence

from .errors import ExportError, ValidationError
from .scene_projection import (
    Mat4,
    _camera,
    _get,
    _mesh,
    _object_id,
    _objects,
    _plain,
    _route,
    _vec3,
    _world_matrix,
)
from .scene_math import inverse_matrix


SCENE_GLTF_VERSION = "nndv-scene-gltf-1"
GLTF_MAGIC = b"glTF"
_ASSET_KEYS = {
    "uri",
    "href",
    "src",
    "url",
    "asset",
    "image",
    "texture",
    "asset_uri",
    "image_uri",
    "texture_uri",
}
_DANGEROUS_SCHEME = re.compile(r"^\s*(?:javascript|vbscript|file|ftp|https?|wss?):", re.IGNORECASE)


def _scene_document(scene: Any) -> dict[str, Any]:
    if hasattr(scene, "validate"):
        scene.validate()
    if hasattr(scene, "to_dict"):
        document = scene.to_dict()
    elif isinstance(scene, Mapping):
        document = copy.deepcopy(dict(scene))
    else:
        document = _plain(scene)
    if not isinstance(document, dict):
        raise ValidationError("Scene JSON export requires a mapping-shaped Scene IR document")
    return document


def validate_scene_assets(scene: Any) -> None:
    """Reject executable or externally fetched scene asset references.

    Scene export currently has no texture/image renderer.  A small allow-list
    accepts only embedded PNG/JPEG bytes, which are inert for all exporters.
    Provenance URLs are not treated as assets and remain plain metadata.
    """

    document = _scene_document(scene)

    def visit(value: Any, path: tuple[str, ...]) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                visit(item, (*path, str(key)))
            return
        if isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                visit(item, (*path, str(index)))
            return
        if not isinstance(value, str):
            return
        lowered = value.lstrip().lower()
        if _DANGEROUS_SCHEME.match(value) or lowered.startswith("data:text/html") or lowered.startswith("data:image/svg+xml"):
            raise ExportError(f"Scene export rejected unsafe URI at {'.'.join(path) or '<root>'}")
        key = path[-1].lower() if path else ""
        if key in _ASSET_KEYS or key.endswith("_uri") or key.endswith("_href") or key.endswith("_src"):
            if not lowered.startswith(("data:image/png;base64,", "data:image/jpeg;base64,")):
                raise ExportError(f"Offline Scene export rejected external asset URI at {'.'.join(path)}")
            try:
                base64.b64decode(value.split(",", 1)[1], validate=True)
            except (ValueError, IndexError) as exc:
                raise ExportError(f"Scene export rejected malformed embedded asset at {'.'.join(path)}") from exc

    visit(document, ())


def scene_json_document(scene: Any) -> dict[str, Any]:
    """Return canonical, directly reloadable Scene IR JSON."""

    validate_scene_assets(scene)
    return copy.deepcopy(_scene_document(scene))


def render_scene_json(scene: Any) -> str:
    return json.dumps(scene_json_document(scene), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def export_scene_json(scene: Any, destination: str | Path) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_scene_json(scene), encoding="utf-8")
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict) or str(parsed.get("schema_version", "")) != "1.0":
        raise ExportError("Scene JSON exporter did not produce a valid Scene IR document")
    return path


def _triangulate(faces: Sequence[Sequence[int]]) -> list[int]:
    result: list[int] = []
    for face in faces:
        for index in range(1, len(face) - 1):
            result.extend((int(face[0]), int(face[index]), int(face[index + 1])))
    return result


def _sample_bezier(points: Sequence[Sequence[float]], count: int = 33) -> list[tuple[float, float, float]]:
    if len(points) != 4:
        raise ValidationError("A cubic glTF bezier route requires four control points")
    control = [_vec3(point) for point in points]
    result: list[tuple[float, float, float]] = []
    for index in range(count):
        amount = index / (count - 1)
        inverse = 1.0 - amount
        weights = (inverse**3, 3.0 * inverse**2 * amount, 3.0 * inverse * amount**2, amount**3)
        result.append(tuple(sum(weights[item] * control[item][axis] for item in range(4)) for axis in range(3)))  # type: ignore[arg-type]
    return result


def _colour(value: Any) -> tuple[list[float], str]:
    text = str(value or "#dbeafe").strip().lstrip("#")
    if len(text) not in {6, 8} or any(character not in "0123456789abcdefABCDEF" for character in text):
        text = "dbeafe"
    if len(text) == 6:
        text += "ff"
    values = [int(text[index : index + 2], 16) / 255.0 for index in range(0, 8, 2)]
    return values, f"#{text.lower()}"


def _material_record(item: Any, *, base_color: Any = None) -> dict[str, Any]:
    material = _get(item, "material", {}) or {}
    colour, canonical = _colour(base_color if base_color is not None else _get(material, "base_color", "#dbeafe"))
    opacity = max(0.0, min(1.0, float(_get(material, "opacity", 1.0))))
    colour[3] *= opacity
    record: dict[str, Any] = {
        "name": f"Material {_object_id(item, 'object')}",
        "pbrMetallicRoughness": {
            "baseColorFactor": [round(value, 7) for value in colour],
            "metallicFactor": max(0.0, min(1.0, float(_get(material, "metallic", 0.0)))),
            "roughnessFactor": max(0.0, min(1.0, float(_get(material, "roughness", 0.85)))),
        },
        "doubleSided": bool(_get(material, "double_sided", False)),
        "extras": {
            "nndvMaterial": _plain(material),
            "canonicalBaseColor": canonical,
        },
    }
    if colour[3] < 0.99999:
        record["alphaMode"] = "BLEND"
    if bool(_get(material, "unlit", False)):
        record["extensions"] = {"KHR_materials_unlit": {}}
    return record


def _arrowhead_mesh(points: Sequence[Sequence[float]], radius: float) -> tuple[list[tuple[float, float, float]], list[list[int]]] | None:
    if len(points) < 2:
        return None
    before, tip = _vec3(points[-2]), _vec3(points[-1])
    direction_raw = tuple(tip[index] - before[index] for index in range(3))
    distance = math.sqrt(sum(value * value for value in direction_raw))
    if distance <= 1.0e-9:
        return None
    direction = tuple(value / distance for value in direction_raw)
    helper = (0.0, 1.0, 0.0) if abs(direction[1]) < 0.9 else (1.0, 0.0, 0.0)
    side_raw = (
        direction[1] * helper[2] - direction[2] * helper[1],
        direction[2] * helper[0] - direction[0] * helper[2],
        direction[0] * helper[1] - direction[1] * helper[0],
    )
    side_length = math.sqrt(sum(value * value for value in side_raw))
    side = tuple(value / side_length for value in side_raw)
    other = (
        side[1] * direction[2] - side[2] * direction[1],
        side[2] * direction[0] - side[0] * direction[2],
        side[0] * direction[1] - side[1] * direction[0],
    )
    base_radius = max(0.04, radius * 2.5)
    head_length = min(distance * 0.4, max(base_radius * 2.5, 0.2))
    base = tuple(tip[index] - direction[index] * head_length for index in range(3))
    vertices = [tip]
    segments = 8
    for index in range(segments):
        angle = 2.0 * math.pi * index / segments
        vertices.append(
            (
                base[0] + base_radius * (math.cos(angle) * side[0] + math.sin(angle) * other[0]),
                base[1] + base_radius * (math.cos(angle) * side[1] + math.sin(angle) * other[1]),
                base[2] + base_radius * (math.cos(angle) * side[2] + math.sin(angle) * other[2]),
            )
        )
    faces = [[0, index + 1, (index + 1) % segments + 1] for index in range(segments)]
    faces.append(list(range(segments, 0, -1)))
    return vertices, faces


def _matrix_to_gltf(matrix: Sequence[Sequence[float]]) -> list[float]:
    """Flatten row-major Scene IR matrix into glTF's column-major array."""

    if len(matrix) != 4 or any(len(row) != 4 for row in matrix):
        raise ValidationError("Scene object world matrix must be 4x4 for glTF export")
    values = [round(float(matrix[row][column]), 9) for column in range(4) for row in range(4)]
    if not all(math.isfinite(value) for value in values):
        raise ValidationError("Scene object world matrix contains non-finite values")
    return values


def _camera_matrix(camera: Any) -> Mat4:
    if hasattr(camera, "view_matrix"):
        try:
            return inverse_matrix(camera.view_matrix())
        except ValueError as exc:
            raise ValidationError("Scene camera view matrix is not invertible for glTF export") from exc
    eye = _vec3(_get(camera, "position"), (8.0, 6.0, 8.0))
    target = _vec3(_get(camera, "target"), (0.0, 0.0, 0.0))
    up = _vec3(_get(camera, "up"), (0.0, 1.0, 0.0))
    forward_raw = tuple(target[index] - eye[index] for index in range(3))
    forward_length = math.sqrt(sum(value * value for value in forward_raw))
    if forward_length <= 1.0e-9:
        raise ValidationError("Scene camera eye and target must differ for glTF export")
    forward = tuple(value / forward_length for value in forward_raw)
    right_raw = (
        forward[1] * up[2] - forward[2] * up[1],
        forward[2] * up[0] - forward[0] * up[2],
        forward[0] * up[1] - forward[1] * up[0],
    )
    right_length = math.sqrt(sum(value * value for value in right_raw))
    if right_length <= 1.0e-9:
        raise ValidationError("Scene camera up vector is parallel to its view for glTF export")
    right = tuple(value / right_length for value in right_raw)
    camera_up = (
        right[1] * forward[2] - right[2] * forward[1],
        right[2] * forward[0] - right[0] * forward[2],
        right[0] * forward[1] - right[1] * forward[0],
    )
    return (
        (right[0], camera_up[0], -forward[0], eye[0]),
        (right[1], camera_up[1], -forward[1], eye[1]),
        (right[2], camera_up[2], -forward[2], eye[2]),
        (0.0, 0.0, 0.0, 1.0),
    )


class _BufferBuilder:
    def __init__(self) -> None:
        self.payload = bytearray()
        self.views: list[dict[str, Any]] = []
        self.accessors: list[dict[str, Any]] = []

    def _align(self) -> None:
        while len(self.payload) % 4:
            self.payload.append(0)

    def add_positions(self, values: Iterable[Sequence[float]]) -> int:
        points = [_vec3(value) for value in values]
        if not points:
            raise ValidationError("glTF position accessors must not be empty")
        self._align()
        offset = len(self.payload)
        for point in points:
            self.payload.extend(struct.pack("<3f", *point))
        view_index = len(self.views)
        self.views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(points) * 12, "target": 34962})
        accessor_index = len(self.accessors)
        self.accessors.append(
            {
                "bufferView": view_index,
                "byteOffset": 0,
                "componentType": 5126,
                "count": len(points),
                "type": "VEC3",
                "min": [min(point[axis] for point in points) for axis in range(3)],
                "max": [max(point[axis] for point in points) for axis in range(3)],
            }
        )
        return accessor_index

    def add_indices(self, values: Iterable[int]) -> int:
        indices = [int(value) for value in values]
        if not indices or min(indices) < 0:
            raise ValidationError("glTF index accessors must contain non-negative indices")
        self._align()
        offset = len(self.payload)
        for value in indices:
            self.payload.extend(struct.pack("<I", value))
        view_index = len(self.views)
        self.views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(indices) * 4, "target": 34963})
        accessor_index = len(self.accessors)
        self.accessors.append(
            {
                "bufferView": view_index,
                "byteOffset": 0,
                "componentType": 5125,
                "count": len(indices),
                "type": "SCALAR",
                "min": [min(indices)],
                "max": [max(indices)],
            }
        )
        return accessor_index


def _provenance(item: Any) -> dict[str, Any]:
    return _plain(_get(item, "provenance", {}))


def _camera_record(camera: Any) -> dict[str, Any]:
    kind = str(_get(camera, "projection", "orthographic")).lower()
    near, far = float(_get(camera, "near", 0.01)), float(_get(camera, "far", 1000.0))
    if not 0.0 <= near < far:
        raise ValidationError("Scene camera must satisfy 0 <= near < far for glTF export")
    if kind == "perspective":
        if near <= 0.0:
            raise ValidationError("Perspective glTF camera near plane must be positive")
        aspect = float(_get(camera, "aspect", 1.5))
        return {
            "name": str(_get(camera, "name", _get(camera, "id", "Camera"))),
            "type": "perspective",
            "perspective": {
                "yfov": math.radians(float(_get(camera, "fov_y_deg", 45.0))),
                "znear": near,
                "zfar": far,
                "aspectRatio": aspect if aspect > 0.0 else 1.5,
            },
            "extras": {"objectId": str(_get(camera, "id", "camera")), "nndvProjection": kind},
        }
    if kind != "orthographic":
        raise ValidationError(f"Unsupported glTF camera projection {kind!r}")
    height, aspect = float(_get(camera, "ortho_height", 12.0)), float(_get(camera, "aspect", 1.5))
    if height <= 0.0 or aspect <= 0.0:
        raise ValidationError("Orthographic glTF camera height/aspect must be positive")
    return {
        "name": str(_get(camera, "name", _get(camera, "id", "Camera"))),
        "type": "orthographic",
        "orthographic": {"xmag": height * aspect / 2.0, "ymag": height / 2.0, "znear": near, "zfar": far},
        "extras": {"objectId": str(_get(camera, "id", "camera")), "nndvProjection": kind},
    }


def build_gltf(scene: Any) -> tuple[dict[str, Any], bytes]:
    """Build a glTF 2.0 JSON document and its single binary buffer."""

    validate_scene_assets(scene)
    if hasattr(scene, "validate"):
        scene.validate()
    builder = _BufferBuilder()
    meshes: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    materials: list[dict[str, Any]] = []
    material_indices: dict[str, int] = {}
    root_nodes: list[int] = []
    extensions_used: set[str] = set()

    def register_material(item: Any, *, base_color: Any = None) -> int:
        material_record = _material_record(item, base_color=base_color)
        material_key = json.dumps(
            {
                "pbr": material_record["pbrMetallicRoughness"],
                "doubleSided": material_record.get("doubleSided"),
                "alphaMode": material_record.get("alphaMode"),
                "extensions": material_record.get("extensions"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        if material_key not in material_indices:
            material_indices[material_key] = len(materials)
            materials.append(material_record)
            if "KHR_materials_unlit" in material_record.get("extensions", {}):
                extensions_used.add("KHR_materials_unlit")
        return material_indices[material_key]

    for ordinal, item in enumerate(_objects(scene, visible_only=True)):
        if not bool(_get(item, "visible", True)):
            continue
        object_id = _object_id(item, f"object:{ordinal:04d}")
        material_index = register_material(item)
        primitives: list[dict[str, Any]] = []
        mesh_value = _mesh(item)
        if mesh_value is not None:
            vertices, faces, face_names = mesh_value
            positions = builder.add_positions(vertices)
            face_colours = _get(_get(item, "material", {}) or {}, "face_colors", {}) or {}
            grouped_faces: dict[int, list[list[int]]] = {}
            for face_index, face in enumerate(faces):
                colour = face_colours.get(face_names[face_index]) if isinstance(face_colours, Mapping) else None
                face_material = register_material(item, base_color=colour) if colour else material_index
                grouped_faces.setdefault(face_material, []).append(face)
            for face_material, material_faces in sorted(grouped_faces.items()):
                indices = builder.add_indices(_triangulate(material_faces))
                primitives.append({"attributes": {"POSITION": positions}, "indices": indices, "material": face_material, "mode": 4})
        route = _route(item)
        if route is not None:
            route_kind, points = route
            if route_kind == "bezier":
                points = _sample_bezier(points)
            positions = builder.add_positions(points)
            primitives.append({"attributes": {"POSITION": positions}, "material": material_index, "mode": 3})
            if route_kind == "arrow":
                geometry = _get(item, "geometry", {}) or {}
                arrowhead = _arrowhead_mesh(points, max(0.0, float(_get(geometry, "radius", 0.05))))
                if arrowhead is not None:
                    head_vertices, head_faces = arrowhead
                    head_positions = builder.add_positions(head_vertices)
                    head_indices = builder.add_indices(_triangulate(head_faces))
                    primitives.append({"attributes": {"POSITION": head_positions}, "indices": head_indices, "material": material_index, "mode": 4})
        if not primitives:
            # Annotation-only objects still retain a pickable node and full
            # provenance even though glTF has no native text primitive.
            node: dict[str, Any] = {
                "name": str(_get(item, "name", object_id)),
                "matrix": _matrix_to_gltf(_world_matrix(scene, item)),
                "extras": {
                    "objectId": object_id,
                    "kind": str(_get(item, "kind", "unknown")),
                    "provenance": _provenance(item),
                    "geometry": _plain(_get(item, "geometry", {})),
                    "visible": True,
                    "locked": bool(_get(item, "locked", False)),
                },
            }
        else:
            mesh_index = len(meshes)
            meshes.append({"name": f"Mesh {object_id}", "primitives": primitives, "extras": {"objectId": object_id}})
            node = {
                "name": str(_get(item, "name", object_id)),
                "mesh": mesh_index,
                "matrix": _matrix_to_gltf(_world_matrix(scene, item)),
                "extras": {
                    "objectId": object_id,
                    "kind": str(_get(item, "kind", "unknown")),
                    "provenance": _provenance(item),
                    "visible": True,
                    "locked": bool(_get(item, "locked", False)),
                },
            }
        root_nodes.append(len(nodes))
        nodes.append(node)

    camera_values = _get(scene, "cameras", []) or []
    camera_items = list(camera_values.values()) if isinstance(camera_values, Mapping) else list(camera_values)
    if not camera_items:
        camera_items = [_camera(scene, None)]
    cameras: list[dict[str, Any]] = []
    for item in sorted(camera_items, key=lambda value: str(_get(value, "id", ""))):
        camera_index = len(cameras)
        cameras.append(_camera_record(item))
        root_nodes.append(len(nodes))
        nodes.append(
            {
                "name": str(_get(item, "name", _get(item, "id", f"Camera {camera_index}"))),
                "camera": camera_index,
                "matrix": _matrix_to_gltf(_camera_matrix(item)),
                "extras": {"objectId": str(_get(item, "id", f"camera:{camera_index}")), "kind": "camera"},
            }
        )

    extensions: dict[str, Any] = {}
    light_values = _get(scene, "lights", []) or []
    light_items = list(light_values.values()) if isinstance(light_values, Mapping) else list(light_values)
    if light_items:
        extensions_used.add("KHR_lights_punctual")
        light_records: list[dict[str, Any]] = []
        for index, item in enumerate(sorted(light_items, key=lambda value: str(_get(value, "id", "")))):
            light_kind = str(_get(item, "kind", _get(item, "type", "directional"))).lower()
            if light_kind not in {"directional", "point", "spot"}:
                light_kind = "directional"
            colour, _canonical = _colour(_get(item, "color", "#ffffff"))
            record: dict[str, Any] = {
                "name": str(_get(item, "name", _get(item, "id", f"Light {index}"))),
                "type": light_kind,
                "color": colour[:3],
                "intensity": max(0.0, float(_get(item, "intensity", 1.0))),
                "extras": {"objectId": str(_get(item, "id", f"light:{index}")), "nndvLight": _plain(item)},
            }
            if light_kind in {"point", "spot"}:
                range_value = float(_get(item, "range", 0.0))
                if range_value > 0.0:
                    record["range"] = range_value
            if light_kind == "spot":
                record["spot"] = {
                    "innerConeAngle": float(_get(item, "inner_cone", 0.0)),
                    "outerConeAngle": float(_get(item, "outer_cone", math.pi / 4.0)),
                }
            light_records.append(record)
            position = _vec3(_get(item, "position"), (0.0, 5.0, 5.0))
            root_nodes.append(len(nodes))
            nodes.append(
                {
                    "name": record["name"],
                    "translation": list(position),
                    "extensions": {"KHR_lights_punctual": {"light": index}},
                    "extras": {"objectId": record["extras"]["objectId"], "kind": "light"},
                }
            )
        extensions["KHR_lights_punctual"] = {"lights": light_records}

    document: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "NN_DaVinci Scene IR 1.0 deterministic exporter", "extras": {"schemaVersion": SCENE_GLTF_VERSION}},
        "scene": 0,
        "scenes": [
            {
                "name": str(_get(scene, "name", "NN_DaVinci Scene")),
                "nodes": root_nodes,
                "extras": {
                    "sceneId": str(_get(scene, "id", "scene")),
                    "activeCameraId": str(_get(scene, "active_camera_id", "")),
                    "sourceDigest": str(scene.digest()) if hasattr(scene, "digest") else "",
                },
            }
        ],
        "nodes": nodes,
        "meshes": meshes,
        "materials": materials,
        "cameras": cameras,
        "buffers": [{"byteLength": len(builder.payload)}],
        "bufferViews": builder.views,
        "accessors": builder.accessors,
    }
    if extensions_used:
        document["extensionsUsed"] = sorted(extensions_used)
        if extensions:
            document["extensions"] = extensions
    validate_gltf(document, bytes(builder.payload), embedded=False)
    return document, bytes(builder.payload)


def validate_gltf(document: Mapping[str, Any], buffer: bytes, *, embedded: bool) -> None:
    if _get(_get(document, "asset", {}), "version") != "2.0":
        raise ExportError("glTF export must declare asset version 2.0")
    buffers = list(_get(document, "buffers", []))
    if len(buffers) != 1 or int(_get(buffers[0], "byteLength", -1)) != len(buffer):
        raise ExportError("glTF buffer declaration does not match emitted binary data")
    uri = _get(buffers[0], "uri")
    if embedded:
        if not isinstance(uri, str) or not uri.startswith("data:application/octet-stream;base64,"):
            raise ExportError("Offline .gltf export must embed its binary buffer")
    elif uri is not None:
        raise ExportError("GLB staging document must not reference an external buffer")
    for image in _get(document, "images", []) or []:
        image_uri = _get(image, "uri")
        if image_uri and not str(image_uri).startswith("data:image/"):
            raise ExportError("glTF export contains an external image URI")
    for accessor in _get(document, "accessors", []) or []:
        view_index = int(_get(accessor, "bufferView", -1))
        if view_index < 0 or view_index >= len(_get(document, "bufferViews", [])):
            raise ExportError("glTF accessor references an invalid buffer view")
    object_ids = [str(_get(_get(node, "extras", {}), "objectId", "")) for node in _get(document, "nodes", [])]
    if any(not value for value in object_ids) or len(object_ids) != len(set(object_ids)):
        raise ExportError("Every glTF node must retain a unique Scene object ID")


def render_scene_gltf(scene: Any) -> bytes:
    document, buffer = build_gltf(scene)
    document = copy.deepcopy(document)
    document["buffers"][0]["uri"] = "data:application/octet-stream;base64," + base64.b64encode(buffer).decode("ascii")
    validate_gltf(document, buffer, embedded=True)
    return (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def render_scene_glb(scene: Any) -> bytes:
    document, buffer = build_gltf(scene)
    json_payload = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    json_payload += b" " * ((4 - len(json_payload) % 4) % 4)
    binary_payload = buffer + b"\x00" * ((4 - len(buffer) % 4) % 4)
    total_length = 12 + 8 + len(json_payload) + 8 + len(binary_payload)
    result = bytearray(struct.pack("<4sII", GLTF_MAGIC, 2, total_length))
    result.extend(struct.pack("<I4s", len(json_payload), b"JSON"))
    result.extend(json_payload)
    result.extend(struct.pack("<I4s", len(binary_payload), b"BIN\x00"))
    result.extend(binary_payload)
    payload = bytes(result)
    validate_glb(payload)
    return payload


def validate_glb(payload: bytes) -> dict[str, Any]:
    if len(payload) < 28:
        raise ExportError("GLB export is truncated")
    magic, version, declared_length = struct.unpack_from("<4sII", payload, 0)
    if magic != GLTF_MAGIC or version != 2 or declared_length != len(payload):
        raise ExportError("GLB header is invalid")
    json_length, json_type = struct.unpack_from("<I4s", payload, 12)
    if json_type != b"JSON" or 20 + json_length + 8 > len(payload):
        raise ExportError("GLB JSON chunk is invalid")
    try:
        document = json.loads(payload[20 : 20 + json_length].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExportError("GLB JSON chunk could not be decoded") from exc
    binary_offset = 20 + json_length
    binary_length, binary_type = struct.unpack_from("<I4s", payload, binary_offset)
    if binary_type != b"BIN\x00" or binary_offset + 8 + binary_length != len(payload):
        raise ExportError("GLB binary chunk is invalid")
    declared_buffer = int(document.get("buffers", [{}])[0].get("byteLength", -1))
    if declared_buffer < 0 or declared_buffer > binary_length or binary_length - declared_buffer > 3:
        raise ExportError("GLB binary padding/declaration is invalid")
    validate_gltf(document, payload[binary_offset + 8 : binary_offset + 8 + declared_buffer], embedded=False)
    return document


def export_scene_gltf(scene: Any, destination: str | Path) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render_scene_gltf(scene))
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        prefix, encoded = document["buffers"][0]["uri"].split(",", 1)
        if prefix != "data:application/octet-stream;base64":
            raise ValueError("unexpected data URI")
        buffer = base64.b64decode(encoded, validate=True)
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise ExportError("Written glTF could not be parsed") from exc
    validate_gltf(document, buffer, embedded=True)
    return path


def export_scene_glb(scene: Any, destination: str | Path) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render_scene_glb(scene))
    validate_glb(path.read_bytes())
    return path


__all__ = [
    "GLTF_MAGIC",
    "SCENE_GLTF_VERSION",
    "build_gltf",
    "export_scene_glb",
    "export_scene_gltf",
    "export_scene_json",
    "render_scene_glb",
    "render_scene_gltf",
    "render_scene_json",
    "scene_json_document",
    "validate_glb",
    "validate_gltf",
    "validate_scene_assets",
]
