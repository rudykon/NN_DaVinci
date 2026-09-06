#!/usr/bin/env python3
"""Create the external 0.5.2 Beta decision after both sealed replays pass."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verification", type=Path, required=True)
    parser.add_argument("--copy-attestation", type=Path, required=True)
    parser.add_argument("--final-attestation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verification = load(args.verification)
    copy = load(args.copy_attestation)
    final = load(args.final_attestation)
    failures = []
    if verification.get("runner_result") != "PASS" or verification.get("pre_seal_audit") != "PASS":
        failures.append("runner or pre-seal audit failed")
    if "release_audit" in verification:
        failures.append("pre-seal verification.json may not self-claim release_audit")
    for label, report in (("copy", copy), ("final", final)):
        replay = report.get("raw_blocker_replay", {})
        predicates = report.get("matrix_predicate_replay", {})
        if (
            report.get("passed") is not True
            or replay.get("independent_blockers") != 34
            or replay.get("passed") != 34
            or replay.get("failed") != 0
            or replay.get("skipped") != 0
            or replay.get("not_run") != 0
            or predicates.get("executed") != 34
            or predicates.get("passed") != 34
            or predicates.get("failed") != 0
        ):
            failures.append(f"{label} post-seal replay is not 34/34 clean")
    if copy.get("run_id") != final.get("run_id") or copy.get("run_id") != verification.get("run_id"):
        failures.append("run IDs differ across pre-seal/copy/final evidence")
    report = {
        "schema_version": "0.5.2-release-decision-1",
        "release": "0.5.2 Beta — Responsive Workspace & Pilot UX Hotfix",
        "run_id": verification.get("run_id"),
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "runner_result": verification.get("runner_result"),
        "pre_seal_audit": verification.get("pre_seal_audit"),
        "copy_attestation": {"path": args.copy_attestation.name, "sha256": sha256(args.copy_attestation), "passed": copy.get("passed")},
        "final_attestation": {"path": args.final_attestation.name, "sha256": sha256(args.final_attestation), "passed": final.get("passed")},
        "release_audit": "PASS" if not failures else "FAIL",
        "maturity": "beta",
        "human_trial_status": verification.get("product_0_5", {}).get("human_trial", {}).get("status"),
        "human_usability_claim": False,
        "failures": failures,
        "passed": not failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"run_id": report["run_id"], "release_audit": report["release_audit"], "failures": failures}, sort_keys=True))
    if failures:
        raise SystemExit("; ".join(failures))


if __name__ == "__main__":
    main()
