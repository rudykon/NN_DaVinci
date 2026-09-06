#!/usr/bin/env python3
"""Run the Scene benchmark and compare every required metric with pinned 0.7.2."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any


RELEASE = "0.7.3 — Reader-Visible Scientific Completeness & Generalization Hotfix"


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _rename_historical_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key).replace("parent_0_7_0", "parent_0_7_2").replace("baseline_0_7_0", "baseline_0_7_2"): _rename_historical_fields(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_rename_historical_fields(item) for item in value]
    if isinstance(value, str):
        return value.replace("from 0.7.0", "from 0.7.2")
    return value


def _metric(report: dict[str, Any], path: tuple[str, ...]) -> float:
    value: Any = report
    for key in path:
        value = value[key]
    return float(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--baseline-scene-report", required=True, type=Path)
    parser.add_argument("--parent-source", required=True, type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    repeats = max(3, args.repeats)
    inherited_script = Path(__file__).with_name("benchmark_scene_studio_0_7_1.py")
    with tempfile.TemporaryDirectory(prefix="nndv-073-performance-") as temporary_name:
        raw_output = Path(temporary_name) / "raw-historical-run.json"
        command = [
            sys.executable,
            str(inherited_script),
            "--output",
            str(raw_output),
            "--baseline-scene-report",
            str(args.baseline_scene_report),
            "--parent-source",
            str(args.parent_source),
            "--repeats",
            str(repeats),
        ]
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
        if not raw_output.is_file():
            raise SystemExit(f"inherited benchmark produced no report: {(completed.stdout + completed.stderr)[-1200:]}")
        current = _rename_historical_fields(json.loads(raw_output.read_text(encoding="utf-8")))

    parent = json.loads(args.baseline_scene_report.read_text(encoding="utf-8"))
    current["schema_version"] = "nndv-0.7.3-scene-studio-performance-1"
    current["release"] = RELEASE
    retained = current["retained_2d"]
    retained.pop("historical_artifact_median_ms", None)
    retained.pop("historical_artifact_regression_percent", None)
    retained["baseline_0_7_2_report"] = str(args.baseline_scene_report.resolve())
    retained["parent_0_7_2_source"] = str(args.parent_source.resolve())

    metric_paths = {
        "first_interactive_250_maximum": ("first_interactive", "250_objects", "maximum_ms"),
        "first_interactive_1000_maximum": ("first_interactive", "1000_objects", "maximum_ms"),
        "orbit_500_p95": ("orbit_500_objects", "p95_ms"),
        "cpu_projection_250_maximum": ("cpu_publication_projection", "250", "maximum_ms"),
        "cpu_projection_1000_maximum": ("cpu_publication_projection", "1000", "maximum_ms"),
        "large_graph_10000_maximum": ("large_graphs", "10000", "maximum_ms"),
        "large_graph_50000_maximum": ("large_graphs", "50000", "maximum_ms"),
    }
    comparisons: list[dict[str, Any]] = []
    failures = list(current.get("failures", []))
    for name, path in metric_paths.items():
        current_value = _metric(current, path)
        parent_value = _metric(parent, path)
        regression = ((current_value - parent_value) / parent_value) * 100.0
        passed = regression <= 20.0
        comparisons.append(
            {
                "metric": name,
                "aggregation": "maximum" if name != "orbit_500_p95" else "p95",
                "current_0_7_3_ms": round(current_value, 3),
                "parent_0_7_2_ms": round(parent_value, 3),
                "regression_percent": round(regression, 3),
                "maximum_allowed_regression_percent": 20.0,
                "status": "PASS" if passed else "FAIL",
            }
        )
        if not passed:
            failures.append(f"{name} regressed {regression:.3f}% from the pinned 0.7.2 artifact")
    current["parent_0_7_2"] = {
        "artifact_report": str(args.baseline_scene_report.resolve()),
        "sha256": _digest(args.baseline_scene_report),
        "reported_schema": parent.get("schema_version"),
        "reported_release": parent.get("release"),
        "classification": "inherited-historical-input-not-current-schema",
    }
    current["required_regression_comparisons"] = comparisons
    current["attributable_regression_gate"] = {
        "status": "PASS" if all(item["status"] == "PASS" for item in comparisons) else "FAIL",
        "method": "fresh three-run current maximum/p95 against the pinned 0.7.2 artifact metric on the same workstation",
        "limit_percent": 20.0,
    }
    current["repeats"] = repeats
    current["failures"] = failures
    current["status"] = "PASS" if completed.returncode == 0 and not failures else "FAIL"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": current["status"],
                "repeats": repeats,
                "comparisons": {item["metric"]: item["regression_percent"] for item in comparisons},
                "failures": failures,
            },
            sort_keys=True,
        )
    )
    return 0 if current["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
