#!/usr/bin/env python3
"""Finalize one passed, fresh 0.7.1 staging tree using existing sealing."""

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
import subprocess
import sys
import time
from typing import Any


RELEASE = "0.7.1 — 3D Publication Quality & UX Completion"
PARENT_RUN_ID = "20260831T044446Z-9e6cd3cf"
PARENT_SOURCE_DIGEST = "16aa60c611c4cf8c327fe4174314091dcb8dae840dc22ce85f73dae9926fb00d"
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
    "parent_source": "reports/source/parent-0.7.0-snapshot.json",
    "parent_artifact": "reports/source/parent-0.7.0-artifact-verification.json",
    "commands": "reports/full/commands.json",
    "environment": "reports/environment.json",
}
EXPECTED_COMMAND_IDS = (
    "clean-0.7.1-source-snapshot",
    "independent-parent-0.7.0-source-snapshot",
    "parent-0.7.0-source-identity",
    "npm-ci-offline",
    "authoritative-parent-0.7.0-artifact-read-only",
    "authoritative-parent-0.7.0-artifact-identity",
    "quick-0.7.1",
    "release-audit-0.7.1",
    "project-1.3-to-1.4-migration",
    "scene-studio-performance-three-repeats",
    "fresh-fourteen-case-scene-generation",
    "independent-scene-artifact-validation",
    "strict-fourteen-svg-chrome-oracle",
    "independent-pdf-tikz-publication-oracle",
    "fourteen-case-0.7.0-to-0.7.1-before-after-proof",
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
    "wheel-sdist-install-0.7.1",
    "environment-manifest",
)
EXACT_SCENE_VIEWPORTS = (
    (1920, 1080),
    (1440, 900),
    (1280, 720),
    (1024, 768),
    (800, 600),
    (568, 320),
    (390, 844),
)
EXACT_REAL_MODEL_SCENES = {
    "resnet50",
    "vision_transformer",
    "bert_encoder",
    "multiscale_unet",
    "diffusion_unet",
    "topk_moe",
    "image_text",
}
EXACT_SCENE_TEMPLATE_FAMILIES = {
    "cnn",
    "resnet",
    "unet",
    "transformer",
    "moe",
    "multimodal-fusion",
    "diffusion-unet",
}
EXACT_SCENE_WORKFLOWS = {
    "blank_2d_3d",
    "real_model_semantic_scene",
    "structure_lens_scene",
    "autosave_reload",
    "scene_exports_10",
    "selection_provenance_3d_to_2d",
    "error_cancel_retry",
    "architectures_7",
    "scene_templates_7",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def passed(report: dict[str, Any]) -> bool:
    status = str(report.get("status", "")).lower()
    if status in {"fail", "failed", "error"}:
        return False
    if report.get("passed") is False or report.get("succeeded") is False:
        return False
    counts = report.get("counts")
    if isinstance(counts, dict) and counts.get("failed", 0) != 0:
        return False
    return bool(
        status in {"pass", "passed"}
        or report.get("passed") is True
        or report.get("succeeded") is True
        or (isinstance(counts, dict) and counts.get("failed") == 0 and counts.get("passed", 0) > 0)
    )


def canonical_inventory_digest(files: dict[str, Path]) -> str:
    records = [
        {"path": name, "sha256": sha256(path), "bytes": path.stat().st_size}
        for name, path in files.items()
    ]
    payload = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def canonical_evidence_digest(records: list[dict[str, Any]], fields: tuple[str, ...]) -> str:
    selected = [
        {name: item.get(name) for name in fields}
        for item in sorted(records, key=lambda item: str(item.get("path", "")))
    ]
    payload = json.dumps(selected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def scene_e2e_failures(report: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    viewports = report.get("viewports", [])
    observed_viewports = tuple(
        (item.get("width"), item.get("height"))
        for item in viewports
        if isinstance(item, dict)
    ) if isinstance(viewports, list) else ()
    workflows = report.get("required_workflows", {})
    quality = report.get("quality_checks", {})
    label_occlusion = quality.get("scene_label_occlusion", {}) if isinstance(quality, dict) else {}
    architecture_comparisons = report.get("architecture_comparisons", {})
    template_architectures = report.get("scene_template_architectures", {})
    screenshot_manifest = report.get("screenshot_manifest", [])
    download_manifest = report.get("download_manifest", [])
    formats = {
        item.get("format")
        for item in download_manifest
        if isinstance(item, dict) and isinstance(item.get("format"), str)
    } if isinstance(download_manifest, list) else set()
    if not (
        report.get("schema_version") == "nndv-0.7.1-scene-studio-e2e-1"
        and report.get("release") == RELEASE
        and report.get("status") == "PASS"
        and report.get("succeeded") is True
        and report.get("human_participants") == 0
        and report.get("assertion_count", 0) >= 78
        and report.get("browser_errors") == []
        and report.get("failures") == []
        and observed_viewports == EXACT_SCENE_VIEWPORTS
        and isinstance(workflows, dict)
        and set(workflows) == EXACT_SCENE_WORKFLOWS
        and all(value is True for value in workflows.values())
        and isinstance(quality, dict)
        and all(quality.get(name) is True for name in (
            "hidden_line", "contrast", "toolbar", "label", "accessibility_labels",
            "font", "focus", "dialog", "menu", "geometry", "overflow", "stroke",
            "canvas_area", "topbar_clear", "compact_drawers_closed",
        ))
        and isinstance(label_occlusion, dict)
        and label_occlusion.get("passed") is True
        and isinstance(label_occlusion.get("label_count"), int)
        and not isinstance(label_occlusion.get("label_count"), bool)
        and label_occlusion.get("label_count", 0) > 0
        and label_occlusion.get("overlap_count") == 0
        and label_occlusion.get("clipped_count") == 0
        and isinstance(architecture_comparisons, dict)
        and set(architecture_comparisons) == EXACT_REAL_MODEL_SCENES
        and all(
            isinstance(item, dict)
            and isinstance(item.get("non_helper_model_objects"), int)
            and not isinstance(item.get("non_helper_model_objects"), bool)
            and item.get("non_helper_model_objects", 0) > 0
            and isinstance(item.get("route_objects"), int)
            and not isinstance(item.get("route_objects"), bool)
            and item.get("route_objects", 0) > 0
            and isinstance(item.get("visible_labels"), int)
            and not isinstance(item.get("visible_labels"), bool)
            and item.get("visible_labels", 0) > 0
            and isinstance(item.get("two_d"), dict)
            and isinstance(item.get("three_d"), dict)
            for item in architecture_comparisons.values()
        )
        and isinstance(template_architectures, dict)
        and set(template_architectures) == EXACT_SCENE_TEMPLATE_FAMILIES
        and all(
            isinstance(item, dict)
            and isinstance(item.get("non_helper_model_objects"), int)
            and not isinstance(item.get("non_helper_model_objects"), bool)
            and item.get("non_helper_model_objects", 0) > 0
            and isinstance(item.get("route_objects"), int)
            and not isinstance(item.get("route_objects"), bool)
            and item.get("route_objects", 0) > 0
            for item in template_architectures.values()
        )
        and isinstance(screenshot_manifest, list)
        and len(screenshot_manifest) >= 44
        and formats == {"svg", "pdf", "tikz", "pptx", "png", "eps", "html", "json", "gltf", "glb"}
        and len(download_manifest) == 10
    ):
        failures.append("Scene Studio E2E lacks the complete workflow, viewport, visual, or download contract")
    return failures


def visual_evidence_failures(report: dict[str, Any], scene: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    checks = report.get("checks", {})
    counts = report.get("counts", {})
    quality = report.get("quality_evidence", {})
    measurement = report.get("measurement_scope", {})
    oracle = report.get("svg_visual_oracle", {})
    text_oracle = oracle.get("text", {}) if isinstance(oracle, dict) else {}
    stroke_oracle = oracle.get("stroke", {}) if isinstance(oracle, dict) else {}
    route_oracle = oracle.get("routes", {}) if isinstance(oracle, dict) else {}
    hidden_oracle = oracle.get("hidden_line", {}) if isinstance(oracle, dict) else {}
    oracle_source = oracle.get("source", {}) if isinstance(oracle, dict) else {}
    downloads = report.get("downloads", [])
    svg_download = next(
        (
            item
            for item in downloads
            if isinstance(item, dict) and item.get("format") == "svg"
        ),
        None,
    ) if isinstance(downloads, list) else None
    expected_checks = {
        "roots",
        "source_report",
        "schema_and_status",
        "workflows_and_quality",
        "exact_viewports",
        "png_manifest_and_files",
        "visual_coverage",
        "architecture_2d_3d_pairs",
        "scene_template_architectures",
        "download_evidence",
        "svg_visual_oracle",
    }
    if not (
        report.get("schema_version") == "nndv-0.7.1-scene-visual-evidence-validation-1"
        and report.get("release") == RELEASE
        and report.get("status") == "PASS"
        and report.get("validator_is_independent_of_e2e_producer") is True
        and report.get("failures") == []
        and isinstance(checks, dict)
        and set(checks) == expected_checks
        and all(value is True for value in checks.values())
        and report.get("roots") == {
            "artifact": ".",
            "screenshots": "screenshots",
            "downloads": "downloads",
        }
        and isinstance(counts, dict)
        and counts.get("assertions") == scene.get("assertion_count")
        and counts.get("browser_errors") == 0
        and counts.get("exact_viewports") == 7
        and isinstance(counts.get("screenshots_reported"), int)
        and counts.get("screenshots_reported", 0) >= 44
        and counts.get("screenshots_validated") == counts.get("screenshots_reported")
        and counts.get("themes") == 4
        and counts.get("architectures") == 7
        and counts.get("architecture_2d_3d_pairs") == 7
        and counts.get("scene_template_architectures") == 7
        and counts.get("downloads_validated") == 10
        and isinstance(quality, dict)
        and quality.get("reported_dom_geometry_contract_passed") is True
        and quality.get("png_files_independently_parsed") is True
        and quality.get("viewport_png_dimensions_independently_cross_checked") is True
        and quality.get("reported_label_occlusion", {}).get("passed") is True
        and quality.get("reported_label_occlusion", {}).get("collision_free") is True
        and quality.get("reported_label_occlusion", {}).get("clipping_free") is True
        and isinstance(measurement, dict)
        and measurement.get("producer_dom_geometry_claim_checked") is True
        and measurement.get("application_proof_metadata_trusted_as_measurement") is False
        and measurement.get("bitmap_ocr_performed") is False
    ):
        failures.append("independent Scene visual evidence identity, counts, or DOM/PNG scope is incomplete")
    if not (
        isinstance(oracle, dict)
        and oracle.get("status") == "PASS"
        and oracle.get("failures") == []
        and isinstance(text_oracle, dict)
        and text_oracle.get("status") == "PASS"
        and isinstance(text_oracle.get("label_count"), int)
        and text_oracle.get("label_count", 0) >= 2
        and isinstance(text_oracle.get("minimum_font_pt"), (int, float))
        and not isinstance(text_oracle.get("minimum_font_pt"), bool)
        and text_oracle.get("minimum_font_pt", 0) >= 7.0
        and text_oracle.get("out_of_viewBox_count") == 0
        and text_oracle.get("overlap_count") == 0
        and isinstance(stroke_oracle, dict)
        and stroke_oracle.get("status") == "PASS"
        and stroke_oracle.get("uniform") is True
        and isinstance(stroke_oracle.get("minimum_stroke_pt"), (int, float))
        and not isinstance(stroke_oracle.get("minimum_stroke_pt"), bool)
        and stroke_oracle.get("minimum_stroke_pt", 0) > 0
        and isinstance(route_oracle, dict)
        and route_oracle.get("status") == "PASS"
        and route_oracle.get("route_primitive_count", 0) > 0
        and route_oracle.get("non_endpoint_intersection_count") == 0
        and isinstance(hidden_oracle, dict)
        and hidden_oracle.get("status") == "PASS"
        and hidden_oracle.get("hidden_edges_option") is True
        and hidden_oracle.get("backface_culling_option") is True
        and hidden_oracle.get("kind_counts_match") is True
        and hidden_oracle.get("object_bindings_match") is True
        and hidden_oracle.get("stroke_option_matches_actual") is True
        and isinstance(oracle_source, dict)
        and isinstance(svg_download, dict)
        and {
            name: oracle_source.get(name)
            for name in ("path", "bytes", "sha256")
        }
        == {
            name: svg_download.get(name)
            for name in ("path", "bytes", "sha256")
        }
    ):
        failures.append("actual downloaded Scene SVG did not pass the independent text/stroke/route/hidden-line oracle")
    architectures = report.get("architecture_comparisons", {})
    templates = report.get("scene_template_architectures", {})
    if not (
        isinstance(architectures, dict)
        and set(architectures) == EXACT_REAL_MODEL_SCENES
        and all(
            isinstance(item, dict)
            and item.get("valid") is True
            and isinstance(item.get("route_objects"), int)
            and not isinstance(item.get("route_objects"), bool)
            and item.get("route_objects", 0) > 0
            and isinstance(item.get("visible_labels"), int)
            and not isinstance(item.get("visible_labels"), bool)
            and item.get("visible_labels", 0) > 0
            for item in architectures.values()
        )
        and isinstance(templates, dict)
        and set(templates) == EXACT_SCENE_TEMPLATE_FAMILIES
        and all(
            isinstance(item, dict)
            and item.get("valid") is True
            and isinstance(item.get("route_objects"), int)
            and not isinstance(item.get("route_objects"), bool)
            and item.get("route_objects", 0) > 0
            for item in templates.values()
        )
    ):
        failures.append("visual evidence does not retain seven valid real-model pairs and seven exact Scene template families")
    return failures


def payload_failures(staging: Path, reports: dict[str, dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    corpus_root = staging / "exports" / "scene-corpus"
    if corpus_root.is_symlink() or not corpus_root.is_dir():
        failures.append("Scene corpus payload directory is absent or unsafe")
    else:
        corpus_files = inventory(corpus_root)
        corpus = reports["scene_corpus"]
        if not (
            len(corpus_files) == 168
            and corpus.get("output_file_count") == 168
            and canonical_inventory_digest(corpus_files) == corpus.get("output_tree_digest")
        ):
            failures.append("Scene corpus report is not bound to the exact 168-file payload")

    proof_root = staging / "evidence" / "publication-before-after"
    proof_files = inventory(proof_root) if proof_root.is_dir() and not proof_root.is_symlink() else {}
    before_after = reports["before_after"]
    expected_proof_paths = {
        path
        for item in before_after.get("cases", [])
        if isinstance(item, dict)
        for path in item.get("paths", {}).values()
        if isinstance(path, str)
    }
    if len(proof_files) != 42 or set(proof_files) != expected_proof_paths:
        failures.append("before/after proof payload is not the exact fourteen × three PNG set")
    else:
        for item in before_after.get("cases", []):
            if not isinstance(item, dict):
                continue
            for role in ("before", "after", "comparison"):
                relative = item.get("paths", {}).get(role)
                claim = item.get(role, {})
                path = proof_files.get(relative)
                if (
                    path is None
                    or path.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n"
                    or claim.get("bytes") != path.stat().st_size
                    or claim.get("sha256") != sha256(path)
                ):
                    failures.append(f"before/after {role} proof is not payload-bound: {relative!r}")

    ids_path = staging / "reports" / "quick" / "collected-test-ids.txt"
    quick_python = reports["quick"].get("python", {})
    if ids_path.is_symlink() or not ids_path.is_file():
        failures.append("fresh collected Python test-ID payload is absent")
    else:
        ids = ids_path.read_text(encoding="utf-8").splitlines()
        if not (
            len(ids) == len(set(ids)) == quick_python.get("collected")
            and sha256(ids_path) == quick_python.get("test_ids_sha256")
        ):
            failures.append("quick report is not bound to the exact unique collected test IDs")

    distributions = staging / "distributions"
    dist_files = inventory(distributions) if distributions.is_dir() and not distributions.is_symlink() else {}
    wheels = {name: path for name, path in dist_files.items() if name.endswith(".whl")}
    sdists = {name: path for name, path in dist_files.items() if name.endswith(".tar.gz")}
    packaging = reports["packaging"]
    claims = (packaging.get("wheel", {}), packaging.get("sdist", {}))
    actual = ({**wheels, **sdists})
    if not (len(dist_files) == 2 and len(wheels) == len(sdists) == 1):
        failures.append("distribution payload must contain exactly one wheel and one sdist")
    else:
        for claim in claims:
            if not isinstance(claim, dict):
                failures.append("distribution report claim is malformed")
                continue
            name = claim.get("name")
            path = actual.get(name) if isinstance(name, str) else None
            if path is None or claim.get("bytes") != path.stat().st_size or claim.get("sha256") != sha256(path):
                failures.append(f"distribution report claim is not payload-bound: {name!r}")

    command_records = reports["commands"].get("commands", [])
    staging_resolved = staging.resolve(strict=True)
    if isinstance(command_records, list):
        for item in command_records:
            if not isinstance(item, dict) or not isinstance(item.get("log"), str):
                continue
            relative = Path(item["log"])
            if relative.is_absolute() or ".." in relative.parts:
                failures.append(f"command log path is unsafe: {item.get('log')!r}")
                continue
            log = (staging / relative).resolve()
            if staging_resolved not in log.parents or not log.is_file() or log.is_symlink():
                failures.append(f"command log is absent from artifact staging: {item.get('log')!r}")
    responsive_root = staging / "screenshots" / "responsive"
    responsive_files = (
        inventory(responsive_root)
        if responsive_root.is_dir() and not responsive_root.is_symlink()
        else {}
    )
    expected_responsive = {
        *(f"toolbar-{width}.png" for width in (1440, 1024, 800, 768, 568, 390, 320)),
        "paper-menu-1440.png",
        "view-menu-390.png",
    }
    if set(responsive_files) != expected_responsive or any(
        path.stat().st_size <= 8 or path.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n"
        for path in responsive_files.values()
    ):
        failures.append("responsive screenshot payload is not the exact non-empty nine-PNG set")

    evidence_root = staging / "evidence" / "scene-studio" / "scene-studio-artifacts"
    visual = reports["visual"]
    scene = reports["scene"]
    if evidence_root.is_symlink() or not evidence_root.is_dir():
        failures.append("Scene visual evidence payload root is absent or unsafe")
        return failures
    expected_top = {"screenshots", "downloads", "pre-reload-project.json"}
    observed_top = {item.name for item in evidence_root.iterdir()}
    if observed_top != expected_top:
        failures.append("Scene visual evidence payload has an unexpected top-level set")
    screenshot_root = evidence_root / "screenshots"
    download_root = evidence_root / "downloads"
    screenshot_files = (
        inventory(screenshot_root)
        if screenshot_root.is_dir() and not screenshot_root.is_symlink()
        else {}
    )
    download_files = (
        inventory(download_root)
        if download_root.is_dir() and not download_root.is_symlink()
        else {}
    )

    def bind_visual_records(
        records: object,
        actual: dict[str, Path],
        prefix: str,
        minimum: int,
    ) -> list[dict[str, Any]]:
        bound: list[dict[str, Any]] = []
        if not isinstance(records, list) or len(records) < minimum:
            failures.append(f"visual {prefix} records are incomplete")
            return bound
        claimed: set[str] = set()
        for item in records:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                failures.append(f"visual {prefix} record is malformed")
                continue
            relative = Path(item["path"])
            if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 2 or relative.parts[0] != prefix:
                failures.append(f"visual {prefix} path is unsafe: {item.get('path')!r}")
                continue
            name = relative.parts[1]
            path = actual.get(name)
            if name in claimed or path is None:
                failures.append(f"visual {prefix} path is duplicate or absent: {item.get('path')!r}")
                continue
            claimed.add(name)
            if (
                item.get("bytes") != path.stat().st_size
                or item.get("sha256") != sha256(path)
                or item.get("valid") is not True
            ):
                failures.append(f"visual {prefix} claim is not payload-bound: {item.get('path')!r}")
                continue
            bound.append(item)
        if claimed != set(actual):
            failures.append(f"visual {prefix} records do not exactly cover the payload tree")
        return bound

    screenshot_records = bind_visual_records(visual.get("screenshots"), screenshot_files, "screenshots", 44)
    download_records = bind_visual_records(visual.get("downloads"), download_files, "downloads", 10)
    if (
        len(screenshot_files) < 44
        or len(screenshot_records) != len(screenshot_files)
        or visual.get("screenshot_tree_digest")
        != canonical_evidence_digest(screenshot_records, ("path", "bytes", "sha256"))
    ):
        failures.append("visual screenshot digest does not bind the complete 44+ PNG payload")
    if (
        len(download_files) != 10
        or len(download_records) != 10
        or visual.get("download_tree_digest")
        != canonical_evidence_digest(download_records, ("format", "path", "bytes", "sha256"))
    ):
        failures.append("visual download digest does not bind the exact ten-format payload")
    scene_path = staging / REPORTS["scene"]
    source_claim = visual.get("source_report", {})
    if not (
        isinstance(source_claim, dict)
        and source_claim.get("sha256") == sha256(scene_path)
        and source_claim.get("bytes") == scene_path.stat().st_size
        and source_claim.get("schema_version") == "nndv-0.7.1-scene-studio-e2e-1"
        and source_claim.get("status") == "PASS"
    ):
        failures.append("visual validation report is not hash-bound to the Scene E2E report")
    if scene.get("artifact_root") != ".":
        failures.append("Scene E2E report is not relocatable within the sealed artifact")
    raw_screenshots = scene.get("screenshot_manifest", [])
    raw_downloads = scene.get("download_manifest", [])
    raw_screenshot_claims = {
        item.get("path"): (item.get("id"), item.get("bytes"), item.get("sha256"))
        for item in raw_screenshots
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    } if isinstance(raw_screenshots, list) else {}
    visual_screenshot_claims = {
        item.get("path"): (item.get("id"), item.get("bytes"), item.get("sha256"))
        for item in screenshot_records
    }
    raw_download_claims = {
        item.get("path"): (item.get("format"), item.get("bytes"), item.get("sha256"))
        for item in raw_downloads
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    } if isinstance(raw_downloads, list) else {}
    visual_download_claims = {
        item.get("path"): (item.get("format"), item.get("bytes"), item.get("sha256"))
        for item in download_records
    }
    if raw_screenshot_claims != visual_screenshot_claims:
        failures.append("Scene E2E and independent visual screenshot claims disagree")
    if raw_download_claims != visual_download_claims:
        failures.append("Scene E2E and independent visual download claims disagree")
    pre_reload = evidence_root / "pre-reload-project.json"
    try:
        pre_reload_project = load_object(pre_reload)
    except (OSError, ValueError, json.JSONDecodeError):
        failures.append("pre-reload Project evidence is absent or malformed")
    else:
        if not (
            pre_reload_project.get("project_version") == "1.4"
            and pre_reload_project.get("scene_ir", {}).get("schema_version") == "1.0"
        ):
            failures.append("pre-reload evidence is not a Project 1.4 with Scene IR 1.0")
    return failures


def inventory(root: Path, *, exclude: set[str] | None = None) -> dict[str, Path]:
    excluded = exclude or set()
    files: dict[str, Path] = {}
    pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                relative = path.relative_to(root).as_posix()
                mode = entry.stat(follow_symlinks=False).st_mode
                if stat.S_ISLNK(mode):
                    raise ValueError(f"artifact contains a symlink: {relative}")
                if stat.S_ISDIR(mode):
                    pending.append(path)
                elif stat.S_ISREG(mode):
                    if relative not in excluded:
                        files[relative] = path
                else:
                    raise ValueError(f"artifact contains a special file: {relative}")
    return dict(sorted(files.items()))


def report_failures(reports: dict[str, dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    quick = reports["quick"]
    python = quick.get("python", {})
    gates = quick.get("coverage", {}).get("gates", {})
    if not (
        quick.get("schema_version") == "nndv-0.7.1-quick-verification-1"
        and quick.get("release") == RELEASE
        and passed(quick)
        and isinstance(python.get("collected"), int)
        and python.get("collected", 0) >= 328
        and python.get("collected") == python.get("passed")
        and python.get("failed") == 0
        and python.get("errors") == 0
        and python.get("skipped") == 0
        and python.get("deselected") == 0
        and python.get("inherited_0_7_0_tests") == 328
        and python.get("baseline_0_7_0_missing") == []
        and all(gates.get(name) is True for name in (
            "old_core_passed", "expanded_core_passed", "all_package_passed", "scene_core_80_percent",
        ))
    ):
        failures.append("quick verification is not an exact all-pass retaining 328 parent test IDs and coverage gates")

    corpus = reports["scene_corpus"]
    expected_counts = {
        "cases": 14,
        "templates": 7,
        "real_models": 7,
        "passing_cases": 14,
        "scene_exports": 140,
        "projects": 14,
        "comparison_files": 14,
        "regular_files": 168,
        "failures": 0,
    }
    if not (
        corpus.get("schema_version") == "nndv-0.7.1-scene-artifact-corpus-1"
        and corpus.get("release") == RELEASE
        and passed(corpus)
        and corpus.get("fresh_outputs") is True
        and corpus.get("offline_generation") is True
        and corpus.get("weights_downloaded") is False
        and corpus.get("counts") == expected_counts
        and corpus.get("format_counts") == {name: 14 for name in (
            "svg", "pdf", "tikz", "pptx", "png", "eps", "html", "json", "gltf", "glb",
        )}
        and corpus.get("failures") == []
    ):
        failures.append("fresh fourteen-case Scene corpus is incomplete or failed")
    validation = reports["scene_corpus_validation"]
    if not (
        validation.get("schema_version") == "nndv-0.7.1-scene-artifact-validation-1"
        and passed(validation)
        and validation.get("validator_is_independent_of_generator") is True
        and validation.get("counts", {}).get("passing_cases") == 14
        and validation.get("failures") == []
    ):
        failures.append("independent Scene artifact validation did not pass all fourteen cases")

    svg_oracle = reports["svg_oracle"]
    if not (
        svg_oracle.get("oracle") == "scene-publication-svg-chrome-v1"
        and svg_oracle.get("status") == "PASS"
        and svg_oracle.get("caseCount") == 14
        and len(svg_oracle.get("cases", [])) == 14
        and all(item.get("status") == "PASS" for item in svg_oracle.get("cases", []))
        and svg_oracle.get("failures") == []
    ):
        failures.append("strict landed-output Chrome SVG oracle did not pass all fourteen cases")
    publication_oracle = reports["publication_oracle"]
    if not (
        publication_oracle.get("oracle") == "scene-publication-cross-format-v1"
        and publication_oracle.get("status") == "PASS"
        and publication_oracle.get("case_count") == 14
        and publication_oracle.get("formats_status") == "PASS"
        and publication_oracle.get("true_3d_status") == "PASS"
        and publication_oracle.get("publication_status") == "PASS"
        and publication_oracle.get("failures") == []
    ):
        failures.append("independent PDF/TikZ/true-3D publication oracle did not pass")
    before_after = reports["before_after"]
    if not (
        before_after.get("schema_version") == "nndv-0.7.1-scene-before-after-report-1"
        and before_after.get("release") == RELEASE
        and before_after.get("status") == "PASS"
        and before_after.get("before") == {
            "release": "0.7.0",
            "run_id": PARENT_RUN_ID,
            "read_only": True,
        }
        and before_after.get("after") == {"release": "0.7.1", "fresh_current_output": True}
        and before_after.get("case_count") == 14
        and before_after.get("proof_png_count") == 42
        and before_after.get("original_pixels_preserved") is True
        and len(before_after.get("cases", [])) == 14
        and all(item.get("status") == "PASS" for item in before_after.get("cases", []))
        and before_after.get("failures") == []
    ):
        failures.append("fourteen-case 0.7.0→0.7.1 before/after proof is incomplete")
    oracle_fixtures = reports["oracle_fixtures"]
    if not (
        oracle_fixtures.get("schema_version") == "nndv-0.7.1-visual-oracle-fixture-report-1"
        and oracle_fixtures.get("status") == "PASS"
        and oracle_fixtures.get("constant_true_rejected") is True
        and oracle_fixtures.get("failures") == []
    ):
        failures.append("positive/negative/mutation visual-oracle truth fixtures did not pass")

    performance = reports["performance"]
    if not (
        performance.get("schema_version") == "nndv-0.7.1-scene-studio-performance-1"
        and passed(performance)
        and performance.get("repeats", 0) >= 3
        and performance.get("failures") == []
    ):
        failures.append("Scene/retained-Figure performance gates did not pass")
    audit = reports["audit"]
    if not (
        audit.get("schema_version") == "nndv-0.7.1-release-audit-1"
        and audit.get("release") == RELEASE
        and audit.get("status") == "PASS"
        and audit.get("failures") == []
        and audit.get("human_participants") == 0
    ):
        failures.append("release/document audit did not pass")
    migration = reports["migration"]
    expected_migration_contract = {
        "graph_ir_mutated": False,
        "figure_ir_mutated": False,
        "scene_geometry_inferred": False,
        "model_semantics_inferred": False,
        "provenance_inferred": False,
    }
    if not (
        migration.get("schema_version") == "nndv-0.7.1-project-scene-migration-1"
        and migration.get("release") == RELEASE
        and passed(migration)
        and migration.get("counts") == {"expected": 7, "checked": 7, "passed": 7, "failed": 0}
        and migration.get("migration_contract") == expected_migration_contract
        and migration.get("failures") == []
    ):
        failures.append("Project 1.3 to 1.4 migration evidence is incomplete or invented Scene facts")
    editor = reports["editor"]
    editor_counts = editor.get("counts", {})
    editor_scenarios = editor.get("scenarios", [])
    if not (
        editor.get("schema_version") == "1.0"
        and isinstance(editor_counts, dict)
        and editor_counts.get("e2e_scenarios", 0) >= 11
        and editor_counts.get("passed") == editor_counts.get("e2e_scenarios")
        and editor_counts.get("failed") == 0
        and editor_counts.get("skipped") == 0
        and editor_counts.get("assertions", 0) >= 71
        and isinstance(editor_scenarios, list)
        and len(editor_scenarios) == editor_counts.get("e2e_scenarios")
        and all(
            isinstance(item, dict)
            and item.get("status") == "passed"
            and item.get("console_errors") == []
            for item in editor_scenarios
        )
    ):
        failures.append("editor Chrome E2E did not retain all inherited scenarios")
    e2e_contracts = {
        "responsive": ("0.5.2-responsive-workspace-e2e-1", 168),
        "semantic": ("0.3.0-semantic-workflow-1", 28),
        "product": ("0.5.1-product-workflow-1", 32),
        "trial": ("0.5.1-trial-workflow-e2e-1", 65),
    }
    for name, (schema, minimum_assertions) in e2e_contracts.items():
        report = reports[name]
        if not (
            report.get("schema_version") == schema
            and report.get("status") == "passed"
            and report.get("assertion_count", 0) >= minimum_assertions
        ):
            failures.append(f"{name} Chrome E2E did not pass its inherited assertion contract")
    figure = reports["figure"]
    figure_counts = figure.get("counts", {})
    if not (
        figure.get("schema_version") == "nndv-0.6.1-figure-studio-e2e-1"
        and figure.get("status") == "PASS"
        and isinstance(figure_counts, dict)
        and figure_counts.get("scenarios", 0) >= 1
        and figure_counts.get("passed") == figure_counts.get("scenarios")
        and figure_counts.get("failed") == 0
        and figure_counts.get("skipped") == 0
        and figure_counts.get("assertions", 0) >= 75
        and figure_counts.get("console_page_request_errors") == 0
        and figure.get("errors") == []
    ):
        failures.append("Figure Studio Chrome E2E did not retain the 0.6.1 workflow")
    failures.extend(scene_e2e_failures(reports["scene"]))
    failures.extend(visual_evidence_failures(reports["visual"], reports["scene"]))
    if reports["trial"].get("human_participants") != 0:
        failures.append("automated Trial evidence was represented as human evidence")
    packaging = reports["packaging"]
    if not (
        packaging.get("checks", 0) >= 16
        and packaging.get("passed") is True
        and all(packaging.get(name) is True for name in (
            "wheel_installed_with_dependencies", "sdist_installed_with_dependencies",
            "pip_check_passed", "web_assets", "figure_templates", "scene_templates", "cli_smoke",
            "lock_matches",
        ))
        and packaging.get("wheel_install", {}).get("version") == "0.7.1"
        and packaging.get("sdist_install", {}).get("version") == "0.7.1"
        and packaging.get("wheel_install", {}).get("passed") is True
        and packaging.get("sdist_install", {}).get("passed") is True
    ):
        failures.append("wheel/sdist installation verification did not pass")
    commands = reports["commands"]
    command_records = commands.get("commands", [])
    observed_command_ids = tuple(
        item.get("id") for item in command_records if isinstance(item, dict)
    ) if isinstance(command_records, list) else ()
    if not (
        commands.get("schema_version") == "nndv-0.7.1-full-command-report-1"
        and commands.get("release") == RELEASE
        and commands.get("fresh_control_root") is True
        and commands.get("old_artifacts_used_as_current_output") is False
        and commands.get("failed") == 0
        and commands.get("completed") == len(EXPECTED_COMMAND_IDS)
        and commands.get("command_count") == len(EXPECTED_COMMAND_IDS)
        and observed_command_ids == EXPECTED_COMMAND_IDS
        and all(
            isinstance(item, dict)
            and item.get("exit_code") == 0
            and item.get("sequence") == index
            and isinstance(item.get("argv"), list)
            and bool(item.get("argv"))
            and isinstance(item.get("log"), str)
            and bool(item.get("log"))
            for index, item in enumerate(command_records, 1)
        )
    ):
        failures.append("full command accounting contains a failure")
    source = reports["source"]
    source_files = source.get("files", {})
    if not (
        source.get("schema_version") == "nndv-clean-source-snapshot-2"
        and source.get("passed") is True
        and source.get("release") == "0.7.1"
        and isinstance(source.get("file_count"), int)
        and source.get("file_count", 0) > 356
        and isinstance(source_files, dict)
        and len(source_files) == source.get("file_count")
        and source.get("forbidden_paths") == []
        and isinstance(source.get("source_tree_digest"), str)
        and len(source.get("source_tree_digest", "")) == 64
    ):
        failures.append("fresh 0.7.1 clean-source snapshot is invalid")
    parent_source = reports["parent_source"]
    if not (
        parent_source.get("passed") is True
        and parent_source.get("schema_version") == "nndv-clean-source-snapshot-2"
        and parent_source.get("file_count") == 356
        and len(parent_source.get("files", {})) == 356
        and parent_source.get("source_tree_digest") == PARENT_SOURCE_DIGEST
        and parent_source.get("forbidden_paths") == []
    ):
        failures.append("frozen parent source no longer matches its authoritative 356-file digest")
    parent_artifact = reports["parent_artifact"]
    if not (
        parent_artifact.get("status") == "PASS"
        and parent_artifact.get("run_id") == PARENT_RUN_ID
        and parent_artifact.get("source_file_count") == 356
        and parent_artifact.get("source_digest") == PARENT_SOURCE_DIGEST
        and parent_artifact.get("failures") == []
    ):
        failures.append("authoritative parent artifact verification did not pass")
    environment = reports["environment"]
    environment_sources = environment.get("sources", {})
    expected_environment_sources = {
        name: item.get("sha256")
        for name, item in source_files.items()
        if isinstance(name, str) and isinstance(item, dict)
    } if isinstance(source_files, dict) else {}
    if not (
        environment.get("project_version") == "0.7.1"
        and environment.get("git_repository") is False
        and isinstance(environment.get("python"), str)
        and isinstance(environment.get("hardware"), dict)
        and isinstance(environment.get("tools"), dict)
        and environment.get("tools", {}).get("browser")
        and environment.get("tools", {}).get("node")
        and environment.get("tools", {}).get("npm")
        and environment_sources == expected_environment_sources
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
        raise SystemExit(f"unsafe 0.7.1 run identifier: {args.run_id!r}")
    supplied_staging = args.staging
    if supplied_staging.is_symlink() or not supplied_staging.is_dir():
        raise SystemExit("artifact staging root is absent or unsafe")
    staging = supplied_staging.resolve(strict=True)
    try:
        started = datetime.fromisoformat(args.started_utc.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit("started UTC timestamp is invalid") from exc
    if started.tzinfo is None:
        raise SystemExit("started UTC timestamp must include a timezone")
    started_epoch_from_utc = started.timestamp()
    now = time.time()
    if abs(started_epoch_from_utc - args.started_epoch) > 2.0 or args.started_epoch > now + 1.0:
        raise SystemExit("started UTC and epoch values disagree or lie in the future")
    reports: dict[str, dict[str, Any]] = {}
    for name, relative in REPORTS.items():
        path = staging / relative
        if not path.is_file() or path.is_symlink():
            raise SystemExit(f"required release report is absent or unsafe: {relative}")
        reports[name] = load_object(path)
    failures = report_failures(reports)
    failures.extend(payload_failures(staging, reports))
    if failures:
        raise SystemExit("0.7.1 artifact preconditions failed:\n- " + "\n- ".join(failures))

    completed = datetime.now(timezone.utc).isoformat()
    quick = reports["quick"]
    corpus = reports["scene_corpus"]
    performance = reports["performance"]
    visual = reports["visual"]
    verification = {
        "schema_version": "nndv-0.7.1-verification-1",
        "release": RELEASE,
        "status": "PASS",
        "run_id": args.run_id,
        "started_utc": args.started_utc,
        "completed_utc": completed,
        "elapsed_seconds": round(time.time() - args.started_epoch, 3),
        "parent": {
            "release": "0.7.0",
            "run_id": PARENT_RUN_ID,
            "source_files": 356,
            "source_digest": PARENT_SOURCE_DIGEST,
            "artifact_verification": "PASS",
        },
        "python": quick["python"],
        "coverage": quick["coverage"],
        "scene": {
            "scene_ir": "1.0",
            "project_schema": "1.4",
            "templates": corpus["counts"]["templates"],
            "real_models": corpus["counts"]["real_models"],
            "cases": corpus["counts"]["cases"],
            "exports": corpus["counts"]["scene_exports"],
            "projects": corpus["counts"]["projects"],
            "comparisons": corpus["counts"]["comparison_files"],
            "true_3d_independent_validation": "PASS",
            "strict_svg_oracle": reports["svg_oracle"]["status"],
            "pdf_tikz_publication_oracle": reports["publication_oracle"]["status"],
            "visual_oracle_truth_fixtures": reports["oracle_fixtures"]["status"],
            "before_after_cases": reports["before_after"]["case_count"],
        },
        "chrome": {
            "suites": 7,
            "scene_assertions": reports["scene"].get("assertion_count", len(reports["scene"].get("assertions", []))),
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
        "performance": performance,
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

    supplied_artifact_root = args.artifact_root
    if supplied_artifact_root.is_symlink():
        raise SystemExit("artifact root may not be a symlink")
    artifact_root = supplied_artifact_root.resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    target = artifact_root / args.run_id
    candidate = artifact_root / f".{args.run_id}.staging"
    if target.exists() or candidate.exists():
        raise SystemExit(f"refusing to overwrite existing artifact path for {args.run_id}")
    prepublish_verification = artifact_root / f".{args.run_id}.prepublish-verification.json"
    if prepublish_verification.exists() or prepublish_verification.is_symlink():
        raise SystemExit(f"refusing to overwrite prepublish verification for {args.run_id}")
    try:
        shutil.copytree(staging, candidate)
        (candidate / "verification.json").write_text(
            json.dumps(verification, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        entries = inventory(candidate, exclude={"MANIFEST.json", "SHA256SUMS"})
        manifest = {
            "schema_version": "nndv-0.7.1-artifact-manifest-1",
            "release": RELEASE,
            "run_id": args.run_id,
            "source_file_count": reports["source"]["file_count"],
            "source_digest": reports["source"]["source_tree_digest"],
            "entries": {
                name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
                for name, path in entries.items()
            },
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
                str(args.project_root / "scripts" / "verify_release_artifact_0_7_1.py"),
                str(candidate),
                "--expected-run-id",
                args.run_id,
                "--output",
                str(prepublish_verification),
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
        prepublish_verification.unlink(missing_ok=True)
    print(f"NNDV_071_ARTIFACT={target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
