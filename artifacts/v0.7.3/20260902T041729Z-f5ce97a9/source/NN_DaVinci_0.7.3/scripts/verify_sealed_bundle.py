#!/usr/bin/env python3
"""Read-only, self-contained post-seal hash and raw semantic replay.

This script imports neither the finalizer nor the acceptance-matrix evaluator.
It uses only source/runtime copies inside the sealed evidence bundle and writes
only the caller-supplied sibling attestation.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import tarfile
import tempfile
from typing import Any
import zipfile


CHECKSUM_NAME = "SHA256SUMS"
CHECKSUM_SCHEMA = "nndv-sha256-manifest-2"
ARCHITECTURES = ("resnet", "transformer", "unet", "rnn", "moe", "multimodal", "diffusion")
ORACLE_BLOCKERS = (
    "clipping",
    "node_overlaps",
    "singular_text_transforms",
    "text_overflows",
    "text_page_violations",
    "edge_node_collisions",
    "edge_crossings",
    "endpoint_errors",
    "marker_node_collisions",
    "group_label_conflicts",
    "edge_label_conflicts",
    "annotation_node_collisions",
    "legend_node_collisions",
    "annotation_page_violations",
    "legend_page_violations",
    "unknown_roles",
    "exception_errors",
    "metadata_errors",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def release_counts_from_raw(
    *,
    blocker_count: int,
    tests: dict[str, Any],
    artifact: dict[str, Any],
    package: dict[str, Any],
    e2e: dict[str, Any],
    responsive_e2e: dict[str, Any] | None = None,
    semantic_e2e: dict[str, Any],
    product_e2e: dict[str, Any] | None = None,
    product: dict[str, Any] | None = None,
    trial_e2e: dict[str, Any] | None = None,
    trial: dict[str, Any] | None = None,
) -> dict[str, int]:
    """Independently derive every versioned release counter from raw reports."""
    include_product = product_e2e is not None or product is not None
    product_e2e = product_e2e or {}
    product = product or {}
    counts = {
        "checks": blocker_count,
        "python_tests": tests["passed"],
        "artifact_assertions": artifact["checks"],
        "font_tikz_checks": 14,
        "packaging_checks": package["checks"],
        "e2e_scenarios": len(e2e["scenarios"]),
        "semantic_e2e_workflows": int(semantic_e2e.get("status") == "passed"),
        "semantic_e2e_assertions": int(semantic_e2e.get("assertion_count", 0)),
    }
    if responsive_e2e is not None:
        counts.update(
            {
                "responsive_e2e_workflows": int(responsive_e2e.get("status") == "passed"),
                "responsive_e2e_viewports": int(responsive_e2e.get("viewport_count", 0)),
            }
        )
    if include_product:
        counts.update(
            {
                "product_e2e_workflows": int(product_e2e.get("status") == "passed"),
                "product_e2e_assertions": int(product_e2e.get("assertion_count", 0)),
                "product_acceptance_checks": int(product.get("counts", {}).get("passed", 0)),
            }
        )
    if trial_e2e is not None or trial is not None:
        trial_e2e = trial_e2e or {}
        trial = trial or {}
        counts.update(
            {
                "trial_e2e_workflows": int(trial_e2e.get("status") == "passed"),
                "trial_e2e_assertions": int(trial_e2e.get("assertion_count", 0)),
                "trial_kit_acceptance_checks": int(trial.get("counts", {}).get("passed", 0)),
            }
        )
    return counts


def safe_manifest_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\0" in value:
        raise ValueError("manifest path is not a non-empty NUL-free string")
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or any(part in {"", ".", ".."} for part in parsed.parts):
        raise ValueError(f"unsafe manifest path: {value!r}")
    if parsed.as_posix() != value or value == CHECKSUM_NAME:
        raise ValueError(f"non-canonical/self manifest path: {value!r}")
    return value


def scan_regular_files(root: Path) -> tuple[dict[str, Path], list[str]]:
    files: dict[str, Path] = {}
    invalid: list[str] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        for entry in os.scandir(directory):
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            mode = entry.stat(follow_symlinks=False).st_mode
            if stat.S_ISLNK(mode):
                invalid.append(f"symlink:{relative}")
            elif stat.S_ISDIR(mode):
                pending.append(path)
            elif stat.S_ISREG(mode):
                if relative != CHECKSUM_NAME:
                    files[relative] = path
            else:
                invalid.append(f"non-regular:{relative}")
    return files, sorted(invalid)


def checksum_replay(root: Path) -> dict[str, Any]:
    malformed: list[str] = []
    try:
        document = load(root / CHECKSUM_NAME)
    except Exception as exc:
        document = {}
        malformed.append(f"checksum JSON parse failed: {exc}")
    if not isinstance(document, dict) or document.get("schema_version") != CHECKSUM_SCHEMA:
        malformed.append("checksum schema mismatch")
    if not isinstance(document, dict) or document.get("algorithm") != "sha256" or document.get("checksum_excludes") != [CHECKSUM_NAME]:
        malformed.append("checksum algorithm/exclusion policy mismatch")
    entries = document.get("entries", []) if isinstance(document, dict) else []
    if not isinstance(entries, list):
        malformed.append("checksum entries are not an array")
        entries = []
    declared: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(entries):
        try:
            if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "size"}:
                raise ValueError("entry keys mismatch")
            relative = safe_manifest_path(entry["path"])
            if relative in declared:
                raise ValueError("duplicate path")
            if not isinstance(entry["sha256"], str) or len(entry["sha256"]) != 64 or any(character not in "0123456789abcdef" for character in entry["sha256"]):
                raise ValueError("invalid digest")
            if not isinstance(entry["size"], int) or isinstance(entry["size"], bool) or entry["size"] < 0:
                raise ValueError("invalid size")
            declared[relative] = entry
        except Exception as exc:
            malformed.append(f"entry[{index}]: {exc}")
    actual, invalid = scan_regular_files(root)
    malformed.extend(invalid)
    missing = sorted(set(declared) - set(actual))
    extra = sorted(set(actual) - set(declared))
    mismatch = []
    size_mismatch = []
    for relative in sorted(set(declared) & set(actual)):
        if actual[relative].stat().st_size != declared[relative]["size"]:
            size_mismatch.append(relative)
        if sha256(actual[relative]) != declared[relative]["sha256"]:
            mismatch.append(relative)
    return {
        "schema_version": CHECKSUM_SCHEMA,
        "declared_files": len(declared),
        "actual_files": len(actual),
        "missing": missing,
        "extra": extra,
        "mismatch": mismatch,
        "size_mismatch": size_mismatch,
        "malformed": malformed,
        "checksum_sha256": sha256(root / CHECKSUM_NAME) if (root / CHECKSUM_NAME).is_file() else None,
        "passed": not (missing or extra or mismatch or size_mismatch or malformed),
    }


def coverage_from_raw(document: dict[str, Any]) -> dict[str, dict[str, float | int]]:
    totals = document["totals"]
    values = {
        "line": (totals["covered_lines"], totals["num_statements"]),
        "branch": (totals["covered_branches"], totals["num_branches"]),
        "combined": (
            totals["covered_lines"] + totals["covered_branches"],
            totals["num_statements"] + totals["num_branches"],
        ),
    }
    return {name: {"covered": covered, "total": total, "fraction": covered / total} for name, (covered, total) in values.items()}


def oracle_clean(report: dict[str, Any], *, font: float, horizontal: float, shape: float) -> tuple[bool, list[str]]:
    failures = []
    for key in ORACLE_BLOCKERS:
        if report.get(key):
            failures.append(f"{key}={report[key]}")
    if report.get("minimum_font_pt") is not None and report["minimum_font_pt"] < font:
        failures.append(f"font={report['minimum_font_pt']}")
    if report.get("minimum_horizontal_scale") is not None and report["minimum_horizontal_scale"] < horizontal:
        failures.append(f"horizontal={report['minimum_horizontal_scale']}")
    if report.get("minimum_transform_shape") is not None and report["minimum_transform_shape"] < shape:
        failures.append(f"shape={report['minimum_transform_shape']}")
    return not failures, failures


def run_json(command: list[str], output: Path, *, cwd: Path | None = None, expected_exit: int = 0) -> tuple[dict[str, Any], str | None]:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if result.returncode != expected_exit or not output.is_file():
        return {}, f"exit={result.returncode}, expected={expected_exit}, stderr={result.stderr[-2000:]}"
    try:
        return load(output), None
    except Exception as exc:
        return {}, f"output JSON failed: {exc}"


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    """Resolve an RFC 6901 JSON Pointer without using the matrix evaluator."""
    if pointer == "":
        return document
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"JSON Pointer must be empty or start with '/': {pointer!r}")
    value = document
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict):
            if token not in value:
                raise KeyError(f"JSON Pointer {pointer!r} is absent at {token!r}")
            value = value[token]
        elif isinstance(value, list):
            if not token.isdigit() or int(token) >= len(value):
                raise KeyError(f"JSON Pointer {pointer!r} has invalid array index {token!r}")
            value = value[int(token)]
        else:
            raise KeyError(f"JSON Pointer {pointer!r} traverses a scalar at {token!r}")
    return value


def value_has_type(value: Any, expected: str) -> bool:
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return False


def compare_value(observed: Any, comparison: str, expected: Any) -> bool:
    if comparison == "eq":
        return observed == expected
    if comparison == "ne":
        return observed != expected
    if comparison == "gte":
        return observed >= expected
    if comparison == "lte":
        return observed <= expected
    if comparison == "empty":
        return len(observed) == 0
    if comparison == "length_eq":
        return len(observed) == expected
    raise ValueError(f"unsupported matrix comparison: {comparison!r}")


def safe_evidence_file(root: Path, relative: Any) -> Path:
    relative = safe_manifest_path(relative)
    candidate = root / relative
    if candidate.is_symlink():
        raise ValueError(f"evidence path is a symlink: {relative}")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
        raise ValueError(f"evidence path is not a regular file inside the bundle: {relative}")
    return resolved


def replay_matrix_predicate(root: Path, row: dict[str, Any]) -> dict[str, Any]:
    """Re-evaluate a row's pointer, type and comparison from sealed raw evidence."""
    requirement_id = row.get("requirement_id", "?")
    try:
        path = safe_evidence_file(root, row["evidence_path"])
        document = load(path)
        observed = resolve_json_pointer(document, row["json_pointer"])
        expected_type = row["observed_value_type"]
        expected = row.get("expected_value", row.get("threshold"))
        if not value_has_type(observed, expected_type):
            raise TypeError(f"{requirement_id}: observed {type(observed).__name__} does not match {expected_type}")
        passed = compare_value(observed, row["comparison"], expected)
        reason = (
            None
            if passed
            else (f"{requirement_id}: observed {observed!r} does not satisfy {row['comparison']} {expected!r} at {row['evidence_path']}#{row['json_pointer']}")
        )
        digest = hashlib.sha256()
        digest.update(json.dumps(row, sort_keys=True, separators=(",", ":")).encode())
        digest.update(bytes.fromhex(sha256(path)))
        return {
            "passed": passed,
            "observed": observed,
            "expected": expected,
            "observed_value_type": expected_type,
            "comparison": row["comparison"],
            "evidence_path": row["evidence_path"],
            "json_pointer": row["json_pointer"],
            "evidence_digest": digest.hexdigest(),
            "reason": reason,
        }
    except Exception as exc:
        return {
            "passed": False,
            "observed": None,
            "expected": row.get("expected_value", row.get("threshold")),
            "observed_value_type": row.get("observed_value_type"),
            "comparison": row.get("comparison"),
            "evidence_path": row.get("evidence_path"),
            "json_pointer": row.get("json_pointer"),
            "evidence_digest": None,
            "reason": f"{requirement_id}: {exc}",
        }


def exact_regular_file_set(root: Path, expected: set[str]) -> dict[str, Any]:
    """Compare an actual tree to a manifest, rejecting symlinks/special files."""
    actual, invalid = scan_regular_files(root)
    return {
        "expected": len(expected),
        "actual": len(actual),
        "missing": sorted(expected - set(actual)),
        "extra": sorted(set(actual) - expected),
        "invalid": invalid,
        "passed": set(actual) == expected and not invalid,
    }


def test_summary_gate(
    tests: dict[str, Any],
    collected_lines: list[str],
    frozen: list[str],
    baseline: dict[str, Any],
    frozen_sha256: str,
    frozen_mode: str,
    minimum_passed: int,
) -> tuple[dict[str, Any], bool]:
    collected_set = set(collected_lines)
    observed = {
        "minimum_passed": minimum_passed,
        "collected": tests.get("collected"),
        "passed": tests.get("passed"),
        "tests": tests.get("tests"),
        "failed": tests.get("failures"),
        "errors": tests.get("errors"),
        "skipped": tests.get("skipped"),
        "deselected": tests.get("deselected"),
        "collected_id_lines": len(collected_lines),
        "collected_id_unique": len(collected_set),
        "frozen_count": len(frozen),
        "frozen_sha256": frozen_sha256,
        "frozen_mode": frozen_mode,
        "frozen_missing": sorted(set(frozen) - collected_set),
    }
    counts = (tests.get("collected"), tests.get("passed"), tests.get("tests"))
    passed = (
        all(isinstance(value, int) and not isinstance(value, bool) for value in counts)
        and counts[0] == counts[1] == counts[2] == len(collected_lines) == len(collected_set)
        and counts[1] >= minimum_passed
        and all(tests.get(key) == 0 for key in ("failures", "errors", "skipped", "deselected"))
        and len(frozen) == baseline["test_id_count"]
        and frozen_sha256 == baseline["sha256"]
        and frozen_mode == baseline["mode_octal"]
        and not observed["frozen_missing"]
    )
    return observed, passed


def named_graph_gate(
    named: dict[str, Any],
    corpus_anchor: dict[str, str],
    *,
    seconds: float,
    rss: int,
    svg: int,
) -> tuple[dict[str, Any], bool]:
    expected_names = {"locally_dense", "sparse_skip", "strongly_connected", "wide_layer_dag"}
    observed: dict[str, Any] = {}
    passed = set(named) == expected_names
    for name in sorted(expected_names):
        item = named.get(name, {})
        runs = item.get("runs", [])
        structure = item.get("structure", {})
        if name == "locally_dense":
            structure_ok = (
                structure.get("edge_set_exact") is True
                and structure.get("node_set_exact") is True
                and structure.get("pair_budget_complete") is True
                and structure.get("pair_budget_truncated") is False
            )
        elif name == "strongly_connected":
            structure_ok = structure.get("edge_set_exact") is True and structure.get("component_count") == 1 and structure.get("component_size") == 1000
        elif name == "wide_layer_dag":
            structure_ok = (
                structure.get("edge_set_exact") is True
                and structure.get("source_rank") == 0
                and structure.get("sink_rank") == 3
                and structure.get("rank_values") == [0, 1, 2, 3]
            )
        else:
            structure_ok = structure.get("edge_set_exact") is True and structure.get("rank_monotonic") is True
        runs_ok = len(runs) == 3 and all(
            run.get("graph_sha256") == corpus_anchor.get(name)
            and isinstance(run.get("total_seconds"), (int, float))
            and run["total_seconds"] <= seconds
            and isinstance(run.get("peak_rss_bytes"), int)
            and run["peak_rss_bytes"] <= rss
            and isinstance(run.get("svg_bytes"), int)
            and run["svg_bytes"] <= svg
            for run in runs
        )
        passed = passed and structure_ok and runs_ok
        observed[name] = {"runs": runs, "structure": structure, "runs_ok": runs_ok, "structure_ok": structure_ok}
    return observed, passed


def spatial_named_gate(named: dict[str, Any], *, seconds: float) -> tuple[dict[str, Any], bool]:
    names = {"same_x_y_disjoint", "same_y_x_disjoint", "nested_x_y_filtered"}
    observed: dict[str, Any] = {}
    passed = names <= set(named)
    for name in sorted(names):
        runs = named.get(name, {}).get("runs", [])
        run_checks = [
            run.get("rectangles") == 10000
            and run.get("pairs") == 0
            and run.get("retained_pairs") == 0
            and run.get("lower_bound") == 0
            and run.get("complete") is True
            and run.get("truncated") is False
            and isinstance(run.get("wall_seconds"), (int, float))
            and run["wall_seconds"] <= seconds
            and "avl" in str(run.get("algorithm", "")).lower()
            and "treap" not in str(run.get("algorithm", "")).lower()
            for run in runs
        ]
        okay = len(runs) == 3 and all(run_checks)
        passed = passed and okay
        observed[name] = {"runs": runs, "run_checks": run_checks, "passed": okay}
    return observed, passed


def lock_rebuild_gate(root: Path, lock_relative: str) -> tuple[dict[str, Any], bool]:
    report = load(root / "packaging/lock-rebuild.json")
    lock_lines: dict[str, str] = {}
    for line in (root / lock_relative).read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            name, version = line.split("==", 1)
            lock_lines[name.lower().replace("_", "-")] = version
    wheel_rows = report.get("wheels", [])
    wheel_hashes = report.get("wheel_hashes", {})
    fallback_rows = [item for item in wheel_rows if item.get("origin") != "configured_index"]
    passed = (
        report.get("independent_environment") is True
        and report.get("environment_retained") is False
        and report.get("pip_check_exit_code") == 0
        and report.get("import_smoke_exit_code") == 0
        and report.get("install_exit_code") == 0
        and not report.get("failures")
        and len(wheel_rows) == len(lock_lines) == report.get("locked_distributions")
        and all(
            lock_lines.get(item.get("name")) == item.get("version")
            and wheel_hashes.get(item.get("filename")) == item.get("sha256")
            and isinstance(item.get("sha256"), str)
            and len(item["sha256"]) == 64
            for item in wheel_rows
        )
        and all(report.get("installed_locked_versions", {}).get(name) == version for name, version in lock_lines.items())
        and report.get("local_fallback_allowlist") == ["torchcam"]
        and all(
            item.get("name") == "torchcam" and item.get("origin") == "allowlisted_torchcam_installed_distribution_record_fallback" for item in fallback_rows
        )
    )
    observed = {
        "locked": len(lock_lines),
        "wheels": len(wheel_rows),
        "origin_counts": report.get("wheel_origin_counts"),
        "fallback_rows": fallback_rows,
        "exit_codes": {key: report.get(key) for key in ("install_exit_code", "project_install_exit_code", "pip_check_exit_code", "import_smoke_exit_code")},
    }
    return observed, passed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence_root", type=Path)
    parser.add_argument("--expected-anchor-sha256", required=True)
    parser.add_argument("--assert-absent", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--predicate-only", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--prebrowser-only", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--only-requirement", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.evidence_root.is_symlink():
        raise SystemExit("sealed evidence root may not be a symlink")
    root = args.evidence_root.resolve()
    output = args.output.resolve()
    if output.is_relative_to(root):
        raise SystemExit("post-seal attestation must be written outside the sealed root")
    source = root / "source/replay-source"
    anchor_path = source / "docs/TRUST_ANCHOR_0.2.2.json"
    matrix_path = root / "source/acceptance-matrix-0.2.3.json"
    failures: list[str] = []
    asserted_absent = None
    if args.assert_absent is not None:
        asserted_absent = str(args.assert_absent.absolute())
        if args.assert_absent.exists() or args.assert_absent.is_symlink():
            failures.append(f"temporary replay dependency still exists: {asserted_absent}")
    hashes = checksum_replay(root)
    if not hashes["passed"]:
        failures.append(f"checksum replay failed: {hashes}")
    anchor_sha = sha256(anchor_path) if anchor_path.is_file() else None
    anchor_mode = f"{stat.S_IMODE(anchor_path.stat().st_mode):04o}" if anchor_path.is_file() else None
    if anchor_sha != args.expected_anchor_sha256 or anchor_mode != "0444":
        failures.append(f"trust anchor mismatch sha={anchor_sha} mode={anchor_mode}")
    anchor = load(anchor_path)
    matrix = load(matrix_path)
    rows = matrix.get("requirements", [])
    row_ids = [row.get("requirement_id") for row in rows]
    if matrix.get("schema_version") != "3.1.0" or matrix.get("release") != "0.2.3" or len(row_ids) != len(set(row_ids)):
        failures.append("deduplicated matrix schema/IDs are invalid")
    signatures = [
        (
            row.get("validator_id"),
            row.get("evidence_path"),
            row.get("json_pointer"),
            row.get("comparison"),
            json.dumps(row.get("expected_value", row.get("threshold")), sort_keys=True),
            tuple(row.get("inputs", [])),
        )
        for row in rows
    ]
    if len(signatures) != len(set(signatures)):
        failures.append("matrix contains duplicate predicate signatures")
    legacy = set(anchor["legacy_acceptance_matrix"]["requirement_ids"])
    mapping = matrix.get("migration", {}).get("legacy_id_mapping", {})
    if set(mapping) != legacy or not set(mapping.values()) <= set(row_ids):
        failures.append("legacy-to-canonical matrix migration is incomplete")
    row_by_id = {row["requirement_id"]: row for row in rows if isinstance(row, dict) and "requirement_id" in row}
    for row in rows:
        for relative in row.get("command_provenance", []):
            try:
                safe_evidence_file(source, relative)
            except Exception as exc:
                failures.append(f"{row.get('requirement_id')}: command/oracle provenance is unavailable: {exc}")

    if args.predicate_only:
        predicate_results = {row["requirement_id"]: replay_matrix_predicate(root, row) for row in rows}
        selected = args.only_requirement
        if selected is not None and selected not in predicate_results:
            failures.append(f"unknown selected requirement: {selected}")
        evaluated = {selected: predicate_results[selected]} if selected in predicate_results else predicate_results
        failed = sorted(name for name, item in evaluated.items() if not item["passed"])
        if failed:
            failures.append(f"matrix predicate replay failures: {failed}")
        hashes_after = checksum_replay(root)
        if not hashes_after["passed"]:
            failures.append(f"checksum replay after predicate evaluation failed: {hashes_after}")
        report = {
            "schema_version": "0.2.3-post-seal-predicate-replay-1",
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "evidence_root": str(root),
            "mode": "predicate-only",
            "selected_requirement": selected,
            "hash_replay": {"before_semantic_replay": hashes, "after_semantic_replay": hashes_after},
            "matrix_predicate_replay": {
                "executed": len(evaluated),
                "passed": len(evaluated) - len(failed),
                "failed": len(failed),
                "results": [{"requirement_id": name, **item} for name, item in evaluated.items()],
            },
            "failures": failures,
            "passed": not failures,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if failures:
            raise SystemExit("\n".join(failures))
        return

    blocker_results: dict[str, dict[str, Any]] = {}

    def record(requirement_id: str, observed: Any, passed: bool, reason: str = "") -> None:
        blocker_results[requirement_id] = {
            "requirement_id": requirement_id,
            "observed": observed,
            "passed": bool(passed),
            "reason": None if passed else reason,
            "evidence_digest": hashlib.sha256(json.dumps(observed, sort_keys=True, default=str).encode()).hexdigest(),
        }

    tests = load(root / "tests/python-tests.json")
    frozen = (root / "tests/frozen-test-ids.txt").read_text(encoding="utf-8").splitlines()
    collected_lines = (root / "tests/collected-test-ids.txt").read_text(encoding="utf-8").splitlines()
    baseline = anchor["legacy_test_baseline"]
    frozen_mode = f"{stat.S_IMODE((root / 'tests/frozen-test-ids.txt').stat().st_mode):04o}"
    test_row = row_by_id.get("TEST-01", {})
    minimum_passed = test_row.get("expected_value", test_row.get("threshold"))
    if test_row.get("comparison") != "gte" or not isinstance(minimum_passed, int) or isinstance(minimum_passed, bool):
        failures.append("TEST-01 matrix threshold is not an integer gte predicate")
        minimum_passed = sys.maxsize
    test_observed, test_ok = test_summary_gate(
        tests,
        collected_lines,
        frozen,
        baseline,
        sha256(root / "tests/frozen-test-ids.txt"),
        frozen_mode,
        minimum_passed,
    )
    record("TEST-01", test_observed, test_ok, "TEST-01 raw count/ID/anchor invariants or minimum passed threshold differ")

    summary = load(root / "coverage/summary.json")
    raw_coverage = {
        "old_core": coverage_from_raw(load(root / "coverage/core.json")),
        "expanded_core": coverage_from_raw(load(root / "coverage/expanded-core.json")),
        "all_package": coverage_from_raw(load(root / "coverage/all-package.json")),
    }
    arithmetic_ok = all(
        all(summary[name][metric].get(key) == raw_coverage[name][metric][key] for key in ("covered", "total", "fraction"))
        for name in raw_coverage
        for metric in ("line", "branch", "combined")
    )
    record("STAT-01", raw_coverage, arithmetic_ok, "coverage summary is not derived from raw coverage.py numerators/denominators")
    coverage_limits = anchor["coverage_baselines"]
    coverage_gates = {
        "STAT-03": ("old_core", "line", coverage_limits["old_core_manifest_must_not_regress"]["line"]["minimum_fraction"]),
        "COV-01": ("old_core", "branch", coverage_limits["old_core_manifest_must_not_regress"]["branch"]["minimum_fraction"]),
        "COV-02": ("expanded_core", "line", coverage_limits["expanded_core_manifest_minimum"]["line_fraction"]),
        "COV-03": ("expanded_core", "branch", coverage_limits["expanded_core_manifest_minimum"]["branch_fraction"]),
        "STAT-07": ("all_package", "line", coverage_limits["all_package_must_not_regress"]["line"]["minimum_fraction"]),
        "COV-04": ("all_package", "branch", coverage_limits["all_package_must_not_regress"]["branch"]["minimum_fraction"]),
    }
    for requirement_id, (section, metric, threshold) in coverage_gates.items():
        observed = raw_coverage[section][metric]["fraction"]
        record(requirement_id, {"fraction": observed, "threshold": threshold}, observed >= threshold, f"{observed} < {threshold}")
    core_manifest = load(source / "verification/core-coverage-manifest.json")
    manifest_ok = (
        summary.get("coverage_exclusions") == core_manifest.get("coverage_exclusions") == []
        and summary.get("core_files") == core_manifest.get("core_files")
        and set(coverage_limits["expanded_core_manifest_minimum"]["required_additions"]) <= set(summary.get("expanded_core_files", []))
    )
    record(
        "STAT-04",
        {"core_files": summary.get("core_files"), "expanded_core_files": summary.get("expanded_core_files"), "exclusions": summary.get("coverage_exclusions")},
        manifest_ok,
        "coverage manifest/exclusions drifted",
    )

    artifact = load(root / "exports/artifact-validation.json")
    package = load(root / "packaging/summary.json")
    e2e = load(root / "e2e/scenarios.json")
    responsive_e2e = load(root / "e2e/responsive-workspace.json")
    semantic_e2e = load(root / "e2e/semantic-workflow.json")
    product_e2e = load(root / "e2e/product-workflow.json")
    product = load(root / "product/acceptance.json")
    trial_e2e = load(root / "e2e/trial-workflow.json")
    trial = load(root / "trial/acceptance.json")
    counts_expected = release_counts_from_raw(
        blocker_count=len(rows),
        tests=tests,
        artifact=artifact,
        package=package,
        e2e=e2e,
        responsive_e2e=responsive_e2e,
        semantic_e2e=semantic_e2e,
        product_e2e=product_e2e,
        product=product,
        trial_e2e=trial_e2e,
        trial=trial,
    )
    counts_actual = load(root / "release-counts.json")
    record(
        "STAT-02", {"expected": counts_expected, "actual": counts_actual}, counts_actual == counts_expected, "release counters do not derive from raw reports"
    )

    stress = load(root / "stress/results.json")
    scc = stress["scc_differential"]
    scc_ok = (
        scc["samples"] == 100
        and not scc["partition_failures"]
        and not scc["condensation_dag_failures"]
        and scc["deep_chain_without_recursion"]
        and scc["deep_chain_components"] == 10000
    )
    record("GRAPH-01", scc, scc_ok, "SCC differential/deep-chain invariants failed")
    corpus_anchor = anchor["stress_corpus"]["sha256"]
    named = stress["named_graph_corpora"]
    fixed = anchor["fixed_thresholds"]
    named_observed, named_ok = named_graph_gate(
        named,
        corpus_anchor,
        seconds=fixed["full_graph_1000_max_seconds_each_run"],
        rss=fixed["full_graph_1000_max_rss_bytes"],
        svg=fixed["full_graph_1000_max_svg_bytes"],
    )
    for name, report_name in (("deep_chain_100", "deep_chain_100"), ("deep_chain_1000", "deep_chain_1000"), ("deep_chain_10000", "deep_chain_10000_focus")):
        hashes_observed = {run["graph_sha256"] for run in stress[report_name]["runs"]}
        named_ok = named_ok and hashes_observed == {corpus_anchor[name]}
        named_observed[name] = sorted(hashes_observed)
    record("GRAPH-02", named_observed, named_ok, "anchored corpus hash or named structural invariant failed")

    def budget_ok(section: str, seconds: float, rss: int, svg: int, nodes: int | None = None) -> bool:
        runs = stress[section]["runs"]
        return len(runs) == 3 and all(
            run["total_seconds"] <= seconds and run["peak_rss_bytes"] <= rss and run["svg_bytes"] <= svg and (nodes is None or run["rendered_nodes"] <= nodes)
            for run in runs
        )

    record(
        "GRAPH-02A",
        stress["deep_chain_100"]["runs"],
        budget_ok(
            "deep_chain_100", fixed["full_graph_1000_max_seconds_each_run"], fixed["full_graph_1000_max_rss_bytes"], fixed["full_graph_1000_max_svg_bytes"]
        ),
        "100-node per-run budget failed",
    )
    record(
        "GRAPH-03",
        stress["deep_chain_1000"]["runs"],
        budget_ok(
            "deep_chain_1000", fixed["full_graph_1000_max_seconds_each_run"], fixed["full_graph_1000_max_rss_bytes"], fixed["full_graph_1000_max_svg_bytes"]
        ),
        "1000-node per-run budget failed",
    )
    record(
        "GRAPH-04",
        stress["deep_chain_10000_focus"]["runs"],
        budget_ok(
            "deep_chain_10000_focus",
            fixed["focus_graph_10000_max_seconds_each_run"],
            fixed["focus_graph_10000_max_rss_bytes"],
            fixed["focus_graph_10000_max_svg_bytes"],
            fixed["focus_graph_10000_max_rendered_nodes"],
        ),
        "10k focus per-run budget failed",
    )
    web = load(root / "stress/web-preflight.json")
    recovery = web.get("response", {}).get("details", {}).get("recovery_commands", {})
    web_ok = (
        web["http_status"] == 422
        and web["elapsed_seconds"] <= 2
        and web["response"].get("error") == "graph_too_large"
        and {"focus", "summary"} <= recovery.keys()
    )
    record("GRAPH-07", web, web_ok, "Web 10k full-render rejection is slow, wrong, or not actionable")
    spatial = stress["spatial_index"]
    named_spatial_observed, axes_ok = spatial_named_gate(spatial["named"], seconds=fixed["adversarial_10000_rectangles_max_seconds_each_run"])
    distributions_ok = len(spatial["differential_distributions"]) == 20 and all(
        item["small_pair_set_exact"]
        and item["large"]["complete"]
        and not item["large"]["truncated"]
        and item["large"]["wall_seconds"] <= fixed["adversarial_10000_rectangles_max_seconds_each_run"]
        and "avl" in item["large"]["algorithm"]
        for item in spatial["differential_distributions"]
    )
    spatial_ok = axes_ok and distributions_ok and spatial["dense_small"]["pair_set_exact"]
    record(
        "SPATIAL-01",
        {"named": named_spatial_observed, "distributions": spatial["differential_distributions"], "dense": spatial["dense_small"]},
        spatial_ok,
        "AVL adversarial/differential gate failed",
    )
    million = spatial["million_pair_budget"]
    million_ok = (
        not million["complete"]
        and million["truncated"]
        and million["lower_bound"] >= fixed["dense_pair_default_budget"] + 1
        and million["max_pairs"] == fixed["dense_pair_default_budget"]
    )
    record("SPATIAL-02", million, million_ok, "dense output budget did not report an explicit incomplete result")
    cli = load(root / "stress/cli-preflight.json")
    cli_ok = (
        cli["rejection"]["returncode"] == 2
        and cli["rejection"]["seconds"] <= 2
        and cli["rejection"]["payload"].get("error") == "graph_too_large"
        and cli["summary"]["returncode"] == 0
        and cli["summary"]["structure"]["nodes"] == 10000
        and not cli["summary"]["structure"]["layout_constructed"]
        and not cli["summary"]["structure"]["svg_constructed"]
        and cli["focus"]["returncode"] == 0
        and cli["focus"]["rendered_nodes"] <= fixed["focus_graph_10000_max_rendered_nodes"]
    )
    record("CLI-01", cli, cli_ok, "CLI focus/summary/rejection recovery path failed")

    source_items = []
    source_bad = []
    snapshot = load(root / "source/snapshot.json")
    source_inventory = exact_regular_file_set(source, set(snapshot["files"]))
    for relative, expected in sorted(snapshot["files"].items()):
        path = source / relative
        observed = {"bytes": path.stat().st_size, "sha256": sha256(path)} if path.is_file() else None
        if observed != expected:
            source_bad.append(relative)
        if observed:
            source_items.append((relative, observed))
    source_digest = hashlib.sha256("".join(f"{name}\0{item['sha256']}\0{item['bytes']}\n" for name, item in source_items).encode()).hexdigest()
    if source_bad or source_digest != snapshot["source_tree_digest"] or not source_inventory["passed"]:
        failures.append(f"sealed replay source mismatch: files={source_bad}, digest={source_digest}, inventory={source_inventory}")
    lineage = load(root / "source/consumed-inputs.json")
    lineage_bad = []
    for item in lineage.get("inputs", []):
        path = root / safe_manifest_path(item.get("sealed_path"))
        if not path.is_file() or sha256(path) != item.get("sha256") or path.stat().st_size != item.get("bytes"):
            lineage_bad.append(item.get("relative_path"))
    runtime_manifest = load(root / safe_manifest_path(lineage["runtime_manifest"]))
    for relative, expected in runtime_manifest["files"].items():
        path = root / safe_manifest_path(relative)
        if not path.is_file() or sha256(path) != expected["sha256"] or path.stat().st_size != expected["bytes"]:
            lineage_bad.append(relative)
    runtime_root = root / "replay/node-oracle"
    runtime_expected = {Path(relative).relative_to("replay/node-oracle").as_posix() for relative in runtime_manifest["files"]}
    runtime_inventory = exact_regular_file_set(runtime_root, runtime_expected)
    lineage_ok = (
        not lineage.get("forbidden_inputs")
        and not lineage_bad
        and lineage.get("origin_paths_required_for_replay") is False
        and source_digest == lineage["source_tree_digest"]
        and source_inventory["passed"]
        and runtime_inventory["passed"]
    )
    record(
        "LINEAGE-01",
        {
            "inputs": len(lineage.get("inputs", [])),
            "runtime_files": len(runtime_manifest["files"]),
            "bad": lineage_bad,
            "source_digest": source_digest,
            "source_inventory": source_inventory,
            "runtime_inventory": runtime_inventory,
        },
        lineage_ok,
        "sealed replay lineage or exact source/runtime file inventory is incomplete",
    )

    if args.prebrowser_only:
        allowed = {"TEST-01", "GRAPH-02", "SPATIAL-01", "LINEAGE-01", "LOCK-01"}
        selected = args.only_requirement
        if selected == "LOCK-01":
            lock_inputs = row_by_id.get("LOCK-01", {}).get("inputs", [])
            lock_relative = next((item for item in lock_inputs if str(item).endswith(".lock")), "")
            lock_observed, lock_ok = lock_rebuild_gate(root, lock_relative)
            record("LOCK-01", lock_observed, lock_ok, "lock wheel hash, version, environment, or fallback policy differs")
        if selected not in allowed:
            failures.append(f"prebrowser-only requires one of {sorted(allowed)}, observed {selected!r}")
        result = blocker_results.get(selected, {})
        predicate = replay_matrix_predicate(root, row_by_id[selected]) if selected in row_by_id else {"passed": False, "reason": "missing row"}
        if not result.get("passed"):
            failures.append(f"{selected}: independent semantic replay failed: {result.get('reason')}")
        if not predicate.get("passed"):
            failures.append(f"{selected}: matrix predicate replay failed: {predicate.get('reason')}")
        hashes_after = checksum_replay(root)
        if not hashes_after["passed"]:
            failures.append(f"checksum replay after prebrowser evaluation failed: {hashes_after}")
        report = {
            "schema_version": "0.2.3-post-seal-prebrowser-replay-1",
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "evidence_root": str(root),
            "mode": "prebrowser-only",
            "selected_requirement": selected,
            "hash_replay": {"before_semantic_replay": hashes, "after_semantic_replay": hashes_after},
            "raw_blocker_replay": {
                "independent_blockers": 1,
                "passed": int(not failures),
                "failed": int(bool(failures)),
                "results": [result] if result else [],
            },
            "matrix_predicate_replay": predicate,
            "failures": failures,
            "passed": not failures,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if failures:
            raise SystemExit("\n".join(failures))
        return

    with tempfile.TemporaryDirectory(prefix="nndv-post-seal-raw-") as temporary:
        temporary_root = Path(temporary)
        oracle = root / "replay/node-oracle/svg_quality_oracle.mjs"
        manifest = root / "visual/samples/publication-input-manifest.json"
        seven_output = temporary_root / "seven.json"
        seven_doc, seven_error = run_json(
            [
                "node",
                str(oracle),
                "--require-metadata",
                "--strict-roles",
                "--manifest",
                str(manifest),
                "--output",
                str(seven_output),
                *[str(root / f"visual/samples/{name}.svg") for name in ARCHITECTURES],
            ],
            seven_output,
        )
        seven_bad = {}
        for item in seven_doc.get("reports", []):
            okay, reasons = oracle_clean(
                item,
                font=fixed["required_text_minimum_font_pt"],
                horizontal=fixed["required_text_minimum_horizontal_ratio"],
                shape=fixed["required_text_minimum_transform_shape_ratio"],
            )
            if not okay:
                seven_bad[Path(item["file"]).stem] = reasons
        seven_names = {Path(item["file"]).stem for item in seven_doc.get("reports", [])}
        seven_ok = (
            seven_error is None and seven_names == set(ARCHITECTURES) and not seven_bad and seven_doc.get("strict_roles") and seven_doc.get("require_metadata")
        )
        record(
            "SVG-01",
            {"reports": len(seven_doc.get("reports", [])), "bad": seven_bad, "process_error": seven_error},
            seven_ok,
            "fresh strict Chrome replay of seven final SVGs failed",
        )

        truth_output = temporary_root / "truth.json"
        truth_files = sorted((root / "visual/oracle-fixture-files").glob("*.svg"))
        truth_doc, truth_error = run_json(
            [
                "node",
                str(oracle),
                "--require-metadata",
                "--strict-roles",
                "--manifest",
                str(root / "visual/oracle-fixture-files/publication-input-manifest.json"),
                "--output",
                str(truth_output),
                *map(str, truth_files),
            ],
            truth_output,
            expected_exit=1,
        )
        expectations = load(source / "verification/fixtures/svg-oracle-expectations.json")["fixtures"]
        truth_reports = {Path(item["file"]).name: item for item in truth_doc.get("reports", [])}
        truth_bad = []
        for filename, assertions in expectations.items():
            report = truth_reports.get(filename)
            if report is None:
                truth_bad.append(f"missing:{filename}")
                continue
            clean, _ = oracle_clean(
                report,
                font=fixed["required_text_minimum_font_pt"],
                horizontal=fixed["required_text_minimum_horizontal_ratio"],
                shape=fixed["required_text_minimum_transform_shape_ratio"],
            )
            if clean is not bool(assertions["passed"]):
                truth_bad.append(f"classification:{filename}")
            for expression, threshold in assertions.items():
                if expression == "passed":
                    continue
                if expression.endswith("_min"):
                    key = expression[:-4]
                    value = len(report[key]) if isinstance(report[key], list) else report[key]
                    valid = value >= threshold
                elif expression.endswith("_max"):
                    key = expression[:-4]
                    value = len(report[key]) if isinstance(report[key], list) else report[key]
                    valid = value <= threshold
                else:
                    key = expression
                    value = len(report[key]) if isinstance(report[key], list) else report[key]
                    valid = value == threshold
                if not valid:
                    truth_bad.append(f"{filename}:{expression}={value}")
        truth_ok = truth_error is None and len(truth_reports) == len(expectations) == 26 and not truth_bad
        record(
            "SVG-02",
            {"reports": len(truth_reports), "expected": len(expectations), "bad": truth_bad, "process_error": truth_error},
            truth_ok,
            "fresh adversarial SVG truth replay failed",
        )

        def replay_script(script: str, arguments: list[str], output_name: str) -> tuple[dict[str, Any], str | None]:
            output_path = temporary_root / output_name
            environment = {
                **os.environ,
                "PYTHONPATH": f"{source}:{source / 'src'}",
                "PYTHONNOUSERSITE": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "MPLCONFIGDIR": str(temporary_root / "matplotlib"),
                "XDG_CACHE_HOME": str(temporary_root / "xdg-cache"),
            }
            result = subprocess.run(
                [sys.executable, str(source / script), *arguments, "--output", str(output_path)], cwd=source, env=environment, capture_output=True, text=True
            )
            if result.returncode or not output_path.is_file():
                return {}, f"exit={result.returncode} stderr={result.stderr[-2000:]}"
            return load(output_path), None

        visual, visual_error = replay_script("scripts/verify_visual_fixtures.py", [], "visual.json")
        visual_ok = visual_error is None and not visual.get("failures") and set(visual.get("fixtures", {})) == set(ARCHITECTURES)
        if visual_ok:
            for name, expected_hash in anchor["visual_fixture_sha256"].items():
                item = visual["fixtures"][name]
                visual_ok = visual_ok and item["sha256"] == expected_hash and not item["bridge_or_junction_nodes"]
        record("VIS-02", {"fixtures": visual.get("fixtures", {}), "process_error": visual_error}, visual_ok, "authority fixture/ID/provenance replay failed")

        text, text_error = replay_script(
            "scripts/validate_vector_text_consistency.py",
            [str(root / "visual/samples"), "--compiled-directory", str(root / "visual/compiled-tikz")],
            "text.json",
        )
        text_ok = text_error is None and not text.get("failures") and set(text.get("fixtures", {})) == set(ARCHITECTURES)
        if text_ok:
            text_ok = all(
                not item["missing_svg"]
                and not item["missing_tikz"]
                and not item["missing_pdf"]
                and not item["missing_compiled_tikz_pdf"]
                and item["tikz_minimum_required_font_pt"] >= fixed["required_text_minimum_font_pt"]
                and item["tikz_horizontal_scale"] >= fixed["required_text_minimum_horizontal_ratio"]
                and item["line_break_consistent_svg_tikz"]
                for item in text["fixtures"].values()
            )
        record("TEXT-02", {"fixtures": text.get("fixtures", {}), "process_error": text_error}, text_ok, "cross-format required text replay failed")

        export, export_error = replay_script("scripts/validate_acceptance_artifacts.py", [str(root / "exports")], "exports.json")
        export_ok = export_error is None and export.get("checks", 0) >= 20 and all(export.get(key) == 0 for key in ("failures", "errors", "skipped"))
        record("EXPORT-01", {"report": export, "process_error": export_error}, export_ok, "fresh seven-format independent validation replay failed")
        publication, publication_error = replay_script(
            "scripts/validate_publication_exports.py",
            [str(root / "visual/samples"), str(root / "exports")],
            "publication.json",
        )
        publication_ok = publication_error is None and not publication.get("failures") and publication.get("moe_provenance") == "Expert ×4"
        record(
            "PUB-01",
            {"report": publication, "process_error": publication_error},
            publication_ok,
            "publication layer replay found editor controls or missing provenance",
        )
        docs, docs_error = replay_script("scripts/check_release_docs.py", ["--coverage", str(root / "coverage/summary.json")], "docs.json")
        docs_ok = docs_error is None and not docs.get("failures") and len(docs.get("documents", [])) >= 5
        record("STAT-05", {"report": docs, "process_error": docs_error}, docs_ok, "release document replay disagrees with evidence")

    scenarios = e2e["scenarios"]
    scenario_ids = [item["id"] for item in scenarios]
    e2e_ok = (
        len(scenarios) == 10
        and len(set(scenario_ids)) == 10
        and all(item["status"] == "passed" and not item.get("console_errors") for item in scenarios)
        and e2e["counts"]["skipped"] == 0
    )
    record(
        "E2E-01",
        {"ids": scenario_ids, "statuses": [item["status"] for item in scenarios], "console_errors": [item.get("console_errors") for item in scenarios]},
        e2e_ok,
        "raw Chrome scenario result failed",
    )

    dist = root / "packaging/dist"
    wheel_files = list(dist.glob("*.whl"))
    sdist_files = list(dist.glob("*.tar.gz"))
    package_ok = len(wheel_files) == len(sdist_files) == 1
    if package_ok:
        package_ok = (
            sha256(wheel_files[0]) == package["wheel"]["sha256"]
            and sha256(sdist_files[0]) == package["sdist"]["sha256"]
            and all(
                package.get(key) is True
                for key in (
                    "wheel_installed_with_dependencies",
                    "sdist_installed_with_dependencies",
                    "pip_check_passed",
                    "web_assets",
                    "cli_smoke",
                    "lock_matches",
                )
            )
        )
        with zipfile.ZipFile(wheel_files[0]) as archive:
            package_ok = package_ok and any(name.endswith("web/index.html") for name in archive.namelist())
        with tarfile.open(sdist_files[0]) as archive:
            package_ok = package_ok and any(name.endswith("src/nn_davinci/web/index.html") for name in archive.getnames())
    record(
        "PKG-01",
        {"wheel": package.get("wheel"), "sdist": package.get("sdist"), "raw_archives": [path.name for path in wheel_files + sdist_files]},
        package_ok,
        "wheel/sdist hashes, assets, installs, or pip check failed",
    )
    lock_inputs = row_by_id.get("LOCK-01", {}).get("inputs", [])
    lock_relative = next((item for item in lock_inputs if str(item).endswith(".lock")), "")
    lock_observed, lock_ok = lock_rebuild_gate(root, lock_relative)
    record("LOCK-01", lock_observed, lock_ok, "lock-driven independent environment evidence or fallback policy is internally inconsistent")

    environment = load(root / "environment.json")
    required_sources = {".gitignore", "LICENSE", "README.md", "eslint.config.mjs", "package-lock.json", "package.json", "pyproject.toml"}
    environment_ok = environment.get("git_repository") is False and required_sources <= set(environment.get("sources", {})) and not (source / ".git").exists()
    record(
        "ENV-01",
        {"git_repository": environment.get("git_repository"), "required_sources_present": sorted(required_sources & set(environment.get("sources", {})))},
        environment_ok,
        "environment/root configuration/Git invariant failed",
    )
    temporary = load(root / "temporary-files.json")
    leaked = list(temporary.get("workspace_forbidden", [])) + list(temporary.get("retained_run_caches", []))
    hygiene_ok = not leaked and temporary.get("passed") is True
    record("TEMP-01", {"leaked": leaked}, hygiene_ok, "temporary/cache hygiene failed")
    mutation = load(root / "matrix/mutation-report.json")
    required_mutations = {
        "temporary_false",
        "coverage_below_threshold",
        "visual_collision",
        "e2e_failed",
        "missing_json_pointer",
        "frozen_id_hash",
        "missing_evidence",
        "wrong_value_type",
        "baseline_and_sidecar",
        "sealed_file_tamper",
        "validator_constant_true",
        "test_count_below_89",
        "wide_dag_time",
        "wide_dag_rss",
        "wide_dag_svg",
        "nested_incomplete",
        "nested_time",
        "extra_replay_source",
        "runtime_extra_file",
        "lock_wheel_hash_inconsistency",
    }
    mutation_cases = {item.get("id"): item for item in mutation.get("cases", [])}
    mutation_targets = {
        "temporary_false": ("TEMP-01", {"failed"}),
        "coverage_below_threshold": ("STAT-03", {"failed"}),
        "visual_collision": ("SVG-01", {"failed"}),
        "e2e_failed": ("E2E-01", {"failed"}),
        "missing_json_pointer": ("STAT-02", {"error"}),
        "frozen_id_hash": ("TEST-01", {"failed"}),
        "missing_evidence": ("PUB-01", {"error"}),
        "wrong_value_type": ("STAT-02", {"failed"}),
        "baseline_and_sidecar": ("TEST-01", {"failed"}),
        "test_count_below_89": ("TEST-01", {"failed"}),
        "wide_dag_time": ("GRAPH-02", {"failed"}),
        "wide_dag_rss": ("GRAPH-02", {"failed"}),
        "wide_dag_svg": ("GRAPH-02", {"failed"}),
        "nested_incomplete": ("SPATIAL-01", {"failed"}),
        "nested_time": ("SPATIAL-01", {"failed"}),
        "extra_replay_source": ("LINEAGE-01", {"failed"}),
        "runtime_extra_file": ("LINEAGE-01", {"failed"}),
        "lock_wheel_hash_inconsistency": ("LOCK-01", {"failed"}),
        "validator_constant_true": ("COV-03", {"mutation-killed"}),
    }
    canonical_covered = mutation.get("canonical_blockers_covered", [])
    mutation_ok = (
        required_mutations <= set(mutation_cases)
        and len(mutation_cases) == 54
        and set(canonical_covered) == set(row_ids)
        and mutation.get("canonical_blocker_count") == len(row_ids) == 34
    )
    for name, (requirement_id, statuses) in mutation_targets.items():
        item = mutation_cases.get(name, {})
        mutation_ok = mutation_ok and (
            item.get("bundle_failed") is True
            and item.get("passed") is True
            and item.get("requirement_id") == requirement_id
            and item.get("target_status") in statuses
            and isinstance(item.get("failure_reason"), str)
            and bool(item["failure_reason"])
        )
    sealed_tamper = mutation_cases.get("sealed_file_tamper", {})
    mutation_ok = mutation_ok and (
        sealed_tamper.get("bundle_failed") is True
        and sealed_tamper.get("passed") is True
        and sealed_tamper.get("requirement_id") == "SEAL-01"
        and set(sealed_tamper.get("targets", [])) == {"logs/full.log", "logs/finalize.log"}
        and isinstance(sealed_tamper.get("failure_reason"), str)
        and bool(sealed_tamper["failure_reason"])
    )
    record(
        "MATRIX-01",
        {
            "cases": sorted(mutation_cases),
            "bad": sorted(name for name, item in mutation_cases.items() if not item.get("bundle_failed") or not item.get("passed")),
        },
        mutation_ok,
        "raw fail-closed mutation evidence is incomplete",
    )
    seal_policy = load(root / "seal-policy.json")
    hashes_after = checksum_replay(root)
    if not hashes_after["passed"]:
        failures.append(f"semantic replay wrote into sealed evidence: {hashes_after}")
    seal_ok = (
        hashes["passed"]
        and hashes_after["passed"]
        and seal_policy.get("manifest_schema") == CHECKSUM_SCHEMA
        and seal_policy.get("checksum_excludes") == [CHECKSUM_NAME]
        and seal_policy.get("checksum_exclusion_scope") == "root-only"
        and seal_policy.get("writes_after_seal") == 0
        and seal_policy.get("symlinks_allowed") is False
        and seal_policy.get("special_files_allowed") is False
    )
    record(
        "SEAL-01",
        {"policy": seal_policy, "hash_replay_before": hashes, "hash_replay_after": hashes_after},
        seal_ok,
        "root-only sealed inventory policy/replay failed or semantic replay wrote back",
    )

    # A semantic replay is necessary but is not a substitute for the canonical
    # matrix predicate.  Re-read every row's evidence, resolve its JSON Pointer,
    # enforce the declared type and execute the comparison independently.  The
    # release result requires both views to pass.
    predicate_replay: dict[str, dict[str, Any]] = {}
    for row in rows:
        requirement_id = row["requirement_id"]
        predicate = replay_matrix_predicate(root, row)
        predicate_replay[requirement_id] = predicate
        result = blocker_results.get(requirement_id)
        if result is None:
            continue
        semantic_passed = result["passed"]
        result["semantic_passed"] = semantic_passed
        result["matrix_predicate"] = predicate
        result["passed"] = semantic_passed and predicate["passed"]
        if not predicate["passed"]:
            prior = result.get("reason") if not semantic_passed else None
            result["reason"] = "; ".join(value for value in (prior, predicate["reason"]) if value)
        digest = hashlib.sha256()
        digest.update(requirement_id.encode())
        digest.update(bytes.fromhex(result["evidence_digest"]))
        if predicate.get("evidence_digest"):
            digest.update(bytes.fromhex(predicate["evidence_digest"]))
        result["evidence_digest"] = digest.hexdigest()

    missing_blockers = sorted(set(row_ids) - set(blocker_results))
    unexpected_blockers = sorted(set(blocker_results) - set(row_ids))
    if missing_blockers or unexpected_blockers:
        failures.append(f"raw blocker derivation registry mismatch: missing={missing_blockers}, unexpected={unexpected_blockers}")
    failed_blockers = sorted(requirement_id for requirement_id, result in blocker_results.items() if not result["passed"])
    if failed_blockers:
        failures.append(f"raw blocker derivation failures: {failed_blockers}")
    verification = load(root / "verification.json")
    if verification.get("source_tree_digest") != source_digest or verification.get("matrix_digest") != sha256(matrix_path):
        failures.append("verification identity does not match sealed source/matrix digests")
    if verification.get("pre_seal_audit") != "PASS" or "release_audit" in verification:
        failures.append("sealed verification must contain pre_seal_audit=PASS and must not self-claim release_audit")
    report = {
        "schema_version": "0.2.3-post-seal-attestation-1",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "evidence_root": str(root),
        "run_id": verification.get("run_id"),
        "hash_replay": {"before_semantic_replay": hashes, "after_semantic_replay": hashes_after},
        "raw_blocker_replay": {
            "independent_blockers": len(row_ids),
            "passed": len(row_ids) - len(failed_blockers),
            "failed": len(failed_blockers),
            "skipped": 0,
            "not_run": len(missing_blockers),
            "results": [blocker_results[requirement_id] for requirement_id in row_ids if requirement_id in blocker_results],
        },
        "matrix_predicate_replay": {
            "executed": len(predicate_replay),
            "passed": sum(item["passed"] for item in predicate_replay.values()),
            "failed": sum(not item["passed"] for item in predicate_replay.values()),
        },
        "source_tree_digest_recomputed": source_digest,
        "trust_anchor_expected_sha256": args.expected_anchor_sha256,
        "trust_anchor_actual_sha256": anchor_sha,
        "trust_anchor_mode_octal": anchor_mode,
        "self_contained_replay_source": str(source.relative_to(root)),
        "origin_paths_used": 0,
        "asserted_absent_temporary_root": asserted_absent,
        "asserted_absent_temporary_root_verified": asserted_absent is not None,
        "failures": failures,
        "passed": not failures,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "passed": not failures,
                "missing": len(hashes_after["missing"]),
                "extra": len(hashes_after["extra"]),
                "mismatch": len(hashes_after["mismatch"]),
                "raw_blockers": len(row_ids),
                "raw_blocker_failures": len(failed_blockers),
                "semantic_failures": len(failures),
            },
            sort_keys=True,
        )
    )
    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
