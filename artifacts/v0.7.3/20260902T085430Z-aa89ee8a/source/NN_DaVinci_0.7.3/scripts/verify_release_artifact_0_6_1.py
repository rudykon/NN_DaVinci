#!/usr/bin/env python3
"""Read-only verification for an NN_DaVinci 0.6.1 release artifact."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any


RELEASE = "0.6.1 Beta — Publication Fidelity & Model-to-Figure Completion"
MINIMUM_FONT_WITH_TOLERANCE_PT = 6.99
MINIMUM_STROKE_PT = 0.1
MINIMUM_RETAINED_EDITOR_SCENARIOS = 10
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
HISTORICAL_ORACLE_REPORT_KEY = "historical_0_6_0_oracle_raw"
HISTORICAL_ORACLE_REPORT_RELATIVE = "reports/exports/authoritative-0.6.0-figure-svg-oracle.json"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
CONTROL_FILES = frozenset({"MANIFEST.json", "SHA256SUMS"})
FORBIDDEN_SOURCE_PARTS = frozenset(
    {
        ".coverage",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "artifacts",
        "build",
        "dist",
        "node_modules",
    }
)
REQUIRED_FIGURE_E2E_WORKFLOWS = frozenset(
    {
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
    }
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative(value: str) -> PurePosixPath:
    relative = PurePosixPath(value)
    if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError(f"unsafe manifest path: {value!r}")
    return relative


def editor_e2e_failures(
    report: dict[str, Any],
    *,
    normalized_count: Any = None,
) -> list[str]:
    """Recompute the retained Editor E2E accounting from raw scenarios."""

    failures: list[str] = []
    scenarios_value = report.get("scenarios")
    counts_value = report.get("counts")
    scenarios = scenarios_value if isinstance(scenarios_value, list) else []
    counts = counts_value if isinstance(counts_value, dict) else {}
    count_fields = ("e2e_scenarios", "passed", "failed", "skipped", "assertions")
    counts_are_integers = all(
        isinstance(counts.get(name), int) and not isinstance(counts.get(name), bool)
        for name in count_fields
    )
    ids = [item.get("id") for item in scenarios if isinstance(item, dict)]
    assertions = [item.get("assertions") for item in scenarios if isinstance(item, dict)]
    valid_assertions = all(
        isinstance(value, int) and not isinstance(value, bool) and value > 0
        for value in assertions
    )
    assertion_total = sum(
        int(value)
        for value in assertions
        if isinstance(value, int) and not isinstance(value, bool)
    )
    if not (
        report.get("schema_version") == "1.0"
        and len(scenarios) >= MINIMUM_RETAINED_EDITOR_SCENARIOS
        and len(ids) == len(scenarios)
        and all(isinstance(value, str) and value for value in ids)
        and len(set(ids)) == len(ids)
        and len(assertions) == len(scenarios)
        and valid_assertions
        and all(
            isinstance(item, dict)
            and item.get("status") == "passed"
            and item.get("console_errors") == []
            for item in scenarios
        )
        and counts_are_integers
        and counts.get("e2e_scenarios") == len(scenarios)
        and counts.get("passed") == len(scenarios)
        and counts.get("failed") == 0
        and counts.get("skipped") == 0
        and counts.get("assertions") == assertion_total
    ):
        failures.append(
            "Editor E2E raw report does not retain at least ten unique, clean scenarios with exact all-pass accounting"
        )
    if normalized_count is not None and not (
        isinstance(normalized_count, int)
        and not isinstance(normalized_count, bool)
        and normalized_count == len(scenarios)
        and normalized_count >= MINIMUM_RETAINED_EDITOR_SCENARIOS
    ):
        failures.append("normalized Editor scenario count differs from the raw retained E2E report")
    return failures


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
                mode = os.lstat(path).st_mode
                if stat.S_ISLNK(mode):
                    unsafe.append(f"symlink:{relative}")
                elif stat.S_ISDIR(mode):
                    pending.append(path)
                elif stat.S_ISREG(mode):
                    files[relative] = path
                else:
                    unsafe.append(f"special:{relative}")
    return files, sorted(unsafe)


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain an object")
    return value


def _negative_control_contract_is_exact(value: Any) -> bool:
    return isinstance(value, dict) and all(
        value.get(name) is expected
        for name, expected in {
            "final_dom_only": True,
            "metadata_trusted": False,
            "python_proof_imported": False,
            "data_scale_claims_trusted": False,
            "stroke_under_full_ctm": True,
        }.items()
    )


def _historical_negative_control_failures(
    root: Path,
    raw: dict[str, Any],
    before_after: dict[str, Any],
    verification: dict[str, Any],
) -> list[str]:
    """Independently validate the pinned persisted-0.6.0 strict-oracle control."""

    failures: list[str] = []
    raw_summary = raw.get("summary")
    raw_cases_value = raw.get("reports")
    if not (
        raw.get("schema_version") == "nndv-figure-svg-oracle-report-1"
        and raw.get("oracle") == "figure-final-svg-chrome-v1"
        and raw.get("passed") is False
        and _negative_control_contract_is_exact(raw.get("measurement_contract"))
        and isinstance(raw_summary, dict)
        and raw_summary.get("files") == 7
        and raw_summary.get("passed") == 0
        and raw_summary.get("failed") == 7
        and isinstance(raw_summary.get("issues"), int)
        and not isinstance(raw_summary.get("issues"), bool)
        and raw_summary["issues"] > 0
        and isinstance(raw_cases_value, list)
        and len(raw_cases_value) == 7
    ):
        failures.append("historical strict negative-control raw Chrome report is incomplete")
    raw_cases = raw_cases_value if isinstance(raw_cases_value, list) else []

    template_by_hash = {claim["sha256"]: template for template, claim in AUTHORITATIVE_060_TEMPLATE_SVGS.items()}
    observed_raw: dict[str, dict[str, Any]] = {}
    total_issues = 0
    for item in raw_cases:
        if not isinstance(item, dict):
            failures.append("historical strict negative-control contains a non-object case")
            continue
        template = template_by_hash.get(item.get("sha256"))
        issues = item.get("issues")
        case_summary = item.get("summary")
        issue_count = case_summary.get("issue_count") if isinstance(case_summary, dict) else None
        issue_counts = item.get("issue_counts")
        source = item.get("source")
        raw_file = item.get("file")
        raw_path = Path(raw_file) if isinstance(raw_file, str) else None
        try:
            expected_uri = raw_path.as_uri() if raw_path is not None and raw_path.is_absolute() else None
        except ValueError:
            expected_uri = None
        expected_relative = f"exports/figure-templates/{template}/figure.svg" if template else ""
        expected_suffix = f"/{AUTHORITATIVE_060_RUN_ID}/{expected_relative}" if template else ""
        derived_issue_counts = (
            Counter(issue["code"] for issue in issues if isinstance(issue, dict) and isinstance(issue.get("code"), str) and issue["code"])
            if isinstance(issues, list)
            else Counter()
        )
        issue_counts_are_exact = (
            isinstance(issues, list)
            and sum(derived_issue_counts.values()) == len(issues)
            and isinstance(issue_counts, dict)
            and dict(derived_issue_counts) == issue_counts
            and all(
                isinstance(code, str) and code and isinstance(count, int) and not isinstance(count, bool) and count > 0 for code, count in issue_counts.items()
            )
        )
        if not (
            template is not None
            and template not in observed_raw
            and item.get("passed") is False
            and isinstance(issues, list)
            and len(issues) > 0
            and isinstance(issue_count, int)
            and not isinstance(issue_count, bool)
            and issue_count == len(issues)
            and issue_counts_are_exact
            and item.get("browser_errors") == []
            and isinstance(raw_file, str)
            and raw_file.replace("\\", "/").endswith(expected_suffix)
            and isinstance(source, dict)
            and source.get("loaded_from_persisted_file") is True
            and source.get("metadata_consulted") is False
            and source.get("url") == expected_uri
        ):
            failures.append(f"historical strict negative-control raw case is invalid: {template!r}")
            continue
        total_issues += issue_count
        observed_raw[template] = item
    if set(observed_raw) != EXPECTED_TEMPLATE_KEYS:
        failures.append("historical strict negative-control does not cover the exact seven templates")
    if isinstance(raw_summary, dict) and raw_summary.get("issues") != total_issues:
        failures.append("historical strict negative-control raw issue total is inconsistent")

    control_value = before_after.get("strict_negative_control")
    if not isinstance(control_value, dict):
        return [*failures, "before/after report has no historical strict negative-control binding"]
    control = control_value
    expected_summary = {"files": 7, "passed": 0, "failed": 7, "issues": total_issues}
    control_cases_value = control.get("cases")
    before_artifact_value = before_after.get("before_artifact")
    before_artifact = before_artifact_value if isinstance(before_artifact_value, dict) else {}
    before_manifest_value = before_artifact.get("manifest")
    before_manifest = before_manifest_value if isinstance(before_manifest_value, dict) else {}
    before_verification_value = before_artifact.get("read_only_verification")
    before_verification = before_verification_value if isinstance(before_verification_value, dict) else {}
    if not (
        before_after.get("authoritative_before_run_id") == AUTHORITATIVE_060_RUN_ID
        and before_after.get("authoritative_before_manifest_sha256") == AUTHORITATIVE_060_MANIFEST_SHA256
        and before_artifact.get("run_id") == AUTHORITATIVE_060_RUN_ID
        and before_manifest.get("relative_path") == "MANIFEST.json"
        and before_manifest.get("sha256") == AUTHORITATIVE_060_MANIFEST_SHA256
        and before_verification.get("status") == "PASS"
        and before_verification.get("run_id") == AUTHORITATIVE_060_RUN_ID
        and control.get("schema_version") == "nndv-0.6.1-authoritative-0.6.0-strict-negative-control-1"
        and control.get("status") == "PASS"
        and control.get("expected_failure_observed") is True
        and control.get("historical_svg_quality_passed") is False
        and control.get("oracle_passed") is False
        and control.get("authoritative_run_id") == AUTHORITATIVE_060_RUN_ID
        and control.get("authoritative_manifest_sha256") == AUTHORITATIVE_060_MANIFEST_SHA256
        and control.get("manifest_hashes_matched") is True
        and control.get("expected_templates") == list(EXPECTED_TEMPLATE_ORDER)
        and _negative_control_contract_is_exact(control.get("measurement_contract"))
        and control.get("summary") == expected_summary
        and isinstance(control_cases_value, list)
        and len(control_cases_value) == 7
        and control.get("failures") == []
    ):
        failures.append("before/after historical strict negative-control binding is incomplete")
    control_cases = control_cases_value if isinstance(control_cases_value, list) else []
    control_by_template = {item.get("template"): item for item in control_cases if isinstance(item, dict) and isinstance(item.get("template"), str)}
    if len(control_by_template) != len(control_cases) or set(control_by_template) != EXPECTED_TEMPLATE_KEYS:
        failures.append("historical strict negative-control has an unexpected or repeated template set")

    before_cases_value = before_after.get("cases")
    before_cases = before_cases_value if isinstance(before_cases_value, list) else []
    before_by_template = {item.get("template"): item for item in before_cases if isinstance(item, dict) and isinstance(item.get("template"), str)}
    if len(before_by_template) != len(before_cases) or set(before_by_template) != EXPECTED_TEMPLATE_KEYS:
        failures.append("before/after cases do not cover the exact seven pinned templates")
    for template in EXPECTED_TEMPLATE_ORDER:
        expected = AUTHORITATIVE_060_TEMPLATE_SVGS[template]
        raw_item = observed_raw.get(template, {})
        control_case = control_by_template.get(template, {})
        before_case = before_by_template.get(template, {})
        before_value = before_case.get("before")
        before = before_value if isinstance(before_value, dict) else {}
        before_source_value = before.get("source")
        before_source = before_source_value if isinstance(before_source_value, dict) else {}
        raw_case_summary_value = raw_item.get("summary")
        raw_case_summary = raw_case_summary_value if isinstance(raw_case_summary_value, dict) else {}
        expected_path = f"exports/figure-templates/{template}/figure.svg"
        if not (
            control_case.get("manifest_path") == expected_path
            and control_case.get("manifest_bytes") == expected["bytes"]
            and control_case.get("manifest_sha256") == expected["sha256"]
            and control_case.get("oracle_sha256") == expected["sha256"]
            and control_case.get("oracle_passed") is False
            and control_case.get("issue_count") == raw_case_summary.get("issue_count")
            and control_case.get("issue_counts") == raw_item.get("issue_counts")
            and control_case.get("browser_errors") == 0
            and control_case.get("loaded_from_persisted_file") is True
            and control_case.get("metadata_consulted") is False
        ):
            failures.append(f"historical strict negative-control case is not pinned: {template}")
        if not (
            before_source.get("relative_path") == expected_path
            and before_source.get("bytes") == expected["bytes"]
            and before_source.get("sha256") == expected["sha256"]
        ):
            failures.append(f"before/after source is not the pinned historical SVG: {template}")

    raw_claim = control.get("raw_report")
    raw_path = root / HISTORICAL_ORACLE_REPORT_RELATIVE
    if not (
        isinstance(raw_claim, dict)
        and raw_claim.get("relative_path") == HISTORICAL_ORACLE_REPORT_RELATIVE
        and raw_path.is_file()
        and not raw_path.is_symlink()
        and raw_claim.get("bytes") == raw_path.stat().st_size
        and raw_claim.get("sha256") == sha256(raw_path)
    ):
        failures.append("historical strict negative-control raw report binding is invalid")
    if verification.get("strict_negative_control") != control:
        failures.append("verification strict negative-control differs from before/after evidence")
    return failures


def _verification_failures(
    verification: dict[str, Any],
    manifest: dict[str, Any],
    source_digest: str,
    expected_files: set[str],
) -> list[str]:
    failures: list[str] = []
    if verification.get("schema_version") != "nndv-0.6.1-full-verification-1":
        failures.append("unexpected full verification schema")
    if verification.get("release") != RELEASE:
        failures.append("unexpected full verification release identity")
    if verification.get("status") != "PASS" or verification.get("failures"):
        failures.append("verification.json does not report a clean PASS")
    if verification.get("run_id") != manifest.get("run_id"):
        failures.append("run_id differs between verification and manifest")
    if verification.get("source", {}).get("digest") != source_digest:
        failures.append("verification source digest differs from inventory")

    python = verification.get("python", {})
    if not (
        python.get("collected", 0) >= 171
        and python.get("passed") == python.get("collected")
        and python.get("failed") == 0
        and python.get("errors") == 0
        and python.get("skipped") == 0
        and python.get("deselected") == 0
        and python.get("inherited_0_6_0_tests") == 171
        and python.get("baseline_0_6_0_missing") == []
    ):
        failures.append("Python evidence does not retain and pass all 171 authoritative 0.6.0 tests")
    coverage_gates = verification.get("coverage", {}).get("gates", {})
    if coverage_gates != {
        "all_package_passed": True,
        "expanded_core_passed": True,
        "old_core_passed": True,
    }:
        failures.append("one or more retained coverage gates are absent or failed")

    editor_scenarios = verification.get("chrome", {}).get("editor_scenarios")
    if not (
        isinstance(editor_scenarios, int)
        and not isinstance(editor_scenarios, bool)
        and editor_scenarios >= MINIMUM_RETAINED_EDITOR_SCENARIOS
    ):
        failures.append("normalized Chrome evidence does not retain at least ten Editor E2E scenarios")

    exports = verification.get("exports", {})
    required_export_counts = {
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
    if any(exports.get(name) != expected for name, expected in required_export_counts.items()):
        failures.append("publication artifact counts do not cover 14 figures and all seven formats")
    strict = verification.get("strict_svg_oracle", {})
    if not (
        strict.get("status") == "PASS"
        and strict.get("final_svg_files") == 14
        and strict.get("passed_svg_files") == 14
        and strict.get("fresh_export_hashes_matched") is True
        and strict.get("python_figure_proof_imported") is False
        and strict.get("measurement_contract", {}).get("stroke_under_full_ctm") is True
        and strict.get("thresholds", {}).get("font_numeric_tolerance_pt") == 0.01
        and strict.get("thresholds", {}).get("minimum_stroke_pt") == MINIMUM_STROKE_PT
        and strict.get("metrics", {}).get("geometry_issues") == 0
        and strict.get("metrics", {}).get("browser_errors") == 0
        and isinstance(strict.get("metrics", {}).get("minimum_font_pt"), (int, float))
        and not isinstance(strict["metrics"]["minimum_font_pt"], bool)
        and strict["metrics"]["minimum_font_pt"] >= MINIMUM_FONT_WITH_TOLERANCE_PT
        and isinstance(strict.get("metrics", {}).get("minimum_stroke_pt"), (int, float))
        and not isinstance(strict["metrics"]["minimum_stroke_pt"], bool)
        and strict["metrics"]["minimum_stroke_pt"] >= MINIMUM_STROKE_PT
        and isinstance(strict.get("metrics", {}).get("maximum_stroke_pt"), (int, float))
        and not isinstance(strict["metrics"]["maximum_stroke_pt"], bool)
        and len(strict.get("cases", [])) == 14
        and all(
            item.get("passed") is True
            and item.get("stroke_count", 0) > 0
            and isinstance(item.get("minimum_stroke_pt"), (int, float))
            and isinstance(item.get("maximum_stroke_pt"), (int, float))
            for item in strict.get("cases", [])
        )
    ):
        failures.append("strict final-SVG Chrome oracle evidence is incomplete or failed")
    cross = verification.get("cross_format_positions", {})
    cross_errors = cross.get("maximum_key_position_error_by_format_mm", {})
    if not (
        cross.get("schema_version") == "nndv-0.6.1-cross-format-position-validation-1"
        and cross.get("release") == RELEASE
        and cross.get("status") == "PASS"
        and cross.get("figures") == 14
        and cross.get("passed_figures") == 14
        and cross.get("key_positions_compared", 0) >= 84
        and isinstance(cross.get("maximum_key_position_error_mm"), (int, float))
        and cross["maximum_key_position_error_mm"] <= 1.0
        and isinstance(cross.get("maximum_page_size_error_mm"), (int, float))
        and cross["maximum_page_size_error_mm"] <= 0.05
        and set(cross_errors) == {"pdf", "tikz_pdf"}
        and all(isinstance(value, (int, float)) and value <= 1.0 for value in cross_errors.values())
        and cross.get("measurement_sources", {}).get("figure_ir_or_python_proof_used") is False
        and len(cross.get("proof_files", [])) == 28
        and len(cross.get("cases", [])) == 14
        and all(item.get("passed") is True and item.get("key_count", 0) >= 3 for item in cross.get("cases", []))
        and cross.get("failures") == []
    ):
        failures.append("SVG/PDF/compiled-TikZ-PDF key-position evidence is incomplete or exceeds 1 mm")
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
            if measured is None or not isinstance(claimed_case_errors.get(label), (int, float)) or abs(measured - float(claimed_case_errors[label])) > 1e-6:
                failures.append(f"cross-format per-case maximum is inconsistent: {case.get('svg')}/{label}")
    if measured_key_count != cross.get("key_positions_compared"):
        failures.append("cross-format key-position count differs from the per-object evidence")
    for label, values in measured_cross_errors.items():
        measured = max(values) if values else None
        if measured is None or not isinstance(cross_errors.get(label), (int, float)) or abs(measured - float(cross_errors[label])) > 1e-6:
            failures.append(f"cross-format top-level {label} maximum differs from per-object evidence")
    if measured_cross_errors["pdf"] and measured_cross_errors["tikz_pdf"]:
        measured_overall = max(max(measured_cross_errors["pdf"]), max(measured_cross_errors["tikz_pdf"]))
        claimed_overall = cross.get("maximum_key_position_error_mm")
        if not isinstance(claimed_overall, (int, float)) or isinstance(claimed_overall, bool) or abs(measured_overall - float(claimed_overall)) > 1e-6:
            failures.append("cross-format overall maximum differs from per-object evidence")
    before_after = verification.get("before_after_proofs", {})
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
        and before_after.get("before_artifact", {}).get("manifest", {}).get("sha256") == AUTHORITATIVE_060_MANIFEST_SHA256
        and before_after.get("before_artifact", {}).get("read_only_verification", {}).get("status") == "PASS"
        and before_after.get("before_artifact", {}).get("read_only_verification", {}).get("run_id") == AUTHORITATIVE_060_RUN_ID
        and before_after.get("failures") == []
    ):
        failures.append("authoritative 0.6.0 to fresh 0.6.1 before/after evidence is incomplete")
    fixtures = verification.get("oracle_fixture_truth", {})
    if not (
        fixtures.get("passed") is True
        and fixtures.get("fixture_count") == 21
        and fixtures.get("classification_count") == 21
        and fixtures.get("positive_count") == 2
        and fixtures.get("negative_count") == 19
    ):
        failures.append("21-case strict-oracle adversarial truth suite is incomplete or failed")
    workflows = verification.get("chrome", {}).get("figure_required_workflows", {})
    if set(workflows) != REQUIRED_FIGURE_E2E_WORKFLOWS or not all(value is True for value in workflows.values()):
        failures.append("0.6.1 Figure Studio browser workflow evidence is incomplete")

    human = verification.get("human_evidence", {})
    expected_human_metrics = {
        "first_figure_median_ms": None,
        "paper_ready_median_ms": None,
        "core_task_success_rate": None,
        "serious_semantic_errors": None,
    }
    if not (
        human.get("participants") == 0
        and human.get("sessions") == 0
        and human.get("human_metrics") == expected_human_metrics
        and human.get("human_usability_claim") is False
        and human.get("automation_is_not_human_evidence") is True
        and human.get("old_sessions_migrated") is False
    ):
        failures.append("artifact violates the zero-participant/null-human-metric boundary")

    reports = verification.get("reports", {})
    if not isinstance(reports, dict):
        failures.append("verification report map is not an object")
    else:
        if reports.get(HISTORICAL_ORACLE_REPORT_KEY) != HISTORICAL_ORACLE_REPORT_RELATIVE:
            failures.append("verification report map lacks the pinned historical strict-oracle report")
        for name, relative in reports.items():
            try:
                normalized = safe_relative(str(relative)).as_posix()
            except ValueError as exc:
                failures.append(f"unsafe verification report {name}: {exc}")
                continue
            if normalized not in expected_files:
                failures.append(f"verification report is absent from the manifest: {name} -> {normalized}")
    return failures


def _payload_report_failures(root: Path, manifested: set[str]) -> list[str]:
    failures: list[str] = []
    try:
        publication = _load_object(root / "reports/exports/publication-artifacts.json")
        strict_raw = _load_object(root / "reports/exports/figure-svg-oracle.json")
        strict_validation = _load_object(root / "reports/exports/strict-svg-validation.json")
        cross_format = _load_object(root / "reports/exports/cross-format-positions.json")
        historical_raw = _load_object(root / HISTORICAL_ORACLE_REPORT_RELATIVE)
        before_after = _load_object(root / "reports/exports/before-after-proofs.json")
        fixture_truth = _load_object(root / "reports/oracle-fixtures/validation.json")
        submission = _load_object(root / "reports/exports/submission-package.json")
        editor_e2e = _load_object(root / "reports/e2e/editor.json")
        figure_e2e = _load_object(root / "reports/e2e/figure-studio.json")
        verification = _load_object(root / "verification.json")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"cannot recompute publication payload bindings: {exc}"]
    expected_publication: dict[str, dict[str, Any]] = {}
    failures.extend(
        editor_e2e_failures(
            editor_e2e,
            normalized_count=verification.get("chrome", {}).get("editor_scenarios"),
        )
    )
    if verification.get("strict_svg_oracle") != strict_validation:
        failures.append("verification strict-SVG evidence differs from its normalized report")
    if verification.get("cross_format_positions") != cross_format:
        failures.append("verification cross-format evidence differs from its normalized report")
    if verification.get("before_after_proofs") != before_after:
        failures.append("verification before/after evidence differs from its normalized report")
    failures.extend(
        _historical_negative_control_failures(
            root,
            historical_raw,
            before_after,
            verification,
        )
    )
    publication_results = publication.get("results", [])
    if publication.get("status") != "PASS" or len(publication_results) != 14:
        failures.append("publication artifact report is not a 14-figure PASS")
    expected_formats = {"svg", "pdf", "tikz", "png", "eps", "pptx", "html"}
    for result in publication_results:
        category = "templates" if result.get("kind") == "template" else "real-models" if result.get("kind") == "real-model" else ""
        key = str(result.get("key", ""))
        if not category or not key or "/" in key or ".." in Path(key).parts:
            failures.append(f"unsafe publication identity in artifact report: {result.get('kind')!r}/{key!r}")
            continue
        for relative, claim in result.get("files", {}).items():
            path = Path(relative)
            if path.is_absolute() or ".." in path.parts:
                failures.append(f"unsafe publication path in artifact report: {relative!r}")
                continue
            name = (Path("exports/publication") / category / key / path).as_posix()
            if name in expected_publication:
                failures.append(f"duplicate publication artifact report path: {name}")
            expected_publication[name] = claim
        result_files = set(result.get("files", {}))
        observed_formats = {
            "svg"
            if name.endswith(".svg")
            else "pdf"
            if name == "figure.pdf"
            else "tikz"
            if name.endswith(".tex")
            else "png"
            if name == "figure.png"
            else "eps"
            if name.endswith(".eps")
            else "pptx"
            if name.endswith(".pptx")
            else "html"
            if name.endswith(".html")
            else ""
            for name in result_files
        }
        if not (
            result.get("status") == "PASS"
            and set(result.get("requested_formats", [])) == expected_formats
            and result.get("release_gate_uses_python_figure_proof") is False
            and result.get("provenance_validation", {}).get("passed") is True
            and expected_formats.issubset(observed_formats)
            and {"figure.tikz.pdf", "figure.proof-300dpi.png", "figure.nndv.json", "provenance.json"}.issubset(result_files)
        ):
            failures.append(f"incomplete per-figure publication record: {result.get('kind')}/{key}")
    actual_publication = {name for name in manifested if name.startswith("exports/publication/")}
    if set(expected_publication) != actual_publication:
        failures.extend(f"publication payload missing from report: {name}" for name in sorted(actual_publication - set(expected_publication)))
        failures.extend(f"publication report file absent from artifact: {name}" for name in sorted(set(expected_publication) - actual_publication))
    for name in sorted(set(expected_publication) & actual_publication):
        claim = expected_publication[name]
        path = root / name
        if claim.get("bytes") != path.stat().st_size or claim.get("sha256") != sha256(path):
            failures.append(f"publication report hash/size mismatch: {name}")
    svg_claims = {f"exports/publication/{item.get('relative_path')}": item for item in publication.get("svg_inputs", [])}
    expected_svg = {name for name in expected_publication if name.endswith(".svg")}
    if set(svg_claims) != expected_svg:
        failures.append("publication SVG-input inventory differs from the exported SVG payload")
    raw_hashes = sorted(str(item.get("sha256")) for item in strict_raw.get("reports", []))
    export_hashes = sorted(str(item.get("sha256")) for item in publication.get("svg_inputs", []))
    if raw_hashes != export_hashes:
        failures.append("strict Chrome report hashes differ from the exported SVG payload")
    if not (
        strict_raw.get("measurement_contract", {}).get("stroke_under_full_ctm") is True
        and strict_raw.get("measurement_contract", {}).get("tolerance", {}).get("minimumStrokePt") == MINIMUM_STROKE_PT
        and len(strict_raw.get("reports", [])) == 14
        and all(
            isinstance(item.get("strokes"), list)
            and item.get("strokes")
            and isinstance(item.get("summary", {}).get("minimum_stroke_pt"), (int, float))
            and isinstance(item.get("summary", {}).get("maximum_stroke_pt"), (int, float))
            for item in strict_raw.get("reports", [])
        )
    ):
        failures.append("raw strict Chrome report lacks the required full-CTM stroke contract")
    if not (
        strict_validation.get("thresholds", {}).get("font_numeric_tolerance_pt") == 0.01
        and strict_validation.get("thresholds", {}).get("minimum_stroke_pt") == MINIMUM_STROKE_PT
        and strict_validation.get("measurement_contract", {}).get("stroke_under_full_ctm") is True
    ):
        failures.append("strict validation report lacks the 0.6.1 font/stroke numeric contract")

    for proof_report, directory_name, inventory_name in (
        (cross_format, "cross-format-proofs", "proof_files"),
        (before_after, "before-after-proofs", "outputs"),
    ):
        prefix = f"exports/{directory_name}/"
        claims: dict[str, dict[str, Any]] = {}
        for claim in proof_report.get(inventory_name, []):
            try:
                relative = safe_relative(str(claim.get("relative_path", ""))).as_posix()
            except ValueError as exc:
                failures.append(f"unsafe {directory_name} report path: {exc}")
                continue
            if relative in claims:
                failures.append(f"duplicate {directory_name} report path: {relative}")
            claims[relative] = claim
        actual = {name[len(prefix) :] for name in manifested if name.startswith(prefix)}
        if set(claims) != actual:
            failures.append(f"{directory_name} report inventory differs from the artifact payload")
        for relative in sorted(set(claims) & actual):
            claim = claims[relative]
            path = root / prefix / relative
            if claim.get("bytes") != path.stat().st_size or claim.get("sha256") != sha256(path):
                failures.append(f"{directory_name} report hash/size mismatch: {relative}")

    cross_outputs = {item.get("relative_path"): item for item in cross_format.get("proof_files", []) if isinstance(item, dict)}
    for case in cross_format.get("cases", []):
        svg_relative = case.get("svg")
        svg_claim = svg_claims.get(f"exports/publication/{svg_relative}", {})
        if case.get("svg_sha256") != svg_claim.get("sha256"):
            failures.append(f"cross-format case is not bound to a fresh SVG: {svg_relative}")
        proofs = case.get("proofs", {})
        for label in ("pdf_300dpi", "tikz_compiled_pdf_300dpi"):
            if proofs.get(label) not in cross_outputs:
                failures.append(f"cross-format case proof is absent from its output inventory: {svg_relative}/{label}")
        expected_svg_proof = str(PurePosixPath(str(svg_relative)).parent / "figure.proof-300dpi.png")
        if proofs.get("svg_300dpi") != expected_svg_proof or f"exports/publication/{expected_svg_proof}" not in expected_publication:
            failures.append(f"cross-format SVG proof is not a fresh publication proof: {svg_relative}")

    before_outputs = {item.get("relative_path"): item for item in before_after.get("outputs", []) if isinstance(item, dict)}
    for case in before_after.get("cases", []):
        template = str(case.get("template", ""))
        before = case.get("before", {})
        after = case.get("after", {})
        before_source = before.get("source", {})
        if not (
            before.get("source_kind") == "persisted-v0.6.0-artifact-svg"
            and before.get("regenerated_from_source") is False
            and before_source.get("relative_path") == f"exports/figure-templates/{template}/figure.svg"
        ):
            failures.append(f"before proof is not bound to the persisted 0.6.0 SVG: {template}")
        for field, relative in (
            ("svg_source", f"templates/{template}/figure.svg"),
            ("proof_source", f"templates/{template}/figure.proof-300dpi.png"),
        ):
            source_claim = after.get(field, {})
            publication_claim = expected_publication.get(f"exports/publication/{relative}", {})
            if not (
                after.get("fresh_export_report_bound") is True
                and source_claim.get("relative_path") == relative
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

    expected_submission = {f"exports/submission-package/{name}" for name in submission.get("files", [])}
    actual_submission = {name for name in manifested if name.startswith("exports/submission-package/")}
    if expected_submission != actual_submission:
        failures.append("submission report inventory differs from the artifact payload")
    fixture_names = {str(item.get("fixture")) for item in fixture_truth.get("cases", [])}
    actual_fixture_names = {Path(name).name for name in manifested if name.startswith("exports/oracle-fixtures/") and name.endswith(".svg")}
    if len(actual_fixture_names) != 21 or actual_fixture_names != fixture_names:
        failures.append("artifact adversarial fixture SVG inventory differs from its 21-case truth report")
    workflows = figure_e2e.get("required_workflows", {})
    if (
        figure_e2e.get("schema_version") != "nndv-0.6.1-figure-studio-e2e-1"
        or set(workflows) != REQUIRED_FIGURE_E2E_WORKFLOWS
        or not all(value is True for value in workflows.values())
    ):
        failures.append("artifact Figure Studio E2E report lacks the required 0.6.1 workflows")
    return failures


def verify(root: Path) -> dict[str, Any]:
    root = root.resolve()
    failures: list[str] = []
    if not root.is_dir() or root.is_symlink():
        return {"status": "FAIL", "failures": [f"artifact root is absent or unsafe: {root}"]}
    files, unsafe = inventory(root)
    failures.extend(f"forbidden object: {item}" for item in unsafe)

    try:
        manifest = _load_object(root / "MANIFEST.json")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"status": "FAIL", "failures": failures + [f"invalid MANIFEST.json: {exc}"]}
    if manifest.get("schema_version") != "nndv-0.6.1-artifact-manifest-1":
        failures.append("unexpected artifact manifest schema")
    if manifest.get("release") != RELEASE:
        failures.append("unexpected artifact release identity")
    entries = manifest.get("entries")
    if not isinstance(entries, dict):
        return {"status": "FAIL", "failures": failures + ["manifest entries must be an object"]}

    expected: dict[str, dict[str, Any]] = {}
    for name, item in entries.items():
        try:
            relative = safe_relative(name)
        except ValueError as exc:
            failures.append(str(exc))
            continue
        normalized = relative.as_posix()
        if normalized in CONTROL_FILES or normalized in expected:
            failures.append(f"duplicate or reserved manifest path: {normalized}")
            continue
        if not isinstance(item, dict):
            failures.append(f"manifest entry is not an object: {normalized}")
            continue
        expected[normalized] = item
    actual_payload = set(files) - CONTROL_FILES
    missing = sorted(set(expected) - actual_payload)
    extra = sorted(actual_payload - set(expected))
    failures.extend(f"missing artifact file: {name}" for name in missing)
    failures.extend(f"extra artifact file: {name}" for name in extra)
    checked = 0
    for name in sorted(set(expected) & actual_payload):
        item = expected[name]
        path = files[name]
        observed_mode = f"{stat.S_IMODE(os.lstat(path).st_mode):04o}"
        if item.get("bytes") != path.stat().st_size:
            failures.append(f"size mismatch: {name}")
        if item.get("sha256") != sha256(path):
            failures.append(f"hash mismatch: {name}")
        if item.get("mode") != observed_mode:
            failures.append(f"mode mismatch: {name}")
        checked += 1

    checksum_path = root / "SHA256SUMS"
    checksums: dict[str, str] = {}
    try:
        for line_number, raw in enumerate(checksum_path.read_text(encoding="utf-8").splitlines(), 1):
            digest, separator, name = raw.partition("  ")
            if not separator or not HEX64.fullmatch(digest):
                failures.append(f"malformed SHA256SUMS line {line_number}")
                continue
            try:
                normalized = safe_relative(name).as_posix()
            except ValueError as exc:
                failures.append(f"SHA256SUMS line {line_number}: {exc}")
                continue
            if normalized in checksums:
                failures.append(f"duplicate SHA256SUMS path: {normalized}")
            checksums[normalized] = digest
    except OSError as exc:
        failures.append(f"cannot read SHA256SUMS: {exc}")
    expected_checksum_paths = set(expected) | {"MANIFEST.json"}
    if set(checksums) != expected_checksum_paths:
        failures.extend(f"SHA256SUMS missing path: {name}" for name in sorted(expected_checksum_paths - set(checksums)))
        failures.extend(f"SHA256SUMS extra path: {name}" for name in sorted(set(checksums) - expected_checksum_paths))
    for name in sorted(set(checksums) & set(files)):
        if checksums[name] != sha256(files[name]):
            failures.append(f"SHA256SUMS hash mismatch: {name}")

    source_prefix = "source/replay-source/"
    source_entries = {name[len(source_prefix) :]: item for name, item in expected.items() if name.startswith(source_prefix)}
    source_digest = hashlib.sha256(
        "".join(f"{name}\0{item.get('sha256')}\0{item.get('bytes')}\n" for name, item in sorted(source_entries.items())).encode()
    ).hexdigest()
    for name in source_entries:
        parts = PurePosixPath(name).parts
        if FORBIDDEN_SOURCE_PARTS.intersection(parts) or any(part.endswith(".egg-info") for part in parts):
            failures.append(f"forbidden source path entered artifact: {name}")
    source_claim = manifest.get("source", {})
    if source_claim.get("file_count") != len(source_entries):
        failures.append("source file count differs from artifact manifest claim")
    if source_claim.get("digest") != source_digest:
        failures.append("source digest differs from artifact manifest claim")
    if source_claim.get("allowlist") != "verification/source-allowlist-0.6.1.json":
        failures.append("artifact source was not selected by the 0.6.1 allowlist")

    try:
        verification = _load_object(root / "verification.json")
        failures.extend(_verification_failures(verification, manifest, source_digest, set(expected)))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        failures.append(f"invalid verification.json: {exc}")
    failures.extend(_payload_report_failures(root, set(expected)))

    return {
        "schema_version": "nndv-0.6.1-artifact-verification-1",
        "status": "PASS" if not failures else "FAIL",
        "artifact": str(root),
        "run_id": manifest.get("run_id"),
        "manifest_entries": len(expected),
        "files_checked": checked,
        "source_file_count": len(source_entries),
        "source_digest": source_digest,
        "sha256sums_sha256": sha256(checksum_path) if checksum_path.is_file() else None,
        "manifest_sha256": sha256(root / "MANIFEST.json"),
        "unsafe_objects": unsafe,
        "missing": missing,
        "extra": extra,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = verify(args.artifact)
    if args.output:
        output = args.output.resolve()
        artifact = args.artifact.resolve()
        try:
            output.relative_to(artifact)
        except ValueError:
            pass
        else:
            raise SystemExit("read-only verification report must be written outside the artifact")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "NNDV_061_ARTIFACT_VERIFY="
        + json.dumps(
            {
                "status": report["status"],
                "manifest_entries": report.get("manifest_entries", 0),
                "source_file_count": report.get("source_file_count", 0),
                "failures": len(report.get("failures", [])),
            },
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
