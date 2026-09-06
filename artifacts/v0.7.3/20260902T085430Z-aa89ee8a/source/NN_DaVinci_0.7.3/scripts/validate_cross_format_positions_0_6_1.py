#!/usr/bin/env python3
"""Compare key text positions in final SVG, PDF, and compiled TikZ PDF.

SVG coordinates come only from the strict Chrome DOM/CTM oracle.  PDF
coordinates come from Poppler's final-page text bounding boxes.  No Figure IR
or producer-side geometry claim participates in the comparison.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Any
import xml.etree.ElementTree as ET


RELEASE = "0.6.1 Beta — Publication Fidelity & Model-to-Figure Completion"
PT_TO_MM = 25.4 / 72.0
MAXIMUM_POSITION_ERROR_MM = 1.0
MAXIMUM_PAGE_SIZE_ERROR_MM = 0.05
MINIMUM_KEYS_PER_FIGURE = 3
MINIMUM_TEXT_KEYS_PER_FIGURE = 1
MINIMUM_SHAPE_KEYS_PER_FIGURE = 1
SINGLE_TOKEN = re.compile(r"^\S+$", flags=re.UNICODE)
CSS_PX_TO_MM = 25.4 / 96.0


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def pdf_text(path: Path) -> tuple[dict[str, list[dict[str, float]]], tuple[float, float]]:
    result = subprocess.run(
        ["pdftotext", "-bbox", str(path), "-"],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "pdftotext failed").strip())
    root = ET.fromstring(result.stdout)
    page = next((item for item in root.iter() if item.tag.rsplit("}", 1)[-1] == "page"), None)
    if page is None:
        raise ValueError("pdftotext bbox output has no page")
    width = float(page.attrib["width"]) * PT_TO_MM
    height = float(page.attrib["height"]) * PT_TO_MM
    words: dict[str, list[dict[str, float]]] = {}
    for item in root.iter():
        if item.tag.rsplit("}", 1)[-1] != "word" or item.text is None:
            continue
        text = item.text.strip()
        if not text:
            continue
        x_min = float(item.attrib["xMin"]) * PT_TO_MM
        x_max = float(item.attrib["xMax"]) * PT_TO_MM
        y_min = float(item.attrib["yMin"]) * PT_TO_MM
        y_max = float(item.attrib["yMax"]) * PT_TO_MM
        words.setdefault(text, []).append({
            "x": x_min,
            "y": y_min,
            "width": x_max - x_min,
            "height": y_max - y_min,
            "center_x": (x_min + x_max) / 2.0,
            "center_y": (y_min + y_max) / 2.0,
        })
    return words, (width, height)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render_pdf_proof(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    prefix = destination.with_suffix("")
    result = subprocess.run(
        ["pdftoppm", "-r", "300", "-f", "1", "-l", "1", "-singlefile", "-png", str(source), str(prefix)],
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    generated = prefix.with_suffix(".png")
    if result.returncode or not generated.is_file():
        raise RuntimeError((result.stderr or result.stdout or "pdftoppm did not produce a PNG proof").strip())


def svg_shape_keys(report: dict[str, Any], maximum: int = 8) -> list[dict[str, Any]]:
    root = report.get("root", {}).get("bbox_px", {})
    root_left = float(root.get("left", 0.0))
    root_top = float(root.get("top", 0.0))
    keys: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in report.get("shapes", []):
        component = str(item.get("component_id", ""))
        bbox = item.get("bbox_px", {})
        if (
            not component
            or component in seen
            or item.get("primitive") != "rect"
            or item.get("hidden")
            or item.get("transparent")
            or item.get("zero_size")
            or not all(isinstance(bbox.get(key), (int, float)) for key in ("left", "top", "width", "height"))
        ):
            continue
        width_mm = float(bbox["width"]) * CSS_PX_TO_MM
        height_mm = float(bbox["height"]) * CSS_PX_TO_MM
        if not (4.0 <= width_mm <= 120.0 and 3.0 <= height_mm <= 60.0):
            continue
        x_mm = (float(bbox["left"]) - root_left) * CSS_PX_TO_MM
        y_mm = (float(bbox["top"]) - root_top) * CSS_PX_TO_MM
        keys.append({
            "id": component,
            "x": x_mm,
            "y": y_mm,
            "width": width_mm,
            "height": height_mm,
            "center_x": x_mm + width_mm / 2.0,
            "center_y": y_mm + height_mm / 2.0,
        })
        seen.add(component)
    ordered = sorted(keys, key=lambda item: (item["center_y"], item["center_x"], item["id"]))
    if len(ordered) <= maximum:
        return ordered
    indices = {round(index * (len(ordered) - 1) / (maximum - 1)) for index in range(maximum)}
    return [ordered[index] for index in sorted(indices)]


def high_contrast_rect_bbox(
    path: Path,
    bbox: dict[str, Any],
    page_size_mm: tuple[float, float],
) -> dict[str, Any]:
    """Locate a final-output rectangle from its four high-contrast borders."""

    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required for independent 300-DPI proof registration") from exc
    with Image.open(path) as opened:
        rgba = opened.convert("RGBA")
    white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    white.alpha_composite(rgba)
    image = white.convert("RGB")
    scale_x = image.width / page_size_mm[0]
    scale_y = image.height / page_size_mm[1]
    expected_left = float(bbox["x"]) * scale_x
    expected_top = float(bbox["y"]) * scale_y
    expected_right = (float(bbox["x"]) + float(bbox["width"])) * scale_x
    expected_bottom = (float(bbox["y"]) + float(bbox["height"])) * scale_y
    search_x = max(2, math.ceil(2.0 * scale_x))
    search_y = max(2, math.ceil(2.0 * scale_y))
    inset_x = max(1, math.floor(1.0 * scale_x))
    inset_y = max(1, math.floor(1.0 * scale_y))
    pixels = image.load()

    def dark(x: int, y: int) -> bool:
        red, green, blue = pixels[x, y]
        return 299 * red + 587 * green + 114 * blue < 190_000

    def best_vertical(center: float) -> tuple[int, int]:
        start = max(0, math.floor(center) - search_x)
        stop = min(image.width, math.ceil(center) + search_x + 1)
        top = max(0, math.floor(expected_top) + inset_y)
        bottom = min(image.height, math.ceil(expected_bottom) - inset_y)
        scores = [(sum(dark(x, y) for y in range(top, bottom)), x) for x in range(start, stop)]
        return max(scores)

    def best_horizontal(center: float) -> tuple[int, int]:
        start = max(0, math.floor(center) - search_y)
        stop = min(image.height, math.ceil(center) + search_y + 1)
        left = max(0, math.floor(expected_left) + inset_x)
        right = min(image.width, math.ceil(expected_right) - inset_x)
        scores = [(sum(dark(x, y) for x in range(left, right)), y) for y in range(start, stop)]
        return max(scores)

    left_score, left = best_vertical(expected_left)
    right_score, right = best_vertical(expected_right)
    top_score, top = best_horizontal(expected_top)
    bottom_score, bottom = best_horizontal(expected_bottom)
    minimum_vertical_score = max(8, math.floor((expected_bottom - expected_top - 2 * inset_y) * 0.3))
    minimum_horizontal_score = max(8, math.floor((expected_right - expected_left - 2 * inset_x) * 0.3))
    if min(left_score, right_score) < minimum_vertical_score:
        raise ValueError(
            f"vertical border evidence {left_score}/{right_score} is below {minimum_vertical_score} pixels"
        )
    if min(top_score, bottom_score) < minimum_horizontal_score:
        raise ValueError(
            f"horizontal border evidence {top_score}/{bottom_score} is below {minimum_horizontal_score} pixels"
        )
    if left >= right or top >= bottom:
        raise ValueError("detected rectangle borders are inverted")
    left_mm = (left + 0.5) / scale_x
    right_mm = (right + 0.5) / scale_x
    top_mm = (top + 0.5) / scale_y
    bottom_mm = (bottom + 0.5) / scale_y
    return {
        "center_x": (left_mm + right_mm) / 2.0,
        "center_y": (top_mm + bottom_mm) / 2.0,
        "bbox_x": left_mm,
        "bbox_y": top_mm,
        "bbox_width": right_mm - left_mm,
        "bbox_height": bottom_mm - top_mm,
        "border_dark_pixels": {
            "left": left_score,
            "right": right_score,
            "top": top_score,
            "bottom": bottom_score,
        },
    }


def svg_key_texts(report: dict[str, Any]) -> dict[str, dict[str, float]]:
    candidates: dict[str, list[dict[str, float]]] = {}
    for item in report.get("texts", []):
        text = str(item.get("text", "")).strip()
        bbox = item.get("bbox_mm", {})
        if (
            not text
            or not SINGLE_TOKEN.fullmatch(text)
            or len(text) > 40
            or item.get("hidden")
            or item.get("transparent")
            or item.get("zero_size")
            or not all(isinstance(bbox.get(key), (int, float)) for key in ("x", "y", "width", "height"))
        ):
            continue
        candidates.setdefault(text, []).append({
            "x": float(bbox["x"]),
            "y": float(bbox["y"]),
            "width": float(bbox["width"]),
            "height": float(bbox["height"]),
            "center_x": float(bbox["x"]) + float(bbox["width"]) / 2.0,
            "center_y": float(bbox["y"]) + float(bbox["height"]) / 2.0,
        })
    return {text: values[0] for text, values in candidates.items() if len(values) == 1}


def select_spread(keys: list[str], svg: dict[str, dict[str, float]], maximum: int = 16) -> list[str]:
    ordered = sorted(keys, key=lambda key: (svg[key]["center_y"], svg[key]["center_x"], key))
    if len(ordered) <= maximum:
        return ordered
    indices = {round(index * (len(ordered) - 1) / (maximum - 1)) for index in range(maximum)}
    return [ordered[index] for index in sorted(indices)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--oracle-report", type=Path, required=True)
    parser.add_argument("--export-report", type=Path, required=True)
    parser.add_argument("--proof-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    oracle = load_object(args.oracle_report)
    exports = load_object(args.export_report)
    failures: list[str] = []
    if oracle.get("schema_version") != "nndv-figure-svg-oracle-report-1" or oracle.get("passed") is not True:
        failures.append("strict final-SVG oracle is not a passed report")
    if exports.get("status") != "PASS" or exports.get("fresh_outputs") is not True:
        failures.append("publication export report is not a fresh PASS")

    output_root = Path(str(exports.get("output_root", ""))).resolve()
    proof_root = args.proof_dir.resolve()
    if proof_root.exists() and any(proof_root.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty cross-format proof directory: {proof_root}")
    proof_root.mkdir(parents=True, exist_ok=True)
    export_by_hash = {item.get("sha256"): item for item in exports.get("svg_inputs", [])}
    cases: list[dict[str, Any]] = []
    all_errors: list[float] = []
    errors_by_format: dict[str, list[float]] = {"pdf": [], "tikz_pdf": []}
    page_size_errors: list[float] = []
    for svg_report in oracle.get("reports", []):
        digest = svg_report.get("sha256")
        claim = export_by_hash.get(digest)
        case_failures: list[str] = []
        case_errors_by_format: dict[str, list[float]] = {"pdf": [], "tikz_pdf": []}
        if claim is None:
            failures.append(f"oracle SVG hash is absent from export report: {digest}")
            continue
        relative = Path(str(claim["relative_path"]))
        directory = output_root / relative.parent
        pdf = directory / "figure.pdf"
        tikz_pdf = directory / "figure.tikz.pdf"
        svg_proof = directory / "figure.proof-300dpi.png"
        proof_case = proof_root / relative.parent
        pdf_proof = proof_case / "pdf-300dpi.png"
        tikz_proof = proof_case / "tikz-compiled-pdf-300dpi.png"
        try:
            pdf_words, pdf_size = pdf_text(pdf)
            tikz_words, tikz_size = pdf_text(tikz_pdf)
            render_pdf_proof(pdf, pdf_proof)
            render_pdf_proof(tikz_pdf, tikz_proof)
        except (OSError, RuntimeError, ValueError, ET.ParseError, subprocess.TimeoutExpired) as exc:
            case_failures.append(f"final PDF text geometry could not be measured: {type(exc).__name__}: {exc}")
            pdf_words, tikz_words = {}, {}
            pdf_size = tikz_size = (math.nan, math.nan)

        root_mm = svg_report.get("root", {}).get("bbox_mm", {})
        svg_size = (root_mm.get("width"), root_mm.get("height"))
        size_metrics: dict[str, Any] = {"svg_mm": svg_size, "pdf_mm": pdf_size, "tikz_pdf_mm": tikz_size}
        if all(isinstance(value, (int, float)) for value in svg_size):
            for label, measured in (("PDF", pdf_size), ("compiled TikZ PDF", tikz_size)):
                error = max(abs(float(svg_size[0]) - measured[0]), abs(float(svg_size[1]) - measured[1]))
                page_size_errors.append(error)
                if error > MAXIMUM_PAGE_SIZE_ERROR_MM:
                    case_failures.append(f"{label} page size differs from final SVG by {error:.4f} mm")
        else:
            case_failures.append("strict SVG report lacks a numeric physical root size")

        svg_words = svg_key_texts(svg_report)
        pdf_counts = Counter({key: len(value) for key, value in pdf_words.items()})
        tikz_counts = Counter({key: len(value) for key, value in tikz_words.items()})
        common = [
            key for key in svg_words
            if pdf_counts[key] == 1 and tikz_counts[key] == 1
        ]
        selected = select_spread(common, svg_words)
        key_metrics: list[dict[str, Any]] = []
        for key in selected:
            reference = svg_words[key]
            formats = {"pdf": pdf_words[key][0], "tikz_pdf": tikz_words[key][0]}
            errors = {}
            for label, measured in formats.items():
                error = math.hypot(
                    measured["center_x"] - reference["center_x"],
                    measured["center_y"] - reference["center_y"],
                )
                errors[label] = round(error, 6)
                all_errors.append(error)
                errors_by_format[label].append(error)
                case_errors_by_format[label].append(error)
                if error > MAXIMUM_POSITION_ERROR_MM:
                    case_failures.append(f"{key!r} {label} center differs from final SVG by {error:.4f} mm")
            key_metrics.append({
                "kind": "text",
                "text": key,
                "svg_center_mm": [round(reference["center_x"], 6), round(reference["center_y"], 6)],
                "pdf_center_mm": [round(formats["pdf"]["center_x"], 6), round(formats["pdf"]["center_y"], 6)],
                "tikz_pdf_center_mm": [round(formats["tikz_pdf"]["center_x"], 6), round(formats["tikz_pdf"]["center_y"], 6)],
                "errors_mm": errors,
            })
        shape_metrics: list[dict[str, Any]] = []
        shape_keys = svg_shape_keys(svg_report)
        if all(math.isfinite(value) and value > 0 for value in pdf_size + tikz_size):
            for key in shape_keys:
                observations: dict[str, dict[str, float]] = {}
                errors: dict[str, float] = {}
                try:
                    svg_observation = high_contrast_rect_bbox(
                        svg_proof,
                        key,
                        (float(svg_size[0]), float(svg_size[1])),
                    )
                except (OSError, RuntimeError, TypeError, ValueError) as exc:
                    case_failures.append(f"{key['id']!r} SVG raster registration failed: {exc}")
                    continue
                for label, proof, size in (
                    ("pdf", pdf_proof, pdf_size),
                    ("tikz_pdf", tikz_proof, tikz_size),
                ):
                    try:
                        measured = high_contrast_rect_bbox(proof, key, size)
                    except (OSError, RuntimeError, ValueError) as exc:
                        case_failures.append(f"{key['id']!r} {label} raster registration failed: {exc}")
                        continue
                    observations[label] = measured
                    error = math.hypot(
                        measured["center_x"] - svg_observation["center_x"],
                        measured["center_y"] - svg_observation["center_y"],
                    )
                    errors[label] = round(error, 6)
                    all_errors.append(error)
                    errors_by_format[label].append(error)
                    case_errors_by_format[label].append(error)
                    if error > MAXIMUM_POSITION_ERROR_MM:
                        case_failures.append(f"{key['id']!r} {label} centroid differs from final SVG by {error:.4f} mm")
                if len(observations) == 2:
                    shape_metrics.append({
                        "kind": "high-contrast-rect-border",
                        "id": key["id"],
                        "svg_oracle_bbox_center_mm": [round(key["center_x"], 6), round(key["center_y"], 6)],
                        "svg_raster_centroid_mm": [round(svg_observation["center_x"], 6), round(svg_observation["center_y"], 6)],
                        "pdf_center_mm": [round(observations["pdf"]["center_x"], 6), round(observations["pdf"]["center_y"], 6)],
                        "tikz_pdf_center_mm": [round(observations["tikz_pdf"]["center_x"], 6), round(observations["tikz_pdf"]["center_y"], 6)],
                        "errors_mm": errors,
                        "border_dark_pixels": {
                            "svg": svg_observation["border_dark_pixels"],
                            **{
                                label: value["border_dark_pixels"]
                                for label, value in observations.items()
                            },
                        },
                    })
        total_keys = len(selected) + len(shape_metrics)
        if total_keys < MINIMUM_KEYS_PER_FIGURE:
            case_failures.append(
                f"only {total_keys} independently matchable text/shape keys; expected at least {MINIMUM_KEYS_PER_FIGURE}"
            )
        if len(selected) < MINIMUM_TEXT_KEYS_PER_FIGURE:
            case_failures.append("no independently matchable final-output text key")
        if len(shape_metrics) < MINIMUM_SHAPE_KEYS_PER_FIGURE:
            case_failures.append("no independently matchable high-contrast final-output rectangle")
        failures.extend(f"{relative.as_posix()}: {message}" for message in case_failures)
        cases.append({
            "svg": relative.as_posix(),
            "svg_sha256": digest,
            "passed": not case_failures,
            "key_count": total_keys,
            "text_key_count": len(selected),
            "shape_key_count": len(shape_metrics),
            "maximum_key_position_error_by_format_mm": {
                label: round(max(values), 6) if values else None
                for label, values in case_errors_by_format.items()
            },
            "page_sizes": size_metrics,
            "keys": [*key_metrics, *shape_metrics],
            "proofs": {
                "svg_300dpi": (directory / "figure.proof-300dpi.png").relative_to(output_root).as_posix(),
                "pdf_300dpi": pdf_proof.relative_to(proof_root).as_posix(),
                "tikz_compiled_pdf_300dpi": tikz_proof.relative_to(proof_root).as_posix(),
            },
            "failures": case_failures,
        })

    if len(cases) != 14:
        failures.append(f"cross-format comparison measured {len(cases)} figures, expected 14")
    result = {
        "schema_version": "nndv-0.6.1-cross-format-position-validation-1",
        "release": RELEASE,
        "status": "PASS" if not failures else "FAIL",
        "measurement_sources": {
            "svg": "strict Chrome DOM/CTM final-SVG oracle",
            "pdf": "Poppler pdftotext final-PDF bbox",
            "tikz_pdf": "Poppler pdftotext bbox after pdflatex -no-shell-escape",
            "shape_registration": "300-DPI final SVG/PDF/TikZ-PDF high-contrast rectangle border bboxes",
            "figure_ir_or_python_proof_used": False,
        },
        "thresholds_mm": {
            "maximum_key_position_error": MAXIMUM_POSITION_ERROR_MM,
            "maximum_page_size_error": MAXIMUM_PAGE_SIZE_ERROR_MM,
        },
        "figures": len(cases),
        "passed_figures": sum(item["passed"] for item in cases),
        "key_positions_compared": sum(item["key_count"] * 2 for item in cases),
        "maximum_key_position_error_mm": round(max(all_errors), 6) if all_errors else None,
        "maximum_key_position_error_by_format_mm": {
            label: round(max(values), 6) if values else None
            for label, values in errors_by_format.items()
        },
        "maximum_page_size_error_mm": round(max(page_size_errors), 6) if page_size_errors else None,
        "cases": cases,
        "proof_root": str(proof_root),
        "proof_files": [
            {
                "relative_path": path.relative_to(proof_root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in sorted(proof_root.rglob("*.png"))
        ],
        "failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "NNDV_061_CROSS_FORMAT_RESULT="
        + json.dumps(
            {
                "status": result["status"],
                "figures": result["figures"],
                "key_positions": result["key_positions_compared"],
                "maximum_error_mm": result["maximum_key_position_error_mm"],
                "failures": len(failures),
            },
            sort_keys=True,
        )
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
