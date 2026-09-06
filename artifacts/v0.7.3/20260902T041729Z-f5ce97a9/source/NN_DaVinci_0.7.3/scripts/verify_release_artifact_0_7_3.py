#!/usr/bin/env python3
"""Independent, artifact-only verification of a sealed 0.7.3 run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from finalize_artifact_0_7_3 import (
    PARENT_RUN_ID,
    PARENT_SOURCE_DIGEST,
    PARENT_SOURCE_FILES,
    RELEASE,
    REPORTS,
    inventory,
    load_object,
    report_failures,
    sha256,
    source_snapshot_failures,
)


CONTROL = {"MANIFEST.json", "SHA256SUMS"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-run-id")
    args = parser.parse_args()
    if args.artifact.is_symlink() or not args.artifact.is_dir():
        raise SystemExit("artifact root is absent or unsafe")
    root = args.artifact.resolve(strict=True)
    output = args.output.resolve()
    if output == root or root in output.parents:
        raise SystemExit("artifact-only verification output must be outside the sealed artifact")
    run_id = args.expected_run_id or root.name
    files, failures = inventory(root)
    for required in ("verification.json", "MANIFEST.json", "SHA256SUMS"):
        if required not in files:
            failures.append(f"missing control file: {required}")
    manifest: dict[str, Any] = load_object(files["MANIFEST.json"]) if "MANIFEST.json" in files else {}
    checksums: dict[str, Any] = load_object(files["SHA256SUMS"]) if "SHA256SUMS" in files else {}
    verification: dict[str, Any] = load_object(files["verification.json"]) if "verification.json" in files else {}

    entries = manifest.get("entries", {}) if isinstance(manifest.get("entries"), dict) else {}
    if not (
        manifest.get("schema_version") == "nndv-0.7.3-artifact-manifest-1"
        and manifest.get("release") == RELEASE
        and manifest.get("run_id") == run_id
        and manifest.get("manifest_excludes") == ["MANIFEST.json", "SHA256SUMS"]
        and set(entries) == set(files) - CONTROL
    ):
        failures.append("MANIFEST identity or exact path set is invalid")
    for relative in sorted(set(entries).intersection(files)):
        claim = entries[relative]
        path = files[relative]
        if not (isinstance(claim, dict) and claim.get("bytes") == path.stat().st_size and claim.get("sha256") == sha256(path)):
            failures.append(f"MANIFEST claim mismatch: {relative}")

    raw_checksum_entries = checksums.get("entries", [])
    checksum_by_path = {
        item["path"]: item
        for item in raw_checksum_entries
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    if not (
        checksums.get("schema_version") == "nndv-sha256-manifest-2"
        and checksums.get("algorithm") == "sha256"
        and checksums.get("checksum_excludes") == ["SHA256SUMS"]
        and len(checksum_by_path) == len(raw_checksum_entries)
        and set(checksum_by_path) == set(files) - {"SHA256SUMS"}
    ):
        failures.append("SHA256SUMS identity or exact path set is invalid")
    for relative, claim in checksum_by_path.items():
        checksum_path = files.get(relative)
        if checksum_path is None or claim.get("size") != checksum_path.stat().st_size or claim.get("sha256") != sha256(checksum_path):
            failures.append(f"SHA256SUMS claim mismatch: {relative}")

    if not (
        verification.get("schema_version") == "nndv-0.7.3-verification-1"
        and verification.get("release") == RELEASE
        and verification.get("run_id") == run_id
        and verification.get("status") == "PASS"
        and verification.get("failures") == []
        and verification.get("reports") == REPORTS
        and verification.get("git_operations") is False
        and verification.get("uploaded_or_published") is False
        and verification.get("human_evidence") == {"participants": 0, "automated_evidence_is_human_evidence": False}
    ):
        failures.append("verification identity or external-action boundary is invalid")
    parent = verification.get("parent_0_7_2", {})
    if not (
        parent.get("run_id") == PARENT_RUN_ID
        and parent.get("source_files") == PARENT_SOURCE_FILES
        and parent.get("source_digest") == PARENT_SOURCE_DIGEST
        and parent.get("test_count") == 353
        and parent.get("artifact_verification") == "PASS"
        and parent.get("read_only") is True
    ):
        failures.append("verification does not bind the authoritative 0.7.2 parent")

    missing_reports = [relative for relative in REPORTS.values() if relative not in files]
    failures.extend(f"missing indexed report: {relative}" for relative in missing_reports)
    reports = {name: load_object(files[relative]) for name, relative in REPORTS.items() if relative in files}
    if not missing_reports:
        failures.extend(report_failures(reports))
        failures.extend(source_snapshot_failures(root, reports["source"]))

    source = verification.get("source", {})
    if not (
        source.get("file_count") == manifest.get("source_file_count")
        and source.get("source_tree_digest") == manifest.get("source_digest")
        and isinstance(source.get("allowlist_sha256"), str)
        and len(source.get("allowlist_sha256")) == 64
    ):
        failures.append("source snapshot, manifest, and verification disagree")
    version_files = {
        "pyproject.toml": 'version = "0.7.3"',
        "package.json": '"version": "0.7.3"',
        "src/nn_davinci/version.py": '__version__ = "0.7.3"',
    }
    for relative, marker in version_files.items():
        path = root / "source" / "NN_DaVinci_0.7.3" / relative
        if not path.is_file() or marker not in path.read_text(encoding="utf-8"):
            failures.append(f"stale-current-version blocker: {relative}")
    if reports and reports.get("audit", {}).get("stale_current_version_blocker") != "PASS":
        failures.append("stale-current-version release audit is not PASS")

    corpus_files, corpus_unsafe = inventory(root / "exports" / "scene-corpus")
    failures.extend(corpus_unsafe)
    if len(corpus_files) != 196:
        failures.append(f"artifact Scene corpus contains {len(corpus_files)} files, expected 196")
    before_files, before_unsafe = inventory(root / "evidence" / "publication-before-after")
    failures.extend(before_unsafe)
    if len([name for name in before_files if name.endswith(".png")]) != 42:
        failures.append("artifact before/after evidence does not contain exactly 42 PNGs")
    tikz_files, tikz_unsafe = inventory(root / "evidence" / "tikz-pdf-proofs")
    failures.extend(tikz_unsafe)
    if len([name for name in tikz_files if name.endswith(".pdf")]) != 7:
        failures.append("artifact does not contain seven compiled TikZ PDFs")

    result = {
        "schema_version": "nndv-0.7.3-artifact-inventory-verification-1",
        "release": RELEASE,
        "status": "PASS" if not failures else "FAIL",
        "run_id": run_id,
        "artifact": str(root),
        "artifact_files": len(files),
        "manifest_entries": len(entries),
        "manifest_sha256": sha256(files["MANIFEST.json"]) if "MANIFEST.json" in files else None,
        "sha256sums_entries": len(checksum_by_path),
        "sha256sums_sha256": sha256(files["SHA256SUMS"]) if "SHA256SUMS" in files else None,
        "source_file_count": manifest.get("source_file_count"),
        "source_digest": manifest.get("source_digest"),
        "failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "run_id": run_id, "artifact_files": len(files), "failures": len(failures)}, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
