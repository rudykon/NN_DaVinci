#!/usr/bin/env python3
"""Gate stable browser scenarios independently of assertion count."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


EXPECTED = {
    "load-console-security", "node-drag-coordinates", "connect-route-constraint",
    "align-distribute-lock-hide-geometry", "undo-redo-state", "group-collapse-focus",
    "annotation-presentation-persistence", "project-round-trip", "seven-format-downloads", "dom-xss",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    ids = [item["id"] for item in report["scenarios"]]
    failures = []
    if set(ids) != EXPECTED or len(ids) != len(set(ids)):
        failures.append("stable scenario ID set drifted or contains duplicates")
    if any(item["status"] != "passed" or item["console_errors"] for item in report["scenarios"]):
        failures.append("a scenario failed or emitted console errors")
    if report["counts"]["skipped"] or report["counts"]["passed"] != len(EXPECTED):
        failures.append("required browser scenario skipped or not passed")
    required_behaviors = {behavior for item in report["scenarios"] for behavior in item["behaviors"]}
    if set(report["behavior_map"]) != required_behaviors:
        failures.append("behavior map does not cover the executed scenarios")
    summary = {
        "stable_scenario_ids": sorted(ids), "behavior_map": report["behavior_map"],
        "passed": report["counts"]["passed"], "failed": report["counts"]["failed"],
        "skipped": report["counts"]["skipped"], "assertions_diagnostic": report["counts"]["assertions"],
        "failures": failures,
    }
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if failures:
        raise SystemExit("\n".join(failures))
    print(json.dumps({"e2e_scenarios": len(ids), "passed": len(ids), "skipped": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
