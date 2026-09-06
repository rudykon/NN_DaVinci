#!/usr/bin/env python3
"""Run unittest discovery and emit a machine-readable acceptance summary."""

from __future__ import annotations

import argparse
import json
import sys
import time
import unittest
from pathlib import Path


def _flatten(suite: unittest.TestSuite) -> list[unittest.TestCase]:
    pending: list[unittest.TestSuite | unittest.TestCase] = [suite]
    result: list[unittest.TestCase] = []
    while pending:
        item = pending.pop(0)
        if isinstance(item, unittest.TestSuite):
            pending[0:0] = list(item)
        else:
            result.append(item)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path)
    parser.add_argument("--test-ids", type=Path)
    parser.add_argument(
        "--baseline-ids",
        type=Path,
        default=Path(__file__).parents[1] / "verification" / "fixtures" / "python-test-ids-0.2.0.txt",
    )
    parser.add_argument("--start-dir", default="tests")
    args = parser.parse_args()
    started = time.perf_counter()
    suite = unittest.defaultTestLoader.discover(args.start_dir)
    test_ids = [case.id() for case in _flatten(suite)]
    if args.test_ids:
        args.test_ids.parent.mkdir(parents=True, exist_ok=True)
        args.test_ids.write_text("\n".join(test_ids) + "\n", encoding="utf-8")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    product_0_4_modules = (
        "test_composer.",
        "test_paper_production.",
        "test_plugins_v2.",
        "test_real_models.",
    )
    product_0_5_modules = ("test_trial_mode.",)
    inherited_0_3_ids = [test_id for test_id in test_ids if not test_id.startswith(product_0_4_modules + product_0_5_modules)]
    product_0_4_ids = [test_id for test_id in test_ids if test_id.startswith(product_0_4_modules)]
    product_0_5_ids = [test_id for test_id in test_ids if test_id.startswith(product_0_5_modules)]
    baseline_ids = (
        [line for line in args.baseline_ids.read_text(encoding="utf-8").splitlines() if line]
        if args.baseline_ids.is_file()
        else []
    )
    missing_baseline_ids = sorted(set(baseline_ids) - set(test_ids))
    passed = result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped)
    summary = {
        "collected": len(test_ids),
        "passed": passed,
        "tests": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "deselected": len(missing_baseline_ids),
        "baseline_count": len(baseline_ids),
        "baseline_ids_missing": missing_baseline_ids,
        "inherited_0_3_tests": len(inherited_0_3_ids),
        "product_0_4_tests": len(product_0_4_ids),
        "product_0_5_tests": len(product_0_5_ids),
        "duration_seconds": round(time.perf_counter() - started, 3),
        "successful": result.wasSuccessful() and not missing_baseline_ids,
    }
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"NNDV_TEST_SUMMARY={json.dumps(summary, sort_keys=True)}")
    return 0 if summary["successful"] else 1


if __name__ == "__main__":
    sys.exit(main())
