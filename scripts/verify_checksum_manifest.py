#!/usr/bin/env python3
"""Independently verify a sealed directory's complete JSON SHA-256 inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
from typing import Any


CHECKSUM_NAME = "SHA256SUMS"
SCHEMA_VERSION = "nndv-sha256-manifest-2"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_relative(value: Any) -> str:
    if not isinstance(value, str) or not value or "\0" in value:
        raise ValueError("manifest path must be a non-empty string without NUL")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe manifest path: {value!r}")
    if path.as_posix() != value or value == CHECKSUM_NAME:
        raise ValueError(f"non-canonical or self-referential manifest path: {value!r}")
    return value


def _actual_files(root: Path) -> tuple[dict[str, Path], list[str]]:
    actual: dict[str, Path] = {}
    invalid: list[str] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            invalid.append(f"{directory}: {exc}")
            continue
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            mode = entry.stat(follow_symlinks=False).st_mode
            if stat.S_ISLNK(mode):
                invalid.append(f"symlink:{relative}")
            elif stat.S_ISDIR(mode):
                pending.append(path)
            elif stat.S_ISREG(mode):
                if relative != CHECKSUM_NAME:
                    actual[relative] = path
            else:
                invalid.append(f"non-regular:{relative}")
    return actual, sorted(invalid)


def verify(root: Path) -> dict[str, object]:
    checksum = root / CHECKSUM_NAME
    malformed: list[str] = []
    declared: dict[str, dict[str, Any]] = {}
    try:
        document = json.loads(checksum.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        document = {}
        malformed.append(f"cannot parse checksum manifest: {exc}")
    if not isinstance(document, dict) or document.get("schema_version") != SCHEMA_VERSION:
        malformed.append("unsupported checksum manifest schema")
    if not isinstance(document, dict) or document.get("algorithm") != "sha256" or document.get("checksum_excludes") != [CHECKSUM_NAME]:
        malformed.append("invalid checksum algorithm or exclusion policy")
    entries = document.get("entries", []) if isinstance(document, dict) else []
    if not isinstance(entries, list):
        malformed.append("entries must be an array")
        entries = []
    for index, entry in enumerate(entries):
        try:
            if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "size"}:
                raise ValueError("entry keys must be path, sha256, size")
            relative = _safe_relative(entry["path"])
            digest = entry["sha256"]
            size = entry["size"]
            if relative in declared:
                raise ValueError(f"duplicate path {relative!r}")
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise ValueError("size must be a non-negative integer")
            declared[relative] = entry
        except (KeyError, ValueError) as exc:
            malformed.append(f"entry[{index}]: {exc}")
    actual, invalid_objects = _actual_files(root)
    malformed.extend(invalid_objects)
    missing = sorted(set(declared) - set(actual))
    extra = sorted(set(actual) - set(declared))
    mismatch: list[str] = []
    size_mismatch: list[str] = []
    for relative in sorted(set(declared) & set(actual)):
        path = actual[relative]
        if path.stat().st_size != declared[relative]["size"]:
            size_mismatch.append(relative)
        if sha256(path) != declared[relative]["sha256"]:
            mismatch.append(relative)
    return {
        "schema_version": SCHEMA_VERSION,
        "declared_files": len(declared),
        "actual_files": len(actual),
        "missing": missing,
        "extra": extra,
        "mismatch": mismatch,
        "size_mismatch": size_mismatch,
        "malformed": malformed,
        "passed": not (missing or extra or mismatch or size_mismatch or malformed),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence_root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.evidence_root
    report = verify(root.resolve()) if not root.is_symlink() else {
        "schema_version": SCHEMA_VERSION, "missing": [], "extra": [], "mismatch": [],
        "size_mismatch": [], "malformed": ["evidence root is a symlink"], "passed": False,
    }
    if args.output:
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    if not report["passed"]:
        raise SystemExit("sealed checksum replay failed")


if __name__ == "__main__":
    main()
