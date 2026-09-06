#!/usr/bin/env python3
"""Validate the new 0.4 product evidence without changing inherited release gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real-models", type=Path, required=True)
    parser.add_argument("--paper-examples", type=Path, required=True)
    parser.add_argument("--publication-quality", type=Path, required=True)
    parser.add_argument("--scientific-fidelity", type=Path, required=True)
    parser.add_argument("--diff", type=Path, required=True)
    parser.add_argument("--performance", type=Path, required=True)
    parser.add_argument("--semantic-e2e", type=Path, required=True)
    parser.add_argument("--product-e2e", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paper_root = args.paper_examples.parent
    real_models = _load(args.real_models)
    paper = _load(args.paper_examples)
    publication_quality = _load(args.publication_quality)
    scientific_fidelity = _load(args.scientific_fidelity)
    difference = _load(args.diff)
    performance = _load(args.performance)
    semantic_e2e = _load(args.semantic_e2e)
    product_e2e = _load(args.product_e2e)
    checks: list[dict[str, Any]] = []

    def check(identifier: str, passed: bool, observed: Any) -> None:
        checks.append({"id": identifier, "passed": bool(passed), "observed": observed})

    models = real_models.get("models", {})
    check("REAL-01", real_models.get("compatible") is True and len(models) == 7, {"models": len(models), "compatible": real_models.get("compatible")})
    check(
        "REAL-02",
        all(set(item.get("views", {})) == {"framework", "module", "operation"} for item in models.values()),
        {name: sorted(item.get("views", {})) for name, item in models.items()},
    )
    check(
        "REAL-03",
        all(
            item.get("bidirectional_provenance") is True
            and all(
                0.0 <= detection.get("confidence", -1) <= 1.0
                and bool(detection.get("reasons"))
                and bool(
                    detection.get("provenance", {}).get("source_node_ids")
                    or detection.get("provenance", {}).get("source_edge_ids")
                )
                for detection in item.get("detections", [])
            )
            for item in models.values()
        ),
        {name: {"detections": len(item.get("detections", [])), "roundtrip": item.get("bidirectional_provenance")} for name, item in models.items()},
    )
    check(
        "REAL-04",
        all(
            item.get("module_first_screen_within_2s") is True
            and all(len(phase.get("runs_ms", [])) == 3 for phase in item.get("timings", {}).values())
            for item in models.values()
        ),
        {name: item.get("timings", {}).get("model_to_module_first_screen") for name, item in models.items()},
    )
    examples = paper.get("examples", {})
    check("PAPER-01", paper.get("passed") is True and len(examples) == 3, {"examples": sorted(examples), "passed": paper.get("passed")})
    check(
        "PAPER-02",
        all(
            {Path(path).suffix.lower() for path in item.get("outputs", [])} == {".svg", ".pdf", ".tex", ".pptx"}
            and all(item.get("compatibility", {}).values())
            and (paper_root / item.get("project", "")).is_file()
            and (paper_root / item.get("semantic_provenance", "")).is_file()
            and (paper_root / item.get("geometry_quality", "")).is_file()
            for item in examples.values()
        ),
        {name: item.get("compatibility") for name, item in examples.items()},
    )
    check(
        "PAPER-QUALITY-01",
        publication_quality.get("passed") is True
        and publication_quality.get("counts") == {"total": 3, "passed": 3, "failed": 0}
        and all(item.get("passed") is True for item in publication_quality.get("examples", {}).values()),
        {
            name: {
                "minimum_font_pt": item.get("minimum_font_pt"),
                "label_overflow": item.get("label_overflow"),
                "edge_node_collision": item.get("edge_node_collision"),
                "physical_size_mm": item.get("physical_size_mm"),
            }
            for name, item in publication_quality.get("examples", {}).items()
        },
    )
    check(
        "SCIENTIFIC-FIDELITY-01",
        scientific_fidelity.get("passed") is True
        and scientific_fidelity.get("counts") == {"total": 3, "passed": 3, "failed": 0}
        and all(item.get("passed") is True for item in scientific_fidelity.get("examples", {}).values()),
        {
            name: {
                "merge_indegree": item.get("merge_indegree"),
                "source_paths_replayed": item.get("source_paths_replayed"),
                "repetition": item.get("repetition"),
            }
            for name, item in scientific_fidelity.get("examples", {}).items()
        },
    )
    comparisons = difference.get("comparisons", {})
    check("DIFF-01", difference.get("passed") is True and len(comparisons) == 3, {"comparisons": sorted(comparisons), "passed": difference.get("passed")})
    check(
        "DIFF-02",
        all(
            item.get("bidirectional_provenance") is True
            and set(item.get("matching", {})) == {"exact", "probable", "unmatched"}
            and bool(item.get("outputs"))
            for item in comparisons.values()
        ),
        {name: item.get("matching") for name, item in comparisons.items()},
    )
    check("PERF-01", performance.get("passed") is True and performance.get("repeats") == 3, {"passed": performance.get("passed"), "repeats": performance.get("repeats")})
    check(
        "PERF-02",
        all(
            item["viewport_update_ms"] <= 200
            and item["rendered_nodes"] <= 500
            and item["dom_object_estimate"] <= 2_000
            for section in (performance["lazy_10k"], performance["summary_50k"])
            for item in section["runs"]
        ),
        {"10k": performance["lazy_10k"]["viewport_update"], "50k": performance["summary_50k"]["viewport_update"]},
    )
    semantic_performance = semantic_e2e.get("performance", {})
    check(
        "E2E-SEMANTIC-01",
        semantic_e2e.get("status") == "passed"
        and semantic_e2e.get("assertion_count", 0) >= 27
        and semantic_performance.get("no_regression") is True,
        {"assertions": semantic_e2e.get("assertion_count"), **semantic_performance},
    )
    automation = product_e2e.get("automation_metrics", {})
    composer_recovery_assertions = {
        "refresh restores the exact Composer panel layout instead of re-layout",
        "refresh restores participant locks and manual routes",
        "reopened Composer restores participant controls and all panels",
        "opening the saved project restores exact Composer geometry and manual edits",
    }
    landed_product_assertions = set(product_e2e.get("assertions", []))
    check(
        "E2E-PRODUCT-01",
        product_e2e.get("status") == "passed"
        and product_e2e.get("assertion_count", 0) >= 31
        and composer_recovery_assertions <= landed_product_assertions
        and automation.get("automated_interaction_only") is True
        and automation.get("lazy_50k_first_view_ms", 1e9) <= 2_000
        and automation.get("cancellation_ms", 1e9) <= 1_000,
        {
            "assertions": product_e2e.get("assertion_count"),
            "missing_composer_recovery_assertions": sorted(
                composer_recovery_assertions - landed_product_assertions
            ),
            **automation,
        },
    )
    failures = [item["id"] for item in checks if not item["passed"]]
    report = {
        "schema_version": "0.5.1-product-acceptance-1",
        "checks": checks,
        "counts": {"total": len(checks), "passed": len(checks) - len(failures), "failed": len(failures)},
        "failures": failures,
        "passed": not failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["counts"], sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
