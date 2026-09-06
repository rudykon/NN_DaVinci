#!/usr/bin/env python3
"""Validate every positive/negative manual oracle truth fixture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def count(report: dict, key: str) -> float:
    value = report[key]
    return float(len(value) if isinstance(value, list) else value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).parents[1]
    expected = json.loads((root / "verification/fixtures/svg-oracle-expectations.json").read_text(encoding="utf-8"))["fixtures"]
    reports = {Path(item["file"]).name: item for item in json.loads(args.report.read_text(encoding="utf-8"))["reports"]}
    failures: list[str] = []
    for name, assertions in expected.items():
        if name not in reports:
            failures.append(f"missing report: {name}")
            continue
        for expression, threshold in assertions.items():
            if expression.endswith("_min"):
                key, valid = expression[:-4], count(reports[name], expression[:-4]) >= float(threshold)
            elif expression.endswith("_max"):
                key, valid = expression[:-4], count(reports[name], expression[:-4]) <= float(threshold)
            else:
                key, valid = expression, count(reports[name], expression) == float(threshold)
            if not valid:
                failures.append(f"{name}: {key}={reports[name].get(key)!r} violates {expression}={threshold}")
    cases = []
    for name, assertions in expected.items():
        expected_pass = bool(assertions["passed"])
        actual_pass = bool(reports.get(name, {}).get("passed", False))
        cases.append({
            "fixture": name,
            "truth_id": reports.get(name, {}).get("truth_id", Path(name).stem),
            "expected_pass": expected_pass,
            "actual_pass": actual_pass,
        })
    output = {"oracle_fixtures": len(expected), "cases": cases, "failures": failures, "passed": not failures}
    if args.output:
        args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if failures:
        raise SystemExit("\n".join(failures))
    print(json.dumps({"oracle_fixtures": len(expected), "passed": len(expected), "failed": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
