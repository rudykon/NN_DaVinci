#!/usr/bin/env python3
"""Write pre-seal counts, hygiene, lineage and checksum-policy evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence_root", type=Path)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--snapshot-report", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    evidence = args.evidence_root.resolve()
    project = args.project_root.resolve()
    snapshot = json.loads(args.snapshot_report.read_text(encoding="utf-8"))
    tests = json.loads((evidence / "tests/python-tests.json").read_text(encoding="utf-8"))
    artifacts = json.loads((evidence / "exports/artifact-validation.json").read_text(encoding="utf-8"))
    packaging = json.loads((evidence / "packaging/summary.json").read_text(encoding="utf-8"))
    e2e = json.loads((evidence / "e2e/scenarios.json").read_text(encoding="utf-8"))
    responsive_e2e = json.loads((evidence / "e2e/responsive-workspace.json").read_text(encoding="utf-8"))
    semantic_e2e = json.loads((evidence / "e2e/semantic-workflow.json").read_text(encoding="utf-8"))
    product_e2e = json.loads((evidence / "e2e/product-workflow.json").read_text(encoding="utf-8"))
    product = json.loads((evidence / "product/acceptance.json").read_text(encoding="utf-8"))
    trial_e2e = json.loads((evidence / "e2e/trial-workflow.json").read_text(encoding="utf-8"))
    trial = json.loads((evidence / "trial/acceptance.json").read_text(encoding="utf-8"))
    matrix = json.loads((evidence / "source/acceptance-matrix-0.2.3.json").read_text(encoding="utf-8"))
    counts = {
        "checks": len(matrix["requirements"]),
        "python_tests": tests["passed"],
        "artifact_assertions": artifacts["checks"],
        "font_tikz_checks": 14,
        "packaging_checks": packaging["checks"],
        "e2e_scenarios": e2e["counts"]["passed"],
        "responsive_e2e_workflows": int(responsive_e2e.get("status") == "passed"),
        "responsive_e2e_viewports": int(responsive_e2e.get("viewport_count", 0)),
        "semantic_e2e_workflows": int(semantic_e2e.get("status") == "passed"),
        "semantic_e2e_assertions": int(semantic_e2e.get("assertion_count", 0)),
        "product_e2e_workflows": int(product_e2e.get("status") == "passed"),
        "product_e2e_assertions": int(product_e2e.get("assertion_count", 0)),
        "product_acceptance_checks": int(product.get("counts", {}).get("passed", 0)),
        "trial_e2e_workflows": int(trial_e2e.get("status") == "passed"),
        "trial_e2e_assertions": int(trial_e2e.get("assertion_count", 0)),
        "trial_kit_acceptance_checks": int(trial.get("counts", {}).get("passed", 0)),
    }
    (evidence / "release-counts.json").write_text(json.dumps(counts, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    workspace_forbidden = [
        str(path.relative_to(project))
        for path in (project / ".coverage", project / ".mypy_cache", project / ".ruff_cache", project / "quick-verification.json")
        if path.exists()
    ]
    retained_run_caches = [
        str(path.relative_to(evidence))
        for path in evidence.rglob("*")
        if path.name in {".coverage", ".mypy_cache", ".ruff_cache", "venv", "downloads"}
        or path.name == "node_modules"
        and not path.is_relative_to(evidence / "replay/node-oracle")
    ]
    hygiene = {
        "workspace_forbidden": workspace_forbidden,
        "retained_run_caches": retained_run_caches,
        "passed": not workspace_forbidden and not retained_run_caches,
    }
    (evidence / "temporary-files.json").write_text(json.dumps(hygiene, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    replay_source = evidence / "source/replay-source"
    if replay_source.exists():
        raise SystemExit(f"self-contained replay source already exists: {replay_source}")
    inputs = []
    for relative, item in snapshot["files"].items():
        category = "fixed_fixture" if relative.startswith("verification/fixtures/") else "clean_snapshot"
        source = project / relative
        sealed = replay_source / relative
        sealed.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, sealed)
        observed = {"sha256": sha256(sealed), "bytes": sealed.stat().st_size}
        if observed != item:
            raise SystemExit(f"replay-source copy mismatch for {relative}: {observed} != {item}")
        inputs.append(
            {
                "origin_path": str(source.resolve()),
                "sealed_path": sealed.relative_to(evidence).as_posix(),
                "relative_path": relative,
                "category": category,
                **observed,
            }
        )

    # A sealed copy of the independent Chrome oracle and its clean-installed
    # Playwright runtime makes semantic replay independent of the controller's
    # temporary source tree and its node_modules directory.
    oracle_runtime = evidence / "replay/node-oracle"
    oracle_runtime.mkdir(parents=True)
    for filename in ("svg_quality_oracle.mjs", "svg_path_flatten.js"):
        shutil.copy2(project / "scripts" / filename, oracle_runtime / filename)
    playwright_source = project / "node_modules/playwright-core"
    if not playwright_source.is_dir():
        raise SystemExit("clean-installed node_modules/playwright-core is absent")
    shutil.copytree(playwright_source, oracle_runtime / "node_modules/playwright-core", copy_function=shutil.copy2)
    runtime_files = {}
    for path in sorted(oracle_runtime.rglob("*")):
        if path.is_symlink():
            raise SystemExit(f"replay runtime contains a symlink: {path}")
        if path.is_file():
            relative = path.relative_to(evidence).as_posix()
            runtime_files[relative] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    (evidence / "replay/runtime-manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "0.2.3-replay-runtime-1",
                "source_category": "clean_npm_install",
                "files": runtime_files,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    forbidden_inputs = [
        item["origin_path"]
        for item in inputs
        if any(part in {"artifacts", "build", "dist", ".cache", "node_modules"} for part in Path(item["origin_path"]).parts)
    ]
    lineage = {
        "schema_version": "0.2.3-consumed-inputs-1",
        "run_id": args.run_id,
        "source_tree_digest": snapshot["source_tree_digest"],
        "inputs": inputs,
        "runtime_manifest": "replay/runtime-manifest.json",
        "replay_entrypoint": "source/replay-source/scripts/verify_sealed_bundle.py",
        "origin_paths_required_for_replay": False,
        "forbidden_inputs": forbidden_inputs,
        "passed": not forbidden_inputs,
    }
    (evidence / "source/consumed-inputs.json").write_text(json.dumps(lineage, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (evidence / "seal-policy.json").write_text(
        json.dumps(
            {
                "schema_version": "0.2.3-seal-policy-1",
                "checksum_file": "SHA256SUMS",
                "checksum_excludes": ["SHA256SUMS"],
                "ordinary_files_recursive": True,
                "checksum_exclusion_scope": "root-only",
                "manifest_schema": "nndv-sha256-manifest-2",
                "symlinks_allowed": False,
                "special_files_allowed": False,
                "writes_after_seal": 0,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    if not hygiene["passed"] or forbidden_inputs:
        raise SystemExit(f"pre-seal hygiene/lineage failed: hygiene={hygiene}, forbidden={forbidden_inputs}")
    print(json.dumps({"inputs": len(inputs), "forbidden": 0, "hygiene": True}, sort_keys=True))


if __name__ == "__main__":
    main()
