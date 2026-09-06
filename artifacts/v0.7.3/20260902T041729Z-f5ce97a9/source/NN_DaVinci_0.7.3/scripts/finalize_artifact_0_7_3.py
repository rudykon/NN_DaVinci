#!/usr/bin/env python3
"""Validate and atomically seal one fresh NN_DaVinci 0.7.3 artifact."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import time
from typing import Any


RELEASE = "0.7.3 — Reader-Visible Scientific Completeness & Generalization Hotfix"
PARENT_RUN_ID = "20260901T142604Z-010606e8"
PARENT_SOURCE_FILES = 410
PARENT_SOURCE_DIGEST = "6d4591e41fd423604fe3537aba200bcdd57e4254c0684dc6bd5b3672fd9c169e"
PARENT_TEST_IDS_SHA256 = "934f1c14e1dc3e31d9a314d7f05fd2d0eab2afb54106f72f3f4b9a1b28bd331b"
EXPECTED_ROLES_ROUTES = {
    "resnet50": (6, 4),
    "vision_transformer": (5, 1),
    "bert_encoder": (5, 1),
    "multiscale_unet": (9, 3),
    "diffusion_unet": (6, 3),
    "topk_moe": (5, 5),
    "image_text": (4, 2),
}
REPORTS = {
    "quick": "reports/quick/quick-verification.json",
    "source": "reports/source/snapshot.json",
    "parent_source": "reports/source/parent-0.7.2-snapshot.json",
    "parent_artifact": "reports/source/parent-0.7.2-artifact-verification.json",
    "audit": "reports/docs/release-audit.json",
    "corpus": "reports/exports/scene-artifacts.json",
    "corpus_validation": "reports/exports/scene-artifacts-validation.json",
    "svg_geometry": "reports/visual/scene-svg-oracle.json",
    "publication": "reports/visual/scene-publication-oracle.json",
    "tikz_proofs": "reports/semantic/tikz-pdf-proofs.json",
    "semantic_dom": "reports/semantic/browser-dom.json",
    "semantic_presentation": "reports/semantic/presentation.json",
    "semantic_matrix": "reports/semantic/completeness-matrix.json",
    "semantic_mutations": "reports/semantic/negative-mutations.json",
    "generalization": "reports/generalization/metamorphic-corpus.json",
    "performance": "reports/performance/scene-studio.json",
    "service": "reports/service/lifecycle.json",
    "before_after": "reports/visual/before-after.json",
    "visual_inspection": "reports/visual/original-resolution-inspection.json",
    "scene_visual": "reports/visual/scene-studio.json",
    "e2e_aggregate": "reports/e2e/aggregate.json",
    "e2e_editor": "reports/e2e/editor.json",
    "e2e_responsive": "reports/e2e/responsive.json",
    "e2e_semantic": "reports/e2e/semantic.json",
    "e2e_product": "reports/e2e/product.json",
    "e2e_trial": "reports/e2e/trial.json",
    "e2e_figure": "reports/e2e/figure-studio.json",
    "e2e_scene": "reports/e2e/scene-studio.json",
    "packaging": "reports/packaging/package-install.json",
    "environment": "reports/environment.json",
    "commands": "reports/full/commands.json",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON document is not an object: {path}")
    return value


def inventory(root: Path, *, excluded: set[str] | None = None) -> tuple[dict[str, Path], list[str]]:
    excluded = excluded or set()
    files: dict[str, Path] = {}
    unsafe: list[str] = []
    for directory, names, filenames in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in list(names):
            path = base / name
            relative = path.relative_to(root).as_posix()
            mode = os.lstat(path).st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                unsafe.append(f"unsafe directory entry: {relative}")
                names.remove(name)
        for name in filenames:
            path = base / name
            relative = path.relative_to(root).as_posix()
            mode = os.lstat(path).st_mode
            if relative in excluded:
                continue
            if stat.S_ISREG(mode):
                files[relative] = path
            else:
                unsafe.append(f"unsafe non-regular file: {relative}")
    return files, unsafe


def source_snapshot_failures(staging: Path, source: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    root = staging / "source" / "NN_DaVinci_0.7.3"
    files, unsafe = inventory(root)
    failures.extend(unsafe)
    claims = source.get("files", {})
    if not isinstance(claims, dict) or set(claims) != set(files):
        failures.append("clean source snapshot inventory does not match its report")
        return failures
    canonical = []
    for relative, path in sorted(files.items()):
        claim = claims[relative]
        digest = sha256(path)
        if claim.get("bytes") != path.stat().st_size or claim.get("sha256") != digest:
            failures.append(f"clean source claim mismatch: {relative}")
        canonical.append(f"{relative}\0{digest}\0{path.stat().st_size}\n")
    digest = hashlib.sha256("".join(canonical).encode()).hexdigest()
    if source.get("file_count") != len(files) or source.get("source_tree_digest") != digest:
        failures.append("clean source count or digest mismatch")
    return failures


def report_failures(reports: dict[str, dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    quick = reports["quick"]
    python = quick.get("python", {})
    coverage = quick.get("coverage", {})
    observed = coverage.get("observed_percent", {})
    floors = coverage.get("authoritative_parent_0_7_2_floors_percent", {})
    if not (
        quick.get("schema_version") == "nndv-0.7.3-quick-verification-1"
        and quick.get("status") == "PASS"
        and python.get("collected") == python.get("passed")
        and python.get("collected", 0) >= 378
        and python.get("inherited_0_7_2_tests") == 353
        and python.get("new_0_7_3_tests") == python.get("collected") - 353
        and python.get("baseline_0_7_2_missing") == []
        and all(python.get(key) == 0 for key in ("failed", "errors", "skipped", "deselected"))
        and set(observed) == set(floors) == {"old_core", "expanded_core", "scene_core", "all_package"}
        and all(observed[name] >= floors[name] for name in floors)
    ):
        failures.append("quick tests, exact parent IDs, or coverage floors did not pass")

    parent_source = reports["parent_source"]
    if not (
        parent_source.get("passed") is True
        and parent_source.get("release") == "0.7.2"
        and parent_source.get("file_count") == PARENT_SOURCE_FILES
        and parent_source.get("source_tree_digest") == PARENT_SOURCE_DIGEST
        and parent_source.get("forbidden_paths") == []
    ):
        failures.append("pinned 0.7.2 source identity is invalid")
    parent_artifact = reports["parent_artifact"]
    if not (
        parent_artifact.get("status") == "PASS"
        and parent_artifact.get("run_id") == PARENT_RUN_ID
        and parent_artifact.get("source_file_count") == PARENT_SOURCE_FILES
        and parent_artifact.get("source_digest") == PARENT_SOURCE_DIGEST
        and parent_artifact.get("failures") == []
    ):
        failures.append("authoritative 0.7.2 artifact verification failed")

    corpus = reports["corpus"]
    counts = corpus.get("counts", {})
    if not (
        corpus.get("schema_version") == "nndv-0.7.3-scene-artifact-corpus-1"
        and corpus.get("status") == "PASS"
        and corpus.get("fresh_outputs") is True
        and corpus.get("offline_generation") is True
        and corpus.get("weights_downloaded") is False
        and counts.get("cases") == 14
        and counts.get("scene_exports") == 140
        and counts.get("regular_files") == 196
        and counts.get("landed_scientific_documents") == 28
        and counts.get("semantic_parity_reports") == 7
        and counts.get("zero_critical_omission_real_models") == 7
        and corpus.get("failures") == []
    ):
        failures.append("fresh fourteen-case/140-export corpus is incomplete")
    validation = reports["corpus_validation"]
    if not (
        validation.get("status") == "PASS"
        and validation.get("validator_is_independent_of_generator") is True
        and validation.get("counts", {}).get("regular_files") == 196
        and validation.get("failures") == []
    ):
        failures.append("independent corpus validation failed")

    svg = reports["svg_geometry"]
    if not (svg.get("status") == "PASS" and svg.get("caseCount") == 14 and svg.get("failures") == []):
        failures.append("fourteen-case Chromium geometry oracle failed")
    publication = reports["publication"]
    if not (
        publication.get("status") == publication.get("formats_status") == publication.get("true_3d_status") == publication.get("publication_status") == "PASS"
        and publication.get("case_count") == 14
        and publication.get("failures") == []
    ):
        failures.append("PDF/TikZ/font/true-3D publication oracle failed")
    if not (reports["tikz_proofs"].get("status") == "PASS" and reports["tikz_proofs"].get("case_count") == 7):
        failures.append("seven compiled TikZ proofs did not pass")
    if not (reports["semantic_dom"].get("status") == "PASS" and len(reports["semantic_dom"].get("cases", [])) == 7):
        failures.append("browser DOM/CTM semantic oracle failed")
    if not (reports["semantic_presentation"].get("status") == "PASS" and reports["semantic_presentation"].get("case_count") == 7):
        failures.append("cross-format semantic presentation oracle failed")

    matrix = reports["semantic_matrix"]
    rows = {row.get("model"): row for row in matrix.get("models", [])}
    if matrix.get("status") != "PASS" or set(rows) != set(EXPECTED_ROLES_ROUTES):
        failures.append("seven-model semantic completeness matrix is incomplete")
    else:
        for model, (roles, routes) in EXPECTED_ROLES_ROUTES.items():
            row = rows[model]
            if not (
                row.get("status") == "PASS"
                and row.get("expected_role_count") == row.get("visible_role_count") == row.get("browser_visible_in_page_role_count") == roles
                and row.get("expected_critical_route_count") == row.get("landed_critical_route_count") == routes
                and all(row.get("format_semantic_consistency", {}).values())
            ):
                failures.append(f"{model}: role/route landing matrix mismatch")

    mutations = reports["semantic_mutations"]
    if not (mutations.get("status") == "PASS" and mutations.get("mutation_count") == 8):
        failures.append("eight semantic negative mutations did not all block")
    generalization = reports["generalization"]
    if not (
        generalization.get("status") == "PASS"
        and generalization.get("seed") == 7300
        and len(generalization.get("real_model_metamorphisms", {})) == 7
        and len(generalization.get("architecture_variants", {})) >= 10
        and generalization.get("failures") == []
    ):
        failures.append("metamorphic/variant generalization corpus failed")

    performance = reports["performance"]
    comparisons = performance.get("required_regression_comparisons", [])
    if not (
        performance.get("schema_version") == "nndv-0.7.3-scene-studio-performance-1"
        and performance.get("status") == "PASS"
        and performance.get("repeats", 0) >= 3
        and len(comparisons) >= 7
        and all(item.get("status") == "PASS" and item.get("regression_percent", 100) <= 20 for item in comparisons)
        and performance.get("failures") == []
    ):
        failures.append("three-repeat performance gate failed")
    service = reports["service"]
    if not (
        service.get("status") == "PASS"
        and service.get("human_participants") == 0
        and service.get("leftover_test_listener") is False
        and len(service.get("steps", [])) == 7
        and service.get("failures") == []
    ):
        failures.append("service lifecycle acceptance failed")

    e2e = reports["e2e_aggregate"]
    if not (
        e2e.get("schema_version") == "nndv-0.7.3-e2e-aggregate-1"
        and e2e.get("status") == "PASS"
        and e2e.get("suite_count") == 7
        and e2e.get("fresh_executions") is True
        and e2e.get("historical_schemas_are_inputs_not_current_schema") is True
        and e2e.get("human_participants") == 0
        and e2e.get("unexpected_browser_errors") == 0
        and e2e.get("failures") == []
    ):
        failures.append("fresh seven-suite E2E aggregate failed")
    scene = reports["e2e_scene"]
    if not (
        scene.get("status") == "PASS"
        and scene.get("succeeded") is True
        and scene.get("assertion_count", 0) >= 131
        and scene.get("browser_errors") == []
        and len(scene.get("viewports", [])) == 7
    ):
        failures.append("Scene WebGL2/CPU fallback E2E failed")

    before = reports["before_after"]
    visual = reports["visual_inspection"]
    if not (
        before.get("status") == "PASS"
        and before.get("case_count") == 14
        and before.get("proof_png_count") == 42
        and before.get("original_pixels_preserved") is True
        and before.get("failures") == []
    ):
        failures.append("original-resolution before/after evidence failed")
    if not (
        visual.get("status") == "PASS"
        and visual.get("inspection_completed") is True
        and visual.get("real_model_count") == 7
        and visual.get("human_participants") == 0
        and visual.get("human_usability_claim") is False
        and visual.get("failures") == []
    ):
        failures.append("direct original-resolution visual inspection record failed")
    scene_visual = reports["scene_visual"]
    if not (scene_visual.get("status") == "PASS" and scene_visual.get("failures") == []):
        failures.append("independent Scene visual evidence validation failed")

    audit = reports["audit"]
    if not (
        audit.get("schema_version") == "nndv-0.7.3-release-audit-1"
        and audit.get("status") == "PASS"
        and audit.get("stale_current_version_blocker") == "PASS"
        and audit.get("generic_role_graph_production_path") == "PASS"
        and audit.get("failures") == []
    ):
        failures.append("release/version hygiene audit failed")
    packaging = reports["packaging"]
    if not (
        packaging.get("passed") is True
        and packaging.get("checks", 0) >= 16
        and packaging.get("lock_matches") is True
        and packaging.get("pip_check_passed") is True
        and packaging.get("wheel_install", {}).get("passed") is True
        and packaging.get("wheel_install", {}).get("version") == "0.7.3"
        and packaging.get("sdist_install", {}).get("passed") is True
        and packaging.get("sdist_install", {}).get("version") == "0.7.3"
    ):
        failures.append("wheel/sdist isolated install failed")
    commands = reports["commands"]
    if not (commands.get("status") == "PASS" and commands.get("failed") == 0 and commands.get("command_count", 0) >= 30):
        failures.append("fresh full command ledger is incomplete")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--started-utc", required=True)
    parser.add_argument("--started-epoch", type=float, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9._-]+", args.run_id):
        raise SystemExit("unsafe run identifier")
    staging = args.staging.resolve(strict=True)
    artifact_root = args.artifact_root.resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    destination = artifact_root / args.run_id
    temporary = artifact_root / f".{args.run_id}.sealing"
    if destination.exists() or temporary.exists():
        raise SystemExit("refusing to overwrite an artifact or incomplete seal")
    files, unsafe = inventory(staging)
    failures = list(unsafe)
    missing = [relative for relative in REPORTS.values() if relative not in files]
    failures.extend(f"missing report: {relative}" for relative in missing)
    reports = {name: load_object(staging / relative) for name, relative in REPORTS.items() if relative not in missing}
    if not missing:
        failures.extend(report_failures(reports))
        failures.extend(source_snapshot_failures(staging, reports["source"]))
    corpus_files, corpus_unsafe = inventory(staging / "exports" / "scene-corpus")
    failures.extend(corpus_unsafe)
    if len(corpus_files) != 196:
        failures.append(f"sealed Scene corpus must contain 196 regular files, found {len(corpus_files)}")
    if failures:
        raise SystemExit("0.7.3 artifact finalization blocked:\n- " + "\n- ".join(failures))

    source = reports["source"]
    quick_python = reports["quick"]["python"]
    matrix_rows = reports["semantic_matrix"]["models"]
    verification = {
        "schema_version": "nndv-0.7.3-verification-1",
        "release": RELEASE,
        "run_id": args.run_id,
        "status": "PASS",
        "failures": [],
        "started_utc": args.started_utc,
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.time() - args.started_epoch, 3),
        "parent_0_7_2": {
            "release": "0.7.2",
            "run_id": PARENT_RUN_ID,
            "source_files": PARENT_SOURCE_FILES,
            "source_digest": PARENT_SOURCE_DIGEST,
            "test_count": 353,
            "test_ids_sha256": PARENT_TEST_IDS_SHA256,
            "artifact_verification": "PASS",
            "read_only": True,
        },
        "python": quick_python,
        "coverage": reports["quick"]["coverage"],
        "semantic_completeness": {
            "status": "PASS",
            "models": matrix_rows,
            "mutation_count": 8,
            "cross_format": ["svg", "pdf", "tikz", "pptx", "tikz_pdf"],
        },
        "generalization": {"status": "PASS", "real_metamorphisms": 7, "variants": len(reports["generalization"]["architecture_variants"]), "seed": 7300},
        "scene": {"status": "PASS", "cases": 14, "exports": 140, "regular_files": 196, "native_pdf_cases": 14, "geometry_failures": 0},
        "chrome": {"status": "PASS", "suites": 7, "assertions": reports["e2e_aggregate"]["assertion_count"], "unexpected_errors": 0},
        "performance": {"status": "PASS", "repeats": reports["performance"]["repeats"], "maximum_regression_percent": max(item["regression_percent"] for item in reports["performance"]["required_regression_comparisons"])},
        "service": {"status": "PASS", "steps": 7, "leftover_test_listener": False},
        "visual_inspection": {"status": "PASS", "real_models": 7, "before_after_cases": 14, "human_participants": 0, "human_usability_claim": False},
        "source": {"file_count": source["file_count"], "source_tree_digest": source["source_tree_digest"], "allowlist_sha256": source["allowlist_sha256"]},
        "reports": REPORTS,
        "human_evidence": {"participants": 0, "automated_evidence_is_human_evidence": False},
        "git_operations": False,
        "uploaded_or_published": False,
    }
    (staging / "verification.json").write_text(json.dumps(verification, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    payload, unsafe = inventory(staging, excluded={"MANIFEST.json", "SHA256SUMS"})
    if unsafe:
        raise SystemExit("unsafe payload appeared before sealing")
    manifest_entries = {
        relative: {"bytes": path.stat().st_size, "sha256": sha256(path), "mode": f"{stat.S_IMODE(os.lstat(path).st_mode):04o}"}
        for relative, path in sorted(payload.items())
    }
    manifest = {
        "schema_version": "nndv-0.7.3-artifact-manifest-1",
        "release": RELEASE,
        "run_id": args.run_id,
        "source_file_count": source["file_count"],
        "source_digest": source["source_tree_digest"],
        "manifest_excludes": ["MANIFEST.json", "SHA256SUMS"],
        "entries": manifest_entries,
    }
    (staging / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    checksum_files, unsafe = inventory(staging, excluded={"SHA256SUMS"})
    if unsafe:
        raise SystemExit("unsafe payload appeared while checksumming")
    checksums = {
        "schema_version": "nndv-sha256-manifest-2",
        "algorithm": "sha256",
        "checksum_excludes": ["SHA256SUMS"],
        "entries": [
            {"path": relative, "size": path.stat().st_size, "sha256": sha256(path)}
            for relative, path in sorted(checksum_files.items())
        ],
    }
    (staging / "SHA256SUMS").write_text(json.dumps(checksums, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    shutil.copytree(staging, temporary, symlinks=False)
    os.replace(temporary, destination)
    print(json.dumps({"status": "PASS", "run_id": args.run_id, "artifact": str(destination), "source_files": source["file_count"], "source_digest": source["source_tree_digest"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
