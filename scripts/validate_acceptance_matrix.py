#!/usr/bin/env python3
"""Execute each versioned acceptance-matrix blocker against current-run evidence.

Matrix JSON selects only an allow-listed semantic validator.  It cannot run a
shell command.  Evidence paths and JSON Pointers are independently checked so
that a missing value, wrong type, symlink escape, or path traversal is a hard
release failure rather than a warning.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import stat
import sys
import time
from typing import Any, Callable


ANCHOR_EXPECTED_ARGUMENT = "--expected-anchor-sha256"
ALLOWED_STATUSES = {"passed", "failed", "error", "skipped", "not-run"}


class MatrixValidationError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MatrixValidationError(f"cannot read JSON {path}: {exc}") from exc


def load_matrix_input(path: Path) -> Any:
    """Load typed matrix inputs without pretending every input is JSON."""
    if path.suffix.lower() == ".json":
        return load_json(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise MatrixValidationError(f"cannot read text input {path}: {exc}") from exc
    return {"format": "text", "text": text, "sha256": sha256(path), "bytes": path.stat().st_size}


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    """Resolve RFC 6901 JSON Pointer without accepting URI-fragment syntax."""
    if pointer == "":
        return document
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise MatrixValidationError(f"invalid JSON Pointer {pointer!r}; expected '' or a leading '/'")
    current = document
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            if token == "-" or not token.isdecimal():
                raise MatrixValidationError(f"JSON Pointer {pointer!r} has invalid array index {token!r}")
            index = int(token)
            if index >= len(current):
                raise MatrixValidationError(f"JSON Pointer {pointer!r} array index {index} is absent")
            current = current[index]
        elif isinstance(current, dict):
            if token not in current:
                raise MatrixValidationError(f"JSON Pointer {pointer!r} key {token!r} is absent")
            current = current[token]
        else:
            raise MatrixValidationError(f"JSON Pointer {pointer!r} traverses scalar at {token!r}")
    return current


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def require_type(value: Any, expected: str) -> None:
    actual = _type_name(value)
    compatible = expected == actual or expected == "number" and actual in {"integer", "number"}
    if not compatible:
        raise MatrixValidationError(f"observed value type is {actual}, expected {expected}")


def compare_value(observed: Any, comparison: str, expected: Any) -> tuple[bool, str]:
    if comparison == "eq":
        okay = observed == expected
    elif comparison == "ne":
        okay = observed != expected
    elif comparison == "gte":
        okay = observed >= expected
    elif comparison == "lte":
        okay = observed <= expected
    elif comparison == "contains":
        okay = expected in observed
    elif comparison == "set_eq":
        okay = set(observed) == set(expected)
    elif comparison == "length_eq":
        okay = len(observed) == int(expected)
    elif comparison == "all_zero":
        okay = all(value == 0 for value in observed)
    elif comparison == "all_true":
        okay = bool(observed) and all(value is True for value in observed)
    elif comparison == "empty":
        okay = len(observed) == 0
    else:
        raise MatrixValidationError(f"unsupported comparison {comparison!r}")
    return okay, "" if okay else f"observed {observed!r} does not satisfy {comparison} {expected!r}"


def _expected(row: dict[str, Any]) -> Any:
    if "expected_value" in row:
        return row["expected_value"]
    if "threshold" in row:
        return row["threshold"]
    raise MatrixValidationError("row has neither expected_value nor threshold")


def _generic_compare(row: dict[str, Any], observed: Any, _: dict[str, Any]) -> tuple[Any, bool, str]:
    okay, reason = compare_value(observed, row["comparison"], _expected(row))
    return observed, okay, reason


def _python_tests(row: dict[str, Any], observed: Any, context: dict[str, Any]) -> tuple[Any, bool, str]:
    document = context["document"]
    required = {"collected", "passed", "tests", "failures", "errors", "skipped", "deselected", "baseline_count"}
    missing = sorted(required - document.keys())
    if missing:
        return observed, False, f"test summary missing fields {missing}"
    failures = {key: document[key] for key in ("failures", "errors", "skipped", "deselected") if document[key] != 0}
    if failures or not document["collected"] == document["passed"] == document["tests"]:
        return observed, False, (
            f"raw Python test state is not clean: {failures}, collected={document['collected']}, "
            f"passed={document['passed']}, tests={document['tests']}"
        )
    if context.get("inputs"):
        supplied = context["inputs"][0].get("baseline", {})
        anchored = context["anchor"]["legacy_test_baseline"]
        if any(supplied.get(key) != anchored[key] for key in ("sha256", "mode_octal", "test_id_count")):
            return observed, False, "test-ID sidecar differs from the external trust anchor"
    if len(context.get("inputs", [])) >= 3:
        collected_input, frozen_input = context["inputs"][1:3]
        collected_ids = collected_input.get("text", "").splitlines()
        frozen_ids = frozen_input.get("text", "").splitlines()
        paths = context.get("input_paths", [])
        anchored = context["anchor"]["legacy_test_baseline"]
        frozen_path = paths[2]
        id_checks = {
            "collected_lines": len(collected_ids) == document["collected"],
            "collected_unique": len(set(collected_ids)) == len(collected_ids),
            "frozen_count": len(frozen_ids) == anchored["test_id_count"],
            "frozen_subset": set(frozen_ids) <= set(collected_ids),
            "frozen_sha256": sha256(frozen_path) == anchored["sha256"],
            "frozen_mode": f"{stat.S_IMODE(frozen_path.stat().st_mode):04o}" == anchored["mode_octal"],
        }
        if not all(id_checks.values()):
            return observed, False, f"collected/frozen test-ID invariants failed: {id_checks}"
    return _generic_compare(row, observed, context)


def _coverage(row: dict[str, Any], observed: Any, context: dict[str, Any]) -> tuple[Any, bool, str]:
    document = context["document"]
    sections = [value for value in document.values() if isinstance(value, dict) and {"line", "branch", "combined"} <= value.keys()]
    for section in sections:
        for name in ("line", "branch", "combined"):
            metric = section[name]
            if not isinstance(metric, dict) or not {"covered", "total", "fraction"} <= metric.keys():
                return observed, False, f"coverage {name} lacks raw numerator/denominator/fraction"
            if metric["total"] <= 0 or metric["fraction"] != metric["covered"] / metric["total"]:
                return observed, False, f"coverage {name} arithmetic mismatch"
        combined = section["combined"]
        if combined["covered"] != section["line"]["covered"] + section["branch"]["covered"]:
            return observed, False, "combined coverage numerator is not line+branch"
        if combined["total"] != section["line"]["total"] + section["branch"]["total"]:
            return observed, False, "combined coverage denominator is not line+branch"
    for raw in context.get("inputs", []):
        totals = raw.get("totals") if isinstance(raw, dict) else None
        if not isinstance(totals, dict) or not {
            "covered_lines", "num_statements", "covered_branches", "num_branches"
        } <= totals.keys():
            continue
        derived = {
            "line": (totals["covered_lines"], totals["num_statements"]),
            "branch": (totals["covered_branches"], totals["num_branches"]),
            "combined": (
                totals["covered_lines"] + totals["covered_branches"],
                totals["num_statements"] + totals["num_branches"],
            ),
        }
        matches = any(
            all(
                section[name]["covered"] == numerator
                and section[name]["total"] == denominator
                and section[name]["fraction"] == numerator / denominator
                for name, (numerator, denominator) in derived.items()
            )
            for section in sections
        )
        if not matches:
            return observed, False, "coverage summary does not derive from a supplied raw coverage.py JSON"
    return _generic_compare(row, observed, context)


def _test_id_baseline(row: dict[str, Any], observed: Any, context: dict[str, Any]) -> tuple[Any, bool, str]:
    anchor = context["anchor"]
    baseline = anchor["legacy_test_baseline"]
    document = context["document"]
    observed_baseline = document.get("baseline", document)
    checks = {
        "sha256": observed_baseline.get("sha256") == baseline["sha256"],
        "mode_octal": observed_baseline.get("mode_octal") == baseline["mode_octal"],
        "test_id_count": observed_baseline.get("test_id_count") == baseline["test_id_count"],
        "anchor_sha256": context["anchor_sha256"] == context["expected_anchor_sha256"],
    }
    if not all(checks.values()):
        return observed, False, f"anchored test-ID baseline mismatch: {checks}"
    return _generic_compare(row, observed, context)


def _e2e(row: dict[str, Any], observed: Any, context: dict[str, Any]) -> tuple[Any, bool, str]:
    document = context["document"]
    scenarios = document.get("scenarios", [])
    ids = [item.get("id") for item in scenarios]
    bad = [item.get("id") for item in scenarios if item.get("status") != "passed" or item.get("console_errors")]
    if len(ids) != len(set(ids)) or bad or document.get("counts", {}).get("skipped") != 0:
        return observed, False, f"E2E scenarios are not independently clean: duplicate={len(ids) != len(set(ids))}, bad={bad}"
    return _generic_compare(row, observed, context)


def _svg_oracle(row: dict[str, Any], observed: Any, context: dict[str, Any]) -> tuple[Any, bool, str]:
    document = context["document"]
    reports = document.get("reports", [])
    if not reports:
        return observed, False, "SVG oracle report has no per-file reports"
    bad: list[str] = []
    for report in reports:
        blockers = (
            report.get("clipping", []), report.get("node_overlaps", []),
            report.get("edge_node_collisions", []), report.get("edge_crossings", []),
            report.get("annotation_node_collisions", []), report.get("legend_node_collisions", []),
            report.get("unknown_roles", []), report.get("metadata_errors", []),
        )
        if any(blockers):
            bad.append(Path(report.get("file", "unknown")).name)
        if report.get("minimum_font_pt") is not None and report["minimum_font_pt"] < 7.0:
            bad.append(Path(report.get("file", "unknown")).name + ":font")
        if report.get("minimum_horizontal_scale") is not None and report["minimum_horizontal_scale"] < 0.85:
            bad.append(Path(report.get("file", "unknown")).name + ":horizontal")
        if report.get("minimum_transform_shape") is not None and report["minimum_transform_shape"] < 0.85:
            bad.append(Path(report.get("file", "unknown")).name + ":shape")
    if bad:
        return observed, False, f"independently recomputed SVG blockers failed: {bad}"
    return _generic_compare(row, observed, context)


def _stress(row: dict[str, Any], observed: Any, context: dict[str, Any]) -> tuple[Any, bool, str]:
    document = context["document"]
    if document.get("hard_failures"):
        return observed, False, f"stress report hard failures: {document['hard_failures']}"
    requirement_id = row["requirement_id"]
    fixed = context["anchor"]["fixed_thresholds"]
    if requirement_id == "GRAPH-01":
        scc = document.get("scc_differential", {})
        okay = (
            scc.get("samples") == 100 and not scc.get("partition_failures")
            and not scc.get("condensation_dag_failures")
            and scc.get("deep_chain_without_recursion") is True
            and scc.get("deep_chain_components") == 10000
        )
        if not okay:
            return observed, False, "SCC differential/deep-chain invariants failed"
    if requirement_id == "GRAPH-02":
        anchor_hashes = context["anchor"]["stress_corpus"]["sha256"]
        named = document.get("named_graph_corpora", {})
        expected = {"locally_dense", "sparse_skip", "strongly_connected", "wide_layer_dag"}
        bad = []
        if set(named) != expected:
            bad.append("corpus-set")
        for name in sorted(expected):
            item = named.get(name, {})
            runs = item.get("runs", [])
            structure = item.get("structure", {})
            performance = len(runs) == 3 and all(
                run.get("graph_sha256") == anchor_hashes.get(name)
                and isinstance(run.get("total_seconds"), (int, float))
                and run["total_seconds"] <= fixed["full_graph_1000_max_seconds_each_run"]
                and isinstance(run.get("peak_rss_bytes"), int)
                and run["peak_rss_bytes"] <= fixed["full_graph_1000_max_rss_bytes"]
                and isinstance(run.get("svg_bytes"), int)
                and run["svg_bytes"] <= fixed["full_graph_1000_max_svg_bytes"]
                for run in runs
            )
            if name == "locally_dense":
                structure_ok = all(structure.get(key) is value for key, value in {
                    "edge_set_exact": True, "node_set_exact": True,
                    "pair_budget_complete": True, "pair_budget_truncated": False,
                }.items())
            elif name == "strongly_connected":
                structure_ok = structure.get("edge_set_exact") is True and structure.get("component_count") == 1 and structure.get("component_size") == 1000
            elif name == "wide_layer_dag":
                structure_ok = structure.get("edge_set_exact") is True and structure.get("source_rank") == 0 and structure.get("sink_rank") == 3 and structure.get("rank_values") == [0, 1, 2, 3]
            else:
                structure_ok = structure.get("edge_set_exact") is True and structure.get("rank_monotonic") is True
            if not performance or not structure_ok:
                bad.append(name)
        if bad:
            return observed, False, f"named graph hash/structure/per-run budget failures: {bad}"
    deep_sections = {
        "GRAPH-02A": ("deep_chain_100", "full_graph_1000_max_seconds_each_run", "full_graph_1000_max_rss_bytes", "full_graph_1000_max_svg_bytes", None),
        "GRAPH-03": ("deep_chain_1000", "full_graph_1000_max_seconds_each_run", "full_graph_1000_max_rss_bytes", "full_graph_1000_max_svg_bytes", None),
        "GRAPH-04": ("deep_chain_10000_focus", "focus_graph_10000_max_seconds_each_run", "focus_graph_10000_max_rss_bytes", "focus_graph_10000_max_svg_bytes", "focus_graph_10000_max_rendered_nodes"),
    }
    if requirement_id in deep_sections:
        section, seconds_key, rss_key, svg_key, nodes_key = deep_sections[requirement_id]
        runs = document.get(section, {}).get("runs", [])
        okay = len(runs) == 3 and all(
            run.get("total_seconds", float("inf")) <= fixed[seconds_key]
            and run.get("peak_rss_bytes", sys.maxsize) <= fixed[rss_key]
            and run.get("svg_bytes", sys.maxsize) <= fixed[svg_key]
            and (nodes_key is None or run.get("rendered_nodes", sys.maxsize) <= fixed[nodes_key])
            for run in runs
        )
        if not okay:
            return observed, False, f"{section} per-run budget failed"
    if requirement_id == "SPATIAL-01":
        spatial = document.get("spatial_index", {})
        names = ("same_x_y_disjoint", "same_y_x_disjoint", "nested_x_y_filtered")
        named_ok = all(
            len(spatial.get("named", {}).get(name, {}).get("runs", [])) == 3
            and all(
                run.get("rectangles") == 10000 and run.get("pairs") == 0
                and run.get("complete") is True and run.get("truncated") is False
                and run.get("wall_seconds", float("inf")) <= fixed["adversarial_10000_rectangles_max_seconds_each_run"]
                and "avl" in str(run.get("algorithm", "")).lower()
                for run in spatial.get("named", {}).get(name, {}).get("runs", [])
            ) for name in names
        )
        distributions = spatial.get("differential_distributions", [])
        distributions_ok = len(distributions) == 20 and all(
            item.get("small_pair_set_exact") is True and item.get("large", {}).get("complete") is True
            and item.get("large", {}).get("truncated") is False
            and item.get("large", {}).get("wall_seconds", float("inf")) <= fixed["adversarial_10000_rectangles_max_seconds_each_run"]
            for item in distributions
        )
        if not named_ok or not distributions_ok or spatial.get("dense_small", {}).get("pair_set_exact") is not True:
            return observed, False, "AVL named/distribution/dense differential gate failed"
    if requirement_id == "SPATIAL-02":
        million = document.get("spatial_index", {}).get("million_pair_budget", {})
        if not (
            million.get("complete") is False and million.get("truncated") is True
            and million.get("lower_bound", 0) >= fixed["dense_pair_default_budget"] + 1
            and million.get("max_pairs") == fixed["dense_pair_default_budget"]
        ):
            return observed, False, "million-pair incomplete/truncated budget semantics failed"
    return _generic_compare(row, observed, context)


def _lineage(row: dict[str, Any], observed: Any, context: dict[str, Any]) -> tuple[Any, bool, str]:
    document = context["document"]
    forbidden = document.get("forbidden_inputs", [])
    if forbidden:
        return observed, False, f"forbidden consumed inputs: {forbidden}"
    root = context.get("evidence_root")
    missing = []
    for item in document.get("inputs", []):
        sealed = root / item.get("sealed_path", "") if root is not None else None
        if sealed is None or not sealed.is_file() or sha256(sealed) != item.get("sha256") or sealed.stat().st_size != item.get("bytes"):
            missing.append(item.get("relative_path", item.get("sealed_path")))
    if missing:
        return observed, False, f"sealed consumed inputs are absent or changed: {missing[:10]}"
    root = context.get("evidence_root")
    if root is not None and len(context.get("inputs", [])) >= 2:
        snapshot, runtime_manifest = context["inputs"][:2]

        def inventory(base: Path) -> tuple[set[str], list[str]]:
            files: set[str] = set()
            invalid: list[str] = []
            for candidate in base.rglob("*"):
                relative = candidate.relative_to(base).as_posix()
                mode = candidate.lstat().st_mode
                if stat.S_ISLNK(mode):
                    invalid.append(f"symlink:{relative}")
                elif stat.S_ISREG(mode):
                    files.add(relative)
                elif not stat.S_ISDIR(mode):
                    invalid.append(f"special:{relative}")
            return files, invalid

        source_files, source_invalid = inventory(root / "source/replay-source")
        runtime_files, runtime_invalid = inventory(root / "replay/node-oracle")
        expected_source = set(snapshot.get("files", {}))
        expected_runtime = {
            Path(relative).relative_to("replay/node-oracle").as_posix()
            for relative in runtime_manifest.get("files", {})
        }
        if source_files != expected_source or runtime_files != expected_runtime or source_invalid or runtime_invalid:
            return observed, False, (
                "replay source/runtime inventory mismatch: "
                f"source_missing={sorted(expected_source-source_files)[:5]}, source_extra={sorted(source_files-expected_source)[:5]}, "
                f"runtime_missing={sorted(expected_runtime-runtime_files)[:5]}, runtime_extra={sorted(runtime_files-expected_runtime)[:5]}, "
                f"invalid={source_invalid + runtime_invalid}"
            )
    return _generic_compare(row, observed, context)


def _fixture_integrity(row: dict[str, Any], observed: Any, context: dict[str, Any]) -> tuple[Any, bool, str]:
    document = context["document"]
    failures = document.get("failures", [])
    if failures or document.get("passed") is False:
        return observed, False, f"fixture integrity failures: {failures}"
    return _generic_compare(row, observed, context)


def _oracle_fixture_truth(row: dict[str, Any], observed: Any, context: dict[str, Any]) -> tuple[Any, bool, str]:
    document = context["document"]
    cases = document.get("cases", [])
    required_failures = set(context["anchor"]["required_oracle_failures"])
    observed_failures = {item.get("truth_id") for item in cases if item.get("expected_pass") is False}
    bad = [item.get("fixture") for item in cases if item.get("actual_pass") is not item.get("expected_pass")]
    if bad or not required_failures <= observed_failures:
        return observed, False, f"SVG truth classification mismatch={bad}; absent required negatives={sorted(required_failures - observed_failures)}"
    return _generic_compare(row, observed, context)


def _export_semantics(row: dict[str, Any], observed: Any, context: dict[str, Any]) -> tuple[Any, bool, str]:
    document = context["document"]
    if any(document.get(key, 0) for key in ("failures", "errors", "skipped")):
        return observed, False, "fresh export validation contains failure/error/skip"
    if document.get("formats") is not None and set(document["formats"]) != {"svg", "pdf", "png", "tikz", "eps", "pptx", "html"}:
        return observed, False, f"seven-format set drifted: {document.get('formats')}"
    return _generic_compare(row, observed, context)


def _packaging_semantics(row: dict[str, Any], observed: Any, context: dict[str, Any]) -> tuple[Any, bool, str]:
    document = context["document"]
    checks = (
        document.get("wheel_installed_with_dependencies"), document.get("sdist_installed_with_dependencies"),
        document.get("pip_check_passed"), document.get("web_assets"), document.get("cli_smoke"),
    )
    if document.get("passed") is not True or not all(checks):
        return observed, False, f"package/dependency rebuild is incomplete: checks={checks}"
    return _generic_compare(row, observed, context)


def _lock_rebuild(row: dict[str, Any], observed: Any, context: dict[str, Any]) -> tuple[Any, bool, str]:
    document = context["document"]
    required = (
        document.get("independent_environment"), document.get("lock_matches"),
        document.get("pip_check_passed"), document.get("import_smoke_passed"),
    )
    hashes = document.get("wheel_hashes")
    input_documents = context.get("inputs", [])
    lock_input = input_documents[0] if input_documents else None
    lock: dict[str, str] = {}
    if isinstance(lock_input, dict) and lock_input.get("format") == "text":
        for raw in lock_input["text"].splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.count("==") != 1:
                return observed, False, f"verification lock line is not exact: {line!r}"
            name, version = line.split("==", 1)
            key = name.lower().replace("_", "-")
            if key in lock:
                return observed, False, f"verification lock repeats distribution {key!r}"
            lock[key] = version
    wheels = document.get("wheels", [])
    installed = document.get("installed_locked_versions", {})
    fallback_rows = [item for item in wheels if item.get("origin") != "configured_index"] if isinstance(wheels, list) else []
    wheel_rows_ok = (
        isinstance(wheels, list) and len(wheels) == len(lock) == document.get("locked_distributions")
        and all(isinstance(item, dict) for item in wheels)
        and all(
            lock.get(item.get("name")) == item.get("version")
            and hashes.get(item.get("filename")) == item.get("sha256")
            and isinstance(item.get("sha256"), str) and len(item["sha256"]) == 64
            for item in wheels
        )
        and all(installed.get(name) == version for name, version in lock.items())
        and document.get("local_fallback_allowlist") == ["torchcam"]
        and all(
            item.get("name") == "torchcam"
            and item.get("origin") == "allowlisted_torchcam_installed_distribution_record_fallback"
            for item in fallback_rows
        )
    )
    if not all(required) or not isinstance(hashes, dict) or not hashes or not lock or not wheel_rows_ok:
        return observed, False, f"verification lock rebuild is incomplete: checks={required}, wheel_hashes={type(hashes).__name__}"
    return _generic_compare(row, observed, context)


def _documentation(row: dict[str, Any], observed: Any, context: dict[str, Any]) -> tuple[Any, bool, str]:
    document = context["document"]
    if document.get("failures") or document.get("passed") is not True:
        return observed, False, f"documentation/evidence mismatches: {document.get('failures')}"
    return _generic_compare(row, observed, context)


def _release_counts(row: dict[str, Any], observed: Any, context: dict[str, Any]) -> tuple[Any, bool, str]:
    document = context["document"]
    fields = (
        "checks", "python_tests", "artifact_assertions", "font_tikz_checks",
        "packaging_checks", "e2e_scenarios", "semantic_e2e_workflows",
        "semantic_e2e_assertions",
    )
    missing = [name for name in fields if not isinstance(document.get(name), int)]
    if missing or len(set(fields)) != len(fields):
        return observed, False, f"release count schema is incomplete: {missing}"
    return _generic_compare(row, observed, context)


def _mutation_gate(row: dict[str, Any], observed: Any, context: dict[str, Any]) -> tuple[Any, bool, str]:
    document = context["document"]
    required = {
        "temporary_false", "coverage_below_threshold", "visual_collision", "e2e_failed",
        "missing_json_pointer", "frozen_id_hash", "missing_evidence", "wrong_value_type",
        "baseline_and_sidecar", "sealed_file_tamper", "validator_constant_true",
        "test_count_below_89", "wide_dag_time", "wide_dag_rss", "wide_dag_svg",
        "nested_incomplete", "nested_time", "extra_replay_source", "runtime_extra_file",
        "lock_wheel_hash_inconsistency",
    }
    cases = document.get("cases", [])
    names = {item.get("id") for item in cases}
    bad = [item.get("id") for item in cases if not item.get("passed")]
    canonical = document.get("canonical_blockers_covered", [])
    if (
        required - names or bad or document.get("passed") is not True
        or document.get("canonical_blocker_count") != 34
        or len(canonical) != 34 or len(set(canonical)) != 34
    ):
        return observed, False, (
            f"mutation cases absent/failed: absent={sorted(required - names)}, bad={bad}, "
            f"canonical_count={document.get('canonical_blocker_count')}"
        )
    return _generic_compare(row, observed, context)


def _seal_policy(row: dict[str, Any], observed: Any, context: dict[str, Any]) -> tuple[Any, bool, str]:
    document = context["document"]
    if (
        document.get("checksum_excludes") != ["SHA256SUMS"]
        or document.get("checksum_exclusion_scope") != "root-only"
        or document.get("manifest_schema") != "nndv-sha256-manifest-2"
        or document.get("writes_after_seal") != 0
        or document.get("special_files_allowed") is not False
    ):
        return observed, False, "pre-seal policy does not cover all retained files or permits post-seal writes"
    return _generic_compare(row, observed, context)


def _hygiene(row: dict[str, Any], observed: Any, context: dict[str, Any]) -> tuple[Any, bool, str]:
    document = context["document"]
    present = list(document.get("workspace_forbidden", [])) + list(document.get("retained_run_caches", []))
    recomputed = not present
    if present or document.get("passed") is not recomputed:
        return observed, False, (
            f"temporary-file result disagrees with independent inventory: reported={document.get('passed')!r}, "
            f"recomputed={recomputed}, present={present}"
        )
    return _generic_compare(row, observed, context)


@dataclass(frozen=True)
class ValidatorSpec:
    requirement_classes: frozenset[str]
    function: Callable[[dict[str, Any], Any, dict[str, Any]], tuple[Any, bool, str]]


VALIDATORS: dict[str, ValidatorSpec] = {
    "python_test_summary": ValidatorSpec(frozenset({"tests"}), _python_tests),
    "anchored_test_ids": ValidatorSpec(frozenset({"tests"}), _test_id_baseline),
    "coverage_arithmetic": ValidatorSpec(frozenset({"coverage"}), _coverage),
    "graph_semantics": ValidatorSpec(frozenset({"graph", "cli"}), _stress),
    "svg_geometry": ValidatorSpec(frozenset({"svg", "text", "visual"}), _svg_oracle),
    "fixture_integrity": ValidatorSpec(frozenset({"visual"}), _fixture_integrity),
    "oracle_fixture_truth": ValidatorSpec(frozenset({"oracle-fixture"}), _oracle_fixture_truth),
    "browser_scenarios": ValidatorSpec(frozenset({"e2e"}), _e2e),
    "export_semantics": ValidatorSpec(frozenset({"export", "publication"}), _export_semantics),
    "packaging_semantics": ValidatorSpec(frozenset({"packaging", "dependencies"}), _packaging_semantics),
    "lock_rebuild": ValidatorSpec(frozenset({"dependencies"}), _lock_rebuild),
    "documentation_consistency": ValidatorSpec(frozenset({"documentation"}), _documentation),
    "environment_integrity": ValidatorSpec(frozenset({"environment", "git"}), _generic_compare),
    "temporary_hygiene": ValidatorSpec(frozenset({"temporary"}), _hygiene),
    "consumed_input_lineage": ValidatorSpec(frozenset({"lineage", "snapshot"}), _lineage),
    "release_count_schema": ValidatorSpec(frozenset({"statistics"}), _release_counts),
    "mutation_gate": ValidatorSpec(frozenset({"matrix"}), _mutation_gate),
    "seal_precondition": ValidatorSpec(frozenset({"seal"}), _seal_policy),
}


REQUIRED_FIELDS = {
    "requirement_id", "title", "validator_id", "requirement_class", "inputs",
    "evidence_path", "json_pointer", "observed_value_type", "comparison",
    "command_provenance", "release_blocker",
}


def validate_anchor(anchor_path: Path, expected_sha256: str) -> tuple[dict[str, Any], str]:
    actual = sha256(anchor_path)
    if actual != expected_sha256:
        raise MatrixValidationError(f"trust anchor SHA-256 mismatch: expected {expected_sha256}, observed {actual}")
    if stat.S_IMODE(anchor_path.stat().st_mode) != 0o444:
        raise MatrixValidationError(f"trust anchor mode mismatch: expected 0444, observed {stat.S_IMODE(anchor_path.stat().st_mode):04o}")
    anchor = load_json(anchor_path)
    if anchor.get("immutable_during_task") is not True:
        raise MatrixValidationError("trust anchor does not declare immutable_during_task=true")
    return anchor, actual


def _safe_evidence_path(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise MatrixValidationError(f"evidence path escapes evidence root: {relative!r}")
    root_real = root.resolve()
    candidate = root / path
    if candidate.is_symlink():
        raise MatrixValidationError(f"evidence path is a symlink: {relative!r}")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root_real):
        raise MatrixValidationError(f"evidence path resolves outside evidence root: {relative!r}")
    if not resolved.is_file():
        raise MatrixValidationError(f"evidence path is not a regular file: {relative!r}")
    return resolved


def _command_paths_exist(row: dict[str, Any], project_root: Path) -> None:
    values = row.get("command_provenance")
    if not isinstance(values, list) or not values:
        raise MatrixValidationError("command_provenance must be a non-empty path list")
    for relative in values:
        path = project_root / relative
        if Path(relative).is_absolute() or ".." in Path(relative).parts or not path.is_file():
            raise MatrixValidationError(f"command/oracle provenance path does not exist: {relative!r}")


def validate_matrix_schema(matrix: dict[str, Any], anchor: dict[str, Any], project_root: Path) -> list[dict[str, Any]]:
    identity = (matrix.get("schema_version"), matrix.get("release"))
    if identity not in {("3.0.0", "0.2.2"), ("3.1.0", "0.2.3")}:
        raise MatrixValidationError(f"unsupported matrix schema_version/release: {identity!r}")
    rows = matrix.get("requirements")
    if not isinstance(rows, list) or not rows:
        raise MatrixValidationError("matrix requirements must be a non-empty array")
    ids = [row.get("requirement_id") for row in rows if isinstance(row, dict)]
    if len(ids) != len(rows) or len(ids) != len(set(ids)):
        raise MatrixValidationError("matrix requirement IDs are absent or duplicated")
    mapping = matrix.get("migration", {}).get("legacy_id_mapping", {})
    legacy_ids = set(anchor["legacy_acceptance_matrix"]["requirement_ids"])
    missing_legacy = sorted(legacy_ids - set(mapping))
    if missing_legacy:
        raise MatrixValidationError(f"legacy requirement IDs lack an explicit canonical mapping: {missing_legacy}")
    unknown_targets = sorted(set(mapping.values()) - set(ids))
    if unknown_targets:
        raise MatrixValidationError(f"legacy requirement mappings target absent blockers: {unknown_targets}")
    blocker_validators: list[str] = []
    for row in rows:
        missing = sorted(REQUIRED_FIELDS - row.keys())
        if missing:
            raise MatrixValidationError(f"{row.get('requirement_id', '?')}: missing fields {missing}")
        if not isinstance(row["release_blocker"], bool) or not row["release_blocker"]:
            raise MatrixValidationError(f"{row['requirement_id']}: every canonical row must be a release blocker")
        if "expected_value" not in row and "threshold" not in row:
            raise MatrixValidationError(f"{row['requirement_id']}: expected_value/threshold is absent")
        validator = VALIDATORS.get(row["validator_id"])
        if validator is None:
            raise MatrixValidationError(f"{row['requirement_id']}: validator {row['validator_id']!r} is not allow-listed")
        if row["requirement_class"] not in validator.requirement_classes:
            raise MatrixValidationError(
                f"{row['requirement_id']}: validator {row['validator_id']} does not support class {row['requirement_class']}"
            )
        _command_paths_exist(row, project_root)
        blocker_validators.append(row["validator_id"])
    if len(set(blocker_validators)) == 1:
        raise MatrixValidationError("all release blockers map to one validator; blanket/always-true matrices are forbidden")
    signatures = [
        (
            row["validator_id"], row["evidence_path"], row["json_pointer"],
            row["comparison"], json.dumps(_expected(row), sort_keys=True), tuple(row["inputs"]),
        )
        for row in rows
    ]
    duplicates = sorted({signature for signature in signatures if signatures.count(signature) > 1})
    if duplicates:
        raise MatrixValidationError(f"duplicate blocker predicates are forbidden: {duplicates}")
    return rows


def _evidence_digest(row: dict[str, Any], files: list[Path]) -> str:
    digest = hashlib.sha256()
    digest.update(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
    for path in files:
        digest.update(path.name.encode())
        digest.update(bytes.fromhex(sha256(path)))
    return digest.hexdigest()


def evaluate_matrix(
    evidence_root: Path,
    matrix_path: Path,
    project_root: Path,
    anchor_path: Path,
    expected_anchor_sha256: str,
) -> dict[str, Any]:
    anchor, anchor_sha = validate_anchor(anchor_path, expected_anchor_sha256)
    matrix = load_json(matrix_path)
    rows = validate_matrix_schema(matrix, anchor, project_root)
    results: list[dict[str, Any]] = []
    for row in rows:
        started_wall = datetime.now(timezone.utc).isoformat()
        started = time.perf_counter()
        result: dict[str, Any] = {
            "requirement_id": row["requirement_id"], "validator_id": row["validator_id"],
            "started_at": started_wall, "status": "error", "observed": None,
            "expected": _expected(row), "evidence_digest": None, "failure_reason": None,
        }
        try:
            evidence = _safe_evidence_path(evidence_root, row["evidence_path"])
            inputs = [_safe_evidence_path(evidence_root, relative) for relative in row["inputs"]]
            document = load_json(evidence)
            observed = resolve_json_pointer(document, row["json_pointer"])
            require_type(observed, row["observed_value_type"])
            spec = VALIDATORS[row["validator_id"]]
            context = {
                "document": document, "inputs": [load_matrix_input(path) for path in inputs],
                "input_paths": inputs, "evidence_root": evidence_root.resolve(),
                "anchor": anchor, "anchor_sha256": anchor_sha,
                "expected_anchor_sha256": expected_anchor_sha256,
            }
            normalized, okay, reason = spec.function(row, observed, context)
            result.update({
                "status": "passed" if okay else "failed", "observed": normalized,
                "evidence_digest": _evidence_digest(row, [evidence, *inputs]),
                "failure_reason": reason or None,
            })
        except Exception as exc:  # one broken row must not hide other independent results
            result["failure_reason"] = f"{type(exc).__name__}: {exc}"
        result["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
        results.append(result)
    counts = {status.replace("-", "_"): sum(item["status"] == status for item in results) for status in ALLOWED_STATUSES}
    passed = counts["passed"] == len(results)
    return {
        "schema_version": "2.0.2-results", "matrix_sha256": sha256(matrix_path),
        "trust_anchor_sha256": anchor_sha, "expected_trust_anchor_sha256": expected_anchor_sha256,
        "release_blocker_checks": len(results), "counts": counts, "requirements": results,
        "passed": passed,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence_root", type=Path)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--trust-anchor", type=Path, required=True)
    parser.add_argument(ANCHOR_EXPECTED_ARGUMENT, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = evaluate_matrix(
            args.evidence_root, args.matrix, args.project_root, args.trust_anchor,
            args.expected_anchor_sha256,
        )
    except MatrixValidationError as exc:
        raise SystemExit(str(exc)) from exc
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"release_blocker_checks": report["release_blocker_checks"], **report["counts"], "passed": report["passed"]}, sort_keys=True))
    if not report["passed"]:
        failures = [f"{item['requirement_id']}: {item['failure_reason']}" for item in report["requirements"] if item["status"] != "passed"]
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
