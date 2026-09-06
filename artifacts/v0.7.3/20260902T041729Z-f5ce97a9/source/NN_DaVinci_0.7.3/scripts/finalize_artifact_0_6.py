#!/usr/bin/env python3
"""Finalize a passed 0.6.0 full run into a self-contained artifact."""

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

from scripts.verify_release_artifact_0_6 import inventory, sha256


RELEASE = "0.6.0 Beta — Scientific Figure Studio"
EXPECTED_REPORTS = {
    "quick": "reports/quick/quick-verification.json",
    "editor": "reports/e2e/editor.json",
    "responsive": "reports/e2e/responsive.json",
    "semantic": "reports/e2e/semantic.json",
    "product": "reports/e2e/product.json",
    "trial": "reports/e2e/trial.json",
    "figure": "reports/e2e/figure-studio.json",
    "exports": "reports/exports/figure-export-report.json",
    "performance": "reports/performance/figure-studio.json",
    "packaging": "reports/packaging/package-install.json",
    "audit": "reports/docs/release-audit.json",
}


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def report_failures(reports: dict[str, dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    quick = reports["quick"]
    if quick.get("status") != "PASS":
        failures.append("quick verification did not pass")
    python = quick.get("python", {})
    if not (
        python.get("collected") == python.get("passed")
        and python.get("failed") == 0
        and python.get("errors") == 0
        and python.get("skipped") == 0
        and python.get("deselected") == 0
        and python.get("inherited_0_5_2_tests") == 149
    ):
        failures.append("Python test accounting is not an exact all-pass with 149 inherited tests")
    if reports["editor"].get("counts", {}).get("failed") != 0 or reports["editor"].get("counts", {}).get("passed") != 10:
        failures.append("editor E2E did not pass 10 scenarios")
    responsive = reports["responsive"]
    if responsive.get("status") != "passed" or responsive.get("viewport_count") != 7:
        failures.append("responsive E2E did not pass seven viewports")
    for name in ("semantic", "product", "trial"):
        if reports[name].get("status") != "passed":
            failures.append(f"{name} E2E did not pass")
    trial = reports["trial"]
    if trial.get("human_participants") != 0 or trial.get("human_usability_claim") is not False:
        failures.append("automated Trial E2E was misrepresented as human evidence")
    figure = reports["figure"]
    if (
        figure.get("status") != "PASS"
        or figure.get("counts", {}).get("failed") != 0
        or figure.get("counts", {}).get("console_page_request_errors") != 0
        or figure.get("median_interaction_ms", float("inf")) > 100
        or figure.get("tested_viewports") != [1440, 800, 390]
    ):
        failures.append("Figure Studio E2E did not satisfy its full interaction contract")
    exports = reports["exports"]
    if exports.get("status") != "PASS" or exports.get("counts", {}).get("formats") != 28 or exports.get("counts", {}).get("failures") != 0:
        failures.append("cross-format validation did not pass all 28 outputs")
    performance = reports["performance"]
    if performance.get("status") != "PASS" or performance.get("figure_objects") != 1_000:
        failures.append("1,000-object Figure Studio performance gate did not pass")
    if reports["packaging"].get("passed") is not True:
        failures.append("wheel/sdist installation gate did not pass")
    if reports["audit"].get("status") != "PASS":
        failures.append("release/document audit did not pass")
    return failures


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
    if failures:
        raise SystemExit("refusing to create a release artifact:\n- " + "\n- ".join(failures))

    source_report = load_object(args.source_report.resolve())
    source_files = source_report.get("files", {})
    if source_report.get("release") != "0.6.0" or source_report.get("passed") is not True or not isinstance(source_files, dict):
        raise SystemExit("clean source report is not a passed 0.6.0 snapshot")
    replay_root = staging / "source" / "replay-source"
    if replay_root.exists():
        raise SystemExit("staging already contains source/replay-source")
    for name, item in sorted(source_files.items()):
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise SystemExit(f"unsafe source inventory path: {name}")
        source = source_root / relative
        if not source.is_file() or source.is_symlink():
            raise SystemExit(f"source inventory file is absent or unsafe: {name}")
        if source.stat().st_size != item.get("bytes") or sha256(source) != item.get("sha256"):
            raise SystemExit(f"source changed after clean snapshot creation: {name}")
        target = replay_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    normalized_source_report = dict(source_report)
    normalized_source_report["source"] = "source/replay-source"
    normalized_source_report["snapshot"] = "source/replay-source"
    write_json(staging / "reports" / "source" / "snapshot.json", normalized_source_report)

    ended = time.time()
    ended_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    quick_python = reports["quick"]["python"]
    browser_assertions = sum(
        int(reports[name].get("assertion_count", reports[name].get("counts", {}).get("assertions", 0)))
        for name in ("editor", "semantic", "product", "trial", "figure")
    )
    verification = {
        "schema_version": "nndv-0.6.0-full-verification-1",
        "release": RELEASE,
        "run_id": args.run_id,
        "status": "PASS",
        "started_utc": args.started_utc,
        "ended_utc": ended_utc,
        "elapsed_seconds": round(ended - args.started_epoch, 3),
        "source": {
            "file_count": source_report["file_count"],
            "digest": source_report["source_tree_digest"],
            "allowlist": source_report["allowlist"],
            "allowlist_sha256": source_report["allowlist_sha256"],
        },
        "python": quick_python,
        "coverage": reports["quick"]["coverage"],
        "chrome": {
            "suites": 6,
            "assertions": browser_assertions,
            "editor_scenarios": reports["editor"]["counts"]["passed"],
            "responsive_viewports": reports["responsive"]["viewport_count"],
            "figure_studio": reports["figure"]["counts"],
            "figure_interaction_median_ms": reports["figure"]["median_interaction_ms"],
            "console_page_request_errors": reports["figure"]["counts"]["console_page_request_errors"],
        },
        "exports": reports["exports"]["counts"],
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
        "schema_version": "nndv-0.6.0-artifact-manifest-1",
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
    print("NNDV_060_ARTIFACT_CREATED=" + json.dumps({
        "artifact": str(final),
        "run_id": args.run_id,
        "manifest_entries": len(entries),
        "source_file_count": source_report["file_count"],
        "source_digest": source_report["source_tree_digest"],
        "manifest_sha256": sha256(final / "MANIFEST.json"),
        "sha256sums_sha256": sha256(final / "SHA256SUMS"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
