#!/usr/bin/env python3
"""Release-block the three real paper examples on final physical geometry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
from typing import Any

from PIL import Image


ZERO_ARRAYS = (
    "clipping",
    "node_overlaps",
    "singular_text_transforms",
    "text_overflows",
    "text_page_violations",
    "edge_node_collisions",
    "edge_crossings",
    "endpoint_errors",
    "marker_node_collisions",
    "group_label_conflicts",
    "edge_label_conflicts",
    "annotation_node_collisions",
    "legend_node_collisions",
    "title_node_collisions",
    "title_legend_collisions",
    "title_group_label_collisions",
    "annotation_page_violations",
    "legend_page_violations",
    "unknown_roles",
    "exception_errors",
    "metadata_errors",
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _pdf_points(path: Path) -> tuple[float, float]:
    completed = subprocess.run(
        ["pdfinfo", str(path)], capture_output=True, text=True, timeout=20, check=False
    )
    if completed.returncode:
        raise RuntimeError(f"pdfinfo failed for {path}: {completed.stderr[-500:]}")
    match = re.search(r"^Page size:\s+([0-9.]+) x ([0-9.]+) pts", completed.stdout, re.MULTILINE)
    if not match:
        raise RuntimeError(f"pdfinfo did not report a point page size for {path}")
    return float(match.group(1)), float(match.group(2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper-examples", type=Path, required=True)
    parser.add_argument("--chrome-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paper = _load(args.paper_examples)
    chrome = _load(args.chrome_report)
    root = args.paper_examples.parent
    browser_by_name = {Path(item["file"]).name: item for item in chrome.get("reports", [])}
    examples: dict[str, Any] = {}
    for name, item in sorted(paper.get("examples", {}).items()):
        outputs = [root / path for path in item.get("outputs", [])]
        svg = next((path for path in outputs if path.suffix.lower() == ".svg"), None)
        pdf = next((path for path in outputs if path.suffix.lower() == ".pdf"), None)
        browser = browser_by_name.get(svg.name if svg else "", {})
        proof = item.get("proof", {})
        width_mm = float(proof.get("width_mm", 0.0))
        height_mm = float(proof.get("height_mm", 0.0))
        expected_points = (width_mm / 25.4 * 72.0, height_mm / 25.4 * 72.0)
        actual_points = _pdf_points(pdf) if pdf and pdf.is_file() else (0.0, 0.0)
        after = root / item.get("after_png", "")
        before = root / item.get("before_png", "")
        comparison = root / item.get("before_after_png", "")
        with Image.open(after) as image:
            after_pixels = image.size
            after_dpi = tuple(float(value) for value in image.info.get("dpi", (0.0, 0.0)))
        expected_pixels = (round(width_mm / 25.4 * 300), round(height_mm / 25.4 * 300))
        arrays_zero = all(not browser.get(key, ["missing"]) for key in ZERO_ARRAYS)
        exact_text_scale = (
            abs(float(browser.get("minimum_horizontal_scale", 0.0)) - 1.0) <= 1e-9
            and abs(float(browser.get("minimum_transform_shape", 0.0)) - 1.0) <= 1e-9
        )
        physical_size = all(abs(actual - expected) <= 0.2 for actual, expected in zip(actual_points, expected_points))
        raster_300dpi = (
            all(abs(actual - expected) <= 2 for actual, expected in zip(after_pixels, expected_pixels))
            and all(abs(value - 300.0) <= 0.1 for value in after_dpi)
        )
        panel_occupancy = proof.get("panel_content_occupancy", {})
        whitespace_balanced = (
            proof.get("balanced_whitespace") is True
            and bool(panel_occupancy)
            and all(0.28 <= float(value) <= 1.0 for value in panel_occupancy.values())
            and 0.55 <= float(browser.get("occupancy", 0.0)) <= 1.0
        )
        passed = (
            browser.get("passed") is True
            and float(browser.get("minimum_font_pt", 0.0)) >= 7.0
            and arrays_zero
            and exact_text_scale
            and proof.get("paper_ready") is True
            and whitespace_balanced
            and physical_size
            and raster_300dpi
            and before.is_file()
            and comparison.is_file()
        )
        examples[name] = {
            "passed": passed,
            "svg": svg.relative_to(root).as_posix() if svg else None,
            "pdf": pdf.relative_to(root).as_posix() if pdf else None,
            "minimum_font_pt": browser.get("minimum_font_pt"),
            "label_overflow": len(browser.get("text_overflows", [])),
            "node_overlap": len(browser.get("node_overlaps", [])),
            "edge_node_collision": len(browser.get("edge_node_collisions", [])),
            "clipping": len(browser.get("clipping", [])),
            "unexplained_crossing": len(browser.get("edge_crossings", [])),
            "horizontal_text_scale": browser.get("minimum_horizontal_scale"),
            "transform_text_scale": browser.get("minimum_transform_shape"),
            "title_legend_node_collisions": sum(
                len(browser.get(key, []))
                for key in (
                    "group_label_conflicts",
                    "legend_node_collisions",
                    "title_node_collisions",
                    "title_legend_collisions",
                    "title_group_label_collisions",
                )
            ),
            "page_occupancy": browser.get("occupancy"),
            "panel_content_occupancy": panel_occupancy,
            "physical_size_mm": [width_mm, height_mm],
            "pdf_page_points": list(actual_points),
            "after_png_pixels_300dpi": list(after_pixels),
            "before_png": before.relative_to(root).as_posix(),
            "after_png": after.relative_to(root).as_posix(),
            "before_after_png": comparison.relative_to(root).as_posix(),
        }
    failures = [name for name, item in examples.items() if not item["passed"]]
    report = {
        "schema_version": "0.4.2-publication-quality-acceptance-1",
        "acceptance": "PASS" if not failures and len(examples) == 3 else "FAIL",
        "examples": examples,
        "counts": {"total": len(examples), "passed": len(examples) - len(failures), "failed": len(failures)},
        "failures": failures,
        "passed": not failures and len(examples) == 3,
        "independence": {
            "svg_geometry": "Chromium getBoundingClientRect/getComputedTextLength over landed SVG files",
            "pdf_geometry": "pdfinfo over landed PDF files",
            "raster": "pdftoppm output reopened with Pillow; 300 DPI dimensions checked from physical page size",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "acceptance": report["acceptance"],
        "total": len(examples),
        "passed": len(examples) - len(failures),
        "failed": len(failures),
    }, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
