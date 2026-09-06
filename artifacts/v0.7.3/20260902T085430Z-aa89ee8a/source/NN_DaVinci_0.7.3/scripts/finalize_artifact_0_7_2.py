#!/usr/bin/env python3
"""Validate and atomically finalize one fresh NN_DaVinci 0.7.2 artifact."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any

import finalize_artifact_0_7_1 as inherited
from finalize_artifact_0_7_1 import (
    inventory,
    load_object,
    passed,
    scene_e2e_failures,
    sha256,
    visual_evidence_failures,
)


RELEASE = "0.7.2 — Scientific Fidelity & Semantic Scene Hotfix"
PARENT_RUN_ID = "20260831T154536Z-d8ec62b7"
PARENT_SOURCE_FILES = 383
PARENT_SOURCE_DIGEST = "d28a979c588dc998c0816e8757d70bca266d252b9c6f0098d56edd8e3021b2a9"
REPORTS = {
    "quick": "reports/quick/quick-verification.json",
    "scene_corpus": "reports/exports/scene-artifacts.json",
    "scene_corpus_validation": "reports/exports/scene-artifacts-validation.json",
    "performance": "reports/performance/scene-studio.json",
    "audit": "reports/docs/release-audit.json",
    "migration": "reports/migration/project-1.3-to-1.4.json",
    "editor": "reports/e2e/editor.json",
    "responsive": "reports/e2e/responsive.json",
    "semantic": "reports/e2e/semantic.json",
    "product": "reports/e2e/product.json",
    "trial": "reports/e2e/trial.json",
    "figure": "reports/e2e/figure-studio.json",
    "scene": "reports/e2e/scene-studio.json",
    "visual": "reports/visual/scene-studio.json",
    "svg_oracle": "reports/visual/scene-svg-oracle.json",
    "publication_oracle": "reports/visual/scene-publication-oracle.json",
    "before_after": "reports/visual/scene-before-after.json",
    "oracle_fixtures": "reports/visual/oracle-fixtures.json",
    "packaging": "reports/packaging/package-install.json",
    "source": "reports/source/snapshot.json",
    "parent_source": "reports/source/parent-0.7.1-snapshot.json",
    "parent_artifact": "reports/source/parent-0.7.1-artifact-verification.json",
    "commands": "reports/full/commands.json",
    "environment": "reports/environment.json",
}
EXPECTED_COMMAND_IDS = (
    "clean-0.7.2-source-snapshot",
    "independent-parent-0.7.1-source-snapshot",
    "parent-0.7.1-source-identity",
    "npm-ci-offline",
    "authoritative-parent-0.7.1-artifact-read-only",
    "authoritative-parent-0.7.1-artifact-identity",
    "quick-0.7.2",
    "release-audit-0.7.2",
    "project-1.3-to-1.4-migration",
    "scene-studio-performance-three-repeats",
    "fresh-fourteen-case-scene-generation",
    "independent-scene-artifact-validation",
    "strict-fourteen-svg-chrome-oracle",
    "independent-pdf-tikz-publication-oracle",
    "fourteen-case-0.7.1-to-0.7.2-before-after-proof",
    "visual-oracle-positive-negative-mutations",
    "e2e-editor",
    "e2e-responsive",
    "e2e-semantic",
    "e2e-product",
    "e2e-trial",
    "e2e-figure-studio",
    "e2e-scene-studio",
    "independent-scene-visual-validation",
    "package-build",
    "wheel-sdist-install-0.7.2",
    "environment-manifest",
)
EXPECTED_CORPUS_COUNTS = {
    "cases": 14,
    "comparison_files": 14,
    "failures": 0,
    "landed_scientific_documents": 28,
    "non_unknown_real_models": 7,
    "passing_cases": 14,
    "projects": 14,
    "real_models": 7,
    "regular_files": 196,
    "scene_exports": 140,
    "semantic_parity_reports": 7,
    "templates": 7,
    "zero_critical_omission_real_models": 7,
}
EXPECTED_VALIDATION_COUNTS = {name: value for name, value in EXPECTED_CORPUS_COUNTS.items() if name != "failures"}


def payload_failures(staging: Path, reports: dict[str, dict[str, Any]]) -> list[str]:
    """Reuse the inherited payload bindings and replace only corpus accounting."""

    inherited.REPORTS = REPORTS
    failures = [
        failure for failure in inherited.payload_failures(staging, reports) if failure != "Scene corpus report is not bound to the exact 168-file payload"
    ]
    corpus_root = staging / "exports" / "scene-corpus"
    corpus = reports["scene_corpus"]
    if corpus_root.is_symlink() or not corpus_root.is_dir():
        failures.append("Scene corpus payload directory is absent or unsafe")
    else:
        files = inventory(corpus_root)
        digest = inherited.canonical_inventory_digest(files)
        if len(files) != 196 or corpus.get("output_file_count") != 196 or digest != corpus.get("output_tree_digest"):
            failures.append("Scene corpus report is not bound to the exact 196-file scientific payload")
    return failures


def report_failures(reports: dict[str, dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    quick = reports["quick"]
    python = quick.get("python", {})
    gates = quick.get("coverage", {}).get("gates", {})
    if not (
        quick.get("schema_version") == "nndv-0.7.2-quick-verification-1"
        and quick.get("release") == RELEASE
        and passed(quick)
        and python.get("collected") == python.get("passed") == 353
        and python.get("failed") == python.get("errors") == python.get("skipped") == python.get("deselected") == 0
        and python.get("inherited_0_7_1_tests") == 342
        and python.get("new_0_7_2_tests") == 11
        and python.get("baseline_0_7_1_missing") == []
        and all(
            gates.get(name) is True
            for name in (
                "old_core_passed",
                "expanded_core_passed",
                "all_package_passed",
                "no_regression_from_0_7_1",
            )
        )
    ):
        failures.append("quick verification does not preserve the exact 342-test parent baseline")

    corpus = reports["scene_corpus"]
    expected_formats = {
        name: 14
        for name in (
            "svg",
            "pdf",
            "tikz",
            "pptx",
            "png",
            "eps",
            "html",
            "json",
            "gltf",
            "glb",
        )
    }
    if not (
        corpus.get("schema_version") == "nndv-0.7.2-scene-artifact-corpus-1"
        and corpus.get("release") == RELEASE
        and passed(corpus)
        and corpus.get("fresh_outputs") is True
        and corpus.get("offline_generation") is True
        and corpus.get("weights_downloaded") is False
        and corpus.get("counts") == EXPECTED_CORPUS_COUNTS
        and corpus.get("format_counts") == expected_formats
        and corpus.get("failures") == []
    ):
        failures.append("fresh fourteen-case scientific Scene corpus is incomplete or failed")
    validation = reports["scene_corpus_validation"]
    if not (
        validation.get("schema_version") == "nndv-0.7.2-scene-artifact-validation-1"
        and validation.get("status") == "PASS"
        and validation.get("validator_is_independent_of_generator") is True
        and validation.get("counts") == EXPECTED_VALIDATION_COUNTS
        and validation.get("failures") == []
    ):
        failures.append("independent scientific Scene validation did not pass all fourteen cases")

    svg = reports["svg_oracle"]
    if not (
        svg.get("oracle") == "scene-publication-svg-chrome-v1"
        and svg.get("status") == "PASS"
        and svg.get("caseCount") == 14
        and len(svg.get("cases", [])) == 14
        and all(item.get("status") == "PASS" for item in svg.get("cases", []))
        and svg.get("failures") == []
    ):
        failures.append("strict landed-output Chrome SVG oracle did not pass all fourteen cases")
    publication = reports["publication_oracle"]
    if not (
        publication.get("oracle") == "scene-publication-cross-format-v1"
        and publication.get("status") == "PASS"
        and publication.get("case_count") == 14
        and publication.get("formats_status") == "PASS"
        and publication.get("true_3d_status") == "PASS"
        and publication.get("publication_status") == "PASS"
        and publication.get("failures") == []
    ):
        failures.append("independent embedded-font PDF/TikZ/true-3D oracle did not pass")
    before_after = reports["before_after"]
    if not (
        before_after.get("schema_version") == "nndv-0.7.2-scene-before-after-report-1"
        and before_after.get("release") == RELEASE
        and before_after.get("status") == "PASS"
        and before_after.get("before")
        == {
            "release": "0.7.1",
            "run_id": PARENT_RUN_ID,
            "read_only": True,
        }
        and before_after.get("after") == {"release": "0.7.2", "fresh_current_output": True}
        and before_after.get("case_count") == 14
        and before_after.get("proof_png_count") == 42
        and before_after.get("original_pixels_preserved") is True
        and all(item.get("status") == "PASS" for item in before_after.get("cases", []))
        and sum(item.get("changed") is True for item in before_after.get("cases", [])) == 7
        and sum(item.get("changed") is False for item in before_after.get("cases", [])) == 7
        and before_after.get("failures") == []
    ):
        failures.append("fourteen-case 0.7.1→0.7.2 before/after proof is incomplete")

    fixtures = reports["oracle_fixtures"]
    if not (
        fixtures.get("schema_version") == "nndv-0.7.1-visual-oracle-fixture-report-1"
        and fixtures.get("status") == "PASS"
        and fixtures.get("constant_true_rejected") is True
        and fixtures.get("failures") == []
    ):
        failures.append("positive/negative/mutation visual-oracle fixtures did not pass")
    performance = reports["performance"]
    if not (
        performance.get("schema_version") == "nndv-0.7.1-scene-studio-performance-1"
        and passed(performance)
        and performance.get("repeats", 0) >= 3
        and performance.get("failures") == []
    ):
        failures.append("Scene and retained Figure performance gates did not pass")
    audit = reports["audit"]
    if not (
        audit.get("schema_version") == "nndv-0.7.2-release-audit-1"
        and audit.get("release") == RELEASE
        and audit.get("status") == "PASS"
        and audit.get("failures") == []
        and audit.get("human_participants") == 0
    ):
        failures.append("0.7.2 release and documentation audit did not pass")
    migration = reports["migration"]
    if not (
        migration.get("schema_version") == "nndv-0.7.1-project-scene-migration-1"
        and passed(migration)
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
        failures.append("Project 1.3→1.4 migration evidence is incomplete or invents semantics")

    editor = reports["editor"]
    editor_counts = editor.get("counts", {})
    if not (
        editor.get("schema_version") == "1.0"
        and editor_counts.get("e2e_scenarios", 0) >= 11
        and editor_counts.get("passed") == editor_counts.get("e2e_scenarios")
        and editor_counts.get("failed") == editor_counts.get("skipped") == 0
        and editor_counts.get("assertions", 0) >= 71
        and all(item.get("status") == "passed" and item.get("console_errors") == [] for item in editor.get("scenarios", []))
    ):
        failures.append("editor Chrome E2E did not retain all inherited scenarios")
    e2e_contracts = {
        "responsive": ("0.5.2-responsive-workspace-e2e-1", 168),
        "semantic": ("0.3.0-semantic-workflow-1", 28),
        "product": ("0.5.1-product-workflow-1", 32),
        "trial": ("0.5.1-trial-workflow-e2e-1", 65),
    }
    for name, (schema, minimum) in e2e_contracts.items():
        report = reports[name]
        if report.get("schema_version") != schema or report.get("status") != "passed" or report.get("assertion_count", 0) < minimum:
            failures.append(f"{name} Chrome E2E did not pass its inherited assertion contract")
    figure = reports["figure"]
    figure_counts = figure.get("counts", {})
    if not (
        figure.get("schema_version") == "nndv-0.6.1-figure-studio-e2e-1"
        and figure.get("status") == "PASS"
        and figure_counts.get("passed") == figure_counts.get("scenarios")
        and figure_counts.get("failed") == figure_counts.get("skipped") == 0
        and figure_counts.get("assertions", 0) >= 75
        and figure_counts.get("console_page_request_errors") == 0
        and figure.get("errors") == []
    ):
        failures.append("Figure Studio Chrome E2E did not retain its inherited workflow")
    failures.extend(scene_e2e_failures(reports["scene"]))
    failures.extend(visual_evidence_failures(reports["visual"], reports["scene"]))
    if reports["trial"].get("human_participants") != 0:
        failures.append("automated Trial evidence was represented as human evidence")

    packaging = reports["packaging"]
    if not (
        packaging.get("checks", 0) >= 16
        and packaging.get("passed") is True
        and all(
            packaging.get(name) is True
            for name in (
                "wheel_installed_with_dependencies",
                "sdist_installed_with_dependencies",
                "pip_check_passed",
                "web_assets",
                "figure_templates",
                "scene_templates",
                "cli_smoke",
                "lock_matches",
            )
        )
        and packaging.get("wheel_install", {}).get("version") == "0.7.2"
        and packaging.get("sdist_install", {}).get("version") == "0.7.2"
        and packaging.get("wheel_install", {}).get("passed") is True
        and packaging.get("sdist_install", {}).get("passed") is True
    ):
        failures.append("0.7.2 wheel/sdist installation verification did not pass")

    commands = reports["commands"]
    command_records = commands.get("commands", [])
    observed_ids = tuple(item.get("id") for item in command_records if isinstance(item, dict))
    if not (
        commands.get("schema_version") == "nndv-0.7.2-full-command-report-1"
        and commands.get("release") == RELEASE
        and commands.get("fresh_control_root") is True
        and commands.get("old_artifacts_used_as_current_output") is False
        and commands.get("failed") == 0
        and commands.get("completed") == commands.get("command_count") == len(EXPECTED_COMMAND_IDS)
        and observed_ids == EXPECTED_COMMAND_IDS
        and all(
            item.get("exit_code") == 0
            and item.get("sequence") == index
            and isinstance(item.get("argv"), list)
            and item.get("argv")
            and isinstance(item.get("log"), str)
            and item.get("log")
            for index, item in enumerate(command_records, 1)
        )
    ):
        failures.append("full command accounting contains a failure or unexpected command")

    source = reports["source"]
    source_files = source.get("files", {})
    if not (
        source.get("schema_version") == "nndv-clean-source-snapshot-2"
        and source.get("passed") is True
        and source.get("release") == "0.7.2"
        and isinstance(source.get("file_count"), int)
        and source.get("file_count", 0) > PARENT_SOURCE_FILES
        and isinstance(source_files, dict)
        and len(source_files) == source.get("file_count")
        and source.get("forbidden_paths") == []
        and isinstance(source.get("source_tree_digest"), str)
        and len(source.get("source_tree_digest")) == 64
    ):
        failures.append("fresh 0.7.2 clean-source snapshot is invalid")
    parent_source = reports["parent_source"]
    if not (
        parent_source.get("passed") is True
        and parent_source.get("schema_version") == "nndv-clean-source-snapshot-2"
        and parent_source.get("release") == "0.7.1"
        and parent_source.get("file_count") == PARENT_SOURCE_FILES
        and len(parent_source.get("files", {})) == PARENT_SOURCE_FILES
        and parent_source.get("source_tree_digest") == PARENT_SOURCE_DIGEST
        and parent_source.get("forbidden_paths") == []
    ):
        failures.append("frozen parent source no longer matches its authoritative 383-file digest")
    parent_artifact = reports["parent_artifact"]
    if not (
        parent_artifact.get("status") == "PASS"
        and parent_artifact.get("run_id") == PARENT_RUN_ID
        and parent_artifact.get("source_file_count") == PARENT_SOURCE_FILES
        and parent_artifact.get("source_digest") == PARENT_SOURCE_DIGEST
        and parent_artifact.get("failures") == []
    ):
        failures.append("authoritative 0.7.1 parent artifact verification did not pass")
    environment = reports["environment"]
    expected_sources = {name: item.get("sha256") for name, item in source_files.items() if isinstance(name, str) and isinstance(item, dict)}
    if not (
        environment.get("project_version") == "0.7.2"
        and environment.get("git_repository") is False
        and isinstance(environment.get("python"), str)
        and isinstance(environment.get("hardware"), dict)
        and environment.get("tools", {}).get("browser")
        and environment.get("tools", {}).get("node")
        and environment.get("tools", {}).get("npm")
        and environment.get("sources") == expected_sources
    ):
        failures.append("environment manifest is absent or not bound to the clean source snapshot")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--started-utc", required=True)
    parser.add_argument("--started-epoch", type=int, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9._-]+", args.run_id) or args.run_id in {".", ".."}:
        raise SystemExit(f"unsafe 0.7.2 run identifier: {args.run_id!r}")
    if args.staging.is_symlink() or not args.staging.is_dir():
        raise SystemExit("artifact staging root is absent or unsafe")
    staging = args.staging.resolve(strict=True)
    try:
        started = datetime.fromisoformat(args.started_utc.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit("started UTC timestamp is invalid") from exc
    if started.tzinfo is None or abs(started.timestamp() - args.started_epoch) > 2.0:
        raise SystemExit("started UTC and epoch values disagree")
    if args.started_epoch > time.time() + 1.0:
        raise SystemExit("started epoch lies in the future")

    reports: dict[str, dict[str, Any]] = {}
    for name, relative in REPORTS.items():
        path = staging / relative
        if not path.is_file() or path.is_symlink():
            raise SystemExit(f"required release report is absent or unsafe: {relative}")
        reports[name] = load_object(path)
    failures = [*report_failures(reports), *payload_failures(staging, reports)]
    if failures:
        raise SystemExit("0.7.2 artifact preconditions failed:\n- " + "\n- ".join(failures))

    quick = reports["quick"]
    corpus = reports["scene_corpus"]
    visual = reports["visual"]
    verification = {
        "schema_version": "nndv-0.7.2-verification-1",
        "release": RELEASE,
        "status": "PASS",
        "run_id": args.run_id,
        "started_utc": args.started_utc,
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.time() - args.started_epoch, 3),
        "parent": {
            "release": "0.7.1",
            "run_id": PARENT_RUN_ID,
            "source_files": PARENT_SOURCE_FILES,
            "source_digest": PARENT_SOURCE_DIGEST,
            "artifact_verification": "PASS",
        },
        "python": quick["python"],
        "coverage": quick["coverage"],
        "scientific_fidelity": {
            "architecture_evidence_version": "1.0",
            "non_unknown_real_models": corpus["counts"]["non_unknown_real_models"],
            "landed_graph_semantic_figure_scene_documents": corpus["counts"]["landed_scientific_documents"],
            "independent_parity_reports": corpus["counts"]["semantic_parity_reports"],
            "zero_critical_omission_real_models": corpus["counts"]["zero_critical_omission_real_models"],
            "name_or_layout_inference_forbidden": True,
        },
        "scene": {
            "scene_ir": "1.0",
            "project_schema": "1.4",
            "templates": corpus["counts"]["templates"],
            "real_models": corpus["counts"]["real_models"],
            "cases": corpus["counts"]["cases"],
            "exports": corpus["counts"]["scene_exports"],
            "projects": corpus["counts"]["projects"],
            "comparisons": corpus["counts"]["comparison_files"],
            "regular_files": corpus["counts"]["regular_files"],
            "true_3d_independent_validation": "PASS",
            "strict_svg_oracle": reports["svg_oracle"]["status"],
            "pdf_tikz_publication_oracle": reports["publication_oracle"]["status"],
            "visual_oracle_truth_fixtures": reports["oracle_fixtures"]["status"],
            "before_after_cases": reports["before_after"]["case_count"],
        },
        "chrome": {
            "suites": 7,
            "scene_assertions": reports["scene"].get(
                "assertion_count",
                len(reports["scene"].get("assertions", [])),
            ),
            "scene_viewports": reports["scene"].get("viewports", []),
            "scene_browser_errors": len(reports["scene"].get("browser_errors", [])),
        },
        "visual_evidence": {
            "status": visual["status"],
            "screenshots": visual["counts"]["screenshots_validated"],
            "downloads": visual["counts"]["downloads_validated"],
            "real_model_2d_3d_pairs": visual["counts"]["architecture_2d_3d_pairs"],
            "scene_template_architectures": visual["counts"]["scene_template_architectures"],
            "svg_visual_oracle": visual["svg_visual_oracle"]["status"],
            "strict_fourteen_svg_oracle": reports["svg_oracle"]["status"],
            "cross_format_publication_oracle": reports["publication_oracle"]["status"],
            "visual_oracle_truth_fixtures": reports["oracle_fixtures"]["status"],
            "before_after_cases": reports["before_after"]["case_count"],
            "screenshot_tree_digest": visual["screenshot_tree_digest"],
            "download_tree_digest": visual["download_tree_digest"],
        },
        "performance": reports["performance"],
        "source": {
            "file_count": reports["source"]["file_count"],
            "source_tree_digest": reports["source"]["source_tree_digest"],
            "allowlist_sha256": reports["source"]["allowlist_sha256"],
        },
        "reports": REPORTS,
        "human_evidence": {
            "participants": 0,
            "completed_sessions": 0,
            "usability": None,
            "ease_or_learnability": None,
            "task_success": None,
            "first_figure_time": None,
            "paper_ready_time": None,
            "automated_evidence_is_human_evidence": False,
        },
        "git_operations": False,
        "uploaded_or_published": False,
        "failures": [],
    }

    if args.artifact_root.is_symlink():
        raise SystemExit("artifact root may not be a symlink")
    artifact_root = args.artifact_root.resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    target = artifact_root / args.run_id
    candidate = artifact_root / f".{args.run_id}.staging"
    prepublish = artifact_root / f".{args.run_id}.prepublish-verification.json"
    if target.exists() or candidate.exists() or prepublish.exists() or prepublish.is_symlink():
        raise SystemExit(f"refusing to overwrite existing artifact path for {args.run_id}")
    try:
        shutil.copytree(staging, candidate)
        (candidate / "verification.json").write_text(
            json.dumps(verification, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        entries = inventory(candidate, exclude={"MANIFEST.json", "SHA256SUMS"})
        manifest = {
            "schema_version": "nndv-0.7.2-artifact-manifest-1",
            "release": RELEASE,
            "run_id": args.run_id,
            "source_file_count": reports["source"]["file_count"],
            "source_digest": reports["source"]["source_tree_digest"],
            "entries": {name: {"bytes": path.stat().st_size, "sha256": sha256(path)} for name, path in entries.items()},
        }
        (candidate / "MANIFEST.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        seal = subprocess.run(
            [sys.executable, str(args.project_root / "scripts" / "seal_evidence.py"), str(candidate)],
            check=False,
            capture_output=True,
            text=True,
        )
        if seal.returncode:
            raise RuntimeError(seal.stderr or seal.stdout)
        independent = subprocess.run(
            [
                sys.executable,
                str(args.project_root / "scripts" / "verify_release_artifact_0_7_2.py"),
                str(candidate),
                "--expected-run-id",
                args.run_id,
                "--output",
                str(prepublish),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if independent.returncode:
            raise RuntimeError(independent.stderr or independent.stdout)
        os.replace(candidate, target)
    except Exception:
        if candidate.exists():
            shutil.rmtree(candidate)
        raise
    finally:
        prepublish.unlink(missing_ok=True)
    print(f"NNDV_072_ARTIFACT={target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
