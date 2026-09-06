#!/usr/bin/env python3
"""Verify the externally supplied 0.2.2 trust anchor before reading values."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trust-anchor", type=Path, required=True)
    parser.add_argument("--expected-anchor-sha256", required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    actual_anchor = digest(args.trust_anchor)
    anchor_mode = f"{stat.S_IMODE(args.trust_anchor.stat().st_mode):04o}"
    if actual_anchor != args.expected_anchor_sha256 or anchor_mode != "0444":
        raise SystemExit(
            f"trust anchor mismatch: expected sha={args.expected_anchor_sha256} mode=0444; "
            f"observed sha={actual_anchor} mode={anchor_mode}"
        )
    anchor = json.loads(args.trust_anchor.read_text(encoding="utf-8"))
    baseline = anchor["legacy_test_baseline"]
    baseline_path = (args.project_root / baseline["path"]).resolve()
    baseline_observed = {
        "path": baseline["path"],
        "sha256": digest(baseline_path),
        "mode_octal": f"{stat.S_IMODE(baseline_path.stat().st_mode):04o}",
        "test_id_count": len(baseline_path.read_text(encoding="utf-8").splitlines()),
    }
    expected_baseline = {key: baseline[key] for key in ("sha256", "mode_octal", "test_id_count")}
    legacy_matrix = anchor["legacy_acceptance_matrix"]
    legacy_path = (args.project_root / legacy_matrix["path"]).resolve()
    legacy_observed = {
        "path": legacy_matrix["path"],
        "sha256": digest(legacy_path),
        "requirement_ids": [
            item["requirement_id"]
            for item in json.loads(legacy_path.read_text(encoding="utf-8"))["requirements"]
        ],
    }
    failures = []
    if {key: baseline_observed[key] for key in expected_baseline} != expected_baseline:
        failures.append("frozen test-ID content/mode/count differs from external anchor")
    if legacy_observed["sha256"] != legacy_matrix["sha256_before_migration"]:
        failures.append("legacy 0.2.1 matrix digest differs from external anchor")
    if legacy_observed["requirement_ids"] != legacy_matrix["requirement_ids"]:
        failures.append("legacy 0.2.1 requirement ID sequence differs from external anchor")
    report = {
        "schema_version": "0.2.2-trust-check-1",
        "expected_anchor_sha256": args.expected_anchor_sha256,
        "actual_anchor_sha256": actual_anchor,
        "anchor_mode_octal": anchor_mode,
        "baseline": baseline_observed,
        "baseline_expected": expected_baseline,
        "legacy_matrix": legacy_observed,
        "failures": failures,
        "passed": not failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"passed": not failures, "anchor_sha256": actual_anchor, "baseline_ids": baseline_observed["test_id_count"]}, sort_keys=True))
    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
