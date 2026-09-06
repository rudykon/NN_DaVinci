from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any
import unittest

from scripts.verify_release_artifact_0_6_1 import verify


ROOT = Path(__file__).parents[1]
RELEASE = "0.6.1 Beta — Publication Fidelity & Model-to-Figure Completion"
BASELINE_SHA256 = "4a4604f0b9a240ebba1b0eef1274edc1e2232930225056069884a2e5f3d5ef53"
TEMPLATE_KEYS = (
    "cnn-feature-pipeline",
    "diffusion-unet-conditioning",
    "moe-router-experts",
    "multimodal-fusion",
    "resnet-overview",
    "transformer-attention-ffn",
    "unet-encoder-decoder",
)
AUTHORITATIVE_SVG_CLAIMS = {
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
HISTORICAL_ORACLE_RELATIVE = "reports/exports/authoritative-0.6.0-figure-svg-oracle.json"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def file_claim(path: Path) -> dict[str, object]:
    return {
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def reseal_artifact(root: Path) -> None:
    """Rebuild both integrity controls so semantic verifier tests are meaningful."""

    manifest_path = root / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file() and not item.is_symlink()):
        relative = path.relative_to(root).as_posix()
        if relative in {"MANIFEST.json", "SHA256SUMS"}:
            continue
        entries[relative] = {
            **file_claim(path),
            "mode": f"{path.stat().st_mode & 0o7777:04o}",
        }
    manifest["entries"] = entries
    write_json(manifest_path, manifest)
    checksum_names = [*sorted(entries), "MANIFEST.json"]
    (root / "SHA256SUMS").write_text(
        "".join(f"{hashlib.sha256((root / name).read_bytes()).hexdigest()}  {name}\n" for name in checksum_names),
        encoding="utf-8",
    )


class ReleaseArtifact061Tests(unittest.TestCase):
    def reports_and_payloads(self, root: Path) -> None:
        quick = {
            "schema_version": "nndv-0.6.1-quick-verification-1",
            "release": RELEASE,
            "status": "PASS",
            "python": {
                "collected": 199,
                "passed": 199,
                "failed": 0,
                "errors": 0,
                "skipped": 0,
                "deselected": 0,
                "inherited_0_6_0_tests": 171,
                "new_0_6_1_tests": 28,
                "baseline_0_6_0_missing": [],
            },
            "coverage": {
                "old_core": {},
                "expanded_core": {},
                "figure_core": {},
                "all_package": {},
                "gates": {
                    "old_core_passed": True,
                    "expanded_core_passed": True,
                    "all_package_passed": True,
                },
            },
        }
        editor_scenarios = [
            {
                "id": f"editor-scenario-{index}",
                "status": "passed",
                "behaviors": [f"behavior-{index}"],
                "assertions": 1,
                "duration_ms": 1,
                "console_errors": [],
            }
            for index in range(11)
        ]
        editor = {
            "schema_version": "1.0",
            "scenarios": editor_scenarios,
            "counts": {
                "e2e_scenarios": 11,
                "passed": 11,
                "failed": 0,
                "skipped": 0,
                "assertions": 11,
            },
        }
        responsive = {"status": "passed", "viewport_count": 7, "assertion_count": 14}
        semantic = {"status": "passed", "assertion_count": 27}
        product = {"status": "passed", "assertion_count": 31}
        trial = {
            "status": "passed",
            "assertion_count": 65,
            "human_participants": 0,
            "human_usability_claim": False,
        }
        figure = {
            "schema_version": "nndv-0.6.1-figure-studio-e2e-1",
            "status": "PASS",
            "tested_viewports": [1440, 800, 390],
            "median_interaction_ms": 16,
            "counts": {
                "passed": 1,
                "failed": 0,
                "assertions": 80,
                "console_page_request_errors": 0,
            },
            "required_workflows": {
                "real_model_semantic_mixed_figure": True,
                "structure_lens_explicit_panel": True,
                "tensor_shape_style_edit": True,
                "long_label_final_svg_bbox": True,
                "second_page": True,
                "six_panels": True,
                "rebuild_undo_restores_evidence": True,
                "save_refresh_restore": True,
                "tampered_project_rejected": True,
                "svg_metadata_roundtrip": True,
                "seven_format_exports": True,
                "submission_package": True,
                "responsive_1440_800_390": True,
                "zero_browser_errors": True,
            },
        }

        publication_root = root / "exports" / "publication"
        results: list[dict[str, Any]] = []
        svg_inputs: list[dict[str, Any]] = []
        for index in range(14):
            kind = "template" if index < 7 else "real-model"
            key = TEMPLATE_KEYS[index] if kind == "template" else f"model-{index - 7}"
            category = "templates" if kind == "template" else "real-models"
            destination = publication_root / category / key
            destination.mkdir(parents=True)
            names = (
                "figure.svg",
                "figure.pdf",
                "figure.tex",
                "figure.png",
                "figure.eps",
                "figure.pptx",
                "figure.html",
                "figure.tikz.pdf",
                "figure.proof-300dpi.png",
                "figure.nndv.json",
                "provenance.json",
            )
            claims = {}
            for name in names:
                path = destination / name
                path.write_bytes(f"fixture {kind} {key} {name}\n".encode())
                claims[name] = file_claim(path)
            relative_svg = f"{category}/{key}/figure.svg"
            svg_inputs.append({"relative_path": relative_svg, **claims["figure.svg"]})
            results.append(
                {
                    "kind": kind,
                    "key": key,
                    "status": "PASS",
                    "requested_formats": ["svg", "pdf", "tikz", "png", "eps", "pptx", "html"],
                    "release_gate_uses_python_figure_proof": False,
                    "provenance_validation": {"passed": True},
                    "files": claims,
                    "failures": [],
                }
            )
        counts = {
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
        publication = {
            "schema_version": "nndv-0.6.1-publication-artifact-corpus-1",
            "release": RELEASE,
            "status": "PASS",
            "fresh_outputs": True,
            "python_figure_proof_is_release_blocker": False,
            "output_root": str(publication_root),
            "counts": counts,
            "svg_inputs": svg_inputs,
            "results": results,
            "failures": [],
        }
        strict_reports: list[dict[str, Any]] = [
            {
                "file": str(publication_root / item["relative_path"]),
                "sha256": item["sha256"],
                "passed": True,
                "issues": [],
                "issue_counts": {},
                "browser_errors": [],
                "summary": {
                    "minimum_font_pt": 6.999744,
                    "minimum_stroke_pt": 0.349987,
                    "maximum_stroke_pt": 0.8,
                    "issue_count": 0,
                },
                "strokes": [{"effective_stroke_pt": 0.349987}],
            }
            for item in svg_inputs
        ]
        strict_raw = {
            "schema_version": "nndv-figure-svg-oracle-report-1",
            "oracle": "figure-final-svg-chrome-v1",
            "passed": True,
            "measurement_contract": {
                "final_dom_only": True,
                "metadata_trusted": False,
                "python_proof_imported": False,
                "stroke_under_full_ctm": True,
                "tolerance": {"minimumFontPt": 7.0, "minimumStrokePt": 0.1},
            },
            "summary": {"files": 14, "passed": 14, "failed": 0, "issues": 0},
            "reports": strict_reports,
        }
        strict = {
            "schema_version": "nndv-0.6.1-strict-publication-svg-validation-1",
            "release": RELEASE,
            "status": "PASS",
            "final_svg_files": 14,
            "passed_svg_files": 14,
            "fresh_export_hashes_matched": True,
            "python_figure_proof_imported": False,
            "measurement_contract": {"stroke_under_full_ctm": True},
            "thresholds": {
                "minimum_font_pt": 7.0,
                "font_numeric_tolerance_pt": 0.01,
                "minimum_stroke_pt": 0.1,
            },
            "metrics": {
                "minimum_font_pt": 6.999744,
                "minimum_stroke_pt": 0.349987,
                "maximum_stroke_pt": 0.8,
                "geometry_issues": 0,
                "browser_errors": 0,
            },
            "cases": [
                {
                    "file": item["file"],
                    "sha256": item["sha256"],
                    "passed": True,
                    "stroke_count": 1,
                    "minimum_stroke_pt": 0.349987,
                    "maximum_stroke_pt": 0.8,
                }
                for item in strict_reports
            ],
            "failures": [],
        }

        cross_root = root / "exports" / "cross-format-proofs"
        cross_proofs = []
        cross_cases = []
        for result in results:
            category = "templates" if result["kind"] == "template" else "real-models"
            relative_directory = Path(category) / result["key"]
            for name in ("pdf-300dpi.png", "tikz-compiled-pdf-300dpi.png"):
                path = cross_root / relative_directory / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(f"cross-format proof {relative_directory}/{name}\n".encode())
                cross_proofs.append({"relative_path": path.relative_to(cross_root).as_posix(), **file_claim(path)})
            cross_cases.append(
                {
                    "svg": (relative_directory / "figure.svg").as_posix(),
                    "svg_sha256": result["files"]["figure.svg"]["sha256"],
                    "passed": True,
                    "key_count": 3,
                    "text_key_count": 1,
                    "shape_key_count": 2,
                    "keys": [
                        {"kind": "text", "text": "fixture", "errors_mm": {"pdf": 0.25, "tikz_pdf": 0.3}},
                        {
                            "kind": "high-contrast-rect-border",
                            "id": "fixture-rect-1",
                            "errors_mm": {"pdf": 0.4, "tikz_pdf": 0.5},
                        },
                        {
                            "kind": "high-contrast-rect-border",
                            "id": "fixture-rect-2",
                            "errors_mm": {"pdf": 0.5, "tikz_pdf": 0.75},
                        },
                    ],
                    "maximum_key_position_error_by_format_mm": {"pdf": 0.5, "tikz_pdf": 0.75},
                    "proofs": {
                        "svg_300dpi": (relative_directory / "figure.proof-300dpi.png").as_posix(),
                        "pdf_300dpi": (relative_directory / "pdf-300dpi.png").as_posix(),
                        "tikz_compiled_pdf_300dpi": (relative_directory / "tikz-compiled-pdf-300dpi.png").as_posix(),
                    },
                    "failures": [],
                }
            )
        cross_format = {
            "schema_version": "nndv-0.6.1-cross-format-position-validation-1",
            "release": RELEASE,
            "status": "PASS",
            "measurement_sources": {"figure_ir_or_python_proof_used": False},
            "thresholds_mm": {"maximum_key_position_error": 1.0, "maximum_page_size_error": 0.05},
            "figures": 14,
            "passed_figures": 14,
            "key_positions_compared": 84,
            "maximum_key_position_error_mm": 0.75,
            "maximum_key_position_error_by_format_mm": {"pdf": 0.5, "tikz_pdf": 0.75},
            "maximum_page_size_error_mm": 0.01,
            "cases": cross_cases,
            "proof_root": str(cross_root),
            "proof_files": cross_proofs,
            "failures": [],
        }

        historical_raw_cases = []
        for key in TEMPLATE_KEYS:
            source_path = f"/fixture/20260829T183558Z-09a7930b/exports/figure-templates/{key}/figure.svg"
            historical_raw_cases.append(
                {
                    "file": source_path,
                    "sha256": AUTHORITATIVE_SVG_CLAIMS[key]["sha256"],
                    "passed": False,
                    "summary": {"issue_count": 1},
                    "issue_counts": {"fixture_historical_defect": 1},
                    "issues": [{"code": "fixture_historical_defect"}],
                    "browser_errors": [],
                    "source": {
                        "loaded_from_persisted_file": True,
                        "url": f"file://{source_path}",
                        "metadata_consulted": False,
                    },
                }
            )
        historical_raw = {
            "schema_version": "nndv-figure-svg-oracle-report-1",
            "oracle": "figure-final-svg-chrome-v1",
            "passed": False,
            "measurement_contract": {
                "final_dom_only": True,
                "metadata_trusted": False,
                "python_proof_imported": False,
                "data_scale_claims_trusted": False,
                "stroke_under_full_ctm": True,
            },
            "summary": {"files": 7, "passed": 0, "failed": 7, "issues": 7},
            "reports": historical_raw_cases,
        }
        historical_raw_path = root / HISTORICAL_ORACLE_RELATIVE
        write_json(historical_raw_path, historical_raw)
        strict_negative_control = {
            "schema_version": "nndv-0.6.1-authoritative-0.6.0-strict-negative-control-1",
            "status": "PASS",
            "interpretation": ("the negative-control validation passed because all seven historical SVGs failed the strict oracle"),
            "expected_failure_observed": True,
            "historical_svg_quality_passed": False,
            "oracle_passed": False,
            "authoritative_run_id": "20260829T183558Z-09a7930b",
            "authoritative_manifest_sha256": ("797d5b38403154b1317d00e8a9e03c48373a2c046e10e4a43229f828769e3cc4"),
            "manifest_hashes_matched": True,
            "expected_templates": list(TEMPLATE_KEYS),
            "measurement_contract": {
                "final_dom_only": True,
                "metadata_trusted": False,
                "python_proof_imported": False,
                "data_scale_claims_trusted": False,
                "stroke_under_full_ctm": True,
            },
            "summary": {"files": 7, "passed": 0, "failed": 7, "issues": 7},
            "raw_report": {
                "relative_path": HISTORICAL_ORACLE_RELATIVE,
                **file_claim(historical_raw_path),
            },
            "cases": [
                {
                    "template": key,
                    "manifest_path": f"exports/figure-templates/{key}/figure.svg",
                    "manifest_bytes": AUTHORITATIVE_SVG_CLAIMS[key]["bytes"],
                    "manifest_sha256": AUTHORITATIVE_SVG_CLAIMS[key]["sha256"],
                    "oracle_sha256": AUTHORITATIVE_SVG_CLAIMS[key]["sha256"],
                    "oracle_passed": False,
                    "issue_count": 1,
                    "issue_counts": {"fixture_historical_defect": 1},
                    "browser_errors": 0,
                    "loaded_from_persisted_file": True,
                    "metadata_consulted": False,
                }
                for key in TEMPLATE_KEYS
            ],
            "failures": [],
        }

        before_root = root / "exports" / "before-after-proofs"
        before_proofs: list[dict[str, Any]] = []
        before_cases: list[dict[str, Any]] = []
        template_results = {item["key"]: item for item in results if item["kind"] == "template"}
        for key in TEMPLATE_KEYS:
            for category in ("before", "after", "comparison"):
                path = before_root / category / f"{key}.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(f"{category} proof {key}\n".encode())
                before_proofs.append({"relative_path": path.relative_to(before_root).as_posix(), **file_claim(path)})
            result = template_results[key]
            before_cases.append(
                {
                    "template": key,
                    "passed": True,
                    "before": {
                        "source": {
                            "relative_path": f"exports/figure-templates/{key}/figure.svg",
                            **AUTHORITATIVE_SVG_CLAIMS[key],
                        },
                        "source_kind": "persisted-v0.6.0-artifact-svg",
                        "regenerated_from_source": False,
                        "proof": next(item for item in before_proofs if item["relative_path"] == f"before/{key}.png"),
                    },
                    "after": {
                        "svg_source": {
                            "relative_path": f"templates/{key}/figure.svg",
                            **result["files"]["figure.svg"],
                        },
                        "proof_source": {
                            "relative_path": f"templates/{key}/figure.proof-300dpi.png",
                            **result["files"]["figure.proof-300dpi.png"],
                        },
                        "fresh_export_report_bound": True,
                        "proof": next(item for item in before_proofs if item["relative_path"] == f"after/{key}.png"),
                    },
                    "comparison": next(item for item in before_proofs if item["relative_path"] == f"comparison/{key}.png"),
                }
            )
        integrity_path = before_root / "integrity-manifest.json"
        write_json(integrity_path, {"schema_version": "nndv-0.6.1-before-after-proof-integrity-1"})
        before_outputs = [*before_proofs, {"relative_path": "integrity-manifest.json", **file_claim(integrity_path)}]
        before_after = {
            "schema_version": "nndv-0.6.1-before-after-proof-1",
            "release": RELEASE,
            "status": "PASS",
            "before_release": "0.6.0",
            "after_release": "0.6.1",
            "authoritative_before_run_id": "20260829T183558Z-09a7930b",
            "authoritative_before_manifest_sha256": ("797d5b38403154b1317d00e8a9e03c48373a2c046e10e4a43229f828769e3cc4"),
            "before_inputs_are_diagnostic_only": True,
            "after_fresh_outputs": True,
            "diagnostic_only": True,
            "release_quality_gate_input": False,
            "before_evidence_policy": {"regenerated": False, "uses_0_6_1_as_before": False},
            "before_artifact": {
                "run_id": "20260829T183558Z-09a7930b",
                "manifest": {"relative_path": "MANIFEST.json", "sha256": "797d5b38403154b1317d00e8a9e03c48373a2c046e10e4a43229f828769e3cc4"},
                "read_only_verification": {"status": "PASS", "run_id": "20260829T183558Z-09a7930b"},
            },
            "strict_negative_control": strict_negative_control,
            "templates": 7,
            "passed_templates": 7,
            "counts": {"templates": 7, "output_files": 22},
            "cases": before_cases,
            "output_root": str(before_root),
            "after_export_report": "/fixture/publication-artifacts.json",
            "proof_files": before_proofs,
            "outputs": before_outputs,
            "integrity_manifest": {"relative_path": "integrity-manifest.json", **file_claim(integrity_path)},
            "failures": [],
        }

        fixture_names = list(json.loads((ROOT / "verification/fixtures/figure-svg-oracle-expectations.json").read_text())["fixtures"])
        fixture_root = root / "exports" / "oracle-fixtures"
        fixture_root.mkdir(parents=True)
        for name in fixture_names:
            (fixture_root / name).write_text(f"<svg><title>{name}</title></svg>\n", encoding="utf-8")
        fixture_raw = {
            "schema_version": "nndv-figure-svg-oracle-report-1",
            "summary": {"files": 21, "passed": 2, "failed": 19},
            "reports": [{"file": str(fixture_root / name)} for name in fixture_names],
            "passed": False,
        }
        fixture_truth = {
            "passed": True,
            "fixture_count": 21,
            "classification_count": 21,
            "positive_count": 2,
            "negative_count": 19,
            "cases": [{"fixture": name, "passed": True} for name in fixture_names],
            "failures": [],
        }

        submission_names = {
            "figure.svg",
            "figure.pdf",
            "figure.tex",
            "figure.png",
            "figure.eps",
            "figure.pptx",
            "figure.html",
            "figure.nndv.json",
            "caption.md",
            "provenance.json",
            "proof.json",
            "export-policy.json",
        }
        submission_root = root / "exports" / "submission-package"
        submission_root.mkdir(parents=True)
        for name in submission_names:
            (submission_root / name).write_text(f"submission fixture {name}\n", encoding="utf-8")
        submission = {
            "status": "PASS",
            "formats": 7,
            "support_files": 5,
            "files": sorted(submission_names),
            "failures": [],
        }
        performance = {
            "schema_version": "nndv-0.6.1-figure-studio-performance-1",
            "release": RELEASE,
            "status": "PASS",
            "figure_objects": 1_000,
        }
        packaging = {"passed": True, "checks": 14, "wheel": {}, "sdist": {}}
        audit = {"schema_version": "nndv-0.6.1-release-audit-1", "release": RELEASE, "status": "PASS"}
        commands = {"schema_version": "nndv-0.6.1-full-command-report-1", "commands": [], "failed": 0}
        values = {
            "reports/quick/quick-verification.json": quick,
            "reports/e2e/editor.json": editor,
            "reports/e2e/responsive.json": responsive,
            "reports/e2e/semantic.json": semantic,
            "reports/e2e/product.json": product,
            "reports/e2e/trial.json": trial,
            "reports/e2e/figure-studio.json": figure,
            "reports/exports/publication-artifacts.json": publication,
            "reports/exports/figure-svg-oracle.json": strict_raw,
            "reports/exports/strict-svg-validation.json": strict,
            "reports/exports/cross-format-positions.json": cross_format,
            HISTORICAL_ORACLE_RELATIVE: historical_raw,
            "reports/exports/before-after-proofs.json": before_after,
            "reports/oracle-fixtures/figure-svg-oracle.json": fixture_raw,
            "reports/oracle-fixtures/validation.json": fixture_truth,
            "reports/exports/submission-package.json": submission,
            "reports/performance/figure-studio.json": performance,
            "reports/packaging/package-install.json": packaging,
            "reports/docs/release-audit.json": audit,
            "reports/full/commands.json": commands,
        }
        for relative, value in values.items():
            write_json(root / relative, value)

    def source_fixture(self, temporary: Path) -> tuple[Path, Path]:
        source = temporary / "source"
        source.mkdir()
        source_file = source / "README.md"
        source_file.write_text("0.6.1 release fixture\n", encoding="utf-8")
        digest = hashlib.sha256(source_file.read_bytes()).hexdigest()
        source_tree_digest = hashlib.sha256(f"README.md\0{digest}\0{source_file.stat().st_size}\n".encode()).hexdigest()
        report = temporary / "source.json"
        write_json(
            report,
            {
                "schema_version": "nndv-clean-source-snapshot-2",
                "release": "0.6.1",
                "passed": True,
                "file_count": 1,
                "source_tree_digest": source_tree_digest,
                "allowlist": "verification/source-allowlist-0.6.1.json",
                "allowlist_sha256": "a" * 64,
                "source": str(source),
                "snapshot": str(source),
                "forbidden_paths": [],
                "files": {"README.md": {**file_claim(source_file), "mode": f"{source_file.stat().st_mode & 0o7777:04o}"}},
            },
        )
        return source, report

    def finalize(self, temporary: Path, staging: Path, source: Path, source_report: Path, run_id: str) -> subprocess.CompletedProcess[str]:
        artifact_root = temporary / "artifacts"
        command = [
            sys.executable,
            str(ROOT / "scripts/finalize_artifact_0_6_1.py"),
            "--staging",
            str(staging),
            "--source-root",
            str(source),
            "--source-report",
            str(source_report),
            "--artifact-root",
            str(artifact_root),
            "--run-id",
            run_id,
            "--started-utc",
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "--started-epoch",
            str(time.time()),
        ]
        environment = {**os.environ, "PYTHONPATH": f"{ROOT}:{ROOT / 'src'}"}
        return subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, check=False)

    def test_finalizer_binds_fresh_payload_and_verifier_rejects_tampering(self) -> None:
        with tempfile.TemporaryDirectory(prefix="nndv-061-artifact-test-") as directory:
            temporary = Path(directory)
            staging = temporary / "staging"
            staging.mkdir()
            self.reports_and_payloads(staging)
            source, source_report = self.source_fixture(temporary)
            run_id = "20260830T000000Z-fixture"
            completed = self.finalize(temporary, staging, source, source_report, run_id)
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            artifact = temporary / "artifacts" / run_id
            report = verify(artifact)
            self.assertEqual("PASS", report["status"], report["failures"])
            verification = json.loads((artifact / "verification.json").read_text())
            self.assertEqual(0, verification["human_evidence"]["participants"])
            self.assertTrue(all(value is None for value in verification["human_evidence"]["human_metrics"].values()))
            self.assertFalse(verification["strict_svg_oracle"]["python_figure_proof_imported"])
            self.assertEqual(
                {"files": 7, "passed": 0, "failed": 7, "issues": 7},
                verification["strict_negative_control"]["summary"],
            )
            self.assertTrue(verification["strict_negative_control"]["expected_failure_observed"])
            self.assertTrue((artifact / HISTORICAL_ORACLE_RELATIVE).is_file())

            editor_path = artifact / "reports/e2e/editor.json"
            verification_path = artifact / "verification.json"
            editor_original = json.loads(editor_path.read_text())
            verification_original = json.loads(verification_path.read_text())
            editor_downgraded = dict(editor_original)
            editor_downgraded["scenarios"] = editor_original["scenarios"][:1]
            editor_downgraded["counts"] = {
                "e2e_scenarios": 1,
                "passed": 1,
                "failed": 0,
                "skipped": 0,
                "assertions": 1,
            }
            verification_downgraded = json.loads(json.dumps(verification_original))
            verification_downgraded["chrome"]["editor_scenarios"] = 1
            write_json(editor_path, editor_downgraded)
            write_json(verification_path, verification_downgraded)
            reseal_artifact(artifact)
            editor_tampered = verify(artifact)
            self.assertEqual("FAIL", editor_tampered["status"])
            self.assertTrue(
                any("editor" in failure.lower() for failure in editor_tampered["failures"]),
                editor_tampered["failures"],
            )
            write_json(editor_path, editor_original)
            write_json(verification_path, verification_original)
            reseal_artifact(artifact)
            self.assertEqual("PASS", verify(artifact)["status"])

            for malformed_name, malformed_counts in (
                (
                    "boolean-zeroes",
                    {**editor_original["counts"], "failed": False, "skipped": False},
                ),
                (
                    "floating-counts",
                    {
                        name: float(value)
                        for name, value in editor_original["counts"].items()
                    },
                ),
            ):
                with self.subTest(editor_count_types=malformed_name):
                    malformed_editor = dict(editor_original)
                    malformed_editor["counts"] = malformed_counts
                    write_json(editor_path, malformed_editor)
                    write_json(verification_path, verification_original)
                    reseal_artifact(artifact)
                    malformed_report = verify(artifact)
                    self.assertEqual("FAIL", malformed_report["status"])
                    self.assertTrue(
                        any("editor" in failure.lower() for failure in malformed_report["failures"]),
                        malformed_report["failures"],
                    )
            write_json(editor_path, editor_original)
            write_json(verification_path, verification_original)
            reseal_artifact(artifact)
            self.assertEqual("PASS", verify(artifact)["status"])

            cross_target = artifact / "exports/cross-format-proofs/templates/cnn-feature-pipeline/pdf-300dpi.png"
            cross_original = cross_target.read_bytes()
            cross_target.write_bytes(b"tampered cross-format proof\n")
            cross_tampered = verify(artifact)
            self.assertEqual("FAIL", cross_tampered["status"])
            self.assertTrue(any("cross-format" in failure for failure in cross_tampered["failures"]))
            cross_target.write_bytes(cross_original)
            self.assertEqual("PASS", verify(artifact)["status"])

            before_target = artifact / "exports/before-after-proofs/before/cnn-feature-pipeline.png"
            before_original = before_target.read_bytes()
            before_target.write_bytes(b"tampered before proof\n")
            before_tampered = verify(artifact)
            self.assertEqual("FAIL", before_tampered["status"])
            self.assertTrue(any("before-after" in failure for failure in before_tampered["failures"]))
            before_target.write_bytes(before_original)
            self.assertEqual("PASS", verify(artifact)["status"])

            target = artifact / f"exports/publication/templates/{TEMPLATE_KEYS[0]}/figure.svg"
            target.write_text("tampered\n", encoding="utf-8")
            tampered = verify(artifact)
            self.assertEqual("FAIL", tampered["status"])
            self.assertTrue(any("mismatch" in failure for failure in tampered["failures"]))

    def test_verifier_rejects_resealed_historical_negative_control_tampering(self) -> None:
        scenarios = (
            "stale-artifact-shape",
            "raw-contract",
            "raw-path",
            "raw-issue-counts",
            "fixed-manifest-claim",
            "unbound-raw-report",
            "verification-copy",
            "report-map",
        )
        for index, scenario in enumerate(scenarios):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory(prefix=f"nndv-061-resealed-negative-{scenario}-") as directory:
                temporary = Path(directory)
                staging = temporary / "staging"
                staging.mkdir()
                self.reports_and_payloads(staging)
                source, source_report = self.source_fixture(temporary)
                run_id = f"20260830T0001{index:02d}Z-resealed-negative"
                completed = self.finalize(temporary, staging, source, source_report, run_id)
                self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
                artifact = temporary / "artifacts" / run_id

                raw_path = artifact / HISTORICAL_ORACLE_RELATIVE
                before_after_path = artifact / "reports/exports/before-after-proofs.json"
                verification_path = artifact / "verification.json"
                raw = json.loads(raw_path.read_text(encoding="utf-8"))
                before_after = json.loads(before_after_path.read_text(encoding="utf-8"))
                verification = json.loads(verification_path.read_text(encoding="utf-8"))
                control = before_after["strict_negative_control"]

                raw_changed = False
                bind_changed_raw = False
                if scenario == "stale-artifact-shape":
                    raw_path.unlink()
                    before_after.pop("strict_negative_control")
                    verification.pop("strict_negative_control")
                    verification["reports"].pop("historical_0_6_0_oracle_raw")
                elif scenario == "raw-contract":
                    raw["measurement_contract"]["metadata_trusted"] = True
                    raw_changed = True
                    bind_changed_raw = True
                elif scenario == "raw-path":
                    raw_case = raw["reports"][0]
                    raw_case["file"] = raw_case["file"].replace(
                        "20260829T183558Z-09a7930b",
                        "20260829T183558Z-wrong-run",
                    )
                    raw_case["source"]["url"] = Path(raw_case["file"]).as_uri()
                    raw_changed = True
                    bind_changed_raw = True
                elif scenario == "raw-issue-counts":
                    raw["reports"][0]["issue_counts"]["fixture_historical_defect"] = 2
                    control["cases"][0]["issue_counts"]["fixture_historical_defect"] = 2
                    raw_changed = True
                    bind_changed_raw = True
                elif scenario == "fixed-manifest-claim":
                    control["cases"][0]["manifest_bytes"] += 1
                elif scenario == "unbound-raw-report":
                    raw["coherently_resealed_but_unbound"] = True
                    raw_changed = True
                elif scenario == "verification-copy":
                    mismatched = json.loads(json.dumps(control))
                    mismatched["summary"]["issues"] += 1
                    verification["strict_negative_control"] = mismatched
                elif scenario == "report-map":
                    verification["reports"]["historical_0_6_0_oracle_raw"] = "reports/exports/figure-svg-oracle.json"

                if raw_changed:
                    write_json(raw_path, raw)
                if bind_changed_raw:
                    control["raw_report"] = {
                        "relative_path": HISTORICAL_ORACLE_RELATIVE,
                        **file_claim(raw_path),
                    }
                if scenario not in {"stale-artifact-shape", "verification-copy"}:
                    before_after["strict_negative_control"] = control
                    verification["strict_negative_control"] = control
                verification["before_after_proofs"] = before_after
                write_json(before_after_path, before_after)
                write_json(verification_path, verification)
                reseal_artifact(artifact)

                report = verify(artifact)
                self.assertEqual("FAIL", report["status"], scenario)
                self.assertTrue(
                    any(
                        "historical strict" in failure or "strict negative-control" in failure or "historical strict-oracle" in failure
                        for failure in report["failures"]
                    ),
                    report["failures"],
                )

    def test_finalizer_aborts_before_artifact_when_strict_oracle_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="nndv-061-artifact-reject-") as directory:
            temporary = Path(directory)
            staging = temporary / "staging"
            staging.mkdir()
            self.reports_and_payloads(staging)
            strict_path = staging / "reports/exports/strict-svg-validation.json"
            strict = json.loads(strict_path.read_text())
            strict["status"] = "FAIL"
            strict["metrics"]["geometry_issues"] = 1
            write_json(strict_path, strict)
            source, source_report = self.source_fixture(temporary)
            run_id = "20260830T000001Z-reject"
            completed = self.finalize(temporary, staging, source, source_report, run_id)
            self.assertNotEqual(0, completed.returncode)
            self.assertIn("strict", completed.stderr.lower())
            self.assertFalse((temporary / "artifacts" / run_id).exists())

    def test_finalizer_requires_explicit_complete_editor_scenario_accounting(self) -> None:
        for index, mutation in enumerate(
            ("missing-count", "downgraded", "boolean-zeroes", "floating-counts")
        ):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(
                prefix=f"nndv-061-editor-{mutation}-"
            ) as directory:
                temporary = Path(directory)
                staging = temporary / "staging"
                staging.mkdir()
                self.reports_and_payloads(staging)
                editor_path = staging / "reports/e2e/editor.json"
                editor = json.loads(editor_path.read_text())
                if mutation == "missing-count":
                    del editor["counts"]["e2e_scenarios"]
                elif mutation == "downgraded":
                    editor["scenarios"] = editor["scenarios"][:1]
                    editor["counts"] = {
                        "e2e_scenarios": 1,
                        "passed": 1,
                        "failed": 0,
                        "skipped": 0,
                        "assertions": 1,
                    }
                elif mutation == "boolean-zeroes":
                    editor["counts"]["failed"] = False
                    editor["counts"]["skipped"] = False
                else:
                    editor["counts"] = {
                        name: float(value) for name, value in editor["counts"].items()
                    }
                write_json(editor_path, editor)
                source, source_report = self.source_fixture(temporary)
                run_id = f"20260830T00002{index}Z-editor-reject"
                completed = self.finalize(temporary, staging, source, source_report, run_id)
                self.assertNotEqual(0, completed.returncode)
                self.assertIn("editor", completed.stderr.lower())
                self.assertFalse((temporary / "artifacts" / run_id).exists())

    def test_finalizer_rejects_missing_tampered_or_unbound_historical_negative_control(self) -> None:
        scenarios = ("missing-raw", "tampered-raw", "unbound-case")
        for index, scenario in enumerate(scenarios):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory(prefix=f"nndv-061-historical-negative-{scenario}-") as directory:
                temporary = Path(directory)
                staging = temporary / "staging"
                staging.mkdir()
                self.reports_and_payloads(staging)
                raw_path = staging / HISTORICAL_ORACLE_RELATIVE
                before_after_path = staging / "reports/exports/before-after-proofs.json"
                if scenario == "missing-raw":
                    raw_path.unlink()
                elif scenario == "tampered-raw":
                    raw = json.loads(raw_path.read_text())
                    raw["measurement_contract"]["metadata_trusted"] = True
                    write_json(raw_path, raw)
                else:
                    before_after = json.loads(before_after_path.read_text())
                    before_after["strict_negative_control"]["cases"][0]["manifest_sha256"] = "0" * 64
                    write_json(before_after_path, before_after)
                source, source_report = self.source_fixture(temporary)
                run_id = f"20260830T00001{index}Z-historical-reject"
                completed = self.finalize(temporary, staging, source, source_report, run_id)
                self.assertNotEqual(0, completed.returncode)
                self.assertTrue(
                    "negative-control" in completed.stderr.lower() or "historical_0_6_0" in completed.stderr.lower(),
                    completed.stdout + completed.stderr,
                )
                self.assertFalse((temporary / "artifacts" / run_id).exists())

    def test_0_6_0_test_identity_fixture_is_exact_and_release_scripts_are_strict(self) -> None:
        baseline = ROOT / "verification/fixtures/python-test-ids-0.6.0.txt"
        ids = baseline.read_text(encoding="utf-8").splitlines()
        self.assertEqual(171, len(ids))
        self.assertEqual(171, len(set(ids)))
        self.assertEqual(BASELINE_SHA256, hashlib.sha256(baseline.read_bytes()).hexdigest())

        quick = (ROOT / "scripts/verify-quick-0.6.1.sh").read_text(encoding="utf-8")
        full = (ROOT / "scripts/verify-full-0.6.1.sh").read_text(encoding="utf-8")
        generator = (ROOT / "scripts/generate_publication_artifacts_0_6_1.py").read_text(encoding="utf-8")
        self.assertIn("--baseline-ids verification/fixtures/python-test-ids-0.6.0.txt", quick)
        self.assertIn("old_core_passed", quick)
        self.assertIn("all_package_passed", quick)
        self.assertIn("figure_svg_oracle.mjs", full)
        self.assertIn("validate_figure_svg_oracle_fixtures.py", full)
        self.assertIn("generate_publication_artifacts_0_6_1.py", full)
        self.assertIn("validate_cross_format_positions_0_6_1.py", full)
        self.assertIn("generate_before_after_proofs_0_6_1.py", full)
        self.assertIn("HISTORICAL_060_SVGS", full)
        self.assertIn("authoritative-0.6.0-figure-svg-oracle.json", full)
        self.assertIn("--before-oracle-report", full)
        self.assertIn("--allow-failures", full)
        self.assertLess(
            full.index("authoritative-0.6.0-figure-svg-oracle.json"),
            full.index("generate_before_after_proofs_0_6_1.py"),
        )
        self.assertLess(full.index("figure_svg_oracle.mjs"), full.index("finalize_artifact_0_6_1.py"))
        self.assertNotIn("validate_figure_exports.py", full)
        self.assertNotIn("from nn_davinci.figure_export import figure_proof", generator)
        self.assertIn('import_real_model(key, view="module")', generator)
        self.assertIn('FORMATS = ("svg", "pdf", "tikz", "png", "eps", "pptx", "html")', generator)

    def test_strict_oracle_validator_requires_exact_fresh_svg_hashes_and_metrics(self) -> None:
        with tempfile.TemporaryDirectory(prefix="nndv-061-strict-validator-") as directory:
            temporary = Path(directory)
            svg_inputs = [{"relative_path": f"templates/t{index}/figure.svg", "sha256": f"{index:064x}"} for index in range(14)]
            exports = {
                "status": "PASS",
                "fresh_outputs": True,
                "python_figure_proof_is_release_blocker": False,
                "svg_inputs": svg_inputs,
            }
            oracle: dict[str, Any] = {
                "schema_version": "nndv-figure-svg-oracle-report-1",
                "oracle": "figure-final-svg-chrome-v1",
                "browser": {"executable": "/usr/bin/google-chrome", "version": "fixture"},
                "measurement_contract": {
                    "final_dom_only": True,
                    "metadata_trusted": False,
                    "python_proof_imported": False,
                    "data_scale_claims_trusted": False,
                    "stroke_under_full_ctm": True,
                    "path_flattener": "svg_path_flatten.js",
                    "tolerance": {"minimumFontPt": 7.0, "minimumStrokePt": 0.1},
                },
                "summary": {"files": 14, "passed": 14, "failed": 0, "issues": 0},
                "passed": True,
                "reports": [
                    {
                        "file": f"/tmp/t{index}/figure.svg",
                        "sha256": item["sha256"],
                        "source": {"loaded_from_persisted_file": True, "metadata_consulted": False},
                        "passed": True,
                        "issues": [],
                        "issue_counts": {},
                        "browser_errors": [],
                        "summary": {
                            "minimum_font_pt": 6.999744,
                            "minimum_stroke_pt": 0.349987,
                            "maximum_stroke_pt": 0.8,
                            "minimum_horizontal_ctm_scale": 1.0,
                            "minimum_vertical_ctm_scale": 1.0,
                            "minimum_transform_shape": 1.0,
                            "issue_count": 0,
                        },
                        "strokes": [
                            {"effective_stroke_pt": 0.349987},
                            {"effective_stroke_pt": 0.8},
                        ],
                        "occupancy": [{"page_id": "page-1", "bbox_occupancy": 0.5}],
                    }
                    for index, item in enumerate(svg_inputs)
                ],
            }
            export_path = temporary / "exports.json"
            oracle_path = temporary / "oracle.json"
            output_path = temporary / "validation.json"
            write_json(export_path, exports)
            write_json(oracle_path, oracle)
            command = [
                sys.executable,
                str(ROOT / "scripts/validate_strict_figure_oracle_0_6_1.py"),
                "--oracle-report",
                str(oracle_path),
                "--export-report",
                str(export_path),
                "--output",
                str(output_path),
            ]
            passed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
            self.assertEqual(0, passed.returncode, passed.stdout + passed.stderr)
            validation = json.loads(output_path.read_text())
            self.assertEqual("PASS", validation["status"])
            self.assertEqual(6.999744, validation["metrics"]["minimum_font_pt"])
            self.assertEqual(0.349987, validation["metrics"]["minimum_stroke_pt"])

            oracle["reports"][0]["sha256"] = "f" * 64
            write_json(oracle_path, oracle)
            rejected = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn("hashes", output_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
