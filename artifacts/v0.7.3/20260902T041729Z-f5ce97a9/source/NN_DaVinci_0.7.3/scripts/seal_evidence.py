#!/usr/bin/env python3
"""Write an unambiguous, complete SHA-256 inventory after evidence closes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unicodedata


CHECKSUM_NAME = "SHA256SUMS"
SCHEMA_VERSION = "nndv-sha256-manifest-2"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _inventory(root: Path) -> list[Path]:
    """Return every regular file except the root manifest; reject ambiguity."""
    files: list[Path] = []
    normalized_names: dict[str, str] = {}
    pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                relative = path.relative_to(root).as_posix()
                mode = entry.stat(follow_symlinks=False).st_mode
                if stat.S_ISLNK(mode):
                    raise ValueError(f"sealed evidence may not contain symlinks: {relative}")
                normalized = unicodedata.normalize("NFC", relative)
                prior = normalized_names.setdefault(normalized, relative)
                if prior != relative:
                    raise ValueError(f"Unicode-normalized path collision: {prior!r} and {relative!r}")
                if stat.S_ISDIR(mode):
                    pending.append(path)
                elif stat.S_ISREG(mode):
                    if relative != CHECKSUM_NAME:
                        files.append(path)
                else:
                    raise ValueError(f"sealed evidence contains a non-regular object: {relative}")
    return sorted(files, key=lambda item: item.relative_to(root).as_posix())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence_root", type=Path)
    args = parser.parse_args()
    supplied_root = args.evidence_root
    if supplied_root.is_symlink():
        raise SystemExit(f"evidence root may not be a symlink: {supplied_root}")
    root = supplied_root.resolve()
    if not root.is_dir():
        raise SystemExit(f"evidence root is absent: {root}")
    try:
        files = _inventory(root)
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    document = {
        "schema_version": SCHEMA_VERSION,
        "algorithm": "sha256",
        "checksum_excludes": [CHECKSUM_NAME],
        "entries": [
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256(path),
                "size": path.stat().st_size,
            }
            for path in files
        ],
    }
    payload = (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=root.parent, prefix=f".{root.name}-sha256-", delete=False
        ) as stream:
            temporary_name = stream.name
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, root / CHECKSUM_NAME)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
    print(f"sealed_files={len(files)} checksum_sha256={sha256(root / CHECKSUM_NAME)} schema={SCHEMA_VERSION}")


if __name__ == "__main__":
    main()
