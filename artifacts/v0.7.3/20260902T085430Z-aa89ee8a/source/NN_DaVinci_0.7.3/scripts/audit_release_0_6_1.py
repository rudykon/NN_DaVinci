#!/usr/bin/env python3
"""Audit the 0.6.1 identity, publication docs, schemas, and fixed assets."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import tomllib
from typing import Any

import nn_davinci
from nn_davinci.figure_templates import TEMPLATE_SPECS, instantiate_template


VERSION = "0.6.1"
RELEASE = "0.6.1 Beta — Publication Fidelity & Model-to-Figure Completion"
REQUIRED_DOCS = (
    "README.md",
    "docs/FIGURE_IR.md",
    "docs/TENSOR_GEOMETRY.md",
    "docs/STRUCTURE_LENS.md",
    "docs/FIGURE_STUDIO.md",
    "docs/PROJECT_SCHEMA_1.3.md",
    "docs/RELEASE_NOTES_0.6.1.md",
    "docs/PUBLICATION_ORACLE.md",
    "docs/UNIT_SYSTEM.md",
    "docs/KNOWN_LIMITATIONS.md",
    "docs/COMPATIBILITY.md",
)
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path(__file__).parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.project_root.resolve()
    failures: list[str] = []

    package = _load_object(root / "package.json")
    lock = _load_object(root / "package-lock.json")
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    identities = {
        "python_package": nn_davinci.__version__,
        "pyproject": pyproject["project"]["version"],
        "npm_package": package.get("version"),
        "npm_lock": lock.get("version"),
        "npm_lock_root": lock.get("packages", {}).get("", {}).get("version"),
    }
    for surface, version in identities.items():
        if version != VERSION:
            failures.append(f"{surface} identifies {version!r}, expected {VERSION!r}")

    missing_docs = [name for name in REQUIRED_DOCS if not (root / name).is_file()]
    failures.extend(f"required document missing: {name}" for name in missing_docs)
    broken_links: list[dict[str, str]] = []
    for name in REQUIRED_DOCS:
        path = root / name
        if not path.is_file():
            continue
        for target in MARKDOWN_LINK.findall(path.read_text(encoding="utf-8")):
            target = target.strip().split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            candidate = (path.parent / target).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                broken_links.append({"document": name, "target": target})
                continue
            if not candidate.exists():
                broken_links.append({"document": name, "target": target})
    failures.extend(
        f"broken or escaping Markdown link: {item['document']} -> {item['target']}"
        for item in broken_links
    )

    schema_paths = ("schemas/figure-ir-1.0.schema.json", "schemas/project-1.3.schema.json")
    schemas: dict[str, dict[str, Any]] = {}
    for relative in schema_paths:
        try:
            schemas[relative] = _load_object(root / relative)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            failures.append(f"invalid required schema {relative}: {exc}")
    if not schemas.get(schema_paths[0], {}).get("$id", "").endswith("figure-ir-1.0.schema.json"):
        failures.append("Figure IR schema does not carry its 1.0 identity")
    if not schemas.get(schema_paths[1], {}).get("$id", "").endswith("project-1.3.schema.json"):
        failures.append("project schema does not carry its 1.3 identity")

    templates: dict[str, Any] = {}
    for spec in TEMPLATE_SPECS:
        public = root / "templates" / "figure_studio" / f"{spec.slug}.nndv.json"
        packaged = root / "src" / "nn_davinci" / "figure_templates" / f"{spec.slug}.nndv.json"
        if not public.is_file() or not packaged.is_file():
            failures.append(f"template copies missing: {spec.slug}")
            continue
        if public.read_bytes() != packaged.read_bytes():
            failures.append(f"template copies differ: {spec.slug}")
        _, figure = instantiate_template(spec.slug)
        figure.validate()
        modes = sorted({panel.mode for panel in figure.iter_panels()})
        templates[spec.slug] = {
            "public_sha256": _sha256(public),
            "packaged_sha256": _sha256(packaged),
            "panels": len(list(figure.iter_panels())),
            "modes": modes,
        }
        if modes != ["schematic", "tensor-geometry"]:
            failures.append(f"template lacks both required modes: {spec.slug}")
    if len(TEMPLATE_SPECS) != 7:
        failures.append(f"expected seven publication templates, found {len(TEMPLATE_SPECS)}")

    expectations_path = root / "verification" / "fixtures" / "figure-svg-oracle-expectations.json"
    try:
        expectations = _load_object(expectations_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        failures.append(f"invalid Figure SVG oracle expectations: {exc}")
        expectations = {}
    fixture_count = len(expectations.get("fixtures", {}))
    if fixture_count != 21:
        failures.append(f"Figure SVG oracle truth suite has {fixture_count} fixtures, expected 21")
    for relative in (
        "scripts/figure_svg_oracle.mjs",
        "scripts/svg_path_flatten.js",
        "scripts/generate_figure_svg_oracle_fixtures.py",
        "scripts/validate_figure_svg_oracle_fixtures.py",
    ):
        if not (root / relative).is_file():
            failures.append(f"strict Figure SVG oracle component missing: {relative}")

    human = _load_object(root / "docs" / "trial" / "human-trial-status.json")
    human_metrics = human.get("human_results", {})
    human_boundary = {
        "build_version": human.get("build_version"),
        "status": human.get("status"),
        "participants": human.get("participants"),
        "completed_sessions": human.get("completed_sessions"),
        "all_metrics_null": bool(human_metrics) and all(value is None for value in human_metrics.values()),
        "automation_counts_as_participants": human.get("automated_runs_count_as_participants"),
    }
    if not (
        human_boundary["participants"] == 0
        and human_boundary["completed_sessions"] == 0
        and human_boundary["all_metrics_null"] is True
        and human_boundary["automation_counts_as_participants"] is False
    ):
        failures.append("human-evidence boundary is not an honest zero-participant/null-metric state")

    report = {
        "schema_version": "nndv-0.6.1-release-audit-1",
        "release": RELEASE,
        "status": "PASS" if not failures else "FAIL",
        "checks": {
            "version_surfaces": identities,
            "required_documents": {"checked": len(REQUIRED_DOCS), "missing": missing_docs},
            "markdown_links": {"broken": broken_links},
            "schemas": {name: {"sha256": _sha256(root / name)} for name in schemas},
            "templates": templates,
            "strict_oracle": {
                "expectations_sha256": _sha256(expectations_path) if expectations_path.is_file() else None,
                "fixture_count": fixture_count,
            },
            "human_evidence_boundary": human_boundary,
        },
        "failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("NNDV_061_RELEASE_AUDIT=" + json.dumps({"status": report["status"], "failures": len(failures)}, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
