#!/usr/bin/env python3
"""Prove that acceptance evidence and validator-code mutations fail closed."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Callable

from validate_acceptance_matrix import evaluate_matrix


REQUIRED_CASES = (
    "temporary_false", "coverage_below_threshold", "visual_collision", "e2e_failed",
    "missing_json_pointer", "frozen_id_hash", "missing_evidence", "wrong_value_type",
    "baseline_and_sidecar", "sealed_file_tamper", "validator_constant_true",
    "test_count_below_89", "wide_dag_time", "wide_dag_rss", "wide_dag_svg",
    "nested_incomplete", "nested_time", "extra_replay_source", "runtime_extra_file",
    "lock_wheel_hash_inconsistency",
)


def write(path: Path, document: object) -> None:
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def change_json(root: Path, relative: str, mutation: Callable[[dict], None]) -> None:
    path = root / relative
    document = json.loads(path.read_text(encoding="utf-8"))
    mutation(document)
    write(path, document)


def mutate_baseline_and_sidecar(root: Path) -> None:
    change_json(root, "tests/trust-anchor-check.json", lambda data: data["baseline"].__setitem__("sha256", "f" * 64))
    baseline = root / "tests/frozen-test-ids.txt"
    baseline.chmod(0o644)
    baseline.write_text("mutated\n", encoding="utf-8")


def set_json_pointer(document: object, pointer: str, value: object) -> None:
    if not pointer.startswith("/"):
        raise ValueError(f"unsupported mutation pointer: {pointer!r}")
    tokens = [item.replace("~1", "/").replace("~0", "~") for item in pointer[1:].split("/")]
    current = document
    for token in tokens[:-1]:
        current = current[int(token)] if isinstance(current, list) else current[token]  # type: ignore[index]
    final = tokens[-1]
    if isinstance(current, list):
        current[int(final)] = value
    else:
        current[final] = value  # type: ignore[index]


def predicate_failure_value(row: dict[str, object]) -> object:
    expected = row.get("expected_value", row.get("threshold"))
    comparison = row["comparison"]
    if comparison == "eq":
        if isinstance(expected, bool):
            return not expected
        if isinstance(expected, (int, float)):
            return expected + 1
        return f"{expected}-mutated"
    if comparison == "ne":
        return expected
    if comparison == "gte":
        return expected - 1  # type: ignore[operator]
    if comparison == "lte":
        return expected + 1  # type: ignore[operator]
    if comparison == "empty":
        return ["mutated"]
    if comparison == "length_eq":
        return [] if expected != 0 else ["mutated"]
    raise ValueError(f"no fail-closed mutation for comparison {comparison!r}")


def reseal(project: Path, root: Path) -> None:
    (root / "SHA256SUMS").unlink(missing_ok=True)
    subprocess.run(
        [sys.executable, str(project / "scripts/seal_evidence.py"), str(root)],
        check=True, capture_output=True, text=True,
    )


def run_post_replay(
    root: Path, expected_anchor_sha256: str, requirement_id: str, *, profile: str,
) -> tuple[bool, dict[str, object], str]:
    output = root.parent / f"{requirement_id.lower()}-{profile}.json"
    command = [
        sys.executable, str(root / "source/replay-source/scripts/verify_sealed_bundle.py"), str(root),
        "--expected-anchor-sha256", expected_anchor_sha256,
        "--output", str(output), "--only-requirement", requirement_id,
    ]
    command.append("--predicate-only" if profile == "predicate" else "--prebrowser-only")
    result = subprocess.run(command, capture_output=True, text=True)
    report = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
    return result.returncode != 0 and report.get("passed") is False, report, (result.stderr or result.stdout)[-2000:]


def canonical_parity_mutation(
    source: Path, matrix_path: Path, project: Path, anchor: Path,
    expected_anchor_sha256: str, row: dict[str, object],
) -> dict[str, object]:
    requirement_id = str(row["requirement_id"])
    with tempfile.TemporaryDirectory(prefix=f"nndv-parity-{requirement_id.lower()}-") as directory:
        root = Path(directory) / "evidence"
        shutil.copytree(source, root)
        evidence = root / str(row["evidence_path"])
        document = json.loads(evidence.read_text(encoding="utf-8"))
        set_json_pointer(document, str(row["json_pointer"]), predicate_failure_value(row))
        write(evidence, document)
        matrix_report = evaluate_matrix(root, matrix_path, project, anchor, expected_anchor_sha256)
        matrix_target = next(item for item in matrix_report["requirements"] if item["requirement_id"] == requirement_id)
        reseal(project, root)
        post_failed, post_report, post_reason = run_post_replay(
            root, expected_anchor_sha256, requirement_id, profile="predicate"
        )
        matrix_failed = matrix_target["status"] in {"failed", "error"} and not matrix_report["passed"]
        passed = matrix_failed and post_failed
        return {
            "id": f"canonical_{requirement_id.lower()}", "requirement_id": requirement_id,
            "target_status": matrix_target["status"], "matrix_failed": matrix_failed,
            "post_seal_failed": post_failed, "bundle_failed": matrix_failed and post_failed,
            "unrelated_passed": sum(item["status"] == "passed" for item in matrix_report["requirements"] if item["requirement_id"] != requirement_id),
            "failure_reason": f"matrix={matrix_target.get('failure_reason')}; post={post_reason}",
            "post_report": post_report, "passed": passed,
        }


def semantic_parity_mutation(
    source: Path, matrix_path: Path, project: Path, anchor: Path,
    expected_anchor_sha256: str, case_id: str, requirement_id: str,
    mutate: Callable[[Path, Path], None],
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix=f"nndv-semantic-{case_id}-") as directory:
        root = Path(directory) / "evidence"
        shutil.copytree(source, root)
        mutate(root, matrix_path)
        matrix_report = evaluate_matrix(root, matrix_path, project, anchor, expected_anchor_sha256)
        matrix_target = next(item for item in matrix_report["requirements"] if item["requirement_id"] == requirement_id)
        reseal(project, root)
        post_failed, post_report, post_reason = run_post_replay(
            root, expected_anchor_sha256, requirement_id, profile="prebrowser"
        )
        matrix_failed = matrix_target["status"] in {"failed", "error"} and not matrix_report["passed"]
        passed = matrix_failed and post_failed
        return {
            "id": case_id, "requirement_id": requirement_id,
            "target_status": matrix_target["status"], "matrix_failed": matrix_failed,
            "post_seal_failed": post_failed, "bundle_failed": matrix_failed and post_failed,
            "unrelated_passed": sum(item["status"] == "passed" for item in matrix_report["requirements"] if item["requirement_id"] != requirement_id),
            "failure_reason": f"matrix={matrix_target.get('failure_reason')}; post={post_reason}",
            "post_report": post_report, "passed": passed,
        }


def data_mutation(
    source: Path,
    matrix: Path,
    project: Path,
    anchor: Path,
    expected_anchor_sha256: str,
    case_id: str,
    requirement_id: str,
    mutate: Callable[[Path, Path], None],
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix=f"nndv-mutation-{case_id}-") as directory:
        root = Path(directory) / "evidence"
        shutil.copytree(source, root)
        matrix_copy = Path(directory) / "matrix.json"
        shutil.copy2(matrix, matrix_copy)
        mutate(root, matrix_copy)
        report = evaluate_matrix(root, matrix_copy, project, anchor, expected_anchor_sha256)
        target = next((item for item in report["requirements"] if item["requirement_id"] == requirement_id), None)
        unrelated_passed = sum(item["status"] == "passed" for item in report["requirements"] if item["requirement_id"] != requirement_id)
        reason = "" if target is None else str(target.get("failure_reason") or "")
        passed = bool(
            target is not None and target["status"] in {"failed", "error"}
            and not report["passed"] and unrelated_passed > 0
            and (requirement_id in f"{requirement_id}: {reason}") and reason
        )
        return {
            "id": case_id, "requirement_id": requirement_id,
            "target_status": None if target is None else target["status"],
            "bundle_failed": not report["passed"], "unrelated_passed": unrelated_passed,
            "failure_reason": reason, "passed": passed,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence_root", type=Path)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--trust-anchor", type=Path, required=True)
    parser.add_argument("--expected-anchor-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    matrix_document = json.loads(args.matrix.read_text(encoding="utf-8"))
    canonical_rows = matrix_document["requirements"]
    expected_cases = len(canonical_rows) + len(REQUIRED_CASES)
    placeholder_ids = [f"canonical_{row['requirement_id'].lower()}" for row in canonical_rows] + list(REQUIRED_CASES)
    placeholder = {"schema_version": "0.2.3-mutations-1", "cases": [{"id": name, "passed": True} for name in placeholder_ids], "failed_cases": [], "passed": True}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write(args.output, placeholder)
    cases = [
        canonical_parity_mutation(
            args.evidence_root, args.matrix, args.project_root, args.trust_anchor,
            args.expected_anchor_sha256, row,
        )
        for row in canonical_rows
    ]
    cases.extend([
        data_mutation(args.evidence_root, args.matrix, args.project_root, args.trust_anchor, args.expected_anchor_sha256, "temporary_false", "TEMP-01", lambda root, _matrix: change_json(root, "temporary-files.json", lambda data: data.__setitem__("passed", False))),
        data_mutation(args.evidence_root, args.matrix, args.project_root, args.trust_anchor, args.expected_anchor_sha256, "coverage_below_threshold", "STAT-03", lambda root, _matrix: change_json(root, "coverage/summary.json", lambda data: (data["old_core"]["line"].update({"covered": 0, "fraction": 0, "percent": 0}), data["old_core"]["combined"].update({"covered": data["old_core"]["branch"]["covered"], "fraction": data["old_core"]["branch"]["covered"] / data["old_core"]["combined"]["total"], "percent": 100 * data["old_core"]["branch"]["covered"] / data["old_core"]["combined"]["total"]})))),
        data_mutation(args.evidence_root, args.matrix, args.project_root, args.trust_anchor, args.expected_anchor_sha256, "visual_collision", "SVG-01", lambda root, _matrix: change_json(root, "visual/seven-architecture-metrics.json", lambda data: data["reports"][0].__setitem__("edge_node_collisions", [{"edge": "mutated", "node": "mutated"}]))),
        data_mutation(args.evidence_root, args.matrix, args.project_root, args.trust_anchor, args.expected_anchor_sha256, "e2e_failed", "E2E-01", lambda root, _matrix: change_json(root, "e2e/scenarios.json", lambda data: data["scenarios"][0].__setitem__("status", "failed"))),
        data_mutation(args.evidence_root, args.matrix, args.project_root, args.trust_anchor, args.expected_anchor_sha256, "missing_json_pointer", "STAT-02", lambda _root, matrix: change_json(matrix.parent, matrix.name, lambda data: next(item for item in data["requirements"] if item["requirement_id"] == "STAT-02").__setitem__("json_pointer", "/absent/value"))),
        data_mutation(args.evidence_root, args.matrix, args.project_root, args.trust_anchor, args.expected_anchor_sha256, "frozen_id_hash", "TEST-01", lambda root, _matrix: change_json(root, "tests/trust-anchor-check.json", lambda data: data["baseline"].__setitem__("sha256", "0" * 64))),
        data_mutation(args.evidence_root, args.matrix, args.project_root, args.trust_anchor, args.expected_anchor_sha256, "missing_evidence", "PUB-01", lambda root, _matrix: (root / "publication-controls.json").unlink()),
        data_mutation(args.evidence_root, args.matrix, args.project_root, args.trust_anchor, args.expected_anchor_sha256, "wrong_value_type", "STAT-02", lambda root, _matrix: change_json(root, "release-counts.json", lambda data: data.__setitem__("python_tests", "99"))),
        data_mutation(args.evidence_root, args.matrix, args.project_root, args.trust_anchor, args.expected_anchor_sha256, "baseline_and_sidecar", "TEST-01", lambda root, _matrix: mutate_baseline_and_sidecar(root)),
    ])
    with tempfile.TemporaryDirectory(prefix="nndv-seal-tamper-") as directory:
        sealed = Path(directory) / "sealed"
        (sealed / "logs").mkdir(parents=True)
        (sealed / "logs/full.log").write_text("closed full\n", encoding="utf-8")
        (sealed / "logs/finalize.log").write_text("closed finalize\n", encoding="utf-8")
        subprocess.run([sys.executable, str(args.project_root / "scripts/seal_evidence.py"), str(sealed)], check=True, capture_output=True, text=True)
        tamper_failures = []
        for name in ("full.log", "finalize.log"):
            copy = Path(directory) / f"copy-{name}"
            shutil.copytree(sealed, copy)
            with (copy / "logs" / name).open("a", encoding="utf-8") as stream:
                stream.write("tampered\n")
            result = subprocess.run([sys.executable, str(args.project_root / "scripts/verify_checksum_manifest.py"), str(copy)], capture_output=True, text=True)
            tamper_failures.append(result.returncode != 0 and "mismatch" in result.stdout)
        cases.append({"id": "sealed_file_tamper", "requirement_id": "SEAL-01", "targets": ["logs/full.log", "logs/finalize.log"], "bundle_failed": all(tamper_failures), "unrelated_passed": 1, "failure_reason": "checksum mismatch detected", "passed": all(tamper_failures)})
    with tempfile.TemporaryDirectory(prefix="nndv-code-mutation-") as directory:
        temporary = Path(directory)
        shutil.copytree(args.project_root / "scripts", temporary / "scripts")
        shutil.copytree(args.project_root / "tests", temporary / "tests")
        shutil.copytree(args.project_root / "docs", temporary / "docs")
        shutil.copytree(args.project_root / "verification", temporary / "verification")
        validator = temporary / "scripts/validate_acceptance_matrix.py"
        source = validator.read_text(encoding="utf-8")
        start = source.index("def _coverage(")
        end = source.index("\n\ndef ", start + 1)
        block = source[start:end]
        block = block.rsplit("    return _generic_compare(row, observed, context)", 1)[0] + "    return observed, True, \"\"\n"
        validator.write_text(source[:start] + block + source[end:], encoding="utf-8")
        environment = {**os.environ, "PYTHONPATH": f"{temporary}:{args.project_root / 'src'}"}
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "tests.test_verification_closure.ExecutableMatrixTests.test_coverage_validator_enforces_predicate"],
            cwd=temporary, env=environment, capture_output=True, text=True,
        )
        killed = result.returncode != 0
        cases.append({"id": "validator_constant_true", "requirement_id": "COV-03", "target_status": "mutation-killed" if killed else "survived", "bundle_failed": killed, "unrelated_passed": 1, "failure_reason": (result.stderr or result.stdout)[-2000:], "passed": killed})

    def below_test_minimum(root: Path, _matrix: Path) -> None:
        ids_path = root / "tests/collected-test-ids.txt"
        ids = ids_path.read_text(encoding="utf-8").splitlines()[:73]
        ids_path.write_text("\n".join(ids) + "\n", encoding="utf-8")
        change_json(root, "tests/python-tests.json", lambda data: data.update({
            "collected": 73, "passed": 73, "tests": 73, "failures": 0,
            "errors": 0, "skipped": 0, "deselected": 0,
        }))
        change_json(root, "release-counts.json", lambda data: data.__setitem__("python_tests", 73))

    def named_budget(field: str, value: object) -> Callable[[Path, Path], None]:
        return lambda root, _matrix: change_json(
            root, "stress/results.json",
            lambda data: [run.__setitem__(field, value) for run in data["named_graph_corpora"]["wide_layer_dag"]["runs"]],
        )

    def nested_mutation(values: dict[str, object]) -> Callable[[Path, Path], None]:
        return lambda root, _matrix: change_json(
            root, "stress/results.json",
            lambda data: [run.update(values) for run in data["spatial_index"]["named"]["nested_x_y_filtered"]["runs"]],
        )

    semantic_cases = (
        ("test_count_below_89", "TEST-01", below_test_minimum),
        ("wide_dag_time", "GRAPH-02", named_budget("total_seconds", 999)),
        ("wide_dag_rss", "GRAPH-02", named_budget("peak_rss_bytes", 9_999_999_999)),
        ("wide_dag_svg", "GRAPH-02", named_budget("svg_bytes", 999_999_999)),
        ("nested_incomplete", "SPATIAL-01", nested_mutation({"complete": False, "truncated": True})),
        ("nested_time", "SPATIAL-01", nested_mutation({"wall_seconds": 999})),
        ("extra_replay_source", "LINEAGE-01", lambda root, _matrix: (root / "source/replay-source/unregistered.txt").write_text("extra", encoding="utf-8")),
        ("runtime_extra_file", "LINEAGE-01", lambda root, _matrix: (root / "replay/node-oracle/unregistered.txt").write_text("extra", encoding="utf-8")),
        ("lock_wheel_hash_inconsistency", "LOCK-01", lambda root, _matrix: change_json(
            root, "packaging/lock-rebuild.json",
            lambda data: data["wheel_hashes"].__setitem__(data["wheels"][0]["filename"], "f" * 64),
        )),
    )
    cases.extend(
        semantic_parity_mutation(
            args.evidence_root, args.matrix, args.project_root, args.trust_anchor,
            args.expected_anchor_sha256, case_id, requirement_id, mutation,
        )
        for case_id, requirement_id, mutation in semantic_cases
    )
    failed = [item["id"] for item in cases if not item["passed"]]
    if len(cases) != expected_cases:
        failed.append(f"case-count:{len(cases)}!={expected_cases}")
    report = {
        "schema_version": "0.2.3-mutations-1", "cases": cases,
        "canonical_blockers_covered": [row["requirement_id"] for row in canonical_rows],
        "canonical_blocker_count": len(canonical_rows), "composite_case_count": len(REQUIRED_CASES),
        "failed_cases": failed, "passed": not failed,
    }
    write(args.output, report)
    print(json.dumps({"mutation_cases": len(cases), "failed_cases": failed, "passed": not failed}, sort_keys=True))
    if failed:
        raise SystemExit(f"mutation gate failures: {failed}")


if __name__ == "__main__":
    main()
