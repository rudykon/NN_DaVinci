#!/usr/bin/env python3
"""Bind strict Chrome SVG measurements to the fresh 0.6.1 export corpus."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any


RELEASE = "0.6.1 Beta — Publication Fidelity & Model-to-Figure Completion"
MINIMUM_FONT_PT = 7.0
FONT_NUMERIC_TOLERANCE_PT = 0.01
MINIMUM_STROKE_PT = 0.1
MINIMUM_SCALE = 0.98
MAXIMUM_SCALE = 1.02
MINIMUM_OCCUPANCY = 0.02
MAXIMUM_OCCUPANCY = 0.98


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--oracle-report", type=Path, required=True)
    parser.add_argument("--export-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    oracle = load_object(args.oracle_report)
    exports = load_object(args.export_report)
    failures: list[str] = []

    if oracle.get("schema_version") != "nndv-figure-svg-oracle-report-1":
        failures.append("unexpected Figure SVG oracle report schema")
    if oracle.get("oracle") != "figure-final-svg-chrome-v1":
        failures.append("unexpected Figure SVG oracle identity")
    contract = oracle.get("measurement_contract", {})
    required_contract = {
        "final_dom_only": True,
        "metadata_trusted": False,
        "python_proof_imported": False,
        "data_scale_claims_trusted": False,
        "stroke_under_full_ctm": True,
        "path_flattener": "svg_path_flatten.js",
    }
    for name, expected in required_contract.items():
        if contract.get(name) != expected:
            failures.append(f"oracle measurement contract {name}={contract.get(name)!r}, expected {expected!r}")
    oracle_tolerance = contract.get("tolerance", {})
    if oracle_tolerance.get("minimumFontPt") != MINIMUM_FONT_PT:
        failures.append("oracle minimumFontPt threshold is not 7 pt")
    if oracle_tolerance.get("minimumStrokePt") != MINIMUM_STROKE_PT:
        failures.append("oracle minimumStrokePt threshold is not 0.1 pt")
    if exports.get("status") != "PASS" or exports.get("fresh_outputs") is not True:
        failures.append("publication export corpus is not a passed fresh run")
    if exports.get("python_figure_proof_is_release_blocker") is not False:
        failures.append("publication corpus incorrectly uses Python figure_proof as a release blocker")

    expected_inputs = exports.get("svg_inputs", [])
    expected_hashes = Counter(item.get("sha256") for item in expected_inputs)
    reports = oracle.get("reports", [])
    measured_hashes = Counter(item.get("sha256") for item in reports)
    if len(expected_inputs) != 14:
        failures.append(f"publication report exposes {len(expected_inputs)} SVG inputs, expected 14")
    if len(reports) != 14:
        failures.append(f"strict oracle measured {len(reports)} SVG files, expected 14")
    if expected_hashes != measured_hashes:
        failures.append("strict oracle inputs do not exactly match the hashes of the fresh exported SVG corpus")
    if oracle.get("summary", {}).get("files") != 14:
        failures.append("strict oracle summary does not account for 14 files")
    if oracle.get("summary", {}).get("passed") != 14 or oracle.get("summary", {}).get("failed") != 0:
        failures.append("strict oracle did not pass all 14 exported SVG files")
    if oracle.get("passed") is not True:
        failures.append("strict oracle top-level verdict is not PASS")

    cases: list[dict[str, Any]] = []
    minimum_fonts: list[float] = []
    minimum_strokes: list[float] = []
    maximum_strokes: list[float] = []
    horizontal_scales: list[float] = []
    vertical_scales: list[float] = []
    transform_shapes: list[float] = []
    occupancies: list[float] = []
    for index, item in enumerate(reports):
        name = Path(str(item.get("file", f"report-{index}"))).name
        case_failures: list[str] = []
        source = item.get("source", {})
        if source.get("loaded_from_persisted_file") is not True:
            case_failures.append("SVG was not loaded from a persisted file URL")
        if source.get("metadata_consulted") is not False:
            case_failures.append("oracle consulted producer metadata")
        if item.get("passed") is not True or item.get("issues") or item.get("issue_counts"):
            case_failures.append("strict geometry issues are non-zero")
        if item.get("browser_errors"):
            case_failures.append("Chrome emitted console/page errors")
        summary = item.get("summary", {})
        font = summary.get("minimum_font_pt")
        minimum_stroke = summary.get("minimum_stroke_pt")
        maximum_stroke = summary.get("maximum_stroke_pt")
        horizontal = summary.get("minimum_horizontal_ctm_scale")
        vertical = summary.get("minimum_vertical_ctm_scale")
        shape = summary.get("minimum_transform_shape")
        for label, value in (
            ("minimum font", font),
            ("minimum effective stroke", minimum_stroke),
            ("maximum effective stroke", maximum_stroke),
            ("horizontal CTM scale", horizontal),
            ("vertical CTM scale", vertical),
            ("transform shape", shape),
        ):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                case_failures.append(f"{label} is not a numeric browser measurement")
        if isinstance(font, (int, float)) and not isinstance(font, bool):
            minimum_fonts.append(float(font))
            if float(font) < MINIMUM_FONT_PT - FONT_NUMERIC_TOLERANCE_PT:
                case_failures.append(
                    f"minimum effective font {font} pt is below {MINIMUM_FONT_PT} pt "
                    f"with {FONT_NUMERIC_TOLERANCE_PT} pt numeric tolerance"
                )
        stroke_values: list[float] = []
        strokes = item.get("strokes")
        if not isinstance(strokes, list) or not strokes:
            case_failures.append("full-CTM stroke measurements are absent")
        else:
            for stroke_index, stroke in enumerate(strokes):
                value = stroke.get("effective_stroke_pt") if isinstance(stroke, dict) else None
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    case_failures.append(f"stroke {stroke_index} lacks a numeric effective_stroke_pt")
                    continue
                stroke_values.append(float(value))
        if isinstance(minimum_stroke, (int, float)) and not isinstance(minimum_stroke, bool):
            minimum_strokes.append(float(minimum_stroke))
            if float(minimum_stroke) < MINIMUM_STROKE_PT:
                case_failures.append(
                    f"minimum effective stroke {minimum_stroke} pt is below {MINIMUM_STROKE_PT} pt"
                )
        if isinstance(maximum_stroke, (int, float)) and not isinstance(maximum_stroke, bool):
            maximum_strokes.append(float(maximum_stroke))
        if stroke_values:
            if isinstance(minimum_stroke, (int, float)) and abs(min(stroke_values) - float(minimum_stroke)) > 1e-6:
                case_failures.append("summary minimum_stroke_pt differs from full-CTM stroke measurements")
            if isinstance(maximum_stroke, (int, float)) and abs(max(stroke_values) - float(maximum_stroke)) > 1e-6:
                case_failures.append("summary maximum_stroke_pt differs from full-CTM stroke measurements")
        for label, value, sink in (
            ("horizontal CTM", horizontal, horizontal_scales),
            ("vertical CTM", vertical, vertical_scales),
            ("transform shape", shape, transform_shapes),
        ):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                sink.append(float(value))
                if not MINIMUM_SCALE <= float(value) <= MAXIMUM_SCALE:
                    case_failures.append(f"{label} scale {value} is outside [{MINIMUM_SCALE}, {MAXIMUM_SCALE}]")
        page_occupancies: list[float] = []
        for page in item.get("occupancy", []):
            value = page.get("bbox_occupancy")
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                case_failures.append("page occupancy is not a numeric browser measurement")
                continue
            numeric = float(value)
            occupancies.append(numeric)
            page_occupancies.append(numeric)
            if not MINIMUM_OCCUPANCY <= numeric <= MAXIMUM_OCCUPANCY:
                case_failures.append(
                    f"page occupancy {numeric} is outside [{MINIMUM_OCCUPANCY}, {MAXIMUM_OCCUPANCY}]"
                )
        failures.extend(f"{name}: {message}" for message in case_failures)
        cases.append(
            {
                "file": item.get("file"),
                "sha256": item.get("sha256"),
                "passed": not case_failures,
                "minimum_font_pt": font,
                "minimum_stroke_pt": minimum_stroke,
                "maximum_stroke_pt": maximum_stroke,
                "stroke_count": len(stroke_values),
                "minimum_horizontal_ctm_scale": horizontal,
                "minimum_vertical_ctm_scale": vertical,
                "minimum_transform_shape": shape,
                "page_occupancies": page_occupancies,
                "issue_count": summary.get("issue_count"),
                "failures": case_failures,
            }
        )

    result = {
        "schema_version": "nndv-0.6.1-strict-publication-svg-validation-1",
        "release": RELEASE,
        "status": "PASS" if not failures else "FAIL",
        "oracle": oracle.get("oracle"),
        "browser": oracle.get("browser"),
        "fresh_export_hashes_matched": expected_hashes == measured_hashes,
        "final_svg_files": len(reports),
        "passed_svg_files": sum(item["passed"] for item in cases),
        "thresholds": {
            "minimum_font_pt": MINIMUM_FONT_PT,
            "font_numeric_tolerance_pt": FONT_NUMERIC_TOLERANCE_PT,
            "minimum_stroke_pt": MINIMUM_STROKE_PT,
            "minimum_text_scale": MINIMUM_SCALE,
            "maximum_text_scale": MAXIMUM_SCALE,
            "minimum_page_occupancy": MINIMUM_OCCUPANCY,
            "maximum_page_occupancy": MAXIMUM_OCCUPANCY,
        },
        "metrics": {
            "minimum_font_pt": min(minimum_fonts) if minimum_fonts else None,
            "minimum_stroke_pt": min(minimum_strokes) if minimum_strokes else None,
            "maximum_stroke_pt": max(maximum_strokes) if maximum_strokes else None,
            "minimum_horizontal_ctm_scale": min(horizontal_scales) if horizontal_scales else None,
            "maximum_horizontal_ctm_scale": max(horizontal_scales) if horizontal_scales else None,
            "minimum_vertical_ctm_scale": min(vertical_scales) if vertical_scales else None,
            "maximum_vertical_ctm_scale": max(vertical_scales) if vertical_scales else None,
            "minimum_transform_shape": min(transform_shapes) if transform_shapes else None,
            "maximum_transform_shape": max(transform_shapes) if transform_shapes else None,
            "minimum_page_occupancy": min(occupancies) if occupancies else None,
            "maximum_page_occupancy": max(occupancies) if occupancies else None,
            "geometry_issues": sum(int(item.get("summary", {}).get("issue_count", 0)) for item in reports),
            "browser_errors": sum(len(item.get("browser_errors", [])) for item in reports),
        },
        "measurement_contract": required_contract,
        "python_figure_proof_imported": False,
        "cases": cases,
        "failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "NNDV_061_STRICT_SVG_RESULT="
        + json.dumps(
            {
                "status": result["status"],
                "files": result["final_svg_files"],
                "passed": result["passed_svg_files"],
                "failures": len(failures),
            },
            sort_keys=True,
        )
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
