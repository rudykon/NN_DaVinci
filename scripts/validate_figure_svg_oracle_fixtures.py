#!/usr/bin/env python3
"""Validate every final-Figure-SVG oracle fixture classification and metric."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def value_at(document: Any, dotted_path: str) -> Any:
    value = document
    for component in dotted_path.split("."):
        if isinstance(value, list):
            value = value[int(component)]
        elif isinstance(value, dict) and component in value:
            value = value[component]
        else:
            raise KeyError(dotted_path)
    return value


def assertion_passes(actual: Any, operation: str, expected: Any) -> bool:
    if operation == "eq":
        return actual == expected
    if operation == "ne":
        return actual != expected
    if operation == "ge":
        return float(actual) >= float(expected)
    if operation == "gt":
        return float(actual) > float(expected)
    if operation == "le":
        return float(actual) <= float(expected)
    if operation == "lt":
        return float(actual) < float(expected)
    if operation == "between":
        low, high = expected
        return float(low) <= float(actual) <= float(high)
    if operation == "contains":
        return expected in actual
    raise ValueError(f"unsupported assertion operation {operation!r}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--expectations", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    expectation_path = args.expectations or (
        project / "verification/fixtures/figure-svg-oracle-expectations.json"
    )
    expected = json.loads(expectation_path.read_text(encoding="utf-8"))
    report = json.loads(args.report.read_text(encoding="utf-8"))
    failures: list[str] = []

    if expected.get("schema_version") != "nndv-figure-svg-oracle-expectations-1":
        failures.append("expectation schema version is unsupported")
    if report.get("schema_version") != "nndv-figure-svg-oracle-report-1":
        failures.append("oracle report schema version is unsupported")
    if report.get("oracle") != expected.get("oracle"):
        failures.append(
            f"oracle identity {report.get('oracle')!r} != {expected.get('oracle')!r}"
        )
    contract = report.get("measurement_contract", {})
    for key, required in {
        "final_dom_only": True,
        "metadata_trusted": False,
        "python_proof_imported": False,
        "data_scale_claims_trusted": False,
        "stroke_under_full_ctm": True,
    }.items():
        if contract.get(key) is not required:
            failures.append(f"measurement contract {key}={contract.get(key)!r}, expected {required!r}")
    if contract.get("path_flattener") != "svg_path_flatten.js":
        failures.append("oracle did not declare the independent SVG path flattener")

    reports: dict[str, dict[str, Any]] = {}
    for item in report.get("reports", []):
        name = Path(item.get("file", "")).name
        if not name:
            failures.append("oracle report entry lacks a file name")
        elif name in reports:
            failures.append(f"duplicate oracle report: {name}")
        else:
            reports[name] = item
    fixture_expectations = expected.get("fixtures", {})
    missing = sorted(set(fixture_expectations) - set(reports))
    unexpected = sorted(set(reports) - set(fixture_expectations))
    failures.extend(f"missing oracle fixture report: {name}" for name in missing)
    failures.extend(f"unexpected oracle fixture report: {name}" for name in unexpected)

    cases: list[dict[str, Any]] = []
    assertion_count = 0
    covered: set[str] = set()
    for name, truth in fixture_expectations.items():
        covered.update(truth.get("covers", []))
        item = reports.get(name)
        case_failures: list[str] = []
        if item is None:
            cases.append({"fixture": name, "passed": False, "failures": ["missing report"]})
            continue
        actual_pass = bool(item.get("passed"))
        expected_pass = bool(truth["expected_pass"])
        if actual_pass is not expected_pass:
            case_failures.append(f"passed={actual_pass!r}, expected {expected_pass!r}")
        actual_counts = item.get("issue_counts", {})
        expected_counts = truth.get("expected_issue_counts", {})
        if actual_counts != expected_counts:
            case_failures.append(
                f"issue_counts={actual_counts!r}, expected exact {expected_counts!r}"
            )
        if item.get("source", {}).get("metadata_consulted") is not False:
            case_failures.append("fixture verdict consulted SVG metadata")
        if item.get("source", {}).get("loaded_from_persisted_file") is not True:
            case_failures.append("fixture was not opened from a persisted file URL")
        for assertion in truth.get("assertions", []):
            assertion_count += 1
            dotted_path = assertion["path"]
            try:
                actual = value_at(item, dotted_path)
                valid = assertion_passes(actual, assertion["op"], assertion["value"])
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                case_failures.append(f"{dotted_path}: assertion could not execute: {exc}")
                continue
            if not valid:
                case_failures.append(
                    f"{dotted_path}={actual!r} violates {assertion['op']} {assertion['value']!r}"
                )
        failures.extend(f"{name}: {message}" for message in case_failures)
        cases.append(
            {
                "fixture": name,
                "expected_pass": expected_pass,
                "actual_pass": actual_pass,
                "issue_counts": actual_counts,
                "assertions": len(truth.get("assertions", [])),
                "passed": not case_failures,
                "failures": case_failures,
            }
        )

    required_coverage = set(expected.get("required_coverage", []))
    missing_coverage = sorted(required_coverage - covered)
    unexpected_coverage = sorted(covered - required_coverage)
    failures.extend(f"missing required fixture coverage: {name}" for name in missing_coverage)
    failures.extend(f"undeclared fixture coverage: {name}" for name in unexpected_coverage)

    positive = sum(bool(item["expected_pass"]) for item in fixture_expectations.values())
    negative = len(fixture_expectations) - positive
    result = {
        "schema_version": "nndv-figure-svg-oracle-fixture-validation-1",
        "oracle": expected.get("oracle"),
        "fixture_count": len(fixture_expectations),
        "positive_count": positive,
        "negative_count": negative,
        "classification_count": len(cases),
        "assertion_count": assertion_count,
        "coverage_count": len(required_coverage),
        "cases": cases,
        "failures": failures,
        "passed": not failures,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "fixtures": result["fixture_count"],
                "positive": positive,
                "negative": negative,
                "classifications": result["classification_count"],
                "assertions": assertion_count,
                "coverage": len(required_coverage),
                "failures": len(failures),
                "passed": not failures,
            },
            sort_keys=True,
        )
    )
    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
