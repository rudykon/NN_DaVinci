#!/usr/bin/env python3
"""Read-only verification for an NN_DaVinci 0.6.0 release artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any


HEX64 = re.compile(r"^[0-9a-f]{64}$")
CONTROL_FILES = frozenset({"MANIFEST.json", "SHA256SUMS"})
FORBIDDEN_SOURCE_PARTS = frozenset({
    ".coverage", ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__",
    "artifacts", "build", "dist", "node_modules",
})


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
    if manifest.get("schema_version") != "nndv-0.6.0-artifact-manifest-1":
        failures.append("unexpected artifact manifest schema")
    if manifest.get("release") != "0.6.0 Beta — Scientific Figure Studio":
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
        observed_size = path.stat().st_size
        observed_hash = sha256(path)
        if item.get("bytes") != observed_size:
            failures.append(f"size mismatch: {name}")
        if item.get("sha256") != observed_hash:
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
        for name in sorted(expected_checksum_paths - set(checksums)):
            failures.append(f"SHA256SUMS missing path: {name}")
        for name in sorted(set(checksums) - expected_checksum_paths):
            failures.append(f"SHA256SUMS extra path: {name}")
    for name in sorted(set(checksums) & set(files)):
        if checksums[name] != sha256(files[name]):
            failures.append(f"SHA256SUMS hash mismatch: {name}")

    source_prefix = "source/replay-source/"
    source_entries = {
        name[len(source_prefix):]: item
        for name, item in expected.items()
        if name.startswith(source_prefix)
    }
    source_digest = hashlib.sha256(
        "".join(
            f"{name}\0{item.get('sha256')}\0{item.get('bytes')}\n"
            for name, item in sorted(source_entries.items())
        ).encode()
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

    try:
        verification = _load_object(root / "verification.json")
        if verification.get("status") != "PASS":
            failures.append("verification.json does not report PASS")
        if verification.get("run_id") != manifest.get("run_id"):
            failures.append("run_id differs between verification and manifest")
        if verification.get("source", {}).get("digest") != source_digest:
            failures.append("verification source digest differs from inventory")
        if verification.get("human_evidence", {}).get("participants") != 0:
            failures.append("artifact incorrectly claims a human participant")
        if verification.get("human_evidence", {}).get("human_usability_claim") is not False:
            failures.append("artifact incorrectly authorizes a human-usability claim")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        failures.append(f"invalid verification.json: {exc}")

    return {
        "schema_version": "nndv-0.6.0-artifact-verification-1",
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
    print("NNDV_060_ARTIFACT_VERIFY=" + json.dumps({
        "status": report["status"],
        "manifest_entries": report.get("manifest_entries", 0),
        "source_file_count": report.get("source_file_count", 0),
        "failures": len(report.get("failures", [])),
    }, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
