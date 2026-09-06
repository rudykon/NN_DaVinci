#!/usr/bin/env python3
"""Inherited 0.5.1 Beta blocker for trial-kit readiness and honest human status."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from nn_davinci.trial import trial_event_schema
from nn_davinci.trial_models import EXTERNAL_MODEL_CASE_KEYS


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--external-models", type=Path, required=True)
    parser.add_argument("--venue-proof", type=Path, required=True)
    parser.add_argument("--trial-e2e", type=Path, required=True)
    parser.add_argument("--human-status", type=Path, required=True)
    parser.add_argument("--docs-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    external = _load(args.external_models)
    venues = _load(args.venue_proof)
    e2e = _load(args.trial_e2e)
    human = _load(args.human_status)
    failures = []
    required_docs = ("TRIAL_PROTOCOL.md", "PARTICIPANT_GUIDE.md", "CONSENT.md", "TASKS.md", "HUMAN_TRIAL_REPORT.md", "trial-event.schema.json")
    for name in required_docs:
        path = args.docs_root / name
        if not path.is_file() or path.stat().st_size < 200:
            failures.append(f"trial document missing or empty: {name}")
    schema_path = args.docs_root / "trial-event.schema.json"
    if schema_path.is_file() and _load(schema_path) != trial_event_schema():
        failures.append("landed trial schema differs from runtime privacy contract")
    if external.get("passed") is not True or set(external.get("models", {})) != set(EXTERNAL_MODEL_CASE_KEYS):
        failures.append("six-case external-model compatibility report failed")
    if not all(item.get("passed") and item.get("paper", {}).get("minimum_font_pt", 0) >= 7 for item in external.get("models", {}).values()):
        failures.append("an external case lacks a paper-ready >=7 pt editable workflow")
    if venues.get("passed") is not True or set(venues.get("venues", {})) != {"neurips2026", "icml2026", "ieee"}:
        failures.append("NeurIPS/ICML/IEEE PDF+TikZ venue proof failed")
    if e2e.get("status") != "passed" or e2e.get("human_participants") != 0 or e2e.get("human_usability_claim") is not False:
        failures.append("trial Chrome E2E failed or misrepresented automation as human evidence")
    if set(e2e.get("cases", {})) != set(EXTERNAL_MODEL_CASE_KEYS):
        failures.append("trial Chrome E2E did not cover all six Web cases")
    assertions = set(e2e.get("assertions", []))
    recovery_assertions = {
        message
        for key in EXTERNAL_MODEL_CASE_KEYS
        for message in (
            f"{key} records the deliberate node and edge edits required by T4",
            f"{key} refresh preserves exact Panel geometry, locks and routes",
            f"{key} saved project preserves exact Composer state",
        )
    }
    recovery_assertions.add("all six automated task paths retain distinct node and edge edit counts")
    recovery_ok = e2e.get("assertion_count", 0) >= 65 and recovery_assertions <= assertions
    if not recovery_ok:
        failures.append(
            "trial Chrome E2E lacks the 0.5.1 six-case Composer/edit-count recovery assertions"
        )
    if human.get("participants") != 0 or human.get("human_study_complete") is not False or human.get("status") != "awaiting_participants":
        failures.append("human trial status must honestly remain awaiting participants")
    if any(value is not None for value in human.get("human_results", {}).values()):
        failures.append("missing human observations were populated with non-human results")
    checks = {
        "local_trial_privacy_schema": not any("schema" in item for item in failures),
        "six_external_web_workflows": (
            external.get("passed") is True
            and set(e2e.get("cases", {})) == set(EXTERNAL_MODEL_CASE_KEYS)
            and recovery_ok
        ),
        "venue_pdf_tikz_proof": venues.get("passed") is True,
        "human_status_is_honest": human.get("participants") == 0 and human.get("human_study_complete") is False,
        "trial_documents_complete": all((args.docs_root / name).is_file() for name in required_docs),
    }
    report = {
        "schema_version": "0.5.1-researcher-trial-kit-acceptance-1",
        "release": "0.5.1 Beta",
        "checks": checks,
        "counts": {"total": len(checks), "passed": sum(checks.values()), "failed": len(checks) - sum(checks.values())},
        "human_trial": {
            "status": human.get("status"),
            "participants": human.get("participants"),
            "conclusions_authorized": False,
        },
        "failures": failures,
        "passed": not failures and all(checks.values()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "checks": report["counts"]}, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
