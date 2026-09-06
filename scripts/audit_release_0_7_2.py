#!/usr/bin/env python3
"""Audit the user-visible 0.7.2 scientific-fidelity contract."""

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
from nn_davinci.architecture_evidence import ARCHITECTURE_EVIDENCE_VERSION
from nn_davinci.model_scene import ARCHITECTURE_FAMILIES, scene_template
from nn_davinci.project import PROJECT_VERSION
from nn_davinci.scene_ir import SCENE_IR_VERSION, Scene


RELEASE = "0.7.2 — Scientific Fidelity & Semantic Scene Hotfix"
REQUIRED_DOCS = (
    "README.md",
    "docs/REQUIREMENTS.md",
    "docs/ARCHITECTURE.md",
    "docs/SCENE_IR.md",
    "docs/SCENE_STUDIO.md",
    "docs/COMPATIBILITY.md",
    "docs/KNOWN_LIMITATIONS.md",
    "docs/RELEASE_NOTES_0.7.2.md",
    "docs/FEATURE_COMPLETION_MATRIX_0.7.2.md",
    "docs/SCIENTIFIC_FIDELITY_REPORT_0.7.2.md",
    "docs/SEMANTIC_PARITY_REPORT_0.7.2.md",
    "docs/PDF_FONT_REPORT_0.7.2.md",
)
RELEASE_DOCS = {
    "README.md",
    "docs/KNOWN_LIMITATIONS.md",
    "docs/RELEASE_NOTES_0.7.2.md",
    "docs/FEATURE_COMPLETION_MATRIX_0.7.2.md",
    "docs/SCIENTIFIC_FIDELITY_REPORT_0.7.2.md",
    "docs/SEMANTIC_PARITY_REPORT_0.7.2.md",
    "docs/PDF_FONT_REPORT_0.7.2.md",
}
BASELINE_COUNT = 342
BASELINE_SHA256 = "8d0c621a059f2d9a3fe4d0dadc2c127a7d56c236da98ae3048df131670676f49"


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
    checks["audited_package"] = {
        "loaded": str(loaded_package),
        "expected_root": str(expected_package),
    }
    if loaded_package.parent != expected_package:
        failures.append("release audit imported nn_davinci outside the clean snapshot")

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
        "architecture_evidence": ARCHITECTURE_EVIDENCE_VERSION,
    }
    checks["versions"] = versions
    if (
        any(
            versions[key] != "0.7.2"
            for key in (
                "python",
                "pyproject",
                "package",
                "package_lock",
                "package_lock_root",
            )
        )
        or versions["project_schema"] != "1.4"
        or versions["scene_ir"] != "1.0"
    ):
        failures.append(f"release versions disagree: {versions}")

    missing_docs = [name for name in REQUIRED_DOCS if not (root / name).is_file()]
    stale_docs = [name for name in RELEASE_DOCS if (root / name).is_file() and "0.7.2" not in (root / name).read_text(encoding="utf-8")]
    checks["docs"] = {"required": len(REQUIRED_DOCS), "missing": missing_docs, "stale": stale_docs}
    if missing_docs:
        failures.append(f"required 0.7.2 docs are missing: {missing_docs}")
    if stale_docs:
        failures.append(f"release docs do not identify 0.7.2: {stale_docs}")

    template_results: dict[str, Any] = {}
    for family in ARCHITECTURE_FAMILIES:
        expected = scene_template(family).digest()
        observed: dict[str, str] = {}
        for label, path in (
            ("public", root / "templates" / "scene_studio" / f"{family}.scene.json"),
            ("packaged", root / "src" / "nn_davinci" / "scene_templates" / f"{family}.scene.json"),
        ):
            try:
                digest = Scene.from_dict(json.loads(path.read_text(encoding="utf-8"))).digest()
            except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
                failures.append(f"{family} {label} Scene template is invalid: {exc}")
                continue
            observed[label] = digest
            if digest != expected:
                failures.append(f"{family} {label} Scene template differs from its factory")
        template_results[family] = {"factory": expected, **observed}
    checks["scene_templates"] = template_results

    web_root = root / "src" / "nn_davinci" / "web"
    web_files = sorted([*web_root.glob("*.js"), *web_root.glob("*.css"), *web_root.glob("*.html")])
    remote_assets: list[str] = []
    blocking_dialogs: list[str] = []
    for path in web_files:
        text = path.read_text(encoding="utf-8")
        if re.search(r"(?:src|href)\s*=\s*[\"']https?://", text, re.IGNORECASE):
            remote_assets.append(path.name)
        if re.search(r"\b(?:window\.)?(?:prompt|alert|confirm)\s*\(", text):
            blocking_dialogs.append(path.name)
    app = (web_root / "app.js").read_text(encoding="utf-8")
    renderer = (web_root / "scene-renderer.js").read_text(encoding="utf-8")
    checks["web"] = {
        "runtime_remote_assets": sorted(set(remote_assets)),
        "blocking_dialogs": sorted(set(blocking_dialogs)),
        "initial_auto_frame": "initial-auto-frame" in app,
        "camera_fit_uses_scene_bounds": "frameObjects(ids = [])" in renderer,
    }
    if remote_assets or blocking_dialogs or not all(checks["web"][name] for name in ("initial_auto_frame", "camera_fit_uses_scene_bounds")):
        failures.append("Web shell violates the offline, non-blocking, or auto-frame contract")

    baseline = root / "verification" / "fixtures" / "python-test-ids-0.7.1.txt"
    ids = baseline.read_text(encoding="utf-8").splitlines()
    baseline_sha = hashlib.sha256(baseline.read_bytes()).hexdigest()
    checks["baseline_tests"] = {"count": len(ids), "unique": len(set(ids)), "sha256": baseline_sha}
    if len(ids) != len(set(ids)) or len(ids) != BASELINE_COUNT or baseline_sha != BASELINE_SHA256:
        failures.append("authoritative 0.7.1 test-ID fixture identity changed")

    font_root = root / "src" / "nn_davinci" / "assets" / "fonts"
    font_paths = (
        font_root / "NotoSans-Regular.ttf",
        font_root / "DroidSansFallbackFull.ttf",
        font_root / "NotoSansMath-Regular.ttf",
        font_root / "licenses" / "Noto-OFL-1.1.txt",
        font_root / "licenses" / "Droid-Apache-2.0.txt",
    )
    checks["embedded_fonts"] = [str(path.relative_to(root)) for path in font_paths if path.is_file()]
    if any(not path.is_file() or path.stat().st_size == 0 for path in font_paths):
        failures.append("packaged Scene PDF fonts or their licenses are missing")

    report = {
        "schema_version": "nndv-0.7.2-release-audit-1",
        "release": RELEASE,
        "status": "PASS" if not failures else "FAIL",
        "checks": checks,
        "failures": failures,
        "human_participants": 0,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("NNDV_072_RELEASE_AUDIT=" + json.dumps({"status": report["status"], "failures": len(failures)}))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
