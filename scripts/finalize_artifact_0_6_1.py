#!/usr/bin/env python3
"""Finalize a passed 0.6.1 full run into a self-contained artifact."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import stat
import time
from typing import Any

from scripts.verify_release_artifact_0_6_1 import editor_e2e_failures, inventory, sha256


RELEASE = "0.6.1 Beta — Publication Fidelity & Model-to-Figure Completion"
MINIMUM_FONT_WITH_TOLERANCE_PT = 6.99
MINIMUM_STROKE_PT = 0.1
MAXIMUM_CROSS_FORMAT_ERROR_MM = 1.0
MAXIMUM_CROSS_FORMAT_PAGE_ERROR_MM = 0.05
AUTHORITATIVE_060_RUN_ID = "20260829T183558Z-09a7930b"
AUTHORITATIVE_060_MANIFEST_SHA256 = "797d5b38403154b1317d00e8a9e03c48373a2c046e10e4a43229f828769e3cc4"
EXPECTED_TEMPLATE_ORDER = (
    "cnn-feature-pipeline",
    "diffusion-unet-conditioning",
    "moe-router-experts",
    "multimodal-fusion",
    "resnet-overview",
    "transformer-attention-ffn",
    "unet-encoder-decoder",
)
EXPECTED_TEMPLATE_KEYS = frozenset(EXPECTED_TEMPLATE_ORDER)
AUTHORITATIVE_060_TEMPLATE_SVGS = {
    "cnn-feature-pipeline": {
        "bytes": 41508,
        "sha256": "443a065422192924e63404c224922ba319d4ae0f00cb47dd925b30c81842cf54",
    },
    "diffusion-unet-conditioning": {
        "bytes": 72153,
        "sha256": "0aa962372ade3adeff52e941d3af3a18f72e6951aa947d93bb7d64833e551a0f",
    },
    "moe-router-experts": {
        "bytes": 54041,
        "sha256": "4cc9ea042e5a11863344253732aa7feb181aadc655512f28753b73b61cd872c1",
    },
    "multimodal-fusion": {
        "bytes": 40771,
        "sha256": "d773b7558e586fec92878ef26a67426ddf9655c165d2349953c45e4d1730da37",
    },
    "resnet-overview": {
        "bytes": 53605,
        "sha256": "9028dafabd74eb5ff61b22e32195b506e197f3c5c0c3ac11376f4baee6900a6f",
    },
    "transformer-attention-ffn": {
        "bytes": 54564,
        "sha256": "1f5e18542429cafc7631b1f03ecd629994124175ffe93388e9cda482a6e63d30",
    },
    "unet-encoder-decoder": {
        "bytes": 53343,
        "sha256": "00bd6357bcbf45bab84efa2f63472e9566d5b13c0b8a8577c32e1e06d2f93b35",
    },
}
EXPECTED_REPORTS = {
    "quick": "reports/quick/quick-verification.json",
    "editor": "reports/e2e/editor.json",
    "responsive": "reports/e2e/responsive.json",
    "semantic": "reports/e2e/semantic.json",
    "product": "reports/e2e/product.json",
    "trial": "reports/e2e/trial.json",
    "figure": "reports/e2e/figure-studio.json",
    "publication_exports": "reports/exports/publication-artifacts.json",
    "strict_svg_oracle_raw": "reports/exports/figure-svg-oracle.json",
    "strict_svg_oracle": "reports/exports/strict-svg-validation.json",
    "cross_format_positions": "reports/exports/cross-format-positions.json",
    "historical_0_6_0_oracle_raw": "reports/exports/authoritative-0.6.0-figure-svg-oracle.json",
    "before_after_proofs": "reports/exports/before-after-proofs.json",
    "fixture_oracle_raw": "reports/oracle-fixtures/figure-svg-oracle.json",
    "fixture_truth": "reports/oracle-fixtures/validation.json",
    "submission": "reports/exports/submission-package.json",
    "performance": "reports/performance/figure-studio.json",
    "packaging": "reports/packaging/package-install.json",
    "audit": "reports/docs/release-audit.json",
    "commands": "reports/full/commands.json",
}
REQUIRED_FIGURE_E2E_WORKFLOWS = frozenset({
    "real_model_semantic_mixed_figure",
    "structure_lens_explicit_panel",
    "tensor_shape_style_edit",
    "long_label_final_svg_bbox",
    "second_page",
    "six_panels",
    "rebuild_undo_restores_evidence",
    "save_refresh_restore",
    "tampered_project_rejected",
    "svg_metadata_roundtrip",
    "seven_format_exports",
    "submission_package",
    "responsive_1440_800_390",
    "zero_browser_errors",
})


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _status_passed(report: dict[str, Any]) -> bool:
    return str(report.get("status", "")).lower() == "pass" or str(report.get("status", "")).lower() == "passed"


def historical_negative_control_failures(
    before_after: dict[str, Any],
    raw: dict[str, Any],
) -> list[str]:
    """Check the persisted 0.6.0 0/7 Chrome result and its manifest bindings."""

    failures: list[str] = []
    contract = raw.get("measurement_contract")
    summary = raw.get("summary")
    raw_cases = raw.get("reports")
    if not (
        raw.get("schema_version") == "nndv-figure-svg-oracle-report-1"
        and raw.get("oracle") == "figure-final-svg-chrome-v1"
        and raw.get("passed") is False
        and isinstance(contract, dict)
        and contract.get("final_dom_only") is True
        and contract.get("metadata_trusted") is False
        and contract.get("python_proof_imported") is False
        and contract.get("data_scale_claims_trusted") is False
        and contract.get("stroke_under_full_ctm") is True
        and isinstance(summary, dict)
        and summary.get("files") == 7
        and summary.get("passed") == 0
        and summary.get("failed") == 7
        and isinstance(summary.get("issues"), int)
        and not isinstance(summary.get("issues"), bool)
        and summary["issues"] > 0
        and isinstance(raw_cases, list)
        and len(raw_cases) == 7
    ):
        failures.append("authoritative 0.6.0 strict negative-control raw report is incomplete")
        raw_cases = raw_cases if isinstance(raw_cases, list) else []

    template_by_hash = {
        claim["sha256"]: template
        for template, claim in AUTHORITATIVE_060_TEMPLATE_SVGS.items()
    }
    observed_raw: dict[str, dict[str, Any]] = {}
    total_issues = 0
    for item in raw_cases:
        if not isinstance(item, dict):
            failures.append("authoritative 0.6.0 strict negative-control contains a non-object case")
            continue
        template = template_by_hash.get(item.get("sha256"))
        issues = item.get("issues")
        case_summary = item.get("summary")
        issue_count = case_summary.get("issue_count") if isinstance(case_summary, dict) else None
        source = item.get("source")
        expected_suffix = f"/exports/figure-templates/{template}/figure.svg" if template else ""
        if not (
            template is not None
            and template not in observed_raw
            and item.get("passed") is False
            and isinstance(issues, list)
            and len(issues) > 0
            and isinstance(issue_count, int)
            and not isinstance(issue_count, bool)
            and issue_count == len(issues)
            and item.get("browser_errors") == []
            and str(item.get("file", "")).replace("\\", "/").endswith(expected_suffix)
            and isinstance(source, dict)
            and source.get("loaded_from_persisted_file") is True
            and source.get("metadata_consulted") is False
        ):
            failures.append(f"authoritative 0.6.0 strict negative-control case is invalid: {template!r}")
            continue
        total_issues += issue_count
        observed_raw[template] = item
    if set(observed_raw) != EXPECTED_TEMPLATE_KEYS:
        failures.append("authoritative 0.6.0 strict negative-control does not cover the exact seven templates")
    if isinstance(summary, dict) and total_issues != summary.get("issues"):
        failures.append("authoritative 0.6.0 strict negative-control issue total is inconsistent")

    control = before_after.get("strict_negative_control")
    if not isinstance(control, dict):
        return [*failures, "before/after report is missing the authoritative strict negative-control block"]
    control_contract = control.get("measurement_contract")
    control_summary = control.get("summary")
    control_cases = control.get("cases")
    if not (
        control.get("schema_version") == "nndv-0.6.1-authoritative-0.6.0-strict-negative-control-1"
        and control.get("status") == "PASS"
        and control.get("expected_failure_observed") is True
        and control.get("historical_svg_quality_passed") is False
        and control.get("oracle_passed") is False
        and control.get("authoritative_run_id") == AUTHORITATIVE_060_RUN_ID
        and control.get("authoritative_manifest_sha256") == AUTHORITATIVE_060_MANIFEST_SHA256
        and control.get("manifest_hashes_matched") is True
        and control.get("expected_templates") == list(EXPECTED_TEMPLATE_ORDER)
        and isinstance(control_contract, dict)
        and control_contract.get("final_dom_only") is True
        and control_contract.get("metadata_trusted") is False
        and control_contract.get("python_proof_imported") is False
        and control_contract.get("data_scale_claims_trusted") is False
        and control_contract.get("stroke_under_full_ctm") is True
        and control_summary == {
            "files": 7,
            "passed": 0,
            "failed": 7,
            "issues": total_issues,
        }
        and isinstance(control_cases, list)
        and len(control_cases) == 7
        and control.get("failures") == []
        and control.get("raw_report", {}).get("relative_path")
        == EXPECTED_REPORTS["historical_0_6_0_oracle_raw"]
    ):
        failures.append("before/after authoritative strict negative-control block is incomplete")
        control_cases = control_cases if isinstance(control_cases, list) else []

    control_by_template = {
        item.get("template"): item
        for item in control_cases
        if isinstance(item, dict) and isinstance(item.get("template"), str)
    }
    if set(control_by_template) != EXPECTED_TEMPLATE_KEYS:
        failures.append("before/after strict negative-control block has an unexpected template set")
    for template in EXPECTED_TEMPLATE_ORDER:
        item = control_by_template.get(template, {})
        raw_item = observed_raw.get(template, {})
        expected = AUTHORITATIVE_060_TEMPLATE_SVGS[template]
        if not (
            item.get("manifest_path") == f"exports/figure-templates/{template}/figure.svg"
            and item.get("manifest_bytes") == expected["bytes"]
            and item.get("manifest_sha256") == expected["sha256"]
            and item.get("oracle_sha256") == expected["sha256"]
            and item.get("oracle_passed") is False
            and item.get("issue_count") == raw_item.get("summary", {}).get("issue_count")
            and item.get("issue_counts") == raw_item.get("issue_counts", {})
            and item.get("browser_errors") == 0
            and item.get("loaded_from_persisted_file") is True
            and item.get("metadata_consulted") is False
        ):
            failures.append(f"strict negative-control case is not bound to the pinned manifest: {template}")
    return failures


def report_failures(reports: dict[str, dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    quick = reports["quick"]
    if quick.get("schema_version") != "nndv-0.6.1-quick-verification-1" or quick.get("release") != RELEASE:
        failures.append("quick verification identity is not 0.6.1")
    if quick.get("status") != "PASS":
        failures.append("quick verification did not pass")
    python = quick.get("python", {})
    if not (
        python.get("collected", 0) >= 171
        and python.get("collected") == python.get("passed")
        and python.get("failed") == 0
        and python.get("errors") == 0
        and python.get("skipped") == 0
        and python.get("deselected") == 0
        and python.get("inherited_0_6_0_tests") == 171
        and python.get("baseline_0_6_0_missing") == []
    ):
        failures.append("Python test accounting does not retain and pass all 171 authoritative 0.6.0 IDs")
    if quick.get("coverage", {}).get("gates") != {
        "old_core_passed": True,
        "expanded_core_passed": True,
        "all_package_passed": True,
    }:
        failures.append("one or more retained coverage gates failed")

    failures.extend(editor_e2e_failures(reports["editor"]))
    responsive = reports["responsive"]
    if not _status_passed(responsive) or responsive.get("viewport_count") != 7:
        failures.append("responsive E2E did not pass seven retained viewports")
    for name in ("semantic", "product", "trial"):
        if not _status_passed(reports[name]):
            failures.append(f"{name} E2E did not pass")
    trial = reports["trial"]
    if trial.get("human_participants") != 0 or trial.get("human_usability_claim") is not False:
        failures.append("automated Trial E2E was misrepresented as human evidence")
    figure = reports["figure"]
    figure_counts = figure.get("counts", {})
    figure_workflows = figure.get("required_workflows", {})
    if not (
        figure.get("schema_version") == "nndv-0.6.1-figure-studio-e2e-1"
        and _status_passed(figure)
        and figure_counts.get("failed") == 0
        and figure_counts.get("console_page_request_errors") == 0
        and figure.get("median_interaction_ms", float("inf")) <= 100
        and figure.get("tested_viewports") == [1440, 800, 390]
        and set(figure_workflows) == REQUIRED_FIGURE_E2E_WORKFLOWS
        and all(value is True for value in figure_workflows.values())
    ):
        failures.append("Figure Studio E2E did not satisfy the complete 0.6.1 interaction contract")

    publication = reports["publication_exports"]
    expected_counts = {
        "figures": 14,
        "templates": 7,
        "real_models": 7,
        "requested_formats": 98,
        "svg_files": 14,
        "tikz_compiled_pdfs": 14,
        "proof_pngs_300dpi": 14,
        "project_files": 14,
        "provenance_files": 14,
        "failures": 0,
    }
    if not (
        publication.get("schema_version") == "nndv-0.6.1-publication-artifact-corpus-1"
        and publication.get("release") == RELEASE
        and publication.get("status") == "PASS"
        and publication.get("fresh_outputs") is True
        and publication.get("python_figure_proof_is_release_blocker") is False
        and all(publication.get("counts", {}).get(name) == value for name, value in expected_counts.items())
    ):
        failures.append("fresh seven-format template/real-model publication corpus is incomplete or failed")
    publication_results = publication.get("results", [])
    expected_formats = {"svg", "pdf", "tikz", "png", "eps", "pptx", "html"}
    if len(publication_results) != 14:
        failures.append("publication corpus does not contain 14 per-figure result records")
    for result in publication_results:
        files = set(result.get("files", {}))
        format_names = {
            "svg" if name.endswith(".svg") else
            "pdf" if name == "figure.pdf" else
            "tikz" if name.endswith(".tex") else
            "png" if name == "figure.png" else
            "eps" if name.endswith(".eps") else
            "pptx" if name.endswith(".pptx") else
            "html" if name.endswith(".html") else
            ""
            for name in files
        }
        if not (
            result.get("status") == "PASS"
            and set(result.get("requested_formats", [])) == expected_formats
            and result.get("release_gate_uses_python_figure_proof") is False
            and result.get("provenance_validation", {}).get("passed") is True
            and expected_formats.issubset(format_names)
            and "figure.tikz.pdf" in files
            and "figure.proof-300dpi.png" in files
            and "figure.nndv.json" in files
            and "provenance.json" in files
        ):
            failures.append(f"publication result is incomplete or failed: {result.get('kind')}/{result.get('key')}")

    strict_raw = reports["strict_svg_oracle_raw"]
    if not (
        strict_raw.get("schema_version") == "nndv-figure-svg-oracle-report-1"
        and strict_raw.get("passed") is True
        and strict_raw.get("summary", {}).get("files") == 14
        and strict_raw.get("summary", {}).get("passed") == 14
        and strict_raw.get("summary", {}).get("failed") == 0
        and strict_raw.get("measurement_contract", {}).get("final_dom_only") is True
        and strict_raw.get("measurement_contract", {}).get("metadata_trusted") is False
        and strict_raw.get("measurement_contract", {}).get("python_proof_imported") is False
        and strict_raw.get("measurement_contract", {}).get("stroke_under_full_ctm") is True
        and strict_raw.get("measurement_contract", {}).get("tolerance", {}).get("minimumStrokePt")
        == MINIMUM_STROKE_PT
    ):
        failures.append("raw strict final-SVG Chrome report is incomplete or failed")
    for item in strict_raw.get("reports", []):
        raw_summary = item.get("summary", {})
        raw_strokes = item.get("strokes")
        if not (
            isinstance(raw_strokes, list)
            and raw_strokes
            and isinstance(raw_summary.get("minimum_stroke_pt"), (int, float))
            and not isinstance(raw_summary.get("minimum_stroke_pt"), bool)
            and isinstance(raw_summary.get("maximum_stroke_pt"), (int, float))
            and not isinstance(raw_summary.get("maximum_stroke_pt"), bool)
        ):
            failures.append(f"raw strict SVG report lacks full-CTM stroke evidence: {item.get('file')}")
    strict = reports["strict_svg_oracle"]
    metrics = strict.get("metrics", {})
    if not (
        strict.get("schema_version") == "nndv-0.6.1-strict-publication-svg-validation-1"
        and strict.get("release") == RELEASE
        and strict.get("status") == "PASS"
        and strict.get("final_svg_files") == 14
        and strict.get("passed_svg_files") == 14
        and strict.get("fresh_export_hashes_matched") is True
        and strict.get("python_figure_proof_imported") is False
        and strict.get("measurement_contract", {}).get("stroke_under_full_ctm") is True
        and strict.get("thresholds", {}).get("font_numeric_tolerance_pt") == 0.01
        and strict.get("thresholds", {}).get("minimum_stroke_pt") == MINIMUM_STROKE_PT
        and metrics.get("geometry_issues") == 0
        and metrics.get("browser_errors") == 0
        and isinstance(metrics.get("minimum_font_pt"), (int, float))
        and not isinstance(metrics.get("minimum_font_pt"), bool)
        and metrics["minimum_font_pt"] >= MINIMUM_FONT_WITH_TOLERANCE_PT
        and isinstance(metrics.get("minimum_stroke_pt"), (int, float))
        and not isinstance(metrics.get("minimum_stroke_pt"), bool)
        and metrics["minimum_stroke_pt"] >= MINIMUM_STROKE_PT
        and isinstance(metrics.get("maximum_stroke_pt"), (int, float))
        and not isinstance(metrics.get("maximum_stroke_pt"), bool)
        and len(strict.get("cases", [])) == 14
        and all(
            item.get("passed") is True
            and item.get("stroke_count", 0) > 0
            and isinstance(item.get("minimum_stroke_pt"), (int, float))
            and isinstance(item.get("maximum_stroke_pt"), (int, float))
            for item in strict.get("cases", [])
        )
    ):
        failures.append("validated strict final-SVG measurements are incomplete or failed")

    cross = reports["cross_format_positions"]
    cross_errors = cross.get("maximum_key_position_error_by_format_mm", {})
    if not (
        cross.get("schema_version") == "nndv-0.6.1-cross-format-position-validation-1"
        and cross.get("release") == RELEASE
        and cross.get("status") == "PASS"
        and cross.get("figures") == 14
        and cross.get("passed_figures") == 14
        and cross.get("key_positions_compared", 0) >= 84
        and isinstance(cross.get("maximum_key_position_error_mm"), (int, float))
        and cross["maximum_key_position_error_mm"] <= MAXIMUM_CROSS_FORMAT_ERROR_MM
        and isinstance(cross.get("maximum_page_size_error_mm"), (int, float))
        and cross["maximum_page_size_error_mm"] <= MAXIMUM_CROSS_FORMAT_PAGE_ERROR_MM
        and set(cross_errors) == {"pdf", "tikz_pdf"}
        and all(
            isinstance(value, (int, float)) and value <= MAXIMUM_CROSS_FORMAT_ERROR_MM
            for value in cross_errors.values()
        )
        and cross.get("measurement_sources", {}).get("figure_ir_or_python_proof_used") is False
        and len(cross.get("proof_files", [])) == 28
        and len(cross.get("cases", [])) == 14
        and all(item.get("passed") is True and item.get("key_count", 0) >= 3 for item in cross.get("cases", []))
        and cross.get("failures") == []
    ):
        failures.append("SVG/PDF/compiled-TikZ-PDF key-position registration is incomplete or exceeds 1 mm")
    measured_cross_errors: dict[str, list[float]] = {"pdf": [], "tikz_pdf": []}
    measured_key_count = 0
    for case in cross.get("cases", []):
        keys = case.get("keys", [])
        if not isinstance(keys, list) or any(not isinstance(item, dict) for item in keys):
            failures.append(f"cross-format case key inventory is invalid: {case.get('svg')}")
            continue
        text_keys = [item for item in keys if item.get("kind") == "text"]
        shape_keys = [item for item in keys if item.get("kind") == "high-contrast-rect-border"]
        if not (
            case.get("key_count") == len(keys)
            and case.get("text_key_count") == len(text_keys)
            and case.get("shape_key_count") == len(shape_keys)
            and text_keys
            and shape_keys
        ):
            failures.append(f"cross-format case lacks independently measured text/shape keys: {case.get('svg')}")
            continue
        measured_key_count += len(keys) * 2
        case_errors: dict[str, list[float]] = {"pdf": [], "tikz_pdf": []}
        for key in keys:
            errors = key.get("errors_mm", {})
            if set(errors) != {"pdf", "tikz_pdf"}:
                failures.append(f"cross-format key lacks both final-output errors: {case.get('svg')}")
                continue
            for label, value in errors.items():
                if not isinstance(value, (int, float)) or isinstance(value, bool) or value > 1.0 or value < 0:
                    failures.append(f"cross-format key error is invalid: {case.get('svg')}/{label}={value!r}")
                    continue
                measured_cross_errors[label].append(float(value))
                case_errors[label].append(float(value))
        claimed_case_errors = case.get("maximum_key_position_error_by_format_mm", {})
        for label, values in case_errors.items():
            measured = max(values) if values else None
            if measured is None or not isinstance(claimed_case_errors.get(label), (int, float)) or abs(
                measured - float(claimed_case_errors[label])
            ) > 1e-6:
                failures.append(f"cross-format per-case maximum is inconsistent: {case.get('svg')}/{label}")
    if measured_key_count != cross.get("key_positions_compared"):
        failures.append("cross-format key-position count differs from the per-object evidence")
    for label, values in measured_cross_errors.items():
        measured = max(values) if values else None
        if measured is None or not isinstance(cross_errors.get(label), (int, float)) or abs(
            measured - float(cross_errors[label])
        ) > 1e-6:
            failures.append(f"cross-format top-level {label} maximum differs from per-object evidence")
    if measured_cross_errors["pdf"] and measured_cross_errors["tikz_pdf"]:
        measured_overall = max(max(measured_cross_errors["pdf"]), max(measured_cross_errors["tikz_pdf"]))
        claimed_overall = cross.get("maximum_key_position_error_mm")
        if (
            not isinstance(claimed_overall, (int, float))
            or isinstance(claimed_overall, bool)
            or abs(measured_overall - float(claimed_overall)) > 1e-6
        ):
            failures.append("cross-format overall maximum differs from per-object evidence")

    before_after = reports["before_after_proofs"]
    if not (
        before_after.get("schema_version") == "nndv-0.6.1-before-after-proof-1"
        and before_after.get("release") == RELEASE
        and before_after.get("status") == "PASS"
        and before_after.get("before_release") == "0.6.0"
        and before_after.get("after_release") == "0.6.1"
        and before_after.get("authoritative_before_run_id") == AUTHORITATIVE_060_RUN_ID
        and before_after.get("authoritative_before_manifest_sha256") == AUTHORITATIVE_060_MANIFEST_SHA256
        and before_after.get("before_inputs_are_diagnostic_only") is True
        and before_after.get("after_fresh_outputs") is True
        and before_after.get("templates") == 7
        and before_after.get("passed_templates") == 7
        and before_after.get("counts", {}).get("output_files") == 22
        and len(before_after.get("proof_files", [])) == 21
        and len(before_after.get("outputs", [])) == 22
        and len(before_after.get("cases", [])) == 7
        and {item.get("template") for item in before_after.get("cases", [])} == EXPECTED_TEMPLATE_KEYS
        and all(item.get("passed") is True for item in before_after.get("cases", []))
        and before_after.get("diagnostic_only") is True
        and before_after.get("release_quality_gate_input") is False
        and before_after.get("before_evidence_policy", {}).get("regenerated") is False
        and before_after.get("before_evidence_policy", {}).get("uses_0_6_1_as_before") is False
        and before_after.get("before_artifact", {}).get("manifest", {}).get("sha256")
        == AUTHORITATIVE_060_MANIFEST_SHA256
        and before_after.get("before_artifact", {}).get("read_only_verification", {}).get("status") == "PASS"
        and before_after.get("before_artifact", {}).get("read_only_verification", {}).get("run_id")
        == AUTHORITATIVE_060_RUN_ID
        and before_after.get("failures") == []
    ):
        failures.append("authoritative 0.6.0 to fresh 0.6.1 before/after proof evidence is incomplete")
    failures.extend(
        historical_negative_control_failures(
            before_after,
            reports["historical_0_6_0_oracle_raw"],
        )
    )

    fixture_raw = reports["fixture_oracle_raw"]
    if not (
        fixture_raw.get("schema_version") == "nndv-figure-svg-oracle-report-1"
        and fixture_raw.get("summary", {}).get("files") == 21
        and len(fixture_raw.get("reports", [])) == 21
    ):
        failures.append("raw adversarial oracle fixture report does not cover 21 persisted SVGs")
    fixture = reports["fixture_truth"]
    if not (
        fixture.get("passed") is True
        and fixture.get("fixture_count") == 21
        and fixture.get("classification_count") == 21
        and fixture.get("positive_count") == 2
        and fixture.get("negative_count") == 19
    ):
        failures.append("adversarial strict-oracle truth validation did not classify all 21 fixtures correctly")

    submission = reports["submission"]
    if not (
        submission.get("status") == "PASS"
        and submission.get("formats") == 7
        and submission.get("support_files", 0) >= 5
        and submission.get("failures") == []
    ):
        failures.append("seven-format submission package gate did not pass")
    performance = reports["performance"]
    if not (
        performance.get("schema_version") == "nndv-0.6.1-figure-studio-performance-1"
        and performance.get("release") == RELEASE
        and performance.get("status") == "PASS"
        and performance.get("figure_objects") == 1_000
    ):
        failures.append("retained 1,000-object Figure Studio performance gate did not pass")
    if reports["packaging"].get("passed") is not True:
        failures.append("wheel/sdist installation gate did not pass")
    if not (
        reports["audit"].get("schema_version") == "nndv-0.6.1-release-audit-1"
        and reports["audit"].get("release") == RELEASE
        and reports["audit"].get("status") == "PASS"
    ):
        failures.append("0.6.1 release/document audit did not pass")
    commands = reports["commands"]
    if commands.get("schema_version") != "nndv-0.6.1-full-command-report-1" or commands.get("failed") != 0:
        failures.append("full command report contains a failed or unaccounted command")
    return failures


def staged_payload_failures(staging: Path, reports: dict[str, dict[str, Any]]) -> list[str]:
    """Recompute report-to-file bindings before any release controls are written."""

    failures: list[str] = []
    publication_root = staging / "exports" / "publication"
    publication = reports["publication_exports"]
    expected: dict[str, dict[str, Any]] = {}
    for result in publication.get("results", []):
        kind = result.get("kind")
        key = str(result.get("key", ""))
        category = "templates" if kind == "template" else "real-models" if kind == "real-model" else ""
        if not category or not key or "/" in key or ".." in Path(key).parts:
            failures.append(f"unsafe or unknown publication result identity: {kind!r}/{key!r}")
            continue
        for relative, claim in result.get("files", {}).items():
            candidate = Path(relative)
            if candidate.is_absolute() or ".." in candidate.parts:
                failures.append(f"unsafe publication result path: {relative!r}")
                continue
            name = (Path(category) / key / candidate).as_posix()
            if name in expected:
                failures.append(f"duplicate publication result path: {name}")
            expected[name] = claim
    actual = {
        path.relative_to(publication_root).as_posix(): path
        for path in publication_root.rglob("*")
        if path.is_file() and not path.is_symlink()
    } if publication_root.is_dir() and not publication_root.is_symlink() else {}
    failures.extend(f"publication report file missing: {name}" for name in sorted(set(expected) - set(actual)))
    failures.extend(f"unreported publication file: {name}" for name in sorted(set(actual) - set(expected)))
    for name in sorted(set(expected) & set(actual)):
        claim = expected[name]
        path = actual[name]
        if claim.get("bytes") != path.stat().st_size or claim.get("sha256") != sha256(path):
            failures.append(f"publication file differs from report claim: {name}")
    svg_claims = {
        item.get("relative_path"): item
        for item in publication.get("svg_inputs", [])
    }
    expected_svg_names = {name for name in expected if name.endswith(".svg")}
    if set(svg_claims) != expected_svg_names:
        failures.append("publication svg_inputs inventory differs from the per-figure file inventory")
    for name in sorted(expected_svg_names & set(svg_claims) & set(actual)):
        claim = svg_claims[name]
        path = actual[name]
        if claim.get("bytes") != path.stat().st_size or claim.get("sha256") != sha256(path):
            failures.append(f"publication SVG input differs from its fresh file: {name}")

    submission = reports["submission"]
    submission_root = staging / "exports" / "submission-package"
    submission_files = {
        path.name: path
        for path in submission_root.iterdir()
        if path.is_file() and not path.is_symlink()
    } if submission_root.is_dir() and not submission_root.is_symlink() else {}
    if set(submission.get("files", [])) != set(submission_files):
        failures.append("submission report inventory differs from the staged package")
    if any(path.stat().st_size == 0 for path in submission_files.values()):
        failures.append("submission package contains an empty file")

    fixture_root = staging / "exports" / "oracle-fixtures"
    fixture_svgs = {
        path.name: path
        for path in fixture_root.glob("*.svg")
        if path.is_file() and not path.is_symlink()
    } if fixture_root.is_dir() and not fixture_root.is_symlink() else {}
    fixture_names = {
        item.get("fixture")
        for item in reports["fixture_truth"].get("cases", [])
    }
    if len(fixture_svgs) != 21 or set(fixture_svgs) != fixture_names:
        failures.append("staged adversarial fixture files differ from the 21-case truth report")

    strict_hashes = sorted(str(item.get("sha256")) for item in reports["strict_svg_oracle_raw"].get("reports", []))
    export_hashes = sorted(str(item.get("sha256")) for item in publication.get("svg_inputs", []))
    if strict_hashes != export_hashes:
        failures.append("raw strict oracle hashes differ from the fresh publication SVG hashes")

    for report_name, directory_name, inventory_name in (
        ("cross_format_positions", "cross-format-proofs", "proof_files"),
        ("before_after_proofs", "before-after-proofs", "outputs"),
    ):
        proof_report = reports[report_name]
        proof_root = staging / "exports" / directory_name
        proof_claims: dict[str, dict[str, Any]] = {}
        for claim in proof_report.get(inventory_name, []):
            relative = Path(str(claim.get("relative_path", "")))
            if (
                not relative.parts
                or relative.is_absolute()
                or ".." in relative.parts
                or relative.as_posix() in proof_claims
            ):
                failures.append(f"unsafe or duplicate {report_name} proof path: {relative}")
                continue
            proof_claims[relative.as_posix()] = claim
        proof_actual = {
            path.relative_to(proof_root).as_posix(): path
            for path in proof_root.rglob("*")
            if path.is_file() and not path.is_symlink()
        } if proof_root.is_dir() and not proof_root.is_symlink() else {}
        if set(proof_claims) != set(proof_actual):
            failures.append(f"{report_name} report inventory differs from the staged proof payload")
        for name in sorted(set(proof_claims) & set(proof_actual)):
            claim = proof_claims[name]
            path = proof_actual[name]
            if claim.get("bytes") != path.stat().st_size or claim.get("sha256") != sha256(path):
                failures.append(f"{report_name} proof differs from report claim: {name}")

    cross = reports["cross_format_positions"]
    cross_outputs = {
        item.get("relative_path"): item
        for item in cross.get("proof_files", [])
        if isinstance(item, dict)
    }
    for case in cross.get("cases", []):
        svg_relative = case.get("svg")
        svg_claim = svg_claims.get(svg_relative, {})
        if case.get("svg_sha256") != svg_claim.get("sha256"):
            failures.append(f"cross-format case is not bound to a fresh SVG: {svg_relative}")
        proofs = case.get("proofs", {})
        for label in ("pdf_300dpi", "tikz_compiled_pdf_300dpi"):
            if proofs.get(label) not in cross_outputs:
                failures.append(f"cross-format case proof is absent from its output inventory: {svg_relative}/{label}")
        expected_svg_proof = str(Path(str(svg_relative)).parent / "figure.proof-300dpi.png")
        if proofs.get("svg_300dpi") != expected_svg_proof or expected_svg_proof not in expected:
            failures.append(f"cross-format SVG proof is not a fresh publication proof: {svg_relative}")

    before_after = reports["before_after_proofs"]
    before_outputs = {
        item.get("relative_path"): item
        for item in before_after.get("outputs", [])
        if isinstance(item, dict)
    }
    for case in before_after.get("cases", []):
        template = str(case.get("template", ""))
        before = case.get("before", {})
        after = case.get("after", {})
        before_source = before.get("source", {})
        expected_before_path = f"exports/figure-templates/{template}/figure.svg"
        authoritative_claim = AUTHORITATIVE_060_TEMPLATE_SVGS.get(template, {})
        if not (
            before.get("source_kind") == "persisted-v0.6.0-artifact-svg"
            and before.get("regenerated_from_source") is False
            and before_source.get("relative_path") == expected_before_path
            and before_source.get("bytes") == authoritative_claim.get("bytes")
            and before_source.get("sha256") == authoritative_claim.get("sha256")
        ):
            failures.append(f"before proof is not bound to the persisted 0.6.0 SVG: {template}")
        for field, publication_name in (
            ("svg_source", f"templates/{template}/figure.svg"),
            ("proof_source", f"templates/{template}/figure.proof-300dpi.png"),
        ):
            source_claim = after.get(field, {})
            publication_claim = expected.get(publication_name, {})
            if not (
                after.get("fresh_export_report_bound") is True
                and source_claim.get("relative_path") == publication_name
                and source_claim.get("bytes") == publication_claim.get("bytes")
                and source_claim.get("sha256") == publication_claim.get("sha256")
            ):
                failures.append(f"after proof source differs from the fresh publication corpus: {template}/{field}")
        for claim in (before.get("proof", {}), after.get("proof", {}), case.get("comparison", {})):
            recorded = before_outputs.get(claim.get("relative_path"), {})
            if claim.get("bytes") != recorded.get("bytes") or claim.get("sha256") != recorded.get("sha256"):
                failures.append(f"before/after case proof differs from output inventory: {template}")
    integrity = before_after.get("integrity_manifest", {})
    integrity_record = before_outputs.get("integrity-manifest.json", {})
    if integrity.get("sha256") != integrity_record.get("sha256") or integrity.get("bytes") != integrity_record.get("bytes"):
        failures.append("before/after integrity manifest differs from the output inventory")

    negative_control = before_after.get("strict_negative_control", {})
    raw_claim = negative_control.get("raw_report", {})
    raw_path = staging / EXPECTED_REPORTS["historical_0_6_0_oracle_raw"]
    if not (
        raw_claim.get("relative_path") == EXPECTED_REPORTS["historical_0_6_0_oracle_raw"]
        and raw_path.is_file()
        and not raw_path.is_symlink()
        and raw_claim.get("bytes") == raw_path.stat().st_size
        and raw_claim.get("sha256") == sha256(raw_path)
    ):
        failures.append("authoritative 0.6.0 strict negative-control raw report is missing or differs from its binding")

    return failures


def normalize_paths(staging: Path, reports: dict[str, dict[str, Any]]) -> None:
    """Replace transient controller paths while retaining hashes and raw metrics."""

    publication = reports["publication_exports"]
    publication["output_root"] = "exports/publication"
    write_json(staging / EXPECTED_REPORTS["publication_exports"], publication)
    by_hash = {
        item["sha256"]: f"exports/publication/{item['relative_path']}"
        for item in publication.get("svg_inputs", [])
    }
    strict_raw = reports["strict_svg_oracle_raw"]
    for item in strict_raw.get("reports", []):
        if item.get("sha256") in by_hash:
            item["file"] = by_hash[item["sha256"]]
    write_json(staging / EXPECTED_REPORTS["strict_svg_oracle_raw"], strict_raw)
    strict = reports["strict_svg_oracle"]
    for item in strict.get("cases", []):
        if item.get("sha256") in by_hash:
            item["file"] = by_hash[item["sha256"]]
    write_json(staging / EXPECTED_REPORTS["strict_svg_oracle"], strict)
    cross = reports["cross_format_positions"]
    cross["proof_root"] = "exports/cross-format-proofs"
    write_json(staging / EXPECTED_REPORTS["cross_format_positions"], cross)
    before_after = reports["before_after_proofs"]
    before_after["output_root"] = "exports/before-after-proofs"
    write_json(staging / EXPECTED_REPORTS["before_after_proofs"], before_after)
    fixture_raw = reports["fixture_oracle_raw"]
    for item in fixture_raw.get("reports", []):
        item["file"] = f"exports/oracle-fixtures/{Path(str(item.get('file', 'unknown.svg'))).name}"
    write_json(staging / EXPECTED_REPORTS["fixture_oracle_raw"], fixture_raw)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--started-utc", required=True)
    parser.add_argument("--started-epoch", type=float, required=True)
    args = parser.parse_args()
    staging = args.staging.resolve()
    source_root = args.source_root.resolve()
    artifact_root = args.artifact_root.resolve()
    if not staging.is_dir() or staging.is_symlink():
        raise SystemExit("artifact staging directory is absent or unsafe")
    if not source_root.is_dir() or source_root.is_symlink():
        raise SystemExit("clean source root is absent or unsafe")
    reports: dict[str, dict[str, Any]] = {}
    for name, relative in EXPECTED_REPORTS.items():
        try:
            reports[name] = load_object(staging / relative)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise SystemExit(f"required full report is invalid ({name}): {exc}") from exc
    failures = report_failures(reports)
    failures.extend(staged_payload_failures(staging, reports))
    if failures:
        raise SystemExit("refusing to create a 0.6.1 release artifact:\n- " + "\n- ".join(failures))
    normalize_paths(staging, reports)

    source_report = load_object(args.source_report.resolve())
    source_files = source_report.get("files", {})
    if source_report.get("release") != "0.6.1" or source_report.get("passed") is not True or not isinstance(source_files, dict):
        raise SystemExit("clean source report is not a passed 0.6.1 snapshot")
    if source_report.get("allowlist") != "verification/source-allowlist-0.6.1.json":
        raise SystemExit("clean source report did not use the 0.6.1 source allowlist")
    replay_root = staging / "source" / "replay-source"
    if replay_root.exists():
        raise SystemExit("staging already contains source/replay-source")
    for name, item in sorted(source_files.items()):
        source_relative = Path(name)
        if source_relative.is_absolute() or ".." in source_relative.parts:
            raise SystemExit(f"unsafe source inventory path: {name}")
        source = source_root / source_relative
        if not source.is_file() or source.is_symlink():
            raise SystemExit(f"source inventory file is absent or unsafe: {name}")
        if source.stat().st_size != item.get("bytes") or sha256(source) != item.get("sha256"):
            raise SystemExit(f"source changed after clean snapshot creation: {name}")
        target = replay_root / source_relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    normalized_source_report = dict(source_report)
    normalized_source_report["source"] = "source/replay-source"
    normalized_source_report["snapshot"] = "source/replay-source"
    write_json(staging / "reports" / "source" / "snapshot.json", normalized_source_report)

    ended = time.time()
    quick = reports["quick"]
    browser_assertions = sum(
        int(reports[name].get("assertion_count", reports[name].get("counts", {}).get("assertions", 0)))
        for name in ("editor", "responsive", "semantic", "product", "trial", "figure")
    )
    verification = {
        "schema_version": "nndv-0.6.1-full-verification-1",
        "release": RELEASE,
        "run_id": args.run_id,
        "status": "PASS",
        "started_utc": args.started_utc,
        "ended_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "elapsed_seconds": round(ended - args.started_epoch, 3),
        "source": {
            "file_count": source_report["file_count"],
            "digest": source_report["source_tree_digest"],
            "allowlist": source_report["allowlist"],
            "allowlist_sha256": source_report["allowlist_sha256"],
        },
        "python": quick["python"],
        "coverage": quick["coverage"],
        "chrome": {
            "suites": 6,
            "assertions": browser_assertions,
            "editor_scenarios": reports["editor"]["counts"]["passed"],
            "responsive_viewports": reports["responsive"]["viewport_count"],
            "figure_studio": reports["figure"]["counts"],
            "figure_required_workflows": reports["figure"]["required_workflows"],
            "figure_interaction_median_ms": reports["figure"]["median_interaction_ms"],
            "console_page_request_errors": reports["figure"]["counts"]["console_page_request_errors"],
        },
        "exports": reports["publication_exports"]["counts"],
        "strict_svg_oracle": reports["strict_svg_oracle"],
        "cross_format_positions": reports["cross_format_positions"],
        "strict_negative_control": reports["before_after_proofs"]["strict_negative_control"],
        "before_after_proofs": reports["before_after_proofs"],
        "oracle_fixture_truth": reports["fixture_truth"],
        "performance": {
            **reports["performance"],
            "browser_interaction_median_ms": reports["figure"]["median_interaction_ms"],
        },
        "packaging": {
            "checks": reports["packaging"].get("checks"),
            "wheel": reports["packaging"].get("wheel"),
            "sdist": reports["packaging"].get("sdist"),
            "passed": True,
        },
        "human_evidence": {
            "participants": 0,
            "sessions": 0,
            "human_metrics": {
                "first_figure_median_ms": None,
                "paper_ready_median_ms": None,
                "core_task_success_rate": None,
                "serious_semantic_errors": None,
            },
            "human_usability_claim": False,
            "automation_is_not_human_evidence": True,
            "old_sessions_migrated": False,
        },
        "reports": EXPECTED_REPORTS,
        "failures": [],
    }
    write_json(staging / "verification.json", verification)

    existing, unsafe = inventory(staging)
    if unsafe:
        raise SystemExit("unsafe object in artifact staging: " + ", ".join(unsafe))
    entries: dict[str, dict[str, Any]] = {}
    for name, path in sorted(existing.items()):
        if name in {"MANIFEST.json", "SHA256SUMS"}:
            raise SystemExit(f"staging contains reserved control file: {name}")
        entries[name] = {
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "mode": f"{stat.S_IMODE(os.lstat(path).st_mode):04o}",
        }
    manifest = {
        "schema_version": "nndv-0.6.1-artifact-manifest-1",
        "release": RELEASE,
        "run_id": args.run_id,
        "source": {
            "file_count": source_report["file_count"],
            "digest": source_report["source_tree_digest"],
            "allowlist": source_report["allowlist"],
            "allowlist_sha256": source_report["allowlist_sha256"],
        },
        "entries": entries,
    }
    write_json(staging / "MANIFEST.json", manifest)
    checksum_names = sorted(entries) + ["MANIFEST.json"]
    (staging / "SHA256SUMS").write_text(
        "".join(f"{sha256(staging / name)}  {name}\n" for name in checksum_names),
        encoding="utf-8",
    )

    artifact_root.mkdir(parents=True, exist_ok=True)
    final = artifact_root / args.run_id
    intermediate = artifact_root / f".staging-{args.run_id}"
    if final.exists() or intermediate.exists():
        raise SystemExit(f"refusing to overwrite release artifact path: {final}")
    try:
        shutil.copytree(staging, intermediate, symlinks=False)
        intermediate.rename(final)
    except Exception:
        if intermediate.is_dir() and not intermediate.is_symlink():
            shutil.rmtree(intermediate)
        raise
    print(
        "NNDV_061_ARTIFACT_CREATED="
        + json.dumps(
            {
                "artifact": str(final),
                "run_id": args.run_id,
                "manifest_entries": len(entries),
                "source_file_count": source_report["file_count"],
                "source_digest": source_report["source_tree_digest"],
                "manifest_sha256": sha256(final / "MANIFEST.json"),
                "sha256sums_sha256": sha256(final / "SHA256SUMS"),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
