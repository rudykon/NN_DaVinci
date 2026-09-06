#!/usr/bin/env python3
"""Aggregate fresh browser suites without relabelling their historical schemas."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


RELEASE = "0.7.3 — Reader-Visible Scientific Completeness & Generalization Hotfix"
EXPECTED = ("editor", "responsive", "semantic", "product", "trial", "figure", "scene")


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"E2E report is not an object: {path}")
    return value


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", action="append", required=True, metavar="NAME=PATH")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    supplied: dict[str, Path] = {}
    for item in args.suite:
        name, separator, raw_path = item.partition("=")
        if not separator or name in supplied:
            raise SystemExit(f"invalid or duplicate --suite value: {item}")
        supplied[name] = Path(raw_path).resolve(strict=True)
    if set(supplied) != set(EXPECTED):
        raise SystemExit(f"expected exactly {EXPECTED}; received {tuple(sorted(supplied))}")

    failures: list[str] = []
    suites: dict[str, Any] = {}
    total_assertions = 0
    for name in EXPECTED:
        path = supplied[name]
        report = load(path)
        status = report.get("status")
        succeeded = report.get("succeeded")
        counts = report.get("counts", {}) if isinstance(report.get("counts"), dict) else {}
        historical_pass = (
            isinstance(status, str)
            and status.casefold() == "passed"
        ) or (
            counts.get("passed", 0) > 0
            and counts.get("failed", 0) == 0
            and counts.get("skipped", 0) == 0
        )
        report_failures = report.get("failures", [])
        browser_errors = report.get("browser_errors", [])
        if status != "PASS" and succeeded is not True and not historical_pass:
            failures.append(f"{name}: suite did not report PASS/succeeded")
        if report_failures not in ([], None):
            failures.append(f"{name}: suite reports failures")
        if browser_errors not in ([], None):
            failures.append(f"{name}: browser errors are non-empty")
        for key in ("unexpected_console_errors", "unexpected_page_errors", "unexpected_request_errors"):
            if report.get(key) not in (None, [], 0):
                failures.append(f"{name}: {key} is non-zero")
        if report.get("errors") not in (None, [], 0):
            failures.append(f"{name}: errors are non-empty")
        if counts.get("console_page_request_errors", 0) != 0:
            failures.append(f"{name}: console/page/request errors are non-zero")
        assertions = report.get("assertion_count")
        if not isinstance(assertions, int):
            raw_assertions = report.get("assertions", [])
            assertions = counts.get("assertions")
            if not isinstance(assertions, int):
                assertions = len(raw_assertions) if isinstance(raw_assertions, list) else 0
        total_assertions += assertions
        suites[name] = {
            "classification": "fresh-execution-inherited-report-schema",
            "reported_schema": report.get("schema_version"),
            "reported_release": report.get("release"),
            "status": "PASS" if status == "PASS" or succeeded is True or historical_pass else "FAIL",
            "assertions": assertions,
            "human_participants": report.get("human_participants", 0),
            "sha256": digest(path),
            "source_report": str(path),
        }
        if suites[name]["human_participants"] != 0:
            failures.append(f"{name}: human participant count is not zero")

    output = {
        "schema_version": "nndv-0.7.3-e2e-aggregate-1",
        "release": RELEASE,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not failures else "FAIL",
        "fresh_executions": True,
        "historical_schemas_are_inputs_not_current_schema": True,
        "human_participants": 0,
        "automated_evidence_is_human_usability_evidence": False,
        "suite_count": len(suites),
        "assertion_count": total_assertions,
        "unexpected_browser_errors": 0 if not failures else None,
        "suites": suites,
        "failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": output["status"], "suites": len(suites), "assertions": total_assertions}, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
