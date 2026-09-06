#!/usr/bin/env python3
"""Independent format, true-3D, PDF and compiled-TikZ release oracle."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import struct
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from PIL import Image

REQUIRED = {
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
    "svg": b"<?xml",
    "pdf": b"%PDF-",
    "tikz": b"\\documentclass",
    "pptx": b"PK\x03\x04",
    "png": b"\x89PNG\r\n\x1a\n",
    "eps": b"%!PS-Adobe-",
    "html": b"<!doctype html>",
    "json": b"{",
    "gltf": b"{",
    "glb": b"glTF",
}
PAGE_MM = (180.0, 120.0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--svg-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-cases", type=int, default=14)
    parser.add_argument("--allow-failures", action="store_true")
    return parser.parse_args()


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_text(value: str) -> str:
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).casefold()


def svg_labels(path: Path) -> list[str]:
    root = ET.parse(path).getroot()
    return [
        "".join(element.itertext()).strip() for element in root.iter() if element.attrib.get("data-kind") == "label" and "".join(element.itertext()).strip()
    ]


def pdf_page(path: Path) -> tuple[float, float, int, list[str]]:
    result = run(["pdfinfo", str(path)])
    failures: list[str] = []
    if result.returncode:
        return 0.0, 0.0, 0, [f"pdfinfo failed: {result.stderr.strip()}"]
    pages_match = re.search(r"^Pages:\s+(\d+)", result.stdout, re.MULTILINE)
    size_match = re.search(r"^Page size:\s+([0-9.]+)\s+x\s+([0-9.]+)\s+pts", result.stdout, re.MULTILINE)
    if not pages_match or not size_match:
        return 0.0, 0.0, 0, ["pdfinfo omitted Pages or Page size"]
    pages = int(pages_match.group(1))
    width_mm = float(size_match.group(1)) * 25.4 / 72.0
    height_mm = float(size_match.group(2)) * 25.4 / 72.0
    if pages != 1:
        failures.append(f"expected one PDF page, observed {pages}")
    if abs(width_mm - PAGE_MM[0]) > 0.05 or abs(height_mm - PAGE_MM[1]) > 0.05:
        failures.append(f"PDF page is {width_mm:.4f} x {height_mm:.4f} mm")
    return width_mm, height_mm, pages, failures


def pdf_fonts(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    result = run(["pdffonts", str(path)])
    failures: list[str] = []
    if result.returncode:
        return [], [f"pdffonts failed: {result.stderr.strip()}"]
    records: list[dict[str, Any]] = []
    for line in result.stdout.splitlines()[2:]:
        fields = line.split()
        if len(fields) < 8:
            continue
        records.append(
            {
                "name": fields[0],
                "type": " ".join(fields[1:-6]),
                "encoding": fields[-6],
                "embedded": fields[-5] == "yes",
                "subset": fields[-4] == "yes",
                "unicode": fields[-3] == "yes",
            }
        )
    if not records:
        failures.append("PDF has no independently discoverable font resource")
    return records, failures


def bbox_words(path: Path) -> tuple[list[dict[str, float | str]], str, list[str]]:
    bbox = run(["pdftotext", "-bbox", str(path), "-"])
    plain = run(["pdftotext", str(path), "-"])
    failures: list[str] = []
    if bbox.returncode or plain.returncode:
        failures.append("pdftotext failed")
        return [], plain.stdout, failures
    words: list[dict[str, float | str]] = []
    pattern = re.compile(r'<word xMin="([0-9.-]+)" yMin="([0-9.-]+)" xMax="([0-9.-]+)" yMax="([0-9.-]+)">(.*?)</word>')
    for match in pattern.finditer(bbox.stdout):
        words.append(
            {
                "left": float(match.group(1)),
                "top": float(match.group(2)),
                "right": float(match.group(3)),
                "bottom": float(match.group(4)),
                "text": re.sub(r"<[^>]+>", "", match.group(5)),
            }
        )
    if not words:
        failures.append("PDF contains no extractable word boxes")
    return words, plain.stdout, failures


def word_geometry(words: list[dict[str, float | str]], width_pt: float, height_pt: float) -> dict[str, Any]:
    boundary: list[str] = []
    overlaps: list[list[str]] = []
    minimum_height = math.inf
    for index, word in enumerate(words):
        left, top, right, bottom = (float(word[key]) for key in ("left", "top", "right", "bottom"))
        minimum_height = min(minimum_height, bottom - top)
        if left < -0.5 or top < -0.5 or right > width_pt + 0.5 or bottom > height_pt + 0.5:
            boundary.append(str(word["text"]))
        for other in words[index + 1 :]:
            other_left, other_top, other_right, other_bottom = (float(other[key]) for key in ("left", "top", "right", "bottom"))
            if min(right, other_right) - max(left, other_left) > 0.25 and min(bottom, other_bottom) - max(top, other_top) > 0.25:
                overlaps.append([str(word["text"]), str(other["text"])])
    return {
        "word_count": len(words),
        "boundary_contacts": boundary,
        "word_overlaps": overlaps,
        "minimum_word_height_pt": round(0.0 if math.isinf(minimum_height) else minimum_height, 6),
    }


def raster_boundary(path: Path, destination: Path) -> tuple[int, list[str]]:
    stem = destination / "render"
    result = run(["pdftocairo", "-png", "-singlefile", "-r", "150", str(path), str(stem)])
    if result.returncode:
        return 0, [f"pdftocairo failed: {result.stderr.strip()}"]
    image_path = stem.with_suffix(".png")
    with Image.open(image_path) as image:
        rgba = image.convert("RGBA")
        width, height = rgba.size
        band = 2
        pixels = []
        for x in range(width):
            pixels.extend(rgba.getpixel((x, y)) for y in [0, 1, height - band, height - 1])
        for y in range(height):
            pixels.extend(rgba.getpixel((x, y)) for x in [0, 1, width - band, width - 1])
        ink = sum(1 for red, green, blue, alpha in pixels if alpha > 0 and min(red, green, blue) < 245)
    return ink, ([] if ink == 0 else [f"rendered ink touches {ink} page-boundary pixels"])


def inspect_pdf(path: Path, labels: list[str], temporary: Path) -> dict[str, Any]:
    temporary.mkdir(parents=True, exist_ok=True)
    width_mm, height_mm, pages, failures = pdf_page(path)
    fonts, font_failures = pdf_fonts(path)
    words, extracted, text_failures = bbox_words(path)
    geometry = word_geometry(words, width_mm / 25.4 * 72.0, height_mm / 25.4 * 72.0)
    boundary_ink, raster_failures = raster_boundary(path, temporary)
    normalized = normalize_text(extracted)
    missing = [label for label in labels if normalize_text(label) not in normalized]
    failures.extend(font_failures)
    failures.extend(text_failures)
    failures.extend(raster_failures)
    if geometry["boundary_contacts"]:
        failures.append(f"text boxes cross the PDF page: {geometry['boundary_contacts']}")
    if geometry["word_overlaps"]:
        failures.append(f"PDF word boxes overlap: {geometry['word_overlaps'][:5]}")
    if geometry["minimum_word_height_pt"] < 5.5:
        failures.append(f"PDF word height is crushed to {geometry['minimum_word_height_pt']} pt")
    if missing:
        failures.append(f"PDF is missing extractable labels: {missing}")
    return {
        "status": "FAIL" if failures else "PASS",
        "sha256": sha256(path),
        "page_mm": [round(width_mm, 6), round(height_mm, 6)],
        "pages": pages,
        "fonts": fonts,
        "all_fonts_embedded": bool(fonts) and all(item["embedded"] for item in fonts),
        "text_geometry": geometry,
        "boundary_ink_pixels": boundary_ink,
        "missing_labels": missing,
        "failures": failures,
    }


def compile_tikz(source: Path, destination: Path) -> tuple[Path | None, list[str]]:
    failures: list[str] = []
    for _pass in range(2):
        result = run(
            [
                "pdflatex",
                "-halt-on-error",
                "-interaction=nonstopmode",
                "-output-directory",
                str(destination),
                str(source),
            ],
            cwd=source.parent,
        )
        if result.returncode:
            failures.append(f"pdflatex failed: {(result.stdout + result.stderr)[-1200:]}")
            return None, failures
    compiled = destination / f"{source.stem}.pdf"
    if not compiled.is_file():
        failures.append("pdflatex did not create the compiled PDF")
        return None, failures
    return compiled, failures


def glb_json(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    if len(payload) < 20 or payload[:4] != b"glTF":
        raise ValueError("invalid GLB header")
    version, total_length = struct.unpack_from("<II", payload, 4)
    if version != 2 or total_length != len(payload):
        raise ValueError("invalid GLB version or length")
    chunk_length, chunk_type = struct.unpack_from("<II", payload, 12)
    if chunk_type != 0x4E4F534A:
        raise ValueError("GLB first chunk is not JSON")
    return json.loads(payload[20 : 20 + chunk_length].decode("utf-8").rstrip(" \x00"))


def inspect_3d(document: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    meshes = document.get("meshes", [])
    nodes = document.get("nodes", [])
    cameras = document.get("cameras", [])
    accessors = document.get("accessors", [])
    position_accessors: list[dict[str, Any]] = []
    for mesh in meshes:
        for primitive in mesh.get("primitives", []):
            index = primitive.get("attributes", {}).get("POSITION")
            if isinstance(index, int) and 0 <= index < len(accessors):
                position_accessors.append(accessors[index])
    z_extents = [
        float(accessor["max"][2]) - float(accessor["min"][2])
        for accessor in position_accessors
        if len(accessor.get("max", [])) >= 3 and len(accessor.get("min", [])) >= 3
    ]
    mesh_nodes = [node for node in nodes if isinstance(node.get("mesh"), int)]
    if document.get("asset", {}).get("version") != "2.0":
        failures.append("glTF asset version is not 2.0")
    if not meshes or not mesh_nodes or not cameras:
        failures.append("glTF lacks meshes, mesh nodes or a camera")
    if not z_extents or max(z_extents) <= 0:
        failures.append("glTF POSITION accessors have no non-zero Z extent")
    if any(not isinstance(node.get("extras", {}).get("object_id") or node.get("extras", {}).get("objectId"), str) for node in mesh_nodes):
        failures.append("glTF mesh node lacks object_id provenance")
    return {
        "asset_version": document.get("asset", {}).get("version"),
        "mesh_count": len(meshes),
        "mesh_node_count": len(mesh_nodes),
        "camera_count": len(cameras),
        "position_accessor_count": len(position_accessors),
        "maximum_z_extent": round(max(z_extents, default=0.0), 6),
    }, failures


def main() -> int:
    args = parse_args()
    root = args.input_root.resolve()
    svg_report = json.loads(args.svg_report.read_text(encoding="utf-8"))
    directories = sorted(path.parent for path in root.rglob("scene.svg"))
    overall_failures: list[str] = []
    if len(directories) != args.expected_cases:
        overall_failures.append(f"expected {args.expected_cases} cases, found {len(directories)}")
    svg_by_file = {Path(item["file"]).resolve(): item for item in svg_report.get("cases", [])}
    reports: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="nndv-scene-publication-oracle-") as raw_temporary:
        temporary = Path(raw_temporary)
        for index, directory in enumerate(directories):
            name = str(directory.relative_to(root))
            failures: list[str] = []
            format_checks: dict[str, Any] = {}
            for format_name, filename in REQUIRED.items():
                path = directory / filename
                valid = (
                    path.is_file() and path.stat().st_size > 0 and path.read_bytes()[: len(SIGNATURES[format_name])].lower() == SIGNATURES[format_name].lower()
                )
                format_checks[format_name] = {
                    "path": str(path),
                    "exists": path.is_file(),
                    "signature_valid": valid,
                    "sha256": sha256(path) if path.is_file() else None,
                }
                if not valid:
                    failures.append(f"{format_name} is absent, empty or has an invalid signature")
            labels = svg_labels(directory / "scene.svg") if (directory / "scene.svg").is_file() else []
            svg_case = svg_by_file.get((directory / "scene.svg").resolve())
            publication_failures: list[str] = []
            if not svg_case or svg_case.get("status") != "PASS":
                publication_failures.append("strict Chrome SVG oracle did not pass this exact file")
            case_temporary = temporary / str(index)
            case_temporary.mkdir()
            pdf = inspect_pdf(directory / "scene.pdf", labels, case_temporary / "pdf")
            compiled_dir = case_temporary / "tikz"
            compiled_dir.mkdir()
            compiled, compile_failures = compile_tikz(directory / "scene.tex", compiled_dir)
            if compiled:
                tikz_pdf = inspect_pdf(compiled, labels, compiled_dir / "proof")
            else:
                tikz_pdf = {"status": "FAIL", "failures": compile_failures}
            publication_failures.extend(pdf["failures"])
            publication_failures.extend(tikz_pdf["failures"])
            gltf_document = json.loads((directory / "scene.gltf").read_text(encoding="utf-8"))
            gltf, gltf_failures = inspect_3d(gltf_document)
            glb, glb_failures = inspect_3d(glb_json(directory / "scene.glb"))
            true_3d_failures = [*gltf_failures, *glb_failures]
            case = {
                "name": name,
                "status": "FAIL" if failures or publication_failures or true_3d_failures else "PASS",
                "formats": {
                    "status": "FAIL" if failures else "PASS",
                    "checks": format_checks,
                    "failures": failures,
                },
                "true_3d": {
                    "status": "FAIL" if true_3d_failures else "PASS",
                    "gltf": gltf,
                    "glb": glb,
                    "failures": true_3d_failures,
                },
                "publication": {
                    "status": "FAIL" if publication_failures else "PASS",
                    "svg": svg_case,
                    "pdf": pdf,
                    "tikz_compiled_pdf": tikz_pdf,
                    "failures": publication_failures,
                },
            }
            reports.append(case)
            overall_failures.extend(f"{name}: {failure}" for failure in [*failures, *publication_failures, *true_3d_failures])
    output = {
        "oracle": "scene-publication-cross-format-v1",
        "status": "FAIL" if overall_failures else "PASS",
        "case_count": len(reports),
        "formats_status": "PASS" if reports and all(case["formats"]["status"] == "PASS" for case in reports) else "FAIL",
        "true_3d_status": "PASS" if reports and all(case["true_3d"]["status"] == "PASS" for case in reports) else "FAIL",
        "publication_status": "PASS" if reports and all(case["publication"]["status"] == "PASS" for case in reports) else "FAIL",
        "tools": {tool: shutil.which(tool) for tool in ("pdfinfo", "pdffonts", "pdftotext", "pdftocairo", "pdflatex")},
        "cases": reports,
        "failures": overall_failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: output[key] for key in ("status", "case_count", "formats_status", "true_3d_status", "publication_status", "failures")}, indent=2))
    return 0 if not overall_failures or args.allow_failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
