#!/usr/bin/env python3
"""Measure Scene Studio core interaction and retained Figure performance.

The interaction-frame metric projects object centres with the real Camera and
world transforms used by the browser renderer; it deliberately does not run
publication-only hidden-line removal on every frame.  The deterministic CPU
publication projector is measured separately and never substituted for the
interactive frame result.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import platform
from statistics import median
import time
from typing import Any, Callable, TypeVar

from nn_davinci.figure_export import render_figure_svg
from nn_davinci.figure_ir import FigureObject, FigureProvenance, new_figure
from nn_davinci.model_scene import model_scene_from_graph
from nn_davinci.scene_ir import Object3D, Scene, SceneProvenance, Transform3D, new_scene
from nn_davinci.scene_math import project_points
from nn_davinci.scene_projection import ProjectionOptions, project_scene
from scripts.stress_graphs import deep_chain


RELEASE = "0.7.1 — 3D Publication Quality & UX Completion"


T = TypeVar("T")


def elapsed_ms(action: Callable[[], T]) -> tuple[T, float]:
    started = time.perf_counter()
    value = action()
    return value, (time.perf_counter() - started) * 1_000.0


def percentile(values: list[float], percentage: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * percentage + 0.999999)))
    return ordered[index]


def grid_scene(count: int) -> Scene:
    scene = new_scene(f"{count}-object Scene Studio benchmark")
    layer = scene.layers[0]
    columns = 25
    rows = 20
    for index in range(count):
        layer.objects.append(
            Object3D.create(
                "tensor-volume",
                f"Object {index}",
                {"size": [0.7, 0.7, 0.7]},
                SceneProvenance.author("Deterministic performance corpus object."),
                identity=f"scene-performance-0.7.1:{count}:{index}",
                transform=Transform3D(
                    [
                        float(index % columns) - columns / 2.0,
                        float((index // columns) % rows) - rows / 2.0,
                        float(index // (columns * rows)) * 2.0,
                    ]
                ),
                metadata={"label": "", "benchmark_object": True},
                order=index,
            )
        )
    scene.validate()
    return scene


def interaction_frame(scene: Scene, yaw: float = 0.35, pitch: float = 0.1) -> int:
    camera = scene.active_camera()
    camera.orbit(yaw, pitch)
    view = camera.view_matrix()
    projection = camera.projection_matrix()
    projected = project_points(
        (item.world.position for item in scene.iter_objects(visible_only=True)),
        view,
        projection,
        (1200.0, 800.0),
    )
    return sum(int(point.visible) for point in projected)


def first_interactive_samples(scene: Scene, repeats: int) -> list[float]:
    document = scene.to_dict()
    samples: list[float] = []
    for _ in range(repeats):
        restored, duration = elapsed_ms(lambda: Scene.from_dict(document))

        def render_first_frame(value: Scene = restored) -> int:
            return interaction_frame(value, 0.0, 0.0)

        _, frame_ms = elapsed_ms(render_first_frame)
        samples.append(duration + frame_ms)
    return samples


def retained_figure(version: str) -> Any:
    figure = new_figure("1,000-object retained Figure benchmark")
    panel = next(figure.iter_panels())
    layer = panel.layers[0]
    for index in range(1_000):
        layer.objects.append(
            FigureObject.create(
                "node-glyph",
                f"N{index}",
                {
                    "x": panel.geometry["x"] + 2 + (index % 40) * 13,
                    "y": panel.geometry["y"] + 5 + (index // 40) * 7,
                    "width": 12,
                    "height": 6,
                },
                FigureProvenance("graph_ir", source_id=f"n{index}", graph_ir_ids=[f"n{index}"]),
                identity=f"retained-performance-{version}:{index}",
                order=index,
            )
        )
    figure.validate()
    return figure


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def retained_figure_render(repeats: int) -> tuple[list[float], list[float], int]:
    """Measure current and frozen-parent-equivalent figures under one load.

    The renderer and Figure IR modules are byte-checked against the parent
    source before this paired comparison is accepted.  Alternating order and
    warming both documents once prevents machine-load drift from being
    misreported as a product regression while retaining exactly three (or
    more) recorded executions for each version.
    """

    current = retained_figure("0.7.1")
    parent = retained_figure("0.7.0")
    render_figure_svg(current)
    render_figure_svg(parent)
    current_samples: list[float] = []
    parent_samples: list[float] = []
    current_svg = ""
    for _index in range(repeats):
        current_observations: list[float] = []
        parent_observations: list[float] = []
        forward = ((current, current_observations), (parent, parent_observations))
        reverse = tuple(reversed(forward))
        # ABBA + BAAB places each version equally at every position in the
        # recorded run. This removes the strong CPU-frequency/order bias
        # observed on this workstation without discarding a result.
        for ordered in (forward, reverse, reverse, forward):
            for figure, observations in ordered:
                rendered, duration = elapsed_ms(lambda value=figure: render_figure_svg(value))
                observations.append(duration)
                if figure is current:
                    current_svg = rendered
        current_samples.append(sum(current_observations) / len(current_observations))
        parent_samples.append(sum(parent_observations) / len(parent_observations))
    return current_samples, parent_samples, current_svg.count('data-text-role="node-label"')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-scene-report", type=Path, required=True)
    parser.add_argument("--parent-source", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    repeats = max(3, args.repeats)

    baseline = json.loads(args.baseline_scene_report.read_text(encoding="utf-8"))
    historical_baseline_2d_ms = float(baseline["retained_2d"]["current_median_ms"])
    baseline_first_1000_maximum_ms = float(baseline["first_interactive"]["1000_objects"]["maximum_ms"])
    project_root = Path(__file__).resolve().parents[1]
    parent_source = args.parent_source.resolve()
    retained_source_identity = {
        relative: {
            "current_sha256": sha256(project_root / relative),
            "parent_0_7_0_sha256": sha256(parent_source / relative),
        }
        for relative in ("src/nn_davinci/figure_export.py", "src/nn_davinci/figure_ir.py")
    }
    retained_source_identical = all(value["current_sha256"] == value["parent_0_7_0_sha256"] for value in retained_source_identity.values())
    scene_250 = grid_scene(250)
    scene_500 = grid_scene(500)
    scene_1000 = grid_scene(1_000)

    first_250 = first_interactive_samples(scene_250, repeats)
    first_1000 = first_interactive_samples(scene_1000, repeats)

    orbit_samples: list[float] = []
    original_world = {item.id: deepcopy(item.world) for item in scene_500.iter_objects()}
    for _ in range(max(60, repeats * 20)):
        _, duration = elapsed_ms(lambda: interaction_frame(scene_500))
        orbit_samples.append(duration)
    world_unchanged = all(item.world == original_world[item.id] for item in scene_500.iter_objects())

    selection_samples: list[float] = []
    identifiers = [item.id for item in scene_500.iter_objects()]
    for index in range(max(30, repeats * 10)):
        target = identifiers[index % len(identifiers)]

        def select_and_inspect(identifier: str = target) -> dict[str, Any]:
            scene_500.set_selection([identifier])
            _layer, item = scene_500.find_object(identifier)
            return {
                "geometry": item.geometry,
                "style": item.material.base_color,
                "evidence": item.provenance.kind,
            }

        _, duration = elapsed_ms(select_and_inspect)
        selection_samples.append(duration)

    cpu_projection: dict[str, list[float]] = {"250": [], "1000": []}
    projection_options = ProjectionOptions(hidden_edges=False, backface_culling=True)
    for label, scene in (("250", scene_250), ("1000", scene_1000)):
        for _ in range(repeats):

            def publication_projection(value: Scene = scene) -> object:
                return project_scene(value, options=projection_options)

            _, duration = elapsed_ms(publication_projection)
            cpu_projection[label].append(duration)

    figure_samples, paired_parent_figure_samples, figure_labels = retained_figure_render(repeats)
    current_2d_ms = median(figure_samples)
    paired_parent_2d_ms = median(paired_parent_figure_samples)
    figure_regression_percent = ((current_2d_ms - paired_parent_2d_ms) / paired_parent_2d_ms) * 100.0
    historical_figure_regression_percent = ((current_2d_ms - historical_baseline_2d_ms) / historical_baseline_2d_ms) * 100.0
    first_1000_regression_percent = ((max(first_1000) - baseline_first_1000_maximum_ms) / baseline_first_1000_maximum_ms) * 100.0

    large_graphs: dict[str, Any] = {}
    for count in (10_000, 50_000):
        graph = deep_chain(count)
        samples: list[float] = []
        generated: Scene | None = None
        for _ in range(repeats):

            def generate_summary(value: Any = graph) -> Scene:
                return model_scene_from_graph(value, architecture="cnn", maximum_objects=250)

            generated, duration = elapsed_ms(generate_summary)
            samples.append(duration)
        assert generated is not None
        large_graphs[str(count)] = {
            "samples_ms": [round(value, 3) for value in samples],
            "median_ms": round(median(samples), 3),
            "maximum_ms": round(max(samples), 3),
            "scene_objects": sum(1 for _ in generated.iter_objects()),
            "summary_first": generated.metadata["model_scene_pipeline"]["summary_first"],
            "provenance_mode": generated.metadata["model_scene_pipeline"]["summary_provenance_mode"],
        }

    thresholds = {
        "standard_250_first_interactive_maximum_ms": 500.0,
        "large_1000_first_interactive_maximum_ms": 1_500.0,
        "orbit_500_frame_p95_ms": 20.0,
        "first_1000_parent_maximum_regression_percent": 20.0,
        "selection_inspector_median_ms": 100.0,
        "retained_2d_maximum_regression_percent": 20.0,
        "maximum_generated_scene_objects": 250,
    }
    failures: list[str] = []
    if max(first_250) > thresholds["standard_250_first_interactive_maximum_ms"]:
        failures.append("250-object first-interactive maximum exceeded 500 ms")
    if max(first_1000) > thresholds["large_1000_first_interactive_maximum_ms"]:
        failures.append("1,000-object first-interactive maximum exceeded 1,500 ms")
    if percentile(orbit_samples, 0.95) > thresholds["orbit_500_frame_p95_ms"]:
        failures.append("500-object interaction-frame p95 exceeded 20 ms")
    if first_1000_regression_percent > thresholds["first_1000_parent_maximum_regression_percent"]:
        failures.append("1,000-object first interaction regressed by more than 20% from 0.7.0")
    if median(selection_samples) > thresholds["selection_inspector_median_ms"]:
        failures.append("selection/Inspector median exceeded 100 ms")
    if figure_regression_percent > thresholds["retained_2d_maximum_regression_percent"]:
        failures.append("retained 2D Figure render regressed by more than 20%")
    if not retained_source_identical:
        failures.append("retained 2D Figure renderer/IR source differs from the pinned 0.7.0 parent")
    if figure_labels != 1_000:
        failures.append("retained 2D Figure render lost labels")
    if not world_unchanged:
        failures.append("camera orbit changed Scene world coordinates")
    for count_key, result in large_graphs.items():
        if not result["summary_first"] or result["scene_objects"] > 250:
            failures.append(f"{count_key}-node model did not remain summary-first and bounded")

    report = {
        "schema_version": "nndv-0.7.1-scene-studio-performance-1",
        "release": RELEASE,
        "status": "PASS" if not failures else "FAIL",
        "repeats": repeats,
        "measurement_scope": {
            "first_interactive": "Scene IR deserialize, world-record refresh, and one real camera interaction frame",
            "orbit_frame": "camera orbit plus one frame-stable batch projection of all visible world-space object centres; publication hidden-line removal excluded",
            "cpu_publication_projection": "deterministic full vector projection with faces and edges; reported separately",
            "human_participants": 0,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor() or "not-reported-by-platform",
            "logical_cpu_count": os.cpu_count(),
        },
        "first_interactive": {
            "250_objects": {
                "samples_ms": [round(value, 3) for value in first_250],
                "median_ms": round(median(first_250), 3),
                "maximum_ms": round(max(first_250), 3),
            },
            "1000_objects": {
                "samples_ms": [round(value, 3) for value in first_1000],
                "median_ms": round(median(first_1000), 3),
                "maximum_ms": round(max(first_1000), 3),
                "parent_0_7_0_maximum_ms": baseline_first_1000_maximum_ms,
                "regression_percent": round(first_1000_regression_percent, 3),
            },
        },
        "orbit_500_objects": {
            "samples": len(orbit_samples),
            "median_ms": round(median(orbit_samples), 3),
            "p95_ms": round(percentile(orbit_samples, 0.95), 3),
            "maximum_ms": round(max(orbit_samples), 3),
            "world_coordinates_unchanged": world_unchanged,
        },
        "selection_inspector": {
            "samples": len(selection_samples),
            "median_ms": round(median(selection_samples), 3),
            "maximum_ms": round(max(selection_samples), 3),
        },
        "cpu_publication_projection": {
            key: {
                "samples_ms": [round(value, 3) for value in samples],
                "median_ms": round(median(samples), 3),
                "maximum_ms": round(max(samples), 3),
            }
            for key, samples in cpu_projection.items()
        },
        "retained_2d": {
            "baseline_0_7_0_report": str(args.baseline_scene_report),
            "parent_0_7_0_source": str(parent_source),
            "comparison_method": "paired-warm-current-load-alternating-order",
            "recorded_runs_per_version": repeats,
            "observations_per_recorded_run": 4,
            "warmup_runs_per_version": 1,
            "retained_source_identical": retained_source_identical,
            "retained_source_identity": retained_source_identity,
            "baseline_median_ms": round(paired_parent_2d_ms, 3),
            "paired_parent_samples_ms": [round(value, 3) for value in paired_parent_figure_samples],
            "current_samples_ms": [round(value, 3) for value in figure_samples],
            "current_median_ms": round(current_2d_ms, 3),
            "regression_percent": round(figure_regression_percent, 3),
            "historical_artifact_median_ms": historical_baseline_2d_ms,
            "historical_artifact_regression_percent": round(historical_figure_regression_percent, 3),
            "labels": figure_labels,
        },
        "large_graphs": large_graphs,
        "thresholds": thresholds,
        "failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "NNDV_071_SCENE_PERFORMANCE="
        + json.dumps(
            {
                "status": report["status"],
                "first_250_maximum_ms": report["first_interactive"]["250_objects"]["maximum_ms"],
                "first_1000_maximum_ms": report["first_interactive"]["1000_objects"]["maximum_ms"],
                "orbit_p95_ms": report["orbit_500_objects"]["p95_ms"],
                "retained_2d_regression_percent": report["retained_2d"]["regression_percent"],
            },
            sort_keys=True,
        )
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
