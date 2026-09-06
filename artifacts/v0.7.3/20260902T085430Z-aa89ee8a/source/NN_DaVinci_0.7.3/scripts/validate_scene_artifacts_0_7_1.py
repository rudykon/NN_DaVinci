#!/usr/bin/env python3
"""Independently validate the NN_DaVinci 0.7.1 Scene artifact corpus.

This validator discovers and parses the landed files.  It does not call the
corpus generator or accept a generator PASS as evidence.
"""

from __future__ import annotations

import argparse
import base64
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import struct
from typing import Any
import xml.etree.ElementTree as ET
import zipfile

from nn_davinci.figure_ir import FigureIR
from nn_davinci.model_scene import validate_model_scene_provenance
from nn_davinci.project import PROJECT_VERSION, Project
from nn_davinci.scene_gltf import validate_glb, validate_gltf
from nn_davinci.scene_ir import SCENE_IR_VERSION, Scene
from nn_davinci.scene_projection import ProjectionOptions, project_scene


REPORT_SCHEMA = "nndv-0.7.1-scene-artifact-validation-1"
GENERATION_REPORT_SCHEMA = "nndv-0.7.1-scene-artifact-corpus-1"
FORMATS = ("svg", "pdf", "tikz", "pptx", "png", "eps", "html", "json", "gltf", "glb")
TEMPLATE_CASES = ("cnn", "resnet", "unet", "transformer", "moe", "multimodal-fusion", "diffusion-unet")
REAL_MODEL_CASES = ("resnet50", "vision_transformer", "bert_encoder", "multiscale_unet", "diffusion_unet", "topk_moe", "image_text")
EXPORT_NAMES = {
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
    "scene.svg": (b"<?xml", "svg-xml"),
    "scene.pdf": (b"%PDF", "pdf"),
    "scene.tex": (b"\\documentclass", "latex"),
    "scene.pptx": (b"PK", "ooxml-zip"),
    "scene.png": (b"\x89PNG\r\n\x1a\n", "png"),
    "scene.eps": (b"%!PS-Adobe-3.0 EPSF-3.0", "epsf-3"),
    "scene.html": (b"<!doctype html>", "html5"),
    "scene.scene.json": (b"{", "scene-json"),
    "scene.gltf": (b"{", "gltf-json"),
    "scene.glb": (b"glTF", "glb"),
    "scene.nndv.json": (b"{", "project-json"),
    "comparison.svg": (b"<?xml", "comparison-svg"),
    "comparison.png": (b"\x89PNG\r\n\x1a\n", "comparison-png"),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_cases() -> tuple[tuple[str, str], ...]:
    return (
        *(("template", key) for key in TEMPLATE_CASES),
        *(("real-model", key) for key in REAL_MODEL_CASES),
    )


def expected_names(kind: str) -> set[str]:
    names = {*EXPORT_NAMES.values(), "scene.nndv.json"}
    if kind == "real-model":
        names.update({"comparison.svg", "comparison.png"})
    return names


def _file_record(path: Path) -> dict[str, Any]:
    signature, signature_name = SIGNATURES[path.name]
    head = path.read_bytes()[: max(24, len(signature))]
    return {
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "signature": signature_name,
        "signature_hex": head[:16].hex(),
        "signature_valid": head.startswith(signature),
    }


def _eps_has_image_operator(payload: bytes) -> bool:
    """Detect executable raster operators, ignoring comments and strings."""

    code = re.sub(rb"(?m)%[^\r\n]*", b"", payload)
    code = re.sub(rb"\((?:\\.|[^()\\])*\)", b"()", code)
    return bool(re.search(rb"(?m)(?:^|\s)(?:colorimage|imagemask|image)(?=\s|$)", code.lower()))


def _decode_gltf(path: Path) -> tuple[dict[str, Any], bytes]:
    document = json.loads(path.read_text(encoding="utf-8"))
    uri = str(document.get("buffers", [{}])[0].get("uri", ""))
    prefix = "data:application/octet-stream;base64,"
    if not uri.startswith(prefix):
        raise ValueError("glTF buffer is not an embedded application/octet-stream data URI")
    binary = base64.b64decode(uri[len(prefix) :], validate=True)
    validate_gltf(document, binary, embedded=True)
    return document, binary


def _decode_glb(path: Path) -> tuple[dict[str, Any], bytes]:
    payload = path.read_bytes()
    document = validate_glb(payload)
    json_length = struct.unpack_from("<I", payload, 12)[0]
    binary_offset = 20 + json_length
    binary_length, binary_type = struct.unpack_from("<I4s", payload, binary_offset)
    if binary_type != b"BIN\x00":
        raise ValueError("GLB has no BIN chunk")
    declared = int(document.get("buffers", [{}])[0].get("byteLength", -1))
    if declared < 0 or declared > binary_length:
        raise ValueError("GLB buffer length is inconsistent")
    return document, payload[binary_offset + 8 : binary_offset + 8 + declared]


def _position_values(document: dict[str, Any], binary: bytes) -> list[float]:
    accessors = {
        int(primitive["attributes"]["POSITION"])
        for mesh in document.get("meshes", [])
        for primitive in mesh.get("primitives", [])
        if "POSITION" in primitive.get("attributes", {})
    }
    values: list[float] = []
    for accessor_index in sorted(accessors):
        accessor = document["accessors"][accessor_index]
        if accessor.get("componentType") != 5126 or accessor.get("type") != "VEC3":
            raise ValueError("mesh POSITION accessor is not float32 VEC3")
        view = document["bufferViews"][accessor["bufferView"]]
        offset = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
        stride = int(view.get("byteStride", 12))
        for index in range(int(accessor["count"])):
            values.extend(struct.unpack_from("<3f", binary, offset + index * stride))
    return values


def _inspect_container(document: dict[str, Any], binary: bytes, scene_ids: set[str]) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    nodes = [node for node in document.get("nodes", []) if "mesh" in node]
    object_ids = [str(node.get("extras", {}).get("objectId", "")) for node in nodes]
    provenance = [node.get("extras", {}).get("provenance") for node in nodes]
    positions = _position_values(document, binary)
    z_values = positions[2::3]
    if document.get("asset", {}).get("version") != "2.0":
        failures.append("asset.version is not 2.0")
    if not document.get("cameras"):
        failures.append("no camera records")
    if not document.get("materials"):
        failures.append("no material records")
    if not document.get("meshes") or not nodes:
        failures.append("no mesh records/nodes")
    if not object_ids or any(not identifier for identifier in object_ids):
        failures.append("mesh node lacks an object ID")
    if set(object_ids) - scene_ids:
        failures.append("mesh node object ID is absent from Scene IR")
    if len(provenance) != len(nodes) or any(not isinstance(value, dict) for value in provenance):
        failures.append("mesh node lacks structured provenance")
    if not z_values or max(z_values) - min(z_values) <= 1.0e-6:
        failures.append("mesh POSITION buffers have no z extent")
    return {
        "passed": not failures,
        "asset_version": document.get("asset", {}).get("version"),
        "camera_count": len(document.get("cameras", [])),
        "material_count": len(document.get("materials", [])),
        "mesh_count": len(document.get("meshes", [])),
        "mesh_node_count": len(nodes),
        "object_id_count": len(set(object_ids)),
        "provenance_count": sum(isinstance(value, dict) for value in provenance),
        "position_value_count": len(positions),
        "z_range": [min(z_values), max(z_values)] if z_values else [],
    }, failures


def _inspect_vectors(case_dir: Path) -> tuple[dict[str, bool], list[str]]:
    svg = (case_dir / "scene.svg").read_text(encoding="utf-8").lower()
    pdf = (case_dir / "scene.pdf").read_bytes()
    tikz = (case_dir / "scene.tex").read_text(encoding="utf-8").lower()
    eps = (case_dir / "scene.eps").read_bytes().lower()
    checks = {
        "svg_native": "<image" not in svg and "<foreignobject" not in svg and any(token in svg for token in ("<polygon", "<polyline", "<path")),
        "pdf_native": b"/Subtype /Image" not in pdf and any(token in pdf for token in (b" l ", b" c ", b" re ")),
        "tikz_native": "\\includegraphics" not in tikz and any(token in tikz for token in ("\\draw", "\\path", "\\node")),
        "eps_native": not _eps_has_image_operator(eps) and any(token in eps for token in (b"lineto", b"curveto", b"show")),
    }
    try:
        ET.fromstring((case_dir / "scene.svg").read_text(encoding="utf-8"))
    except ET.ParseError:
        checks["svg_parseable"] = False
    else:
        checks["svg_parseable"] = True
    return checks, [f"{name} failed" for name, passed in checks.items() if not passed]


def _inspect_pptx(path: Path) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            slide = archive.read("ppt/slides/slide1.xml")
        media = [name for name in names if name.startswith("ppt/media/")]
        shape_count = slide.count(b"<p:sp") + slide.count(b"<p:cxnSp")
    except (KeyError, OSError, zipfile.BadZipFile) as exc:
        return {"passed": False, "error": f"{type(exc).__name__}: {exc}"}, ["PPTX package parsing failed"]
    if media:
        failures.append("PPTX contains flattened media")
    if not shape_count:
        failures.append("PPTX contains no editable DrawingML shapes/connectors")
    return {"passed": not failures, "editable_shape_count": shape_count, "media": media}, failures


def _inspect_png(path: Path, *, comparison: bool = False) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    try:
        from PIL import Image

        with Image.open(path) as image:
            dpi = tuple(float(value) for value in image.info.get("dpi", (0.0, 0.0)))
            metadata_key = "nndv.comparison" if comparison else "nndv.scene_export"
            metadata = json.loads(image.info.get(metadata_key, "{}"))
            record = {"format": image.format, "mode": image.mode, "pixels": list(image.size), "dpi": list(dpi), "metadata": metadata}
    except (ImportError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return {"passed": False, "error": f"{type(exc).__name__}: {exc}"}, ["PNG inspection failed"]
    if record["format"] != "PNG" or len(dpi) != 2 or min(dpi) < 299.0:
        failures.append("PNG is not a 300-DPI PNG")
    if metadata.get("dpi") != 300:
        failures.append("PNG lacks its 300-DPI metadata record")
    if not comparison and metadata.get("source") != "cpu-vector-projection":
        failures.append("Scene PNG does not identify the direct CPU vector projection source")
    if comparison and metadata.get("schema_version") != "nndv-0.7.1-2d-3d-comparison-1":
        failures.append("comparison PNG metadata is missing")
    record["passed"] = not failures
    return record, failures


def _inspect_html(path: Path) -> tuple[dict[str, Any], list[str]]:
    payload = path.read_text(encoding="utf-8").lower()
    remote_references = re.findall(r"(?:src|href)\s*=\s*['\"]\s*(?:https?:)?//", payload)
    executable_network = re.findall(r"\b(?:fetch|xmlhttprequest|websocket)\s*\(", payload)
    passed = "content-security-policy" in payload and "nndv-scene-projection" in payload and "<svg" in payload and not remote_references and not executable_network
    return {
        "passed": passed,
        "content_security_policy": "content-security-policy" in payload,
        "embedded_svg": "<svg" in payload,
        "remote_reference_count": len(remote_references),
        "network_api_count": len(executable_network),
    }, [] if passed else ["HTML is not standalone/offline"]


def _inspect_comparison(case_dir: Path) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    path = case_dir / "comparison.svg"
    try:
        payload = path.read_text(encoding="utf-8")
        root = ET.fromstring(payload)
        roles = {item.attrib.get("data-comparison-role") for item in root.iter() if item.attrib.get("data-comparison-role")}
        vector_only = "<image" not in payload.lower() and "<foreignobject" not in payload.lower()
        svg_passed = root.attrib.get("data-nndv-comparison") == "figure-ir-2d:scene-ir-3d" and roles == {"figure-ir-2d", "scene-ir-3d"} and vector_only
    except (OSError, ET.ParseError):
        roles, vector_only, svg_passed = set(), False, False
    if not svg_passed:
        failures.append("2D-vs-3D comparison SVG is missing native paired views")
    png, png_failures = _inspect_png(case_dir / "comparison.png", comparison=True)
    failures.extend(png_failures)
    return {"passed": not failures, "svg_native": svg_passed, "svg_roles": sorted(str(value) for value in roles), "svg_vector_only": vector_only, "png": png}, failures


def validate_case(case_dir: Path, kind: str, key: str) -> dict[str, Any]:
    """Validate one landed case using only its persisted files."""

    failures: list[str] = []
    required = expected_names(kind)
    if not case_dir.is_dir():
        return {"kind": kind, "key": key, "status": "FAIL", "files": {}, "failures": ["case directory is missing"]}
    entries = {path.name for path in case_dir.iterdir() if path.is_file() and not path.is_symlink()}
    symlinks = sorted(path.name for path in case_dir.iterdir() if path.is_symlink())
    directories = sorted(path.name for path in case_dir.iterdir() if path.is_dir() and not path.is_symlink())
    missing, extra = sorted(required - entries), sorted(entries - required)
    if missing:
        failures.append(f"missing exact files: {missing!r}")
    if extra:
        failures.append(f"unexpected files: {extra!r}")
    if symlinks:
        failures.append(f"symlinks are not allowed: {symlinks!r}")
    if directories:
        failures.append(f"unexpected nested directories: {directories!r}")
    if missing:
        return {
            "kind": kind,
            "key": key,
            "status": "FAIL",
            "expected_files": sorted(required),
            "actual_files": sorted(entries),
            "files": {},
            "failures": failures,
        }
    files = {name: _file_record(case_dir / name) for name in sorted(required)}
    failures.extend(f"{name} has the wrong content signature" for name, record in files.items() if not record["signature_valid"])

    try:
        scene = Scene.from_dict(json.loads((case_dir / "scene.scene.json").read_text(encoding="utf-8")))
        project = Project.load(case_dir / "scene.nndv.json")
        persisted_scene = project.persisted_scene()
        project_roundtrip = (
            project.project_version == PROJECT_VERSION
            and scene.schema_version == SCENE_IR_VERSION
            and persisted_scene.digest() == scene.digest()
            and project.export.get("workspace") == "scene"
            and project.export.get("formats") == list(FORMATS)
        )
        expected_artifacts = required - {"scene.nndv.json"}
        persisted_artifacts = {str(record.get("path", "")) for record in project.artifacts}
        project_roundtrip = project_roundtrip and persisted_artifacts == expected_artifacts
    except Exception as exc:
        return {
            "kind": kind,
            "key": key,
            "status": "FAIL",
            "files": files,
            "failures": [*failures, f"Scene/Project reload failed: {type(exc).__name__}: {exc}"],
        }
    if not project_roundtrip:
        failures.append("Project 1.4 and Scene IR 1.0 do not round-trip exactly")

    if kind == "real-model":
        semantic = project.persisted_semantic_view()
        figure = FigureIR.from_dict(project.figure_ir) if project.figure_ir else None
        provenance = validate_model_scene_provenance(scene, project.graph, semantic, figure)
        if not provenance.get("passed"):
            failures.append("model Scene provenance is invalid")
    else:
        claimed = [item.id for item in scene.iter_objects() if item.provenance.kind in {"graph_ir", "semantic_view", "figure_ir"}]
        provenance = {
            "schema_version": "nndv-scene-template-provenance-validation-1",
            "passed": not claimed,
            "scope": "explicit-template-no-model-evidence",
            "unexpected_evidence_object_ids": claimed,
        }
        if claimed:
            failures.append("editable template makes model-evidence claims")

    projection = project_scene(scene, options=ProjectionOptions())
    projection.validate()
    projection_ids = {primitive.object_id for primitive in projection.primitives}
    projection_record = {
        "passed": bool(projection.primitives) and projection.source_digest == scene.digest(),
        "camera_id": projection.camera_id,
        "primitive_count": len(projection.primitives),
        "object_id_count": len(projection_ids),
        "source_digest": projection.source_digest,
    }
    if not projection_record["passed"]:
        failures.append("CPU projection is empty or not digest-bound to Scene IR")

    vectors, vector_failures = _inspect_vectors(case_dir)
    pptx, pptx_failures = _inspect_pptx(case_dir / "scene.pptx")
    png, png_failures = _inspect_png(case_dir / "scene.png")
    html, html_failures = _inspect_html(case_dir / "scene.html")
    failures.extend([*vector_failures, *pptx_failures, *png_failures, *html_failures])
    scene_ids = {item.id for item in scene.iter_objects()}
    try:
        gltf_document, gltf_binary = _decode_gltf(case_dir / "scene.gltf")
        glb_document, glb_binary = _decode_glb(case_dir / "scene.glb")
        gltf, gltf_failures = _inspect_container(gltf_document, gltf_binary, scene_ids)
        glb, glb_failures = _inspect_container(glb_document, glb_binary, scene_ids)
        failures.extend(f"glTF: {message}" for message in gltf_failures)
        failures.extend(f"GLB: {message}" for message in glb_failures)
    except Exception as exc:
        gltf = {"passed": False, "error": f"{type(exc).__name__}: {exc}"}
        glb = {"passed": False, "error": f"{type(exc).__name__}: {exc}"}
        failures.append("glTF/GLB true-3D validation raised an error")
    world_depth = [float(item.world.bounds_max[2]) - float(item.world.bounds_min[2]) for item in scene.iter_objects()]
    if not world_depth or max(world_depth) <= 1.0e-6:
        failures.append("Scene IR objects have no world-space depth")
    true_3d = {
        "passed": bool(gltf.get("passed") and glb.get("passed") and world_depth and max(world_depth) > 1.0e-6),
        "scene_max_world_depth": max(world_depth) if world_depth else 0.0,
        "gltf": gltf,
        "glb": glb,
    }
    comparison: dict[str, Any] | None = None
    if kind == "real-model":
        comparison, comparison_failures = _inspect_comparison(case_dir)
        failures.extend(comparison_failures)
    return {
        "kind": kind,
        "key": key,
        "status": "PASS" if not failures else "FAIL",
        "expected_files": sorted(required),
        "actual_files": sorted(entries),
        "files": files,
        "project_roundtrip": project_roundtrip,
        "scene_digest": scene.digest(),
        "scene_object_count": len(scene_ids),
        "projection_validation": projection_record,
        "provenance_validation": provenance,
        "native_vector_validation": vectors,
        "editable_pptx_validation": pptx,
        "png_300dpi_validation": png,
        "offline_html_validation": html,
        "true_3d_validation": true_3d,
        "comparison_validation": comparison,
        "format_accounting": {name: EXPORT_NAMES[name] for name in FORMATS},
        "failures": failures,
    }


def _verify_generation_report(path: Path, results: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "error": f"{type(exc).__name__}: {exc}"}, ["generation report is unreadable"]
    if report.get("schema_version") != GENERATION_REPORT_SCHEMA or report.get("status") != "PASS":
        failures.append("generation report schema/status is not a passing 0.7.1 corpus report")
    expected_ids = [f"{kind}:{key}" for kind, key in expected_cases()]
    if report.get("exact_case_ids") != expected_ids:
        failures.append("generation report does not declare the exact fourteen case IDs")
    report_cases = {(item.get("kind"), item.get("key")): item for item in report.get("cases", [])}
    for result in results:
        identifier = (result["kind"], result["key"])
        reported = report_cases.get(identifier)
        if reported is None:
            failures.append(f"generation report lacks {identifier!r}")
            continue
        for name, record in result.get("files", {}).items():
            reported_record = reported.get("files", {}).get(name)
            if not reported_record or reported_record.get("sha256") != record.get("sha256") or reported_record.get("bytes") != record.get("bytes"):
                failures.append(f"generation report hash/size disagrees for {identifier!r}/{name}")
    return {"passed": not failures, "schema_version": report.get("schema_version"), "status": report.get("status"), "sha256": sha256(path)}, failures


def validate_corpus(output_dir: Path, generation_report: Path | None = None) -> dict[str, Any]:
    results = [
        validate_case(output_dir / ("templates" if kind == "template" else "real-models") / key, kind, key)
        for kind, key in expected_cases()
    ]
    failures = [
        {"kind": item["kind"], "key": item["key"], "message": message}
        for item in results
        for message in item.get("failures", [])
    ]
    expected_top = {"templates", "real-models"}
    actual_top = {path.name for path in output_dir.iterdir() if not path.is_symlink()} if output_dir.is_dir() else set()
    if actual_top != expected_top or any(not (output_dir / name).is_dir() for name in expected_top):
        failures.append({"kind": "corpus", "key": "top-level", "message": f"top-level entries {sorted(actual_top)!r} != exact directories {sorted(expected_top)!r}"})
    recursive_symlinks = sorted(path.relative_to(output_dir).as_posix() for path in output_dir.rglob("*") if path.is_symlink()) if output_dir.is_dir() else []
    if recursive_symlinks:
        failures.append({"kind": "corpus", "key": "symlinks", "message": f"symlinks are forbidden: {recursive_symlinks!r}"})
    format_counts = Counter(name for item in results if item.get("status") == "PASS" for name in item.get("format_accounting", {}))
    counts = {
        "cases": len(results),
        "templates": sum(item["kind"] == "template" for item in results),
        "real_models": sum(item["kind"] == "real-model" for item in results),
        "passing_cases": sum(item.get("status") == "PASS" for item in results),
        "scene_exports": sum(format_counts.values()),
        "projects": sum("scene.nndv.json" in item.get("files", {}) for item in results),
        "comparison_files": sum(sum(name in item.get("files", {}) for name in ("comparison.svg", "comparison.png")) for item in results),
    }
    expected_counts = {"cases": 14, "templates": 7, "real_models": 7, "passing_cases": 14, "scene_exports": 140, "projects": 14, "comparison_files": 14}
    for name, expected in expected_counts.items():
        if counts[name] != expected:
            failures.append({"kind": "corpus", "key": name, "message": f"count {counts[name]} != {expected}"})
    expected_format_counts = {name: 14 for name in FORMATS}
    if dict(format_counts) != expected_format_counts:
        failures.append({"kind": "corpus", "key": "formats", "message": f"passing format counts {dict(format_counts)!r} != {expected_format_counts!r}"})
    generation_check: dict[str, Any] | None = None
    if generation_report is not None:
        generation_check, generation_failures = _verify_generation_report(generation_report, results)
        failures.extend({"kind": "corpus", "key": "generation-report", "message": message} for message in generation_failures)
    return {
        "schema_version": REPORT_SCHEMA,
        "status": "PASS" if not failures else "FAIL",
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "validator_is_independent_of_generator": True,
        "output_root": str(output_dir),
        "exact_case_ids": [f"{kind}:{key}" for kind, key in expected_cases()],
        "formats": list(FORMATS),
        "counts": counts,
        "expected_counts": expected_counts,
        "format_counts": dict(sorted(format_counts.items())),
        "expected_format_counts": expected_format_counts,
        "generation_report_validation": generation_check,
        "cases": results,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--generation-report", type=Path)
    args = parser.parse_args()
    report = validate_corpus(args.output_dir.resolve(), args.generation_report.resolve() if args.generation_report else None)
    args.report.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.report.resolve().write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "counts": report["counts"], "report": str(args.report.resolve())}, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
