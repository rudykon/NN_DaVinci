#!/usr/bin/env python3
"""Build the seven-model reader-visible role/route acceptance matrix."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


RELEASE = "0.7.3 — Reader-Visible Scientific Completeness & Generalization Hotfix"
EXPECTED = {
    "resnet50": (6, 4),
    "vision_transformer": (5, 1),
    "bert_encoder": (5, 1),
    "multiscale_unet": (9, 3),
    "diffusion_unet": (6, 3),
    "topk_moe": (5, 5),
    "image_text": (4, 2),
}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"report is not a JSON object: {path}")
    return value


def case_name(case: dict[str, Any]) -> str:
    return Path(str(case.get("case_dir", ""))).name


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--presentation", type=Path, required=True)
    parser.add_argument("--browser-dom", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    presentation = load(args.presentation)
    dom = load(args.browser_dom)
    p_cases = {case_name(case): case for case in presentation.get("cases", [])}
    d_cases = {case_name(case): case for case in dom.get("cases", [])}
    failures: list[str] = []
    rows: list[dict[str, Any]] = []

    if presentation.get("status") != "PASS":
        failures.append("semantic presentation oracle did not pass")
    if dom.get("status") != "PASS":
        failures.append("browser DOM/CTM oracle did not pass")
    if set(p_cases) != set(EXPECTED) or set(d_cases) != set(EXPECTED):
        failures.append("semantic reports do not contain exactly the seven required models")

    for name, (expected_roles, expected_routes) in EXPECTED.items():
        case = p_cases.get(name, {})
        dom_case = d_cases.get(name, {})
        inspections = case.get("inspections", {})
        svg = inspections.get("svg", {})
        landed_roles = len(set(svg.get("visible_role_ids", [])))
        landed_routes = min(
            (inspections.get(fmt, {}).get("bound_routes", -1) for fmt in ("svg", "pdf", "tikz", "pptx")),
            default=-1,
        )
        formats = {
            fmt: (
                inspections.get(fmt, {}).get("missing_role_ids", []) == []
                and (
                    fmt == "tikz_pdf"
                    or inspections.get(fmt, {}).get("bound_role_labels") == expected_roles
                )
            )
            for fmt in ("svg", "pdf", "tikz", "pptx", "tikz_pdf")
        }
        dom_visible = sum(
            row.get("visible") is True and row.get("in_page") is True
            for row in dom_case.get("label_rows", [])
        )
        blockers = list(case.get("blockers", [])) + list(dom_case.get("blockers", []))
        passed = (
            case.get("status") == dom_case.get("status") == "PASS"
            and case.get("expected_role_count") == expected_roles
            and case.get("expected_route_count") == expected_routes
            and landed_roles == expected_roles
            and dom_visible == expected_roles
            and landed_routes == expected_routes
            and all(formats.values())
            and not blockers
        )
        if not passed:
            failures.append(f"{name}: expected/visible roles or expected/landed routes disagree")
        rows.append(
            {
                "model": name,
                "family": case.get("family"),
                "expected_role_count": expected_roles,
                "visible_role_count": landed_roles,
                "browser_visible_in_page_role_count": dom_visible,
                "expected_critical_route_count": expected_routes,
                "landed_critical_route_count": landed_routes,
                "format_semantic_consistency": formats,
                "evidence_digest": case.get("evidence_digest"),
                "status": "PASS" if passed else "FAIL",
                "blockers": blockers,
            }
        )

    report = {
        "schema_version": "nndv-0.7.3-semantic-completeness-matrix-1",
        "release": RELEASE,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not failures else "FAIL",
        "model_count": len(rows),
        "all_roles_reader_visible": not failures,
        "all_critical_routes_landed_with_direction": not failures,
        "formats": ["svg", "pdf", "tikz", "pptx", "tikz_pdf"],
        "models": rows,
        "failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "models": len(rows)}, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
