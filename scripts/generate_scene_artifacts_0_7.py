#!/usr/bin/env python3
"""Generate the NN_DaVinci 0.7.0 editable Scene artifact corpus.

The generator is deliberately offline: real-model weights are initialized
from fixed local seeds, every asset is embedded, and no network client is
used.  Each case is exported from one validated Scene IR document so the 2D
vector/raster views and the glTF/GLB documents share one source digest.
"""

from __future__ import annotations

import argparse
import base64
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import gc
import hashlib
import json
from pathlib import Path
import re
import struct
import tempfile
from typing import Any, Iterable
import xml.etree.ElementTree as ET
import zipfile

from nn_davinci.figure_export import export_figure, render_figure_svg
from nn_davinci.figure_ir import FigureIR
from nn_davinci.ir import GraphIR
from nn_davinci.model_figure import model_figure_from_graph
from nn_davinci.model_scene import (
    ARCHITECTURE_FAMILIES,
    model_scene_from_graph,
    scene_template,
    validate_model_scene_provenance,
)
from nn_davinci.project import PROJECT_VERSION, Project
from nn_davinci.real_models import import_real_model, real_model_registry
from nn_davinci.scene_export import PNG_EXPORT_DPI, export_scene
from nn_davinci.scene_gltf import validate_glb, validate_gltf
from nn_davinci.scene_ir import SCENE_IR_VERSION, Scene
from nn_davinci.scene_projection import ProjectionOptions, project_scene
from nn_davinci.semantic import SemanticView, derive_semantic_view


VERSION = "0.7.0"
RELEASE = "0.7.0 Beta — 3D Neural Figure & UX Completion"
REPORT_SCHEMA = "nndv-0.7.0-scene-artifact-corpus-1"
FIXED_TIMESTAMP = "2026-08-31T00:00:00+00:00"
FORMATS = ("svg", "pdf", "tikz", "pptx", "png", "eps", "html", "json", "gltf", "glb")
TEMPLATE_CASES = tuple(ARCHITECTURE_FAMILIES)
REAL_MODEL_CASES = tuple(real_model_registry())
REAL_MODEL_ARCHITECTURES = {
    "resnet50": "resnet",
    "vision_transformer": "transformer",
    "bert_encoder": "transformer",
    "multiscale_unet": "unet",
    "diffusion_unet": "diffusion-unet",
    "topk_moe": "moe",
    "image_text": "multimodal-fusion",
}
EXPECTED_EXPORT_NAMES = {
    "svg": "scene.svg",
    "pdf": "scene.pdf",
    "tikz": "scene.tex",
    "pptx": "scene.pptx",
    "png": "scene.png",
    "eps": "scene.eps",
    "html": "scene.html",
    "json": "scene.scene.json",
    "gltf": "scene.gltf",
    "glb": "scene.glb",
}
SIGNATURES = {
    ".svg": (b"<?xml", "svg-xml"),
    ".pdf": (b"%PDF", "pdf"),
    ".tex": (b"\\documentclass", "latex"),
    ".pptx": (b"PK", "ooxml-zip"),
    ".png": (b"\x89PNG\r\n\x1a\n", "png"),
    ".eps": (b"%!PS-Adobe-3.0 EPSF-3.0", "epsf-3"),
    ".html": (b"<!doctype html>", "html5"),
    ".gltf": (b"{", "gltf-json"),
    ".glb": (b"glTF", "glb"),
    ".json": (b"{", "json"),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_json(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def corpus_jobs() -> tuple[tuple[str, str], ...]:
    """Return the exact, stable fourteen-case release plan."""

    return (
        *(("template", key) for key in TEMPLATE_CASES),
        *(("real-model", key) for key in REAL_MODEL_CASES),
    )


def _signature_record(path: Path) -> dict[str, Any]:
    expected, name = SIGNATURES[path.suffix.lower()]
    head = path.read_bytes()[: max(24, len(expected))]
    return {
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "signature": name,
        "signature_hex": head[:16].hex(),
        "signature_valid": head.startswith(expected),
    }


def _eps_has_image_operator(payload: bytes) -> bool:
    """Detect raster operators without treating label strings as code."""

    code = re.sub(rb"(?m)%[^\r\n]*", b"", payload)
    code = re.sub(rb"\((?:\\.|[^()\\])*\)", b"()", code)
    return bool(re.search(rb"(?m)(?:^|\s)(?:colorimage|imagemask|image)(?=\s|$)", code.lower()))


def _position_values(document: dict[str, Any], payload: bytes) -> list[float]:
    values: list[float] = []
    position_accessors = {
        int(primitive["attributes"]["POSITION"])
        for mesh in document.get("meshes", [])
        for primitive in mesh.get("primitives", [])
        if "POSITION" in primitive.get("attributes", {})
    }
    for accessor_index in sorted(position_accessors):
        accessor = document["accessors"][accessor_index]
        if accessor.get("type") != "VEC3" or accessor.get("componentType") != 5126:
            continue
        view = document["bufferViews"][accessor["bufferView"]]
        offset = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
        stride = int(view.get("byteStride", 12))
        for index in range(int(accessor["count"])):
            values.extend(struct.unpack_from("<3f", payload, offset + index * stride))
    return values


def _decode_gltf(path: Path) -> tuple[dict[str, Any], bytes]:
    document = json.loads(path.read_text(encoding="utf-8"))
    uri = str(document.get("buffers", [{}])[0].get("uri", ""))
    prefix = "data:application/octet-stream;base64,"
    if not uri.startswith(prefix):
        raise ValueError("glTF buffer is not embedded as an offline data URI")
    payload = base64.b64decode(uri[len(prefix) :], validate=True)
    validate_gltf(document, payload, embedded=True)
    return document, payload


def _decode_glb(path: Path) -> tuple[dict[str, Any], bytes]:
    payload = path.read_bytes()
    document = validate_glb(payload)
    json_length = struct.unpack_from("<I", payload, 12)[0]
    binary_offset = 20 + json_length
    binary_length, binary_kind = struct.unpack_from("<I4s", payload, binary_offset)
    if binary_kind != b"BIN\x00":
        raise ValueError("GLB does not contain the required binary chunk")
    declared = int(document["buffers"][0]["byteLength"])
    binary = payload[binary_offset + 8 : binary_offset + 8 + min(binary_length, declared)]
    return document, binary


def inspect_true_3d(scene: Scene, gltf_path: Path, glb_path: Path) -> tuple[dict[str, Any], list[str]]:
    """Inspect both 3D containers rather than accepting their extensions."""

    failures: list[str] = []
    try:
        gltf, gltf_binary = _decode_gltf(gltf_path)
        glb, glb_binary = _decode_glb(glb_path)
    except Exception as exc:
        return {"passed": False, "error": f"{type(exc).__name__}: {exc}"}, ["glTF/GLB structural parsing failed"]

    scene_ids = {item.id for item in scene.iter_objects()}

    def facts(document: dict[str, Any], binary: bytes) -> dict[str, Any]:
        mesh_nodes = [node for node in document.get("nodes", []) if "mesh" in node]
        object_ids = [str(node.get("extras", {}).get("objectId", "")) for node in mesh_nodes]
        provenance_count = sum(isinstance(node.get("extras", {}).get("provenance"), dict) for node in mesh_nodes)
        positions = _position_values(document, binary)
        z_values = positions[2::3]
        return {
            "asset_version": document.get("asset", {}).get("version"),
            "camera_count": len(document.get("cameras", [])),
            "material_count": len(document.get("materials", [])),
            "mesh_count": len(document.get("meshes", [])),
            "mesh_node_count": len(mesh_nodes),
            "mesh_node_object_ids": object_ids,
            "mesh_node_provenance_count": provenance_count,
            "position_value_count": len(positions),
            "z_min": min(z_values) if z_values else None,
            "z_max": max(z_values) if z_values else None,
            "z_extent": (max(z_values) - min(z_values)) if z_values else 0.0,
        }

    gltf_facts = facts(gltf, gltf_binary)
    glb_facts = facts(glb, glb_binary)
    world_z = [float(item.world.position[2]) for item in scene.iter_objects()]
    depth_spans = [float(item.world.bounds_max[2]) - float(item.world.bounds_min[2]) for item in scene.iter_objects()]
    for label, record in (("glTF", gltf_facts), ("GLB", glb_facts)):
        if record["asset_version"] != "2.0":
            failures.append(f"{label} asset version is not 2.0")
        if not record["camera_count"] or not record["mesh_count"] or not record["mesh_node_count"]:
            failures.append(f"{label} lacks cameras or meshes")
        if not record["material_count"]:
            failures.append(f"{label} lacks materials")
        if record["mesh_node_provenance_count"] != record["mesh_node_count"]:
            failures.append(f"{label} mesh nodes do not all retain provenance")
        if not all(record["mesh_node_object_ids"]):
            failures.append(f"{label} mesh nodes do not all retain object IDs")
        if set(record["mesh_node_object_ids"]) - scene_ids:
            failures.append(f"{label} contains object IDs absent from Scene IR")
        if float(record["z_extent"]) <= 1.0e-6:
            failures.append(f"{label} POSITION buffers have no 3D depth extent")
    if not depth_spans or max(depth_spans) <= 1.0e-6:
        failures.append("Scene IR world bounds have no 3D depth")
    return {
        "passed": not failures,
        "scene_world_z_range": [min(world_z), max(world_z)] if world_z else [],
        "scene_max_depth_span": max(depth_spans) if depth_spans else 0.0,
        "gltf": gltf_facts,
        "glb": glb_facts,
    }, failures


def inspect_outputs(scene: Scene, paths: Iterable[Path]) -> tuple[dict[str, Any], list[str]]:
    """Perform immediate content checks; the separate validator repeats them."""

    supplied = {path.name: path for path in paths}
    failures: list[str] = []
    for name in EXPECTED_EXPORT_NAMES.values():
        if name not in supplied:
            failures.append(f"missing requested export {name}")
    if failures:
        return {"passed": False, "files_seen": sorted(supplied)}, failures
    signature_checks = {name: _signature_record(supplied[name]) for name in EXPECTED_EXPORT_NAMES.values()}
    failures.extend(f"{name} has the wrong file signature" for name, record in signature_checks.items() if not record["signature_valid"])

    svg = supplied["scene.svg"].read_text(encoding="utf-8").lower()
    pdf = supplied["scene.pdf"].read_bytes()
    tikz = supplied["scene.tex"].read_text(encoding="utf-8").lower()
    eps = supplied["scene.eps"].read_bytes().lower()
    html = supplied["scene.html"].read_text(encoding="utf-8").lower()
    native_vector = {
        "svg": "<image" not in svg and "<foreignobject" not in svg and any(token in svg for token in ("<polygon", "<polyline", "<path")),
        "pdf": b"/Subtype /Image" not in pdf and any(token in pdf for token in (b" l ", b" c ", b" re ")),
        "tikz": "\\includegraphics" not in tikz and any(token in tikz for token in ("\\draw", "\\path", "\\node")),
        "eps": not _eps_has_image_operator(eps) and any(token in eps for token in (b"lineto", b"curveto", b"show")),
    }
    failures.extend(f"{name} is not a native vector export" for name, passed in native_vector.items() if not passed)
    try:
        with zipfile.ZipFile(supplied["scene.pptx"]) as archive:
            names = archive.namelist()
            slide = archive.read("ppt/slides/slide1.xml")
        editable_pptx = not any(name.startswith("ppt/media/") for name in names) and (b"<p:sp" in slide or b"<p:cxnSp" in slide)
    except (KeyError, OSError, zipfile.BadZipFile):
        editable_pptx = False
    if not editable_pptx:
        failures.append("PPTX is not an editable native-shape presentation")
    offline_html = (
        "content-security-policy" in html
        and "nndv-scene-projection" in html
        and "<svg" in html
        and not re.search(r"(?:src|href)\s*=\s*['\"]\s*(?:https?:)?//", html)
        and not re.search(r"\b(?:fetch|xmlhttprequest|websocket)\s*\(", html)
    )
    if not offline_html:
        failures.append("HTML is not a self-contained offline Scene viewer")
    try:
        from PIL import Image

        with Image.open(supplied["scene.png"]) as image:
            dpi = tuple(float(value) for value in image.info.get("dpi", (0.0, 0.0)))
            png_metadata = json.loads(image.info.get("nndv.scene_export", "{}"))
            png_inspection = {
                "format": image.format,
                "mode": image.mode,
                "pixels": list(image.size),
                "dpi": list(dpi),
                "metadata": png_metadata,
            }
        png_300dpi = (
            png_inspection["format"] == "PNG"
            and len(dpi) == 2
            and min(dpi) >= 299.0
            and png_metadata.get("dpi") == PNG_EXPORT_DPI
            and png_metadata.get("source") == "cpu-vector-projection"
        )
    except (ImportError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        png_inspection = {"error": f"{type(exc).__name__}: {exc}"}
        png_300dpi = False
    if not png_300dpi:
        failures.append("PNG is not a metadata-bearing direct 300-DPI CPU projection")

    try:
        restored = Scene.from_dict(json.loads(supplied["scene.scene.json"].read_text(encoding="utf-8")))
        scene_roundtrip = restored.digest() == scene.digest()
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        scene_roundtrip = False
    if not scene_roundtrip:
        failures.append("Scene JSON is not an exact reloadable Scene IR document")
    projection = project_scene(scene, options=ProjectionOptions(auto_frame=True, density="paper"))
    projection.validate()
    projected_ids = {primitive.object_id for primitive in projection.primitives}
    true_3d, true_3d_failures = inspect_true_3d(scene, supplied["scene.gltf"], supplied["scene.glb"])
    failures.extend(true_3d_failures)
    return {
        "passed": not failures,
        "signature_checks": signature_checks,
        "native_vector": native_vector,
        "editable_pptx": editable_pptx,
        "offline_html": offline_html,
        "png_300dpi": png_300dpi,
        "png": png_inspection,
        "scene_json_roundtrip": scene_roundtrip,
        "projection_validation": {
            "passed": True,
            "camera_id": projection.camera_id,
            "primitive_count": len(projection.primitives),
            "source_digest": projection.source_digest,
            "projected_object_id_count": len(projected_ids),
        },
        "true_3d": true_3d,
    }, failures


def _svg_dimensions(root: ET.Element) -> tuple[list[float], float, float]:
    view_box = [float(value) for value in root.attrib.get("viewBox", "0 0 180 120").replace(",", " ").split()]
    if len(view_box) != 4 or view_box[2] <= 0.0 or view_box[3] <= 0.0:
        raise ValueError("comparison source SVG has an invalid viewBox")
    return view_box, view_box[2], view_box[3]


def write_comparison_svg(figure: FigureIR, scene: Scene, destination: Path) -> Path:
    """Write a native-vector, side-by-side Figure IR vs Scene projection."""

    ET.register_namespace("", "http://www.w3.org/2000/svg")
    figure_root = ET.fromstring(render_figure_svg(figure))
    scene_path = destination.with_name("scene.svg")
    scene_root = ET.fromstring(scene_path.read_text(encoding="utf-8"))
    figure_box, figure_width, figure_height = _svg_dimensions(figure_root)
    scene_box, scene_width, scene_height = _svg_dimensions(scene_root)
    gap, header = 8.0, 8.0
    width, height = figure_width + gap + scene_width, max(figure_height, scene_height) + header
    namespace = "http://www.w3.org/2000/svg"
    root = ET.Element(
        f"{{{namespace}}}svg",
        {
            "width": f"{width:g}mm",
            "height": f"{height:g}mm",
            "viewBox": f"0 0 {width:g} {height:g}",
            "data-nndv-comparison": "figure-ir-2d:scene-ir-3d",
            "data-figure-digest": figure.digest(),
            "data-scene-digest": scene.digest(),
        },
    )
    ET.SubElement(root, f"{{{namespace}}}title").text = "NN_DaVinci 2D Figure IR vs 3D Scene IR projection"
    for x, label in ((0.0, "2D Figure IR"), (figure_width + gap, "3D Scene IR CPU projection")):
        text = ET.SubElement(
            root, f"{{{namespace}}}text", {"x": f"{x + 2:g}", "y": "5.5", "font-size": "3.4", "font-family": "Arial, sans-serif", "fill": "#0f172a"}
        )
        text.text = label
    for source, box, x, item_width, item_height, role in (
        (figure_root, figure_box, 0.0, figure_width, figure_height, "figure-ir-2d"),
        (scene_root, scene_box, figure_width + gap, scene_width, scene_height, "scene-ir-3d"),
    ):
        nested = ET.SubElement(
            root,
            f"{{{namespace}}}svg",
            {
                "x": f"{x:g}",
                "y": f"{header:g}",
                "width": f"{item_width:g}",
                "height": f"{item_height:g}",
                "viewBox": " ".join(f"{value:g}" for value in box),
                "data-comparison-role": role,
            },
        )
        for child in source:
            nested.append(deepcopy(child))
    ET.SubElement(
        root,
        f"{{{namespace}}}line",
        {"x1": f"{figure_width + gap / 2:g}", "x2": f"{figure_width + gap / 2:g}", "y1": "0", "y2": f"{height:g}", "stroke": "#94a3b8", "stroke-width": "0.35"},
    )
    payload = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"
    lowered = payload.lower()
    if "<image" in lowered or "<foreignobject" in lowered:
        raise ValueError("comparison SVG must retain native vectors and text")
    destination.write_text(payload, encoding="utf-8")
    return destination


def write_comparison_png(figure: FigureIR, scene_png: Path, destination: Path) -> Path:
    """Write a 300-DPI side-by-side raster comparison from both CPU exports."""

    try:
        from PIL import Image, ImageDraw, ImageFont, PngImagePlugin
    except ImportError as exc:  # pragma: no cover - release environment supplies Pillow
        raise RuntimeError("comparison PNG generation requires Pillow") from exc
    with tempfile.TemporaryDirectory(prefix="nndv-070-comparison-") as directory:
        figure_paths = export_figure(figure, Path(directory) / "figure", formats=("png",))
        with Image.open(figure_paths[0]) as figure_image, Image.open(scene_png) as scene_image:
            left = figure_image.convert("RGBA")
            right = scene_image.convert("RGBA")
            header, gap = 96, 48
            canvas = Image.new("RGBA", (left.width + gap + right.width, max(left.height, right.height) + header), "white")
            canvas.alpha_composite(left, (0, header))
            canvas.alpha_composite(right, (left.width + gap, header))
            draw = ImageDraw.Draw(canvas)
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36)
            except OSError:
                font = ImageFont.load_default()
            draw.text((24, 24), "2D Figure IR", fill="#0f172a", font=font)
            draw.text((left.width + gap + 24, 24), "3D Scene IR CPU projection", fill="#0f172a", font=font)
            draw.line((left.width + gap // 2, 0, left.width + gap // 2, canvas.height), fill="#94a3b8", width=3)
            metadata = PngImagePlugin.PngInfo()
            metadata.add_text(
                "nndv.comparison",
                json.dumps(
                    {
                        "schema_version": "nndv-0.7.0-2d-3d-comparison-1",
                        "dpi": PNG_EXPORT_DPI,
                        "left": "Figure IR 2D native export",
                        "right": "Scene IR 3D CPU projection",
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
            canvas.save(destination, format="PNG", dpi=(PNG_EXPORT_DPI, PNG_EXPORT_DPI), pnginfo=metadata)
    return destination


def _fixed_project(project: Project, destination: Path) -> Path:
    """Persist a deterministic, reloadable Project 1.4 JSON document."""

    project.stamp_environment()
    project.created_at = FIXED_TIMESTAMP
    project.updated_at = FIXED_TIMESTAMP
    return write_json(destination, project.to_dict())


def _template_documents(key: str) -> tuple[GraphIR, None, None, Scene, dict[str, Any]]:
    graph = GraphIR(
        name=f"{key} editable 3D template",
        metadata={"source": "bundled-scene-template", "template_id": key, "offline": True},
    ).validate()
    scene = scene_template(key, name=f"{key} editable 3D template")
    provenance = {
        "schema_version": "nndv-scene-template-provenance-1",
        "passed": all(item.provenance.kind not in {"graph_ir", "semantic_view", "figure_ir"} for item in scene.iter_objects()),
        "scope": "explicit-template-no-model-evidence",
        "linked_object_count": 0,
    }
    return graph, None, None, scene, provenance


def _real_model_documents(key: str) -> tuple[GraphIR, SemanticView, FigureIR, Scene, dict[str, Any]]:
    graph = import_real_model(key, view="module")
    semantic = derive_semantic_view(graph)
    figure = model_figure_from_graph(
        graph,
        semantic_view=semantic,
        level="stage",
        view="paper",
        mode="mixed",
        page_preset="double-column",
    )
    scene = model_scene_from_graph(
        graph,
        semantic_view=semantic,
        figure_ir=figure,
        architecture=REAL_MODEL_ARCHITECTURES[key],
        level="stage",
        view="paper",
        maximum_objects=180,
        projection="orthographic",
    )
    provenance = validate_model_scene_provenance(scene, graph, semantic, figure)
    return graph, semantic, figure, scene, provenance


def generate_one(kind: str, key: str, destination: Path) -> dict[str, Any]:
    """Generate, reload, and inspect one corpus case."""

    destination.mkdir(parents=True, exist_ok=False)
    failures: list[str] = []
    if kind == "template":
        graph, semantic, figure, scene, provenance = _template_documents(key)
    elif kind == "real-model":
        graph, semantic, figure, scene, provenance = _real_model_documents(key)
    else:
        raise ValueError(f"unsupported corpus kind {kind!r}")
    scene.validate()
    if not provenance.get("passed"):
        failures.append("Graph IR ↔ Semantic View ↔ Figure IR ↔ Scene IR provenance validation failed")

    export_paths = export_scene(scene, destination / "scene", formats=FORMATS)
    inspection, inspection_failures = inspect_outputs(scene, export_paths)
    failures.extend(inspection_failures)
    comparison_paths: list[Path] = []
    if kind == "real-model":
        assert figure is not None
        comparison_paths = [
            write_comparison_svg(figure, scene, destination / "comparison.svg"),
            write_comparison_png(figure, destination / "scene.png", destination / "comparison.png"),
        ]

    relative_artifacts = [path.relative_to(destination).as_posix() for path in [*export_paths, *comparison_paths]]
    project = Project(
        name=scene.name,
        graph=graph,
        model_source={
            "kind": kind,
            "key": key,
            "architecture": key if kind == "template" else REAL_MODEL_ARCHITECTURES[key],
            "offline": True,
            "weights_downloaded": False,
            "deterministic": True,
        },
        semantic_view={
            "version": "1.0",
            "level": "template" if semantic is None else "stage",
            "view": "paper",
            **({"document": semantic.to_dict()} if semantic is not None else {}),
        },
        export={
            "workspace": "scene",
            "formats": list(FORMATS),
            "dpi": PNG_EXPORT_DPI,
            "transparent": False,
            "offline": True,
        },
        figure_ir=figure.to_dict() if figure is not None else {},
        scene_ir=scene.to_dict(),
        artifacts=[
            {"path": path, "format": Path(path).suffix.lower().lstrip("."), "role": "2d-3d-comparison" if path.startswith("comparison") else "scene-export"}
            for path in relative_artifacts
        ],
        environment={"artifact_corpus": REPORT_SCHEMA, "network_access": False, "fixed_seed_models": kind == "real-model"},
        created_at=FIXED_TIMESTAMP,
        updated_at=FIXED_TIMESTAMP,
    )
    project_path = _fixed_project(project, destination / "scene.nndv.json")
    try:
        restored_project = Project.load(project_path)
        restored_scene = restored_project.persisted_scene()
        project_roundtrip = (
            restored_project.project_version == PROJECT_VERSION
            and restored_project.graph.to_dict() == graph.to_dict()
            and restored_scene.digest() == scene.digest()
            and restored_project.figure_ir == (figure.to_dict() if figure is not None else {})
        )
        if semantic is not None:
            restored_semantic = restored_project.persisted_semantic_view()
            project_roundtrip = bool(restored_semantic is not None and restored_semantic.to_dict() == semantic.to_dict() and project_roundtrip)
    except Exception as exc:
        project_roundtrip = False
        failures.append(f"Project reload raised {type(exc).__name__}: {exc}")
    if not project_roundtrip:
        failures.append("Project 1.4 did not round-trip Graph/Figure/Scene evidence exactly")

    all_paths = [*export_paths, *comparison_paths, project_path]
    files = {path.relative_to(destination).as_posix(): _signature_record(path) for path in sorted(all_paths)}
    export_accounting = {
        name: [path.relative_to(destination).as_posix() for path in export_paths if path.name == expected] for name, expected in EXPECTED_EXPORT_NAMES.items()
    }
    comparison_accounting = [path.relative_to(destination).as_posix() for path in comparison_paths]
    return {
        "kind": kind,
        "key": key,
        "status": "PASS" if not failures else "FAIL",
        "project_version": PROJECT_VERSION,
        "scene_ir_version": SCENE_IR_VERSION,
        "graph_digest": canonical_digest(graph.to_dict()),
        "figure_digest": figure.digest() if figure is not None else None,
        "scene_digest": scene.digest(),
        "scene_object_count": sum(1 for _ in scene.iter_objects()),
        "requested_formats": list(FORMATS),
        "format_accounting": export_accounting,
        "comparison_accounting": comparison_accounting,
        "project_roundtrip": project_roundtrip,
        "inspection": inspection,
        "provenance_validation": provenance,
        "files": files,
        "failures": failures,
    }


def build_report(results: list[dict[str, Any]], output_dir: Path) -> dict[str, Any]:
    regular_files = sorted(path for path in output_dir.rglob("*") if path.is_file() and not path.is_symlink())
    failures = [{"kind": item["kind"], "key": item["key"], "message": message} for item in results for message in item.get("failures", [])]
    case_ids = [f"{item['kind']}:{item['key']}" for item in results]
    expected_ids = [f"{kind}:{key}" for kind, key in corpus_jobs()]
    if case_ids != expected_ids:
        failures.append({"kind": "corpus", "key": "case-plan", "message": "case IDs/order do not match the exact fourteen-case plan"})
    format_counts = Counter(format_name for item in results for format_name, paths in item.get("format_accounting", {}).items() for _path in paths)
    counts = {
        "cases": len(results),
        "templates": sum(item.get("kind") == "template" for item in results),
        "real_models": sum(item.get("kind") == "real-model" for item in results),
        "scene_exports": sum(format_counts.values()),
        "projects": sum("scene.nndv.json" in item.get("files", {}) for item in results),
        "comparison_files": sum(len(item.get("comparison_accounting", [])) for item in results),
        "passing_cases": sum(item.get("status") == "PASS" for item in results),
        "regular_files": len(regular_files),
        "failures": len(failures),
    }
    expected_counts = {
        "cases": 14,
        "templates": 7,
        "real_models": 7,
        "scene_exports": 14 * len(FORMATS),
        "projects": 14,
        "comparison_files": 7 * 2,
        "passing_cases": 14,
        "regular_files": 168,
        "failures": 0,
    }
    for name, expected in expected_counts.items():
        if counts[name] != expected:
            failures.append({"kind": "corpus", "key": name, "message": f"count {counts[name]} != {expected}"})
    counts["failures"] = len(failures)
    expected_format_counts = {name: 14 for name in FORMATS}
    if dict(format_counts) != expected_format_counts:
        failures.append({"kind": "corpus", "key": "formats", "message": f"format accounting {dict(format_counts)!r} != {expected_format_counts!r}"})
        counts["failures"] = len(failures)
    return {
        "schema_version": REPORT_SCHEMA,
        "release": RELEASE,
        "nn_davinci_version": VERSION,
        "project_version": PROJECT_VERSION,
        "scene_ir_version": SCENE_IR_VERSION,
        "status": "PASS" if not failures else "FAIL",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fresh_outputs": True,
        "offline_generation": True,
        "weights_downloaded": False,
        "exact_case_ids": expected_ids,
        "formats": list(FORMATS),
        "counts": counts,
        "expected_counts": expected_counts,
        "format_counts": dict(sorted(format_counts.items())),
        "expected_format_counts": expected_format_counts,
        "output_root": str(output_dir),
        "output_file_count": len(regular_files),
        "output_tree_digest": canonical_digest(
            [{"path": path.relative_to(output_dir).as_posix(), "sha256": sha256(path), "bytes": path.stat().st_size} for path in regular_files]
        ),
        "cases": results,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True, help="new or empty directory for the fourteen-case corpus")
    parser.add_argument("--report", type=Path, required=True, help="JSON generation report destination")
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty Scene artifact directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for kind, key in corpus_jobs():
        destination = output_dir / ("templates" if kind == "template" else "real-models") / key
        try:
            result = generate_one(kind, key, destination)
        except Exception as exc:  # keep all fourteen result slots auditable
            result = {
                "kind": kind,
                "key": key,
                "status": "FAIL",
                "requested_formats": list(FORMATS),
                "format_accounting": {},
                "comparison_accounting": [],
                "files": {},
                "failures": [f"{type(exc).__name__}: {exc}"],
            }
        results.append(result)
        gc.collect()
    report = build_report(results, output_dir)
    write_json(args.report.resolve(), report)
    print(json.dumps({"status": report["status"], "counts": report["counts"], "report": str(args.report.resolve())}, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
