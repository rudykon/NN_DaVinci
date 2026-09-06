#!/usr/bin/env python3
"""Validate Figure Studio vector parity using independently parsed outputs."""

from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any
import xml.etree.ElementTree as ET
import zipfile

from nn_davinci.figure_export import compile_figure, export_figure, figure_proof
from nn_davinci.figure_templates import TEMPLATE_SPECS, instantiate_template


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def command(arguments: list[str], *, cwd: Path | None = None, timeout: int = 90) -> subprocess.CompletedProcess[str]:
    return subprocess.run(arguments, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False)


def svg_local(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def validate_template(slug: str, root: Path) -> dict[str, Any]:
    _, figure = instantiate_template(slug)
    destination = root / slug
    destination.mkdir(parents=True, exist_ok=True)
    paths = export_figure(figure, destination / "figure", formats=("svg", "pdf", "tikz", "pptx"))
    by_suffix = {path.suffix: path for path in paths}
    failures: list[str] = []

    compiled = compile_figure(figure)
    expected_texts = Counter(
        str(primitive.values["text"])
        for _, _, _, primitive in compiled
        if primitive.kind == "text"
    )
    expected_polygons = sum(primitive.kind == "polygon" for _, _, _, primitive in compiled)
    expected_tensor_polygons = sum(
        primitive.kind == "polygon" and bool(primitive.values.get("face"))
        for _, _, _, primitive in compiled
    )
    expected_edges = [
        primitive for _, _, _, primitive in compiled if primitive.kind in {"polyline", "line"}
    ]
    expected_arrowheads = sum(
        primitive.values.get("arrow") in {"end", "both", "true"}
        for primitive in expected_edges
    )
    expected_panel_ids = [panel.id for panel in figure.iter_panels()]
    expected_panel_labels = [panel.label for panel in figure.iter_panels()]

    try:
        svg_root = ET.parse(by_suffix[".svg"]).getroot()
    except (ET.ParseError, OSError) as exc:
        failures.append(f"SVG XML invalid: {exc}")
        svg_root = ET.Element("invalid")
    svg_texts = Counter(
        element.text or ""
        for element in svg_root.iter()
        if svg_local(element) == "text" and element.get("data-figure-object-id")
    )
    if svg_texts != expected_texts:
        failures.append("SVG object text differs from compiled Figure IR text")
    svg_polygons = sum(
        svg_local(element) == "polygon" and bool(element.get("data-tensor-face"))
        for element in svg_root.iter()
    )
    if svg_polygons != expected_tensor_polygons:
        failures.append(f"SVG tensor polygon count {svg_polygons} != {expected_tensor_polygons}")
    svg_panels = [
        element.get("data-panel-label")
        for element in svg_root.iter()
        if "figure-panel" in element.get("class", "").split()
    ]
    if svg_panels != expected_panel_labels:
        failures.append(f"SVG panel order {svg_panels!r} != {expected_panel_labels!r}")
    metadata = next(
        (
            element
            for element in svg_root.iter()
            if svg_local(element) == "metadata" and element.get("id") == "nndv-figure-ir"
        ),
        None,
    )
    if metadata is None or not metadata.text:
        failures.append("SVG lacks versioned Figure IR metadata")
    else:
        document = json.loads(metadata.text)
        if (
            document.get("schema_version") != "nndv-figure-svg-metadata-1"
            or document.get("nn_davinci_version") != "0.6.0"
            or document.get("figure_digest") != figure.digest()
        ):
            failures.append("SVG metadata identity differs from Figure IR")

    tikz = by_suffix[".tex"].read_text(encoding="utf-8")
    if tikz.count("\\node[") != sum(expected_texts.values()):
        failures.append("TikZ text node count differs from compiled Figure IR text")
    if tikz.count(" -- cycle;") != expected_polygons:
        failures.append("TikZ tensor polygon count differs from compiled Figure IR")
    if tikz.count("tensor-face=") != expected_tensor_polygons:
        failures.append("TikZ tensor face count differs from compiled Figure IR")
    panel_positions = [tikz.find(panel_id) for panel_id in expected_panel_ids]
    if any(position < 0 for position in panel_positions) or panel_positions != sorted(panel_positions):
        failures.append("TikZ panel order differs from Figure IR")
    for edge in expected_edges:
        marker = f"{edge.object_id} {edge.semantic}"
        if marker not in tikz:
            failures.append(f"TikZ lacks edge semantic marker {marker!r}")

    tikz_build = destination / "tikz-build"
    tikz_build.mkdir(exist_ok=True)
    shutil.copy2(by_suffix[".tex"], tikz_build / "figure.tex")
    latex = command(
        ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "figure.tex"],
        cwd=tikz_build,
    )
    if latex.returncode or not (tikz_build / "figure.pdf").is_file():
        failures.append(f"standalone TikZ compile failed: {latex.stdout[-600:]}")

    fonts = command(["pdffonts", str(by_suffix[".pdf"])])
    font_rows = [
        line.split()
        for line in fonts.stdout.splitlines()[2:]
        if line.strip() and not set(line.strip()) <= {"-"}
    ]
    if fonts.returncode or not font_rows:
        failures.append("PDF has no independently discoverable font table")
    elif any(len(row) < 4 or row[3] != "yes" for row in font_rows):
        failures.append("PDF contains a non-embedded font")
    pdf_text = command(["pdftotext", str(by_suffix[".pdf"]), "-"])
    if pdf_text.returncode or not pdf_text.stdout.strip():
        failures.append("PDF text is not extractable")
    elif any(label not in pdf_text.stdout for label in expected_panel_labels):
        failures.append("PDF panel labels differ from Figure IR")

    try:
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE

        presentation = Presentation(by_suffix[".pptx"])
        shapes = [shape for slide in presentation.slides for shape in slide.shapes]
        pptx_texts = Counter(
            shape.text for shape in shapes if getattr(shape, "has_text_frame", False) and shape.text
        )
        if pptx_texts != expected_texts:
            failures.append("PPTX editable text differs from compiled Figure IR text")
        pptx_polygons = sum(shape.name.startswith("NNDV tensor face") for shape in shapes)
        if pptx_polygons != expected_tensor_polygons:
            failures.append(f"PPTX tensor polygon count {pptx_polygons} != {expected_tensor_polygons}")
        pptx_panels = [shape.name.split()[2] for shape in shapes if shape.name.startswith("NNDV Panel ")]
        if pptx_panels != expected_panel_labels:
            failures.append(f"PPTX panel order {pptx_panels!r} != {expected_panel_labels!r}")
        if any(shape.shape_type == MSO_SHAPE_TYPE.PICTURE for shape in shapes):
            failures.append("PPTX contains a raster picture instead of editable vector objects")
        connector_names = [shape.name for shape in shapes if shape.name.startswith("NNDV editable connector")]
        for edge in expected_edges:
            if not any(edge.object_id in name and edge.semantic in name for name in connector_names):
                failures.append(f"PPTX lacks editable semantic connector {edge.object_id!r}")
        with zipfile.ZipFile(by_suffix[".pptx"]) as archive:
            slide_xml = b"".join(
                archive.read(name)
                for name in archive.namelist()
                if name.startswith("ppt/slides/slide") and name.endswith(".xml")
            )
        if slide_xml.count(b"<a:tailEnd") != expected_arrowheads:
            failures.append("PPTX editable connector arrowheads differ from Figure IR")
    except Exception as exc:  # independently parsing OOXML must be a hard failure
        failures.append(f"PPTX parse failed: {type(exc).__name__}: {exc}")
        shapes = []
        connector_names = []

    proof = figure_proof(figure)
    if not proof["pass"]:
        failures.append("Figure proof failed")
    return {
        "template": slug,
        "status": "PASS" if not failures else "FAIL",
        "figure_digest": figure.digest(),
        "panel_order": expected_panel_labels,
        "compiled": {
            "text_objects": sum(expected_texts.values()),
            "vector_polygons": expected_polygons,
            "tensor_polygons": expected_tensor_polygons,
            "edge_primitives": len(expected_edges),
        },
        "svg": {"valid_xml": svg_root.tag != "invalid", "text_objects": sum(svg_texts.values()), "tensor_polygons": svg_polygons},
        "pdf": {"embedded_fonts": len(font_rows), "extractable_text": bool(pdf_text.stdout.strip())},
        "tikz": {"standalone_compile": latex.returncode == 0, "tensor_polygons": tikz.count(" -- cycle;")},
        "pptx": {"editable_shapes": len(shapes), "editable_connectors": len(connector_names), "tensor_polygons": expected_tensor_polygons},
        "proof": proof,
        "files": {path.name: {"bytes": path.stat().st_size, "sha256": digest(path)} for path in paths},
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = [validate_template(spec.slug, args.output_dir) for spec in TEMPLATE_SPECS]
    failures = [
        {"template": result["template"], "message": message}
        for result in results
        for message in result["failures"]
    ]
    report = {
        "schema_version": "nndv-figure-export-acceptance-1",
        "release": "0.6.0 Beta — Scientific Figure Studio",
        "status": "PASS" if not failures else "FAIL",
        "counts": {
            "templates": len(results),
            "formats": len(results) * 4,
            "svg_xml_passed": sum(result["svg"]["valid_xml"] for result in results),
            "pdf_font_embedding_passed": sum(result["pdf"]["embedded_fonts"] > 0 for result in results),
            "tikz_compile_passed": sum(result["tikz"]["standalone_compile"] for result in results),
            "pptx_editable_passed": sum(result["pptx"]["editable_shapes"] > 0 for result in results),
            "proof_passed": sum(result["proof"]["pass"] for result in results),
            "failures": len(failures),
        },
        "results": results,
        "failures": failures,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("NNDV_FIGURE_EXPORT_RESULT=" + json.dumps({"status": report["status"], **report["counts"]}, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
