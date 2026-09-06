#!/usr/bin/env python3
"""Create and gate old-core, expanded-core, and all-package coverage."""

from __future__ import annotations

import argparse
import json
from fractions import Fraction
from pathlib import Path

from nn_davinci.verification import format_coverage, meets_coverage_thresholds, summarize_coverage_totals


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--expanded-core", type=Path, required=True)
    parser.add_argument("--all-package", type=Path, required=True)
    parser.add_argument("--tests", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).parents[1]
    manifest = json.loads((root / "verification/core-coverage-manifest.json").read_text(encoding="utf-8"))
    expanded_manifest = json.loads((root / "verification/expanded-core-coverage-manifest.json").read_text(encoding="utf-8"))
    historical_all = json.loads((root / "verification/fixtures/all-package-denominators-0.2.1-diagnostic.json").read_text(encoding="utf-8"))
    core_raw = json.loads(args.core.read_text(encoding="utf-8"))
    expanded_raw = json.loads(args.expanded_core.read_text(encoding="utf-8"))
    all_raw = json.loads(args.all_package.read_text(encoding="utf-8"))
    tests = json.loads(args.tests.read_text(encoding="utf-8"))
    core_files = sorted(core_raw["files"])
    if core_files != sorted(manifest["core_files"]):
        raise SystemExit(f"core coverage file set drift: {core_files!r}")
    expanded_files = sorted(expanded_raw["files"])
    if expanded_files != sorted(expanded_manifest["core_files"]):
        raise SystemExit(f"expanded-core coverage file set drift: {expanded_files!r}")
    if expanded_manifest["coverage_exclusions"] or manifest["coverage_exclusions"]:
        raise SystemExit("coverage exclusions changed; 0.2.2 requires both manifests to remain empty")
    historical_files = historical_all["denominators_by_file"]
    historical_statement_total = sum(item["statements"] for item in historical_files.values())
    historical_branch_total = sum(item["branches"] for item in historical_files.values())
    if historical_all.get("authoritative_for_pass") is not False:
        raise SystemExit("historical all-package denominator inventory must remain diagnostic-only")
    if (historical_statement_total, historical_branch_total) != (4716, 1690):
        raise SystemExit("historical all-package denominator inventory does not match the immutable 0.2.1 totals")
    core = summarize_coverage_totals(core_raw["totals"])
    expanded_core = summarize_coverage_totals(expanded_raw["totals"])
    all_package = summarize_coverage_totals(all_raw["totals"])
    thresholds = manifest["thresholds"]
    old_core_passed = core.line.fraction >= Fraction(1893, 2076) and core.branch.fraction >= Fraction(648, 778)
    expanded_core_passed = meets_coverage_thresholds(expanded_core, minimum_line=Fraction(177, 200), minimum_branch=Fraction(4, 5))
    all_passed = all_package.line.fraction >= Fraction(3926, 4716) and all_package.branch.fraction >= Fraction(1264, 1690)
    legacy_baseline = manifest["baseline_denominators_by_file"]
    legacy_denominator_diff = {}
    for file_name in manifest["core_files"]:
        current = core_raw["files"][file_name]["summary"]
        old = legacy_baseline[file_name]
        delta = {"statements": int(current["num_statements"]) - old["statements"], "branches": int(current["num_branches"]) - old["branches"]}
        if delta != {"statements": 0, "branches": 0}:
            legacy_denominator_diff[file_name] = {
                "baseline": old,
                "current": {"statements": current["num_statements"], "branches": current["num_branches"]},
                "delta": delta,
            }
    core_denominator_diff = {}
    for file_name in manifest["core_files"]:
        if file_name not in historical_files:
            raise SystemExit(f"0.2.1 all-package denominator inventory is missing old-core file {file_name!r}")
        current = core_raw["files"][file_name]["summary"]
        old = historical_files[file_name]
        delta = {
            "statements": int(current["num_statements"]) - old["statements"],
            "branches": int(current["num_branches"]) - old["branches"],
        }
        if any(delta.values()):
            core_denominator_diff[file_name] = {
                "baseline_release": "0.2.1",
                "baseline": old,
                "current": {
                    "statements": int(current["num_statements"]),
                    "branches": int(current["num_branches"]),
                },
                "delta": delta,
            }
    current_all_files = {
        file_name: {
            "statements": int(details["summary"]["num_statements"]),
            "branches": int(details["summary"]["num_branches"]),
        }
        for file_name, details in all_raw["files"].items()
    }
    all_denominator_diff = {}
    for file_name in sorted(set(historical_files) | set(current_all_files)):
        old = historical_files.get(file_name)
        current = current_all_files.get(file_name)
        delta = {
            "statements": (current or {"statements": 0})["statements"] - (old or {"statements": 0})["statements"],
            "branches": (current or {"branches": 0})["branches"] - (old or {"branches": 0})["branches"],
        }
        status = "added" if old is None else "removed" if current is None else "changed" if any(delta.values()) else "unchanged"
        all_denominator_diff[file_name] = {
            "baseline_0_2_1": old,
            "current_0_2_2": current,
            "delta": delta,
            "status": status,
        }
    report = {
        "old_core": core.to_dict(),
        "core": core.to_dict(),
        "expanded_core": expanded_core.to_dict(),
        "all_package": all_package.to_dict(),
        "thresholds": {
            **thresholds,
            "old_core_line_fraction": 1893 / 2076,
            "old_core_branch_fraction": 648 / 778,
            "expanded_core_line_fraction": 0.885,
            "expanded_core_branch_fraction": 0.8,
            "all_package_line_fraction": 3926 / 4716,
            "all_package_branch_fraction": 1264 / 1690,
        },
        "old_core_passed": old_core_passed,
        "core_passed": old_core_passed,
        "expanded_core_passed": expanded_core_passed,
        "all_package_passed": all_passed,
        "core_files": core_files,
        "expanded_core_files": expanded_files,
        "coverage_exclusions": manifest["coverage_exclusions"],
        "core_denominator_diff": core_denominator_diff,
        "legacy_0_2_0_core_denominator_diff": legacy_denominator_diff,
        "all_package_denominator_diff_by_file": all_denominator_diff,
        "all_package_total_denominator_diff": {
            "baseline_release": "0.2.1",
            "baseline": {"statements": historical_statement_total, "branches": historical_branch_total},
            "current": {"statements": all_package.line.total, "branches": all_package.branch.total},
            "delta": {
                "statements": all_package.line.total - historical_statement_total,
                "branches": all_package.branch.total - historical_branch_total,
            },
            "reason": "0.2.2 adds adversarial geometry, scale recovery, publication-role, and verification closure code; the all-package source selection is not reduced.",
            "diagnostic_inventory_authoritative_for_pass": historical_all["authoritative_for_pass"],
            "release_threshold_source": "docs/TRUST_ANCHOR_0.2.2.json",
        },
        "python_tests": tests,
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(format_coverage("core", core))
    print(format_coverage("expanded_core", expanded_core))
    print(format_coverage("all_package", all_package))
    if not old_core_passed:
        raise SystemExit("old-core coverage regressed below anchored 0.2.1 line/branch fractions")
    if not expanded_core_passed:
        raise SystemExit("expanded-core coverage gate failed: exact line >=88.5% and true branch >=80% are required")
    if not all_passed:
        raise SystemExit("all-package coverage regressed below anchored 0.2.1 line/branch fractions")


if __name__ == "__main__":
    main()
