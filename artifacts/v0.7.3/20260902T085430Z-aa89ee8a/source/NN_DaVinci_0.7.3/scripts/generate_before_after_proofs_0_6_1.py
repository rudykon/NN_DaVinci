#!/usr/bin/env python3
"""Build diagnostic 0.6.0-before/0.6.1-after proof images offline.

The before side is deliberately pinned to the persisted, independently
verifiable 0.6.0 release artifact.  It is never regenerated from source and it
is never substituted with a 0.6.1 export.  These images are diagnostic release
history, not inputs to the 0.6.1 publication-quality pass decision.
"""

from __future__ import annotations

import argparse
from io import BytesIO
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
from typing import Any


VERSION = "0.6.1"
RELEASE = "0.6.1 Beta — Publication Fidelity & Model-to-Figure Completion"
BEFORE_RELEASE = "0.6.0 Beta — Scientific Figure Studio"
BEFORE_RUN_ID = "20260829T183558Z-09a7930b"
BEFORE_MANIFEST_SHA256 = "797d5b38403154b1317d00e8a9e03c48373a2c046e10e4a43229f828769e3cc4"
HISTORICAL_VERIFIER_SHA256 = "24d27e094e6c19b13449846014fddc67fffb93aef92afc729300e354720005d8"
HISTORICAL_ORACLE_REPORT_RELATIVE = "reports/exports/authoritative-0.6.0-figure-svg-oracle.json"
EXPECTED_TEMPLATES = (
    "cnn-feature-pipeline",
    "diffusion-unet-conditioning",
    "moe-router-experts",
    "multimodal-fusion",
    "resnet-overview",
    "transformer-attention-ffn",
    "unet-encoder-decoder",
)
PNG_DPI = 300.0


class ProofGenerationError(RuntimeError):
    """Raised when an input cannot support trustworthy proof generation."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path, relative_path: str) -> dict[str, Any]:
    return {
        "relative_path": relative_path,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProofGenerationError(f"cannot read JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProofGenerationError(f"JSON document is not an object: {path}")
    return value


def safe_relative(value: str) -> PurePosixPath:
    relative = PurePosixPath(value)
    if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ProofGenerationError(f"unsafe relative path: {value!r}")
    return relative


def verified_file(root: Path, relative_path: str, claim: Any) -> Path:
    relative = safe_relative(relative_path)
    if not isinstance(claim, dict):
        raise ProofGenerationError(f"file claim is not an object: {relative_path}")
    path = root.joinpath(*relative.parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ProofGenerationError(f"file escapes or is absent from export root: {relative_path}") from exc
    if path.is_symlink() or not resolved.is_file():
        raise ProofGenerationError(f"export is not a regular non-symlink file: {relative_path}")
    observed_bytes = resolved.stat().st_size
    observed_hash = sha256(resolved)
    if claim.get("bytes") != observed_bytes or claim.get("sha256") != observed_hash:
        raise ProofGenerationError(f"export report hash/size mismatch: {relative_path}")
    return resolved


def run_historical_verifier(artifact: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest_path = artifact / "MANIFEST.json"
    manifest = load_object(manifest_path)
    if artifact.name != BEFORE_RUN_ID or manifest.get("run_id") != BEFORE_RUN_ID:
        raise ProofGenerationError(f"before artifact must be authoritative run {BEFORE_RUN_ID}, got {artifact.name!r}")
    if manifest.get("release") != BEFORE_RELEASE:
        raise ProofGenerationError("before artifact has an unexpected release identity")
    observed_manifest_hash = sha256(manifest_path)
    if observed_manifest_hash != BEFORE_MANIFEST_SHA256:
        raise ProofGenerationError("before artifact MANIFEST.json is not the pinned authoritative 0.6.0 manifest")

    verifier_path = Path(__file__).resolve().with_name("verify_release_artifact_0_6.py")
    if not verifier_path.is_file() or sha256(verifier_path) != HISTORICAL_VERIFIER_SHA256:
        raise ProofGenerationError("the pinned historical 0.6.0 read-only verifier is unavailable")
    spec = importlib.util.spec_from_file_location("nndv_historical_artifact_verifier_060", verifier_path)
    if spec is None or spec.loader is None:
        raise ProofGenerationError("cannot load the historical 0.6.0 artifact verifier")
    module = importlib.util.module_from_spec(spec)
    previous_dont_write_bytecode = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous_dont_write_bytecode
    verifier = getattr(module, "verify", None)
    if not callable(verifier):
        raise ProofGenerationError("historical 0.6.0 verifier does not expose verify()")
    verification = verifier(artifact)
    if not isinstance(verification, dict) or verification.get("status") != "PASS":
        failures = verification.get("failures", []) if isinstance(verification, dict) else []
        raise ProofGenerationError(f"authoritative 0.6.0 artifact verification failed: {failures}")
    if verification.get("run_id") != BEFORE_RUN_ID:
        raise ProofGenerationError("historical verifier returned an unexpected run id")
    if verification.get("manifest_sha256") != BEFORE_MANIFEST_SHA256:
        raise ProofGenerationError("historical verifier returned an unexpected manifest hash")
    return manifest, verification


def validate_historical_oracle(
    report_path: Path,
    *,
    artifact: Path,
    manifest_entries: dict[str, Any],
    before_svgs: list[Path],
) -> dict[str, Any]:
    """Validate the independent Chrome result for the seven persisted 0.6.0 SVGs."""

    report = load_object(report_path)
    contract = report.get("measurement_contract")
    summary = report.get("summary")
    raw_cases = report.get("reports")
    if not (
        report.get("schema_version") == "nndv-figure-svg-oracle-report-1"
        and report.get("oracle") == "figure-final-svg-chrome-v1"
        and report.get("passed") is False
        and isinstance(contract, dict)
        and contract.get("final_dom_only") is True
        and contract.get("metadata_trusted") is False
        and contract.get("python_proof_imported") is False
        and contract.get("data_scale_claims_trusted") is False
        and contract.get("stroke_under_full_ctm") is True
        and isinstance(summary, dict)
        and summary.get("files") == len(EXPECTED_TEMPLATES)
        and summary.get("passed") == 0
        and summary.get("failed") == len(EXPECTED_TEMPLATES)
        and isinstance(summary.get("issues"), int)
        and not isinstance(summary.get("issues"), bool)
        and summary["issues"] > 0
        and isinstance(raw_cases, list)
        and len(raw_cases) == len(EXPECTED_TEMPLATES)
    ):
        raise ProofGenerationError("historical strict SVG oracle is not an exact 0/7 final-DOM negative control")

    expected_by_hash: dict[str, dict[str, Any]] = {}
    for template, source in zip(EXPECTED_TEMPLATES, before_svgs, strict=True):
        relative = source.relative_to(artifact).as_posix()
        claim = manifest_entries.get(relative)
        verified_file(artifact, relative, claim)
        if not isinstance(claim, dict):
            raise ProofGenerationError(f"authoritative manifest claim is absent: {relative}")
        digest = claim.get("sha256")
        if not isinstance(digest, str) or digest in expected_by_hash:
            raise ProofGenerationError("authoritative historical SVG hashes are missing or not unique")
        expected_by_hash[digest] = {
            "template": template,
            "manifest_path": relative,
            "bytes": claim.get("bytes"),
            "sha256": digest,
            "source": source,
        }

    observed_by_template: dict[str, dict[str, Any]] = {}
    total_issues = 0
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            raise ProofGenerationError("historical strict SVG oracle contains a non-object case")
        digest = raw_case.get("sha256")
        if not isinstance(digest, str):
            raise ProofGenerationError("historical oracle SVG case has no SHA-256 digest")
        expected = expected_by_hash.get(digest)
        if expected is None:
            raise ProofGenerationError(f"historical oracle SVG hash is absent from the pinned manifest: {digest!r}")
        template = expected["template"]
        if template in observed_by_template:
            raise ProofGenerationError(f"historical oracle repeats template: {template}")
        issues = raw_case.get("issues")
        case_summary = raw_case.get("summary")
        source_claim = raw_case.get("source")
        raw_file = raw_case.get("file")
        issue_count = case_summary.get("issue_count") if isinstance(case_summary, dict) else None
        try:
            oracle_source = Path(raw_file).resolve(strict=True) if isinstance(raw_file, str) else None
        except OSError as exc:
            raise ProofGenerationError(f"historical oracle source is unavailable for {template}: {exc}") from exc
        if not (
            raw_case.get("passed") is False
            and isinstance(issues, list)
            and len(issues) > 0
            and isinstance(issue_count, int)
            and not isinstance(issue_count, bool)
            and issue_count == len(issues)
            and raw_case.get("browser_errors") == []
            and isinstance(source_claim, dict)
            and source_claim.get("loaded_from_persisted_file") is True
            and source_claim.get("metadata_consulted") is False
            and oracle_source == expected["source"]
            and source_claim.get("url") == expected["source"].as_uri()
        ):
            raise ProofGenerationError(f"historical oracle case violates the persisted final-DOM contract: {template}")
        total_issues += issue_count
        observed_by_template[template] = {
            "template": template,
            "manifest_path": expected["manifest_path"],
            "manifest_bytes": expected["bytes"],
            "manifest_sha256": expected["sha256"],
            "oracle_sha256": digest,
            "oracle_passed": False,
            "issue_count": issue_count,
            "issue_counts": raw_case.get("issue_counts", {}),
            "browser_errors": 0,
            "loaded_from_persisted_file": True,
            "metadata_consulted": False,
        }

    if set(observed_by_template) != set(EXPECTED_TEMPLATES) or total_issues != summary["issues"]:
        raise ProofGenerationError("historical strict SVG oracle template or issue totals are inconsistent")

    return {
        "schema_version": "nndv-0.6.1-authoritative-0.6.0-strict-negative-control-1",
        "status": "PASS",
        "interpretation": "the negative-control validation passed because all seven historical SVGs failed the strict oracle",
        "expected_failure_observed": True,
        "historical_svg_quality_passed": False,
        "oracle_passed": False,
        "authoritative_run_id": BEFORE_RUN_ID,
        "authoritative_manifest_sha256": BEFORE_MANIFEST_SHA256,
        "manifest_hashes_matched": True,
        "expected_templates": list(EXPECTED_TEMPLATES),
        "measurement_contract": {
            "final_dom_only": True,
            "metadata_trusted": False,
            "python_proof_imported": False,
            "data_scale_claims_trusted": False,
            "stroke_under_full_ctm": True,
        },
        "summary": {
            "files": len(EXPECTED_TEMPLATES),
            "passed": 0,
            "failed": len(EXPECTED_TEMPLATES),
            "issues": total_issues,
        },
        "raw_report": file_record(report_path, HISTORICAL_ORACLE_REPORT_RELATIVE),
        "cases": [observed_by_template[template] for template in EXPECTED_TEMPLATES],
        "failures": [],
    }


def load_after_templates(
    report_path: Path,
) -> tuple[dict[str, Any], Path, dict[str, dict[str, Path]]]:
    report = load_object(report_path)
    if report.get("schema_version") != "nndv-0.6.1-publication-artifact-corpus-1":
        raise ProofGenerationError("after export report has an unexpected schema")
    if report.get("release") != RELEASE or report.get("status") != "PASS":
        raise ProofGenerationError("after export report is not a passing 0.6.1 corpus")
    if report.get("fresh_outputs") is not True:
        raise ProofGenerationError("after export report does not attest fresh outputs")
    counts = report.get("counts")
    if not isinstance(counts, dict) or counts.get("templates") != 7 or counts.get("failures") != 0:
        raise ProofGenerationError("after export report does not contain exactly seven passing templates")

    raw_root = report.get("output_root")
    if not isinstance(raw_root, str) or not raw_root:
        raise ProofGenerationError("after export report has no output_root")
    candidate = Path(raw_root)
    if not candidate.is_absolute():
        candidate = report_path.parent / candidate
    if candidate.is_symlink():
        raise ProofGenerationError("after export root must not be a symlink")
    try:
        output_root = candidate.resolve(strict=True)
    except OSError as exc:
        raise ProofGenerationError(f"after export root is unavailable: {candidate}") from exc
    if output_root.is_symlink() or not output_root.is_dir():
        raise ProofGenerationError("after export root is not a regular directory")

    svg_inputs_raw = report.get("svg_inputs")
    if not isinstance(svg_inputs_raw, list):
        raise ProofGenerationError("after export report has no SVG input inventory")
    svg_inputs: dict[str, dict[str, Any]] = {}
    for item in svg_inputs_raw:
        if not isinstance(item, dict) or not isinstance(item.get("relative_path"), str):
            raise ProofGenerationError("after SVG input inventory contains an invalid record")
        relative_path = item["relative_path"]
        if relative_path in svg_inputs:
            raise ProofGenerationError(f"duplicate after SVG input record: {relative_path}")
        svg_inputs[relative_path] = item

    results_raw = report.get("results")
    if not isinstance(results_raw, list):
        raise ProofGenerationError("after export report has no result inventory")
    template_results: dict[str, dict[str, Any]] = {}
    for item in results_raw:
        if not isinstance(item, dict) or item.get("kind") != "template":
            continue
        key = item.get("key")
        if not isinstance(key, str) or key in template_results:
            raise ProofGenerationError("after export report has an invalid/duplicate template result")
        template_results[key] = item
    if tuple(sorted(template_results)) != EXPECTED_TEMPLATES:
        raise ProofGenerationError(f"after template set is {sorted(template_results)}, expected {list(EXPECTED_TEMPLATES)}")

    resolved: dict[str, dict[str, Path]] = {}
    for template in EXPECTED_TEMPLATES:
        item = template_results[template]
        if item.get("status") != "PASS" or item.get("failures") != []:
            raise ProofGenerationError(f"after template is not a clean PASS: {template}")
        files = item.get("files")
        if not isinstance(files, dict):
            raise ProofGenerationError(f"after template has no file inventory: {template}")
        svg_relative = f"templates/{template}/figure.svg"
        proof_relative = f"templates/{template}/figure.proof-300dpi.png"
        svg_claim = files.get("figure.svg")
        proof_claim = files.get("figure.proof-300dpi.png")
        svg_input_claim = svg_inputs.get(svg_relative)
        if (
            not isinstance(svg_input_claim, dict)
            or not isinstance(svg_claim, dict)
            or any(svg_input_claim.get(field) != svg_claim.get(field) for field in ("bytes", "sha256"))
        ):
            raise ProofGenerationError(f"SVG inventories disagree for after template: {template}")
        resolved[template] = {
            "svg": verified_file(output_root, svg_relative, svg_claim),
            "proof": verified_file(output_root, proof_relative, proof_claim),
        }
    return report, output_root, resolved


def rasterize_before(source: Path, destination: Path) -> dict[str, Any]:
    try:
        import cairosvg
        from PIL import Image

        png = cairosvg.svg2png(bytestring=source.read_bytes(), dpi=PNG_DPI)
        with Image.open(BytesIO(png)) as opened:
            image = opened.convert("RGBA")
        image.save(
            destination,
            format="PNG",
            dpi=(PNG_DPI, PNG_DPI),
            optimize=False,
            compress_level=9,
        )
        width, height = image.size
    except Exception as exc:
        raise ProofGenerationError(f"offline 300-DPI SVG rasterization failed for {source}: {type(exc).__name__}: {exc}") from exc
    if width not in {2102, 2103} or height != 1394:
        raise ProofGenerationError(f"unexpected before raster size {width}x{height}; expected 178x118 mm at 300 DPI")
    return {"width_px": width, "height_px": height, "mode": "RGBA", "requested_dpi": PNG_DPI}


def inspect_png(path: Path) -> dict[str, Any]:
    try:
        from PIL import Image

        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
            mode = image.mode
            dpi = tuple(float(value) for value in image.info.get("dpi", (0.0, 0.0)))
    except Exception as exc:
        raise ProofGenerationError(f"invalid after proof PNG {path}: {type(exc).__name__}: {exc}") from exc
    if width not in {2102, 2103} or height != 1394:
        raise ProofGenerationError(f"after proof is not a 178x118 mm 300-DPI raster: {path}")
    if len(dpi) < 2 or any(abs(value - PNG_DPI) > 0.1 for value in dpi[:2]):
        raise ProofGenerationError(f"after proof lacks 300-DPI metadata: {path}")
    return {"width_px": width, "height_px": height, "mode": mode, "dpi": list(dpi[:2])}


def compose_comparison(before: Path, after: Path, destination: Path) -> dict[str, Any]:
    try:
        from PIL import Image

        with Image.open(before) as opened:
            left = opened.convert("RGBA")
        with Image.open(after) as opened:
            right = opened.convert("RGBA")
        gap = 8
        canvas = Image.new(
            "RGBA",
            (left.width + gap + right.width, max(left.height, right.height)),
            (255, 255, 255, 255),
        )
        canvas.paste(left, (0, 0), left)
        canvas.paste(right, (left.width + gap, 0), right)
        for x in range(left.width + 3, left.width + 5):
            for y in range(canvas.height):
                canvas.putpixel((x, y), (31, 41, 55, 255))
        canvas.save(
            destination,
            format="PNG",
            dpi=(PNG_DPI, PNG_DPI),
            optimize=False,
            compress_level=9,
        )
    except Exception as exc:
        raise ProofGenerationError(f"before/after comparison composition failed: {type(exc).__name__}: {exc}") from exc
    return {
        "width_px": canvas.width,
        "height_px": canvas.height,
        "mode": "RGBA",
        "layout": "0.6.0 authoritative before | 0.6.1 fresh after",
        "divider_px": gap,
    }


def generate(
    *,
    before_artifact: Path,
    before_oracle_report: Path,
    after_export_report: Path,
    output_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    if output_dir.exists():
        if output_dir.is_symlink() or not output_dir.is_dir() or any(output_dir.iterdir()):
            raise ProofGenerationError(f"refusing to overwrite non-empty/unsafe output directory: {output_dir}")
    if report_path.exists() or report_path.is_symlink():
        raise ProofGenerationError(f"refusing to overwrite report: {report_path}")
    try:
        report_path.resolve().relative_to(output_dir.resolve())
    except ValueError:
        pass
    else:
        raise ProofGenerationError("report must be outside the proof output directory")

    try:
        artifact = before_artifact.resolve(strict=True)
        historical_oracle_path = before_oracle_report.resolve(strict=True)
        after_report_path = after_export_report.resolve(strict=True)
    except OSError as exc:
        raise ProofGenerationError(f"required input is absent: {exc}") from exc
    if artifact.is_symlink() or not artifact.is_dir():
        raise ProofGenerationError("before artifact must be a regular directory")
    if historical_oracle_path.is_symlink() or not historical_oracle_path.is_file():
        raise ProofGenerationError("historical strict SVG oracle report must be a regular file")
    if after_report_path.is_symlink() or not after_report_path.is_file():
        raise ProofGenerationError("after export report must be a regular file")

    before_manifest, before_verification = run_historical_verifier(artifact)
    after_report, after_root, after_templates = load_after_templates(after_report_path)

    before_root = artifact / "exports" / "figure-templates"
    before_svgs = sorted(before_root.glob("*/figure.svg"))
    observed_before = tuple(path.parent.name for path in before_svgs)
    if observed_before != EXPECTED_TEMPLATES:
        raise ProofGenerationError(f"authoritative artifact has before templates {list(observed_before)}, expected {list(EXPECTED_TEMPLATES)}")
    manifest_entries = before_manifest.get("entries")
    if not isinstance(manifest_entries, dict):
        raise ProofGenerationError("authoritative artifact manifest has no entries")
    for source in before_svgs:
        relative = source.relative_to(artifact).as_posix()
        verified_file(artifact, relative, manifest_entries.get(relative))
    strict_negative_control = validate_historical_oracle(
        historical_oracle_path,
        artifact=artifact,
        manifest_entries=manifest_entries,
        before_svgs=before_svgs,
    )

    # All inputs and their claims are validated before any output is created.
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in ("before", "after", "comparison"):
        (output_dir / name).mkdir()

    cases: list[dict[str, Any]] = []
    for template, before_source in zip(EXPECTED_TEMPLATES, before_svgs, strict=True):
        after_svg = after_templates[template]["svg"]
        after_proof = after_templates[template]["proof"]
        before_output = output_dir / "before" / f"{template}.png"
        after_output = output_dir / "after" / f"{template}.png"
        comparison_output = output_dir / "comparison" / f"{template}.png"

        before_image = rasterize_before(before_source, before_output)
        after_image = inspect_png(after_proof)
        shutil.copyfile(after_proof, after_output)
        if sha256(after_output) != sha256(after_proof):
            raise ProofGenerationError(f"after proof copy changed bytes: {template}")
        comparison_image = compose_comparison(before_output, after_output, comparison_output)

        cases.append(
            {
                "template": template,
                "passed": True,
                "before": {
                    "source": file_record(
                        before_source,
                        before_source.relative_to(artifact).as_posix(),
                    ),
                    "source_kind": "persisted-v0.6.0-artifact-svg",
                    "regenerated_from_source": False,
                    "proof": {
                        **file_record(before_output, before_output.relative_to(output_dir).as_posix()),
                        **before_image,
                    },
                },
                "after": {
                    "svg_source": file_record(
                        after_svg,
                        after_svg.relative_to(after_root).as_posix(),
                    ),
                    "proof_source": file_record(
                        after_proof,
                        after_proof.relative_to(after_root).as_posix(),
                    ),
                    "fresh_export_report_bound": True,
                    "proof": {
                        **file_record(after_output, after_output.relative_to(output_dir).as_posix()),
                        **after_image,
                    },
                },
                "comparison": {
                    **file_record(
                        comparison_output,
                        comparison_output.relative_to(output_dir).as_posix(),
                    ),
                    **comparison_image,
                },
            }
        )

    integrity_manifest = {
        "schema_version": "nndv-0.6.1-before-after-proof-integrity-1",
        "release": RELEASE,
        "diagnostic_only": True,
        "release_quality_gate_input": False,
        "before": {
            "release": BEFORE_RELEASE,
            "run_id": BEFORE_RUN_ID,
            "manifest_sha256": BEFORE_MANIFEST_SHA256,
            "authoritative_persisted_exports": True,
            "regenerated": False,
            "uses_0_6_1_as_before": False,
        },
        "after": {
            "release": RELEASE,
            "fresh_outputs": True,
            "export_report": file_record(after_report_path, after_report_path.name),
        },
        "rasterization": {
            "offline": True,
            "before_svg_dpi": PNG_DPI,
            "after_proof_policy": "exact byte copy of hash-verified fresh export proof",
        },
        "templates": cases,
    }
    integrity_path = output_dir / "integrity-manifest.json"
    write_json(integrity_path, integrity_manifest)

    output_files = [path for path in sorted(output_dir.rglob("*")) if path.is_file() and not path.is_symlink()]
    expected_output_count = len(EXPECTED_TEMPLATES) * 3 + 1
    if len(output_files) != expected_output_count:
        raise ProofGenerationError(f"proof output inventory has {len(output_files)} files, expected {expected_output_count}")
    output_inventory = [file_record(path, path.relative_to(output_dir).as_posix()) for path in output_files]
    proof_files = [item for item in output_inventory if str(item["relative_path"]).endswith(".png")]

    verification_summary = {
        key: before_verification.get(key)
        for key in (
            "status",
            "run_id",
            "manifest_entries",
            "files_checked",
            "source_file_count",
            "source_digest",
            "sha256sums_sha256",
            "manifest_sha256",
        )
    }
    report = {
        "schema_version": "nndv-0.6.1-before-after-proof-1",
        "release": RELEASE,
        "status": "PASS",
        "before_release": "0.6.0",
        "after_release": VERSION,
        "authoritative_before_run_id": BEFORE_RUN_ID,
        "authoritative_before_manifest_sha256": BEFORE_MANIFEST_SHA256,
        "before_inputs_are_diagnostic_only": True,
        "after_fresh_outputs": True,
        "templates": len(cases),
        "passed_templates": sum(item["passed"] is True for item in cases),
        "output_root": str(output_dir.resolve()),
        "diagnostic_only": True,
        "release_quality_gate_input": False,
        "before_evidence_policy": {
            "authoritative_persisted_v0_6_0_artifact_only": True,
            "run_id": BEFORE_RUN_ID,
            "regenerated": False,
            "uses_0_6_1_as_before": False,
        },
        "before_artifact": {
            "release": BEFORE_RELEASE,
            "run_id": BEFORE_RUN_ID,
            "manifest": file_record(artifact / "MANIFEST.json", "MANIFEST.json"),
            "read_only_verification": verification_summary,
        },
        "strict_negative_control": strict_negative_control,
        "after_export": {
            "release": RELEASE,
            "schema_version": after_report.get("schema_version"),
            "fresh_outputs": after_report.get("fresh_outputs"),
            "report": file_record(after_report_path, after_report_path.name),
        },
        "counts": {
            "templates": len(cases),
            "before_svg_sources": len(cases),
            "after_svg_sources": len(cases),
            "after_proof_sources": len(cases),
            "before_proof_pngs": len(cases),
            "after_proof_pngs": len(cases),
            "comparison_pngs": len(cases),
            "output_files": len(output_files),
        },
        "integrity_manifest": file_record(
            integrity_path,
            integrity_path.relative_to(output_dir).as_posix(),
        ),
        "cases": cases,
        "proof_files": proof_files,
        "outputs": output_inventory,
        "failures": [],
    }
    write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before-artifact", type=Path, required=True)
    parser.add_argument("--before-oracle-report", type=Path, required=True)
    parser.add_argument("--after-export-report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = generate(
            before_artifact=args.before_artifact,
            before_oracle_report=args.before_oracle_report,
            after_export_report=args.after_export_report,
            output_dir=args.output_dir,
            report_path=args.report,
        )
    except (OSError, ProofGenerationError) as exc:
        print(f"NNDV_061_BEFORE_AFTER_ERROR={exc}", file=sys.stderr)
        return 1
    print(
        "NNDV_061_BEFORE_AFTER="
        + json.dumps(
            {
                "status": report["status"],
                "templates": report["counts"]["templates"],
                "outputs": report["counts"]["output_files"],
                "diagnostic_only": report["diagnostic_only"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
