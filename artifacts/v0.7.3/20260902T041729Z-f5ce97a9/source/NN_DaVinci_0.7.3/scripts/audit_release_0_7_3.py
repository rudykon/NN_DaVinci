#!/usr/bin/env python3
"""Audit 0.7.3 version hygiene, documentation, and production-path boundaries."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import tomllib


RELEASE = "0.7.3 — Reader-Visible Scientific Completeness & Generalization Hotfix"
DOCS = (
    "docs/RELEASE_NOTES_0.7.3.md",
    "docs/SEMANTIC_PRESENTATION_COMPLETENESS_0.7.3.md",
    "docs/GENERALIZATION_REPORT_0.7.3.md",
    "docs/SERVICE_LIFECYCLE_0.7.3.md",
    "docs/KNOWN_LIMITATIONS.md",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.project_root.resolve(strict=True)
    failures: list[str] = []
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((root / "package-lock.json").read_text(encoding="utf-8"))
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version_text = (root / "src/nn_davinci/version.py").read_text(encoding="utf-8")
    versions = {
        "pyproject": pyproject.get("project", {}).get("version"),
        "package": package.get("version"),
        "package_lock": lock.get("version"),
        "package_lock_root": lock.get("packages", {}).get("", {}).get("version"),
        "python": "0.7.3" if '__version__ = "0.7.3"' in version_text else None,
    }
    for location, version in versions.items():
        if version != "0.7.3":
            failures.append(f"stale-current-version: {location}={version!r}")
    for relative in DOCS:
        path = root / relative
        if path.is_symlink() or not path.is_file() or path.stat().st_size < 80:
            failures.append(f"missing or undersized release documentation: {relative}")
    current_files = [
        *sorted((root / "scripts").glob("*0_7_3*")),
        *sorted((root / "scripts").glob("*0.7.3*")),
        *[root / relative for relative in DOCS[:4]],
    ]
    deprecated_fields: list[str] = []
    for path in set(current_files):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if (
            "parent_0_7_0" in text
            and path.name not in {"audit_release_0_7_3.py", "benchmark_scene_studio_0_7_3.py"}
        ):
            deprecated_fields.append(str(path.relative_to(root)))
    if deprecated_fields:
        failures.append("deprecated parent_0_7_0 field appears in current files: " + ", ".join(sorted(deprecated_fields)))
    graph_source = (root / "src/nn_davinci/architecture_role_graph.py").read_text(encoding="utf-8")
    production_sources = "\n".join(
        (root / relative).read_text(encoding="utf-8")
        for relative in ("src/nn_davinci/model_figure.py", "src/nn_davinci/model_scene.py")
    )
    if "corpus_key" in graph_source:
        failures.append("generic role graph reads corpus_key")
    dispatch = "_architecture_publication_projection("
    legacy_dispatch = "or _legacy_corpus_publication_projection("
    if (
        dispatch not in production_sources
        or legacy_dispatch not in production_sources
        or production_sources.index(dispatch) > production_sources.index(legacy_dispatch)
        or "stage/paper production projection is exclusively" not in production_sources
    ):
        failures.append("generic role-graph projection is not the primary stage/paper production path")

    report = {
        "schema_version": "nndv-0.7.3-release-audit-1",
        "release": RELEASE,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not failures else "FAIL",
        "versions": versions,
        "stale_current_version_blocker": "PASS" if not any("stale-current-version" in item for item in failures) else "FAIL",
        "parent_field_hygiene": "PASS" if not deprecated_fields else "FAIL",
        "generic_role_graph_production_path": "PASS" if not any("role-graph" in item or "corpus_key" in item for item in failures) else "FAIL",
        "documentation": list(DOCS),
        "human_participants": 0,
        "git_operations": False,
        "uploaded_or_published": False,
        "failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "failures": len(failures)}, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
