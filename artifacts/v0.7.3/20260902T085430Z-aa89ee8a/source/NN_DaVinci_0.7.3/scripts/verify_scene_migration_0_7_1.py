#!/usr/bin/env python3
"""Verify Project 1.3 to 1.4 migration without inventing Scene evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from nn_davinci.figure_ir import FigureIR
from nn_davinci.ir import GraphIR
from nn_davinci.project import PROJECT_VERSION, Project


RELEASE = "0.7.1 — 3D Publication Quality & UX Completion"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def document_digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def verify_case(path: Path) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    source = load_object(path)
    if source.get("project_version") != "1.3":
        failures.append("source is not Project 1.3")
    source_graph = GraphIR.from_dict(source.get("graph", {}))
    source_figure = FigureIR.from_dict(source.get("figure_ir", {}))
    source_graph_digest = document_digest(source_graph.to_dict())
    source_figure_digest = source_figure.digest()
    migrated = Project.from_dict(source)
    scene = migrated.persisted_scene()
    roundtrip = Project.from_dict(migrated.to_dict())
    migration_records = migrated.environment.get("project_schema_migrations", [])
    scene_records = scene.migrations
    objects = list(scene.iter_objects())

    checks = {
        "project_1_4": migrated.project_version == PROJECT_VERSION == "1.4",
        "graph_digest_unchanged": document_digest(migrated.graph.to_dict()) == source_graph_digest,
        "figure_digest_unchanged": FigureIR.from_dict(migrated.figure_ir).digest() == source_figure_digest,
        "scene_ir_1_0": scene.schema_version == "1.0",
        "scene_has_zero_objects": not objects,
        "scene_has_zero_layers": not scene.layers,
        "scene_selection_empty": scene.selection_ids == [],
        "scene_marked_empty": scene.metadata.get("empty") is True,
        "geometry_not_inferred": scene.metadata.get("model_geometry_inferred") is False,
        "semantics_not_inferred": scene.metadata.get("model_semantics_inferred") is False,
        "provenance_not_inferred": scene.metadata.get("provenance_inferred") is False,
        "project_migration_recorded": any(
            isinstance(item, dict) and item.get("from") == "1.3" and item.get("to") == "1.4"
            for item in migration_records
        ),
        "scene_migration_recorded": any(
            isinstance(item, dict) and item.get("from") == "project-1.3" and item.get("to") == "1.0"
            for item in scene_records
        ),
        "roundtrip_stable": roundtrip.to_dict() == migrated.to_dict(),
    }
    for name, passed in checks.items():
        if not passed:
            failures.append(name)
    return {
        "case": path.stem,
        "source": str(path),
        "source_sha256": sha256(path),
        "source_project_version": source.get("project_version"),
        "migrated_project_version": migrated.project_version,
        "scene_ir_version": scene.schema_version,
        "graph_digest_before": source_graph_digest,
        "graph_digest_after": document_digest(migrated.graph.to_dict()),
        "figure_digest_before": source_figure_digest,
        "figure_digest_after": FigureIR.from_dict(migrated.figure_ir).digest(),
        "scene_objects": len(objects),
        "checks": checks,
        "failures": failures,
    }, failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    project_root = args.project_root.resolve()
    template_root = project_root / "src" / "nn_davinci" / "figure_templates"
    paths = sorted(template_root.glob("*.nndv.json"))
    cases: list[dict[str, Any]] = []
    failures: list[str] = []
    if len(paths) != 7:
        failures.append(f"expected 7 Project 1.3 templates, found {len(paths)}")
    for path in paths:
        try:
            case, case_failures = verify_case(path)
        except Exception as exc:  # the report must preserve actionable diagnostics
            failures.append(f"{path.name}: {type(exc).__name__}: {exc}")
            continue
        cases.append(case)
        failures.extend(f"{path.name}: {failure}" for failure in case_failures)
    report: dict[str, Any] = {
        "schema_version": "nndv-0.7.1-project-scene-migration-1",
        "release": RELEASE,
        "status": "PASS" if not failures else "FAIL",
        "source_schema": "Project 1.3",
        "target_schema": "Project 1.4 + Scene IR 1.0",
        "cases": cases,
        "counts": {
            "expected": 7,
            "checked": len(cases),
            "passed": sum(not case["failures"] for case in cases),
            "failed": len(failures),
        },
        "migration_contract": {
            "graph_ir_mutated": False,
            "figure_ir_mutated": False,
            "scene_geometry_inferred": False,
            "model_semantics_inferred": False,
            "provenance_inferred": False,
        },
        "failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "NNDV_071_MIGRATION="
        + json.dumps({"status": report["status"], **report["counts"]}, sort_keys=True)
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
