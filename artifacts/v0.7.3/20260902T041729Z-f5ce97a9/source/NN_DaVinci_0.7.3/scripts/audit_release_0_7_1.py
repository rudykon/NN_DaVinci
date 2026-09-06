#!/usr/bin/env python3
"""Audit the user-visible 0.7.1 release contract without trusting artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import tomllib
from typing import Any

import nn_davinci
from nn_davinci import __version__
from nn_davinci.model_scene import ARCHITECTURE_FAMILIES, scene_template
from nn_davinci.project import PROJECT_VERSION
from nn_davinci.scene_ir import SCENE_IR_VERSION, Scene


RELEASE = "0.7.1 — 3D Publication Quality & UX Completion"
REQUIRED_DOCS = (
    "README.md",
    "docs/REQUIREMENTS.md",
    "docs/ARCHITECTURE.md",
    "docs/FIGURE_IR.md",
    "docs/SCENE_IR.md",
    "docs/FIGURE_STUDIO.md",
    "docs/SCENE_STUDIO.md",
    "docs/UX_DESIGN_SYSTEM.md",
    "docs/RESPONSIVE_TOOLBAR.md",
    "docs/COMPATIBILITY.md",
    "docs/KNOWN_LIMITATIONS.md",
    "docs/RELEASE_NOTES_0.7.1.md",
    "docs/FEATURE_COMPLETION_MATRIX_0.7.1.md",
    "docs/PUBLICATION_VISUAL_REPORT_0.7.1.md",
    "docs/UX_COMPLETION_REPORT_0.7.1.md",
)
RELEASE_DOCS = {
    "README.md",
    "docs/KNOWN_LIMITATIONS.md",
    "docs/RELEASE_NOTES_0.7.1.md",
    "docs/FEATURE_COMPLETION_MATRIX_0.7.1.md",
    "docs/PUBLICATION_VISUAL_REPORT_0.7.1.md",
    "docs/UX_COMPLETION_REPORT_0.7.1.md",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.project_root.resolve()
    failures: list[str] = []
    checks: dict[str, Any] = {}

    loaded_package = Path(nn_davinci.__file__).resolve()
    expected_package = (root / "src" / "nn_davinci").resolve()
    checks["audited_package"] = {"loaded": str(loaded_package), "expected_root": str(expected_package)}
    if loaded_package.parent != expected_package:
        failures.append("release audit imported nn_davinci from outside the requested project root")

    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((root / "package-lock.json").read_text(encoding="utf-8"))
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    versions = {
        "python": __version__,
        "pyproject": project["project"]["version"],
        "package": package["version"],
        "package_lock": lock["version"],
        "package_lock_root": lock["packages"][""]["version"],
        "project_schema": PROJECT_VERSION,
        "scene_ir": SCENE_IR_VERSION,
    }
    if set(versions.values()) != {"0.7.1", "1.4", "1.0"} or any(
        versions[key] != "0.7.1"
        for key in ("python", "pyproject", "package", "package_lock", "package_lock_root")
    ):
        failures.append(f"release versions disagree: {versions}")
    checks["versions"] = versions

    missing_docs = [name for name in REQUIRED_DOCS if not (root / name).is_file()]
    stale_docs: list[str] = []
    for name in REQUIRED_DOCS:
        path = root / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if name in RELEASE_DOCS and "0.7.1" not in text:
            stale_docs.append(name)
    if missing_docs:
        failures.append(f"required 0.7.1 docs are missing: {missing_docs}")
    if stale_docs:
        failures.append(f"required docs do not identify 0.7.1: {stale_docs}")
    checks["docs"] = {"required": len(REQUIRED_DOCS), "missing": missing_docs, "stale": stale_docs}

    schema_results: dict[str, Any] = {}
    schema_names = ("figure-ir-1.0.schema.json", "scene-ir-1.0.schema.json", "project-1.4.schema.json")
    for name in schema_names:
        path = root / "schemas" / name
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            failures.append(f"schema {name} is unreadable: {exc}")
            continue
        schema_results[name] = {"id": document.get("$id"), "title": document.get("title")}
        if not (
            document.get("$schema") == "https://json-schema.org/draft/2020-12/schema"
            and document.get("$id") == f"https://nn-davinci.local/schemas/{name}"
            and document.get("type") == "object"
            and isinstance(document.get("title"), str)
            and document.get("title")
        ):
            failures.append(f"schema {name} lacks its fixed 2020-12 identity or object contract")
    checks["schemas"] = schema_results

    template_results: dict[str, Any] = {}
    for family in ARCHITECTURE_FAMILIES:
        generated = scene_template(family)
        expected_digest = generated.digest()
        public = root / "templates" / "scene_studio" / f"{family}.scene.json"
        packaged = root / "src" / "nn_davinci" / "scene_templates" / f"{family}.scene.json"
        observed: dict[str, Any] = {}
        for label, path in (("public", public), ("packaged", packaged)):
            try:
                scene = Scene.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
                failures.append(f"{family} {label} Scene template is invalid: {exc}")
                continue
            observed[label] = scene.digest()
            if scene.digest() != expected_digest:
                failures.append(f"{family} {label} Scene template differs from its factory")
        template_results[family] = {"factory_digest": expected_digest, **observed}
    checks["scene_templates"] = template_results

    web_root = root / "src" / "nn_davinci" / "web"
    web_files = sorted([
        *web_root.glob("*.js"),
        *web_root.glob("*.css"),
        *web_root.glob("*.html"),
    ])
    remote_references: list[str] = []
    blocking_dialogs: list[str] = []
    for path in web_files:
        text = path.read_text(encoding="utf-8")
        if re.search(r"(?:src|href)\s*=\s*[\"']https?://", text, re.IGNORECASE):
            remote_references.append(path.name)
        if path.suffix == ".css" and re.search(r"url\(\s*[\"']?https?://", text, re.IGNORECASE):
            remote_references.append(path.name)
        if path.suffix == ".js" and re.search(
            r"(?:fetch\s*\(|import\s*\(|new\s+WebSocket\s*\()[^\n]{0,80}[\"'](?:https?|wss?)://",
            text,
            re.IGNORECASE,
        ):
            remote_references.append(path.name)
        if re.search(r"\b(?:window\.)?(?:prompt|alert|confirm)\s*\(", text):
            blocking_dialogs.append(path.name)
    remote_references = sorted(set(remote_references))
    if remote_references:
        failures.append(f"Web package contains runtime remote assets: {remote_references}")
    if blocking_dialogs:
        failures.append(f"Web package uses browser blocking dialogs: {blocking_dialogs}")
    index = (web_root / "index.html").read_text(encoding="utf-8")
    checks["web"] = {
        "files": len(web_files),
        "runtime_remote_assets": remote_references,
        "blocking_dialogs": blocking_dialogs,
        "scene_canvas": 'id="scene-webgl"' in index,
        "cpu_fallback": 'id="scene-cpu-fallback"' in index,
        "command_palette": 'id="command-palette"' in index,
        "scene_gizmo": 'id="scene-transform-gizmo"' in index,
        "scene_batch": 'id="scene-batch-export"' in index,
        "scene_density": 'id="scene-content-density"' in index,
        "scene_tree_search": 'id="scene-tree-search"' in index,
        "project_schema_1_4": 'data-project-schema="1.4"' in index,
    }
    if not all(
        checks["web"][key]
        for key in (
            "scene_canvas",
            "cpu_fallback",
            "command_palette",
            "scene_gizmo",
            "scene_batch",
            "scene_density",
            "scene_tree_search",
            "project_schema_1_4",
        )
    ):
        failures.append("Web shell lacks one or more required Scene/command/schema surfaces")

    baseline = root / "verification" / "fixtures" / "python-test-ids-0.7.0.txt"
    ids = baseline.read_text(encoding="utf-8").splitlines()
    baseline_sha = hashlib.sha256(baseline.read_bytes()).hexdigest()
    checks["baseline_tests"] = {"count": len(ids), "unique": len(set(ids)), "sha256": baseline_sha}
    if (
        len(ids) != len(set(ids))
        or len(ids) != 328
        or baseline_sha != "a66646fea24b51f1d39432adac615de612186791300c1bec4296731b0ee83dac"
    ):
        failures.append("authoritative 0.7.0 test-ID fixture identity changed")

    report = {
        "schema_version": "nndv-0.7.1-release-audit-1",
        "release": RELEASE,
        "status": "PASS" if not failures else "FAIL",
        "checks": checks,
        "failures": failures,
        "human_participants": 0,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("NNDV_071_RELEASE_AUDIT=" + json.dumps({"status": report["status"], "failures": len(failures)}, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
