#!/usr/bin/env python3
"""Aggregate inherited predicates plus the 0.5.2 responsive workspace gate."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import time


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence_root", type=Path)
    parser.add_argument("--started-epoch", type=float, required=True)
    parser.add_argument("--started-utc", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--final-relative-root", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.evidence_root.resolve()
    tests = load(root / "tests/python-tests.json")
    coverage = load(root / "coverage/summary.json")
    matrix = load(root / "matrix/results.json")
    commands = load(root / "source/commands.json")
    snapshot = load(root / "source/snapshot.json")
    counts = load(root / "release-counts.json")
    e2e = load(root / "e2e/scenarios.json")
    responsive_e2e = load(root / "e2e/responsive-workspace.json")
    semantic_e2e = load(root / "e2e/semantic-workflow.json")
    product_e2e = load(root / "e2e/product-workflow.json")
    product = load(root / "product/acceptance.json")
    real_models = load(root / "product/real-models/compatibility.json")
    paper_examples = load(root / "product/paper-examples/paper-examples-report.json")
    publication_quality = load(root / "product/publication-quality/acceptance.json")
    scientific_fidelity = load(root / "product/scientific-fidelity/acceptance.json")
    model_diff = load(root / "product/diff/real-model-diff-report.json")
    product_performance = load(root / "product/performance/three-runs.json")
    trial_acceptance = load(root / "trial/acceptance.json")
    trial_models = load(root / "trial/external-models/compatibility.json")
    venue_proof = load(root / "trial/venue-proof/venue-proof-report.json")
    trial_e2e = load(root / "e2e/trial-workflow.json")
    human_trial = load(root / "trial/kit/human-trial-status.json")
    structure = load(root / "visual/fixture-integrity.json")
    visual = load(root / "visual/seven-architecture-metrics.json")
    mutation = load(root / "matrix/mutation-report.json")
    failures: list[str] = []
    bad_commands = [item["id"] for item in commands["commands"] if item["exit_code"] != item.get("expected_exit_code", 0)]
    if bad_commands:
        failures.append(f"workload commands failed: {bad_commands}")
    if tests["collected"] != tests["passed"] or any(tests[key] for key in ("failures", "errors", "skipped", "deselected")):
        failures.append("Python test state is not clean")
    if not all(coverage[key] for key in ("old_core_passed", "expanded_core_passed", "all_package_passed")):
        failures.append("coverage release gate failed")
    if not matrix["passed"] or any(matrix["counts"].get(key, 0) for key in ("failed", "error", "skipped", "not_run")):
        failures.append("executable acceptance matrix has a non-passing blocker")
    if not mutation["passed"]:
        failures.append("mutation gate failed")
    if e2e["counts"]["passed"] != 10 or e2e["counts"]["skipped"]:
        failures.append("browser E2E scenario gate failed")
    responsive_coverage = responsive_e2e.get("coverage", {})
    responsive_requirements = {
        "canonical_workspace_drawers",
        "inspector_selection_entry",
        "mutually_exclusive_surfaces",
        "keyboard_and_focus_restore",
        "breakpoint_cleanup",
        "bounded_workflow_dialogs",
    }
    expected_composer_panels = [
        {"id": "A", "title": "Semantic blocks", "level": "block"},
        {"id": "B", "title": "Operation evidence", "level": "operation"},
    ]
    expected_mobile_workflow = [
        "import-model",
        "block-view",
        "paper-view",
        "composer-a-b",
        "save-project",
        "export-svg",
    ]
    if (
        responsive_e2e.get("status") != "passed"
        or responsive_e2e.get("viewport_count") != 7
        or not all(responsive_coverage.get(key) is True for key in responsive_requirements)
        or responsive_coverage.get("composer_default_panels") != expected_composer_panels
        or responsive_coverage.get("duplicate_composer_initializations") != 0
        or responsive_coverage.get("mobile_workflow") != expected_mobile_workflow
        or responsive_coverage.get("unexpected_browser_errors") != 0
    ):
        failures.append("0.5.2 responsive workspace browser workflow gate failed")
    if semantic_e2e.get("status") != "passed" or semantic_e2e.get("assertion_count", 0) < 27:
        failures.append("0.3 semantic/paper browser workflow gate failed")
    if tests.get("inherited_0_3_tests", 0) != 130:
        failures.append("the inherited 130-test 0.3 suite is not intact")
    composer_recovery_assertions = {
        "refresh restores the exact Composer panel layout instead of re-layout",
        "refresh restores participant locks and manual routes",
        "reopened Composer restores participant controls and all panels",
        "opening the saved project restores exact Composer geometry and manual edits",
    }
    if (
        product_e2e.get("status") != "passed"
        or product_e2e.get("assertion_count", 0) < 31
        or not composer_recovery_assertions <= set(product_e2e.get("assertions", []))
    ):
        failures.append("0.5.1 Composer recovery browser workflow gate failed")
    if not product.get("passed") or product.get("counts", {}).get("failed"):
        failures.append("0.4 product acceptance gate failed")
    if not all(item.get("passed") for item in (real_models, paper_examples, model_diff, product_performance)):
        failures.append("one or more 0.4 real-model production reports failed")
    if not publication_quality.get("passed") or publication_quality.get("counts", {}).get("passed") != 3:
        failures.append("0.4.1 publication-quality release blocker failed")
    if not scientific_fidelity.get("passed") or scientific_fidelity.get("counts", {}).get("passed") != 3:
        failures.append("0.4.2 scientific-fidelity release blocker failed")
    if not trial_acceptance.get("passed") or trial_acceptance.get("counts", {}).get("passed") != 5:
        failures.append("0.5.1 inherited researcher-trial kit release blocker failed")
    trial_recovery_assertions = {
        message
        for key in trial_models.get("models", {})
        for message in (
            f"{key} records the deliberate node and edge edits required by T4",
            f"{key} refresh preserves exact Panel geometry, locks and routes",
            f"{key} saved project preserves exact Composer state",
        )
    }
    trial_recovery_assertions.add("all six automated task paths retain distinct node and edge edit counts")
    if (
        trial_e2e.get("status") != "passed"
        or trial_e2e.get("assertion_count", 0) < 65
        or set(trial_e2e.get("cases", {})) != set(trial_models.get("models", {}))
        or not trial_recovery_assertions <= set(trial_e2e.get("assertions", []))
    ):
        failures.append("0.5.1 inherited six-case Trial Mode Chrome workflow failed")
    if human_trial.get("status") != "awaiting_participants" or human_trial.get("participants") != 0:
        failures.append("0.5.1 human-trial status is not honest about unavailable participants")
    report = {
        "schema_version": "0.5.2-verification-1",
        "release": "0.5.2 Beta — Responsive Workspace & Pilot UX Hotfix",
        "run_id": args.run_id,
        "evidence_root": args.final_relative_root,
        "started_utc": args.started_utc,
        "ended_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": time.time() - args.started_epoch,
        "python": platform.python_version(),
        "runner_result": "PASS" if not bad_commands else "FAIL",
        "pre_seal_audit": "PASS" if not failures else "FAIL",
        "commands": commands["commands"],
        "counts": {**counts, "release_blocker_checks": matrix["release_blocker_checks"], "e2e_assertions_diagnostic": e2e["counts"]["assertions"]},
        "tests": {
            "collected": tests["collected"],
            "passed": tests["passed"],
            "failed": tests["failures"],
            "errors": tests["errors"],
            "skipped": tests["skipped"],
            "deselected": tests["deselected"],
            "frozen_ids": tests["baseline_count"],
            "inherited_0_3_tests": tests["inherited_0_3_tests"],
            "product_0_4_tests": tests["product_0_4_tests"],
            "product_0_5_tests": tests["product_0_5_tests"],
        },
        "coverage": {key: coverage[key] for key in ("old_core", "expanded_core", "all_package")},
        "coverage_denominator_diff": {
            "old_core_by_file": coverage["core_denominator_diff"],
            "all_package_total": coverage["all_package_total_denominator_diff"],
        },
        "acceptance_matrix": {
            "digest": matrix["matrix_sha256"],
            "release_blocker_checks": matrix["release_blocker_checks"],
            "counts": matrix["counts"],
            "passed": matrix["passed"],
        },
        "mutations": {"cases": len(mutation["cases"]), "failed_cases": mutation["failed_cases"], "passed": mutation["passed"]},
        "stress": load(root / "stress/results.json"),
        "visual": {
            "authority_hashes": {name: item["sha256"] for name, item in structure["fixtures"].items()},
            "strict_oracle": visual,
        },
        "e2e": {
            "counts": e2e["counts"],
            "scenario_ids": [item["id"] for item in e2e["scenarios"]],
            "responsive_workspace": {
                "scenario": responsive_e2e["scenario"],
                "status": responsive_e2e["status"],
                "viewports": responsive_e2e["viewports"],
                "viewport_count": responsive_e2e["viewport_count"],
                "coverage": responsive_coverage,
            },
            "semantic_workflow": {
                "scenario": semantic_e2e["scenario"],
                "status": semantic_e2e["status"],
                "assertions": semantic_e2e["assertion_count"],
                "duration_ms": semantic_e2e["duration_ms"],
            },
            "product_workflow": {
                "scenario": product_e2e["scenario"],
                "status": product_e2e["status"],
                "assertions": product_e2e["assertion_count"],
                "duration_ms": product_e2e["duration_ms"],
                "automation_metrics": product_e2e["automation_metrics"],
                "usability_claim": product_e2e["usability_claim"],
            },
            "trial_workflow": {
                "scenario": trial_e2e["scenario"],
                "status": trial_e2e["status"],
                "assertions": trial_e2e["assertion_count"],
                "automated_metrics": trial_e2e["automated_metrics"],
                "human_participants": trial_e2e["human_participants"],
                "human_usability_claim": trial_e2e["human_usability_claim"],
            },
        },
        "product_0_4": {
            "acceptance": product["counts"],
            "real_models": {
                "count": len(real_models["models"]),
                "compatible": real_models["compatible"],
                "module_first_screen_ms": {name: item["timings"]["model_to_module_first_screen"] for name, item in real_models["models"].items()},
            },
            "paper_examples": sorted(paper_examples["examples"]),
            "publication_quality": publication_quality,
            "scientific_fidelity": scientific_fidelity,
            "model_diffs": sorted(model_diff["comparisons"]),
            "performance": product_performance,
        },
        "product_0_5": {
            "trial_kit_acceptance": trial_acceptance,
            "external_models": {
                "count": len(trial_models["models"]),
                "compatible": trial_models["compatible"],
                "cases": sorted(trial_models["models"]),
            },
            "venue_proof": {
                "passed": venue_proof["passed"],
                "venues": {name: item["passed"] for name, item in venue_proof["venues"].items()},
            },
            "human_trial": human_trial,
        },
        "source_tree_digest": snapshot["source_tree_digest"],
        "source_snapshot_manifest_sha256": sha256(root / "source/snapshot.json"),
        "matrix_digest": sha256(root / "source/acceptance-matrix-0.2.3.json"),
        "consumed_input_manifest_sha256": sha256(root / "source/consumed-inputs.json"),
        "checksum_strategy": load(root / "seal-policy.json"),
        "post_seal_verifier": "external sibling attestation; executed after copy and after atomic local promotion",
        "failures": failures,
        "passed": not failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "run_id": args.run_id,
                "runner_result": report["runner_result"],
                "pre_seal_audit": report["pre_seal_audit"],
                "blockers": matrix["release_blocker_checks"],
                "failures": failures,
            },
            sort_keys=True,
        )
    )
    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
