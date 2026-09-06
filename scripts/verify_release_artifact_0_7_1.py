#!/usr/bin/env python3
"""Independent read-only verification for a sealed 0.7.1 artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any

from finalize_artifact_0_7_1 import REPORTS as REQUIRED_REPORTS
from finalize_artifact_0_7_1 import payload_failures, report_failures


RELEASE = "0.7.1 — 3D Publication Quality & UX Completion"
CONTROL_FILES = {"MANIFEST.json", "SHA256SUMS"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inventory(root: Path) -> tuple[dict[str, Path], list[str]]:
    files: dict[str, Path] = {}
    unsafe: list[str] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                relative = path.relative_to(root).as_posix()
                mode = entry.stat(follow_symlinks=False).st_mode
                if stat.S_ISLNK(mode):
                    unsafe.append(f"symlink:{relative}")
                elif stat.S_ISDIR(mode):
                    pending.append(path)
                elif stat.S_ISREG(mode):
                    files[relative] = path
                else:
                    unsafe.append(f"special:{relative}")
    return dict(sorted(files.items())), sorted(unsafe)


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-run-id")
    args = parser.parse_args()
    supplied = args.artifact
    failures: list[str] = []
    if supplied.is_symlink() or not supplied.is_dir():
        raise SystemExit("artifact root is absent or a symlink")
    root = supplied.resolve()
    output = args.output.resolve()
    if output == root or root in output.parents:
        raise SystemExit("verification output must remain outside the sealed artifact")
    files, unsafe = inventory(root)
    failures.extend(unsafe)
    for required in ("MANIFEST.json", "SHA256SUMS", "verification.json"):
        if required not in files:
            failures.append(f"missing required control file: {required}")
    if failures:
        manifest: dict[str, Any] = {}
        checksums: dict[str, Any] = {}
        verification: dict[str, Any] = {}
    else:
        manifest = load_object(files["MANIFEST.json"])
        checksums = load_object(files["SHA256SUMS"])
        verification = load_object(files["verification.json"])

    run_id = args.expected_run_id or root.name
    if not (
        manifest.get("schema_version") == "nndv-0.7.1-artifact-manifest-1"
        and manifest.get("release") == RELEASE
        and manifest.get("run_id") == run_id
        and isinstance(manifest.get("entries"), dict)
    ):
        failures.append("artifact MANIFEST identity or entries are invalid")
    manifest_entries = manifest.get("entries", {}) if isinstance(manifest.get("entries"), dict) else {}
    actual_manifest_paths = set(files) - CONTROL_FILES
    if set(manifest_entries) != actual_manifest_paths:
        failures.append("MANIFEST path set does not exactly match artifact payload")
    for name in sorted(set(manifest_entries).intersection(files)):
        claim = manifest_entries[name]
        path = files[name]
        if not isinstance(claim, dict) or claim.get("bytes") != path.stat().st_size or claim.get("sha256") != sha256(path):
            failures.append(f"MANIFEST claim mismatch: {name}")

    checksum_entries = checksums.get("entries")
    if not (
        checksums.get("schema_version") == "nndv-sha256-manifest-2"
        and checksums.get("algorithm") == "sha256"
        and checksums.get("checksum_excludes") == ["SHA256SUMS"]
        and isinstance(checksum_entries, list)
    ):
        failures.append("SHA256SUMS document identity is invalid")
        checksum_entries = []
    checksum_by_path: dict[str, dict[str, Any]] = {}
    for item in checksum_entries:
        if not isinstance(item, dict):
            continue
        item_path = item.get("path")
        if isinstance(item_path, str):
            checksum_by_path[item_path] = item
    if set(checksum_by_path) != set(files) - {"SHA256SUMS"}:
        failures.append("SHA256SUMS path set does not exactly match sealed files")
    for name, claim in checksum_by_path.items():
        candidate = files.get(name)
        if (
            candidate is None
            or claim.get("size") != candidate.stat().st_size
            or claim.get("sha256") != sha256(candidate)
        ):
            failures.append(f"SHA256SUMS claim mismatch: {name}")

    if not (
        verification.get("schema_version") == "nndv-0.7.1-verification-1"
        and verification.get("release") == RELEASE
        and verification.get("status") == "PASS"
        and verification.get("run_id") == run_id
        and verification.get("failures") == []
        and verification.get("human_evidence", {}).get("participants") == 0
        and verification.get("human_evidence", {}).get("automated_evidence_is_human_evidence") is False
        and verification.get("git_operations") is False
        and verification.get("uploaded_or_published") is False
    ):
        failures.append("verification identity, status, or human/external-action boundary is invalid")

    python = verification.get("python", {})
    if not (
        isinstance(python.get("collected"), int)
        and python.get("collected", 0) >= 328
        and python.get("collected") == python.get("passed")
        and python.get("failed") == 0
        and python.get("errors") == 0
        and python.get("skipped") == 0
        and python.get("deselected") == 0
        and python.get("inherited_0_7_0_tests") == 328
        and python.get("baseline_0_7_0_missing") == []
    ):
        failures.append("verification does not retain an exact all-pass 328-test parent baseline")
    gates = verification.get("coverage", {}).get("gates", {})
    if not all(gates.get(name) is True for name in (
        "old_core_passed", "expanded_core_passed", "all_package_passed", "scene_core_80_percent",
    )):
        failures.append("verification coverage gates are incomplete")
    scene = verification.get("scene", {})
    if not (
        scene.get("scene_ir") == "1.0"
        and scene.get("project_schema") == "1.4"
        and scene.get("templates") == 7
        and scene.get("real_models") == 7
        and scene.get("cases") == 14
        and scene.get("exports") == 140
        and scene.get("projects") == 14
        and scene.get("comparisons") == 14
        and scene.get("true_3d_independent_validation") == "PASS"
        and scene.get("strict_svg_oracle") == "PASS"
        and scene.get("pdf_tikz_publication_oracle") == "PASS"
        and scene.get("visual_oracle_truth_fixtures") == "PASS"
        and scene.get("before_after_cases") == 14
    ):
        failures.append("verification Scene corpus accounting is incomplete")
    performance = verification.get("performance", {})
    if not (
        performance.get("status") == "PASS"
        and performance.get("repeats", 0) >= 3
        and performance.get("failures") == []
    ):
        failures.append("verification performance report is not an all-pass three-run measurement")
    visual_evidence = verification.get("visual_evidence", {})
    if not (
        visual_evidence.get("status") == "PASS"
        and isinstance(visual_evidence.get("screenshots"), int)
        and visual_evidence.get("screenshots", 0) >= 44
        and visual_evidence.get("downloads") == 10
        and visual_evidence.get("real_model_2d_3d_pairs") == 7
        and visual_evidence.get("scene_template_architectures") == 7
        and visual_evidence.get("svg_visual_oracle") == "PASS"
        and visual_evidence.get("strict_fourteen_svg_oracle") == "PASS"
        and visual_evidence.get("cross_format_publication_oracle") == "PASS"
        and visual_evidence.get("visual_oracle_truth_fixtures") == "PASS"
        and visual_evidence.get("before_after_cases") == 14
        and isinstance(visual_evidence.get("screenshot_tree_digest"), str)
        and len(visual_evidence.get("screenshot_tree_digest", "")) == 64
        and isinstance(visual_evidence.get("download_tree_digest"), str)
        and len(visual_evidence.get("download_tree_digest", "")) == 64
    ):
        failures.append("verification visual-evidence summary is incomplete")

    report_paths = verification.get("reports", {})
    if not isinstance(report_paths, dict):
        failures.append("verification report index is missing")
        report_paths = {}
    if report_paths != REQUIRED_REPORTS:
        failures.append("verification report index does not exactly match the required release reports")
    for name, relative in report_paths.items():
        if not isinstance(name, str) or not isinstance(relative, str) or relative not in files:
            failures.append(f"verification report path is missing: {name}={relative!r}")
    if report_paths == REQUIRED_REPORTS and all(relative in files for relative in REQUIRED_REPORTS.values()):
        raw_reports = {
            name: load_object(files[relative])
            for name, relative in REQUIRED_REPORTS.items()
        }
        failures.extend(report_failures(raw_reports))
        failures.extend(payload_failures(root, raw_reports))
        raw_visual = raw_reports["visual"]
        expected_visual_summary = {
            "status": raw_visual.get("status"),
            "screenshots": raw_visual.get("counts", {}).get("screenshots_validated"),
            "downloads": raw_visual.get("counts", {}).get("downloads_validated"),
            "real_model_2d_3d_pairs": raw_visual.get("counts", {}).get("architecture_2d_3d_pairs"),
            "scene_template_architectures": raw_visual.get("counts", {}).get("scene_template_architectures"),
            "svg_visual_oracle": raw_visual.get("svg_visual_oracle", {}).get("status"),
            "strict_fourteen_svg_oracle": raw_reports["svg_oracle"].get("status"),
            "cross_format_publication_oracle": raw_reports["publication_oracle"].get("status"),
            "visual_oracle_truth_fixtures": raw_reports["oracle_fixtures"].get("status"),
            "before_after_cases": raw_reports["before_after"].get("case_count"),
            "screenshot_tree_digest": raw_visual.get("screenshot_tree_digest"),
            "download_tree_digest": raw_visual.get("download_tree_digest"),
        }
        if visual_evidence != expected_visual_summary:
            failures.append("verification visual-evidence summary does not exactly match its raw validated report")
    migration_relative = report_paths.get("migration")
    if isinstance(migration_relative, str) and migration_relative in files:
        migration = load_object(files[migration_relative])
        if not (
            migration.get("schema_version") == "nndv-0.7.1-project-scene-migration-1"
            and migration.get("status") == "PASS"
            and migration.get("counts") == {"expected": 7, "checked": 7, "passed": 7, "failed": 0}
            and migration.get("migration_contract")
            == {
                "graph_ir_mutated": False,
                "figure_ir_mutated": False,
                "scene_geometry_inferred": False,
                "model_semantics_inferred": False,
                "provenance_inferred": False,
            }
            and migration.get("failures") == []
        ):
            failures.append("sealed Project/Scene migration report is incomplete")
    source_relative = report_paths.get("source")
    if isinstance(source_relative, str) and source_relative in files:
        source = load_object(files[source_relative])
        if not (
            source.get("passed") is True
            and source.get("file_count") == manifest.get("source_file_count")
            and source.get("source_tree_digest") == manifest.get("source_digest")
            and source.get("source_tree_digest") == verification.get("source", {}).get("source_tree_digest")
        ):
            failures.append("source snapshot, manifest, and verification identities disagree")

    result = {
        "schema_version": "nndv-0.7.1-artifact-inventory-verification-1",
        "status": "PASS" if not failures else "FAIL",
        "run_id": run_id,
        "artifact": str(root),
        "manifest_entries": len(manifest_entries),
        "manifest_sha256": sha256(files["MANIFEST.json"]) if "MANIFEST.json" in files else None,
        "sha256sums_entries": len(checksum_by_path),
        "sha256sums_sha256": sha256(files["SHA256SUMS"]) if "SHA256SUMS" in files else None,
        "source_file_count": manifest.get("source_file_count"),
        "source_digest": manifest.get("source_digest"),
        "artifact_files": len(files),
        "artifact_bytes": sum(path.stat().st_size for path in files.values()),
        "failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("NNDV_071_ARTIFACT_VERIFY=" + json.dumps({
        "status": result["status"],
        "run_id": run_id,
        "manifest_entries": result["manifest_entries"],
        "source_file_count": result["source_file_count"],
    }, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
