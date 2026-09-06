#!/usr/bin/env python3
"""Copy an explicit source allowlist into a new clean snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--allowlist",
        default="verification/source-allowlist-0.2.3.json",
        help="allowlist path relative to the source root",
    )
    parser.add_argument(
        "--reject-symlinks",
        action="store_true",
        help="fail if a selected source root contains any symbolic link",
    )
    args = parser.parse_args()
    source = args.source.resolve()
    destination = args.destination.resolve()
    if destination.exists():
        raise SystemExit(f"snapshot destination already exists: {destination}")
    allowlist_path = (source / args.allowlist).resolve()
    try:
        allowlist_relative = allowlist_path.relative_to(source)
    except ValueError as exc:
        raise SystemExit("allowlist must stay inside the source root") from exc
    if not allowlist_path.is_file() or allowlist_path.is_symlink():
        raise SystemExit(f"source allowlist is absent or unsafe: {allowlist_relative}")
    allowlist = json.loads(allowlist_path.read_text(encoding="utf-8"))
    excluded = set(allowlist["excluded_parts"])
    selected: list[Path] = []
    for relative in allowlist["root_files"]:
        path = source / relative
        if not path.is_file() or path.is_symlink():
            raise SystemExit(f"allowlisted root file is absent or unsafe: {relative}")
        selected.append(path)
    for relative in allowlist["roots"]:
        root = source / relative
        if not root.is_dir() or root.is_symlink():
            raise SystemExit(f"allowlisted source root is absent: {relative}")
        if args.reject_symlinks:
            links = [path for path in root.rglob("*") if path.is_symlink()]
            if links:
                raise SystemExit(
                    "symbolic links are forbidden in a release source snapshot: "
                    + ", ".join(str(path.relative_to(source)) for path in links[:10])
                )
        selected.extend(
            path for path in root.rglob("*")
            if path.is_file() and not path.is_symlink()
            and not excluded.intersection(path.relative_to(source).parts)
            and not any(part.endswith(".egg-info") for part in path.relative_to(source).parts)
        )
    selected = sorted(set(selected), key=lambda path: str(path.relative_to(source)))
    destination.mkdir(parents=True)
    files: dict[str, dict[str, object]] = {}
    for path in selected:
        relative = path.relative_to(source)
        if excluded.intersection(relative.parts):
            raise SystemExit(f"forbidden path reached snapshot selection: {relative}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        mode = stat.S_IMODE(os.lstat(target).st_mode)
        files[str(relative)] = {
            "bytes": target.stat().st_size,
            "sha256": sha256(target),
            "mode": f"{mode:04o}",
        }
    digest = hashlib.sha256(
        "".join(f"{name}\0{item['sha256']}\0{item['bytes']}\n" for name, item in files.items()).encode()
    ).hexdigest()
    forbidden_present = [
        str(path.relative_to(destination))
        for path in destination.rglob("*")
        if excluded.intersection(path.relative_to(destination).parts)
    ]
    report = {
        "schema_version": "nndv-clean-source-snapshot-2",
        "release": allowlist.get("release", "unknown"),
        "source": str(source),
        "snapshot": str(destination),
        "allowlist": str(allowlist_relative),
        "allowlist_sha256": sha256(allowlist_path),
        "source_tree_digest": digest,
        "files": files,
        "file_count": len(files),
        "forbidden_paths": forbidden_present,
        "passed": not forbidden_present,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"source_tree_digest": digest, "files": len(files), "passed": not forbidden_present}, sort_keys=True))
    if forbidden_present:
        raise SystemExit(f"forbidden files entered clean snapshot: {forbidden_present}")


if __name__ == "__main__":
    main()
