#!/usr/bin/env python3
"""Independent, read-only verification for a sealed NN_DaVinci 0.7.2 artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from finalize_artifact_0_7_2 import (
    PARENT_RUN_ID,
    PARENT_SOURCE_DIGEST,
    PARENT_SOURCE_FILES,
    RELEASE,
    REPORTS,
    load_object,
    payload_failures,
    report_failures,
    sha256,
)
from verify_release_artifact_0_7_1 import inventory


CONTROL_FILES = {"MANIFEST.json", "SHA256SUMS"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-run-id")
    args = parser.parse_args()
    failures: list[str] = []
    if args.artifact.is_symlink() or not args.artifact.is_dir():
        raise SystemExit("artifact root is absent or a symlink")
    root = args.artifact.resolve()
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
        manifest.get("schema_version") == "nndv-0.7.2-artifact-manifest-1"
        and manifest.get("release") == RELEASE
        and manifest.get("run_id") == run_id
        and isinstance(manifest.get("entries"), dict)
    ):
        failures.append("artifact MANIFEST identity or entries are invalid")
    manifest_entries = manifest.get("entries", {}) if isinstance(manifest.get("entries"), dict) else {}
    if set(manifest_entries) != set(files) - CONTROL_FILES:
        failures.append("MANIFEST path set does not exactly match artifact payload")
    for name in sorted(set(manifest_entries).intersection(files)):
        claim = manifest_entries[name]
        path = files[name]
        if not (isinstance(claim, dict) and claim.get("bytes") == path.stat().st_size and claim.get("sha256") == sha256(path)):
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
    checksum_by_path = {item["path"]: item for item in checksum_entries if isinstance(item, dict) and isinstance(item.get("path"), str)}
    if set(checksum_by_path) != set(files) - {"SHA256SUMS"}:
        failures.append("SHA256SUMS path set does not exactly match sealed files")
    for name, claim in checksum_by_path.items():
        path = files.get(name)
        if path is None or claim.get("size") != path.stat().st_size or claim.get("sha256") != sha256(path):
            failures.append(f"SHA256SUMS claim mismatch: {name}")

    if not (
        verification.get("schema_version") == "nndv-0.7.2-verification-1"
        and verification.get("release") == RELEASE
        and verification.get("status") == "PASS"
        and verification.get("run_id") == run_id
        and verification.get("failures") == []
        and verification.get("parent")
        == {
            "release": "0.7.1",
            "run_id": PARENT_RUN_ID,
            "source_files": PARENT_SOURCE_FILES,
            "source_digest": PARENT_SOURCE_DIGEST,
            "artifact_verification": "PASS",
        }
        and verification.get("human_evidence", {}).get("participants") == 0
        and verification.get("human_evidence", {}).get("automated_evidence_is_human_evidence") is False
        and verification.get("git_operations") is False
        and verification.get("uploaded_or_published") is False
    ):
        failures.append("verification identity, parent, or external-action boundary is invalid")

    python = verification.get("python", {})
    if not (
        python.get("collected") == python.get("passed") == 353
        and python.get("failed") == python.get("errors") == python.get("skipped") == python.get("deselected") == 0
        and python.get("inherited_0_7_1_tests") == 342
        and python.get("new_0_7_2_tests") == 11
        and python.get("baseline_0_7_1_missing") == []
    ):
        failures.append("verification does not retain the exact all-pass 342-test parent baseline")
    gates = verification.get("coverage", {}).get("gates", {})
    if not all(
        gates.get(name) is True
        for name in (
            "old_core_passed",
            "expanded_core_passed",
            "all_package_passed",
            "no_regression_from_0_7_1",
        )
    ):
        failures.append("verification coverage gates are incomplete")

    fidelity = verification.get("scientific_fidelity", {})
    if not (
        fidelity.get("architecture_evidence_version") == "1.0"
        and fidelity.get("non_unknown_real_models") == 7
        and fidelity.get("landed_graph_semantic_figure_scene_documents") == 28
        and fidelity.get("independent_parity_reports") == 7
        and fidelity.get("zero_critical_omission_real_models") == 7
        and fidelity.get("name_or_layout_inference_forbidden") is True
    ):
        failures.append("verification scientific-fidelity summary is incomplete")
    scene = verification.get("scene", {})
    if not (
        scene.get("scene_ir") == "1.0"
        and scene.get("project_schema") == "1.4"
        and scene.get("templates") == scene.get("real_models") == 7
        and scene.get("cases") == 14
        and scene.get("exports") == 140
        and scene.get("projects") == scene.get("comparisons") == 14
        and scene.get("regular_files") == 196
        and scene.get("true_3d_independent_validation") == "PASS"
        and scene.get("strict_svg_oracle") == "PASS"
        and scene.get("pdf_tikz_publication_oracle") == "PASS"
        and scene.get("visual_oracle_truth_fixtures") == "PASS"
        and scene.get("before_after_cases") == 14
    ):
        failures.append("verification Scene corpus accounting is incomplete")
    performance = verification.get("performance", {})
    if performance.get("status") != "PASS" or performance.get("repeats", 0) < 3 or performance.get("failures") != []:
        failures.append("verification performance report is not an all-pass three-run measurement")
    visual = verification.get("visual_evidence", {})
    if not (
        visual.get("status") == "PASS"
        and visual.get("screenshots", 0) >= 44
        and visual.get("downloads") == 10
        and visual.get("real_model_2d_3d_pairs") == 7
        and visual.get("scene_template_architectures") == 7
        and visual.get("svg_visual_oracle") == "PASS"
        and visual.get("strict_fourteen_svg_oracle") == "PASS"
        and visual.get("cross_format_publication_oracle") == "PASS"
        and visual.get("visual_oracle_truth_fixtures") == "PASS"
        and visual.get("before_after_cases") == 14
        and isinstance(visual.get("screenshot_tree_digest"), str)
        and len(visual.get("screenshot_tree_digest")) == 64
        and isinstance(visual.get("download_tree_digest"), str)
        and len(visual.get("download_tree_digest")) == 64
    ):
        failures.append("verification visual-evidence summary is incomplete")

    report_paths = verification.get("reports", {})
    if report_paths != REPORTS:
        failures.append("verification report index does not exactly match required reports")
    for name, relative in REPORTS.items():
        if relative not in files:
            failures.append(f"verification report path is missing: {name}={relative}")
    if report_paths == REPORTS and all(relative in files for relative in REPORTS.values()):
        raw_reports = {name: load_object(files[relative]) for name, relative in REPORTS.items()}
        failures.extend(report_failures(raw_reports))
        failures.extend(payload_failures(root, raw_reports))
        expected_visual = {
            "status": raw_reports["visual"].get("status"),
            "screenshots": raw_reports["visual"].get("counts", {}).get("screenshots_validated"),
            "downloads": raw_reports["visual"].get("counts", {}).get("downloads_validated"),
            "real_model_2d_3d_pairs": raw_reports["visual"].get("counts", {}).get("architecture_2d_3d_pairs"),
            "scene_template_architectures": raw_reports["visual"].get("counts", {}).get("scene_template_architectures"),
            "svg_visual_oracle": raw_reports["visual"].get("svg_visual_oracle", {}).get("status"),
            "strict_fourteen_svg_oracle": raw_reports["svg_oracle"].get("status"),
            "cross_format_publication_oracle": raw_reports["publication_oracle"].get("status"),
            "visual_oracle_truth_fixtures": raw_reports["oracle_fixtures"].get("status"),
            "before_after_cases": raw_reports["before_after"].get("case_count"),
            "screenshot_tree_digest": raw_reports["visual"].get("screenshot_tree_digest"),
            "download_tree_digest": raw_reports["visual"].get("download_tree_digest"),
        }
        if visual != expected_visual:
            failures.append("verification visual summary disagrees with its raw validated report")

    source = verification.get("source", {})
    if not (
        source.get("file_count") == manifest.get("source_file_count")
        and source.get("source_tree_digest") == manifest.get("source_digest")
        and isinstance(source.get("allowlist_sha256"), str)
        and len(source.get("allowlist_sha256")) == 64
    ):
        failures.append("source snapshot, manifest, and verification identities disagree")

    result = {
        "schema_version": "nndv-0.7.2-artifact-inventory-verification-1",
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
        "failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "NNDV_072_ARTIFACT_VERIFY="
        + json.dumps(
            {
                "status": result["status"],
                "run_id": run_id,
                "artifact_files": len(files),
                "failures": len(failures),
            },
            sort_keys=True,
        )
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
