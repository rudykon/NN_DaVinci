#!/usr/bin/env python3
"""Measure deterministic 1,000-object Figure IR operations for release evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
import time

from nn_davinci.figure_export import render_figure_svg
from nn_davinci.figure_ir import FigureIR, FigureObject, FigureProvenance, new_figure
from nn_davinci.server import create_app
from scripts.stress_graphs import deep_chain


def elapsed_ms(action):
    started = time.perf_counter()
    value = action()
    return value, (time.perf_counter() - started) * 1_000


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    figure = new_figure("1,000-object release benchmark")
    panel = next(figure.iter_panels())
    source_layer, target_layer = panel.layers[0], panel.layers[2]
    for index in range(1_000):
        source_layer.objects.append(
            FigureObject.create(
                "node-glyph",
                f"N{index}",
                {
                    "x": panel.geometry["x"] + 2 + (index % 40) * 4,
                    "y": panel.geometry["y"] + 5 + (index // 40) * 4,
                    "width": 3,
                    "height": 2,
                },
                FigureProvenance("graph_ir", source_id=f"n{index}", graph_ir_ids=[f"n{index}"]),
                identity=f"release-performance:{index}",
                order=index,
            )
        )
    figure.validate()

    serialization_samples = []
    render_samples = []
    for _ in range(5):
        document, duration = elapsed_ms(figure.to_dict)
        serialization_samples.append(duration)
        _, duration = elapsed_ms(lambda value=document: FigureIR.from_dict(value))
        serialization_samples.append(duration)
        svg, duration = elapsed_ms(lambda: render_figure_svg(figure))
        render_samples.append(duration)
    moved = source_layer.objects[500]
    _, move_ms = elapsed_ms(lambda: figure.move_object(moved.id, target_layer.id))

    graph = deep_chain(1_001)
    client = create_app().test_client()
    response, summary_ms = elapsed_ms(
        lambda: client.post("/api/figure/from-graph", json={"graph": graph.to_dict(), "mode": "mixed"})
    )
    summary = response.get_json()["figure"]
    summary_objects = sum(
        len(layer["objects"])
        for page in summary["pages"]
        for summary_panel in page["panels"]
        for layer in summary_panel["layers"]
    )
    failures = []
    if svg.count('class="node-label"') != 1_000:
        failures.append("1,000-object SVG lost a node label")
    if median(render_samples) > 2_000:
        failures.append("1,000-object median render exceeded 2,000 ms")
    if move_ms > 2_000:
        failures.append("1,000-object cross-layer move exceeded 2,000 ms")
    if response.status_code != 200 or summary_objects >= 1_001 or summary_ms > 3_000:
        failures.append("1,001-node graph did not use a bounded summary within 3,000 ms")

    report = {
        "schema_version": "nndv-figure-studio-performance-1",
        "release": "0.6.0 Beta — Scientific Figure Studio",
        "status": "PASS" if not failures else "FAIL",
        "figure_objects": 1_000,
        "serialization_samples_ms": [round(value, 3) for value in serialization_samples],
        "serialization_median_ms": round(median(serialization_samples), 3),
        "render_samples_ms": [round(value, 3) for value in render_samples],
        "render_median_ms": round(median(render_samples), 3),
        "cross_layer_move_ms": round(move_ms, 3),
        "large_graph": {
            "source_nodes": 1_001,
            "summary_objects": summary_objects,
            "elapsed_ms": round(summary_ms, 3),
            "strategy": summary["metadata"]["large_graph"]["figure_source"],
        },
        "failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("NNDV_060_FIGURE_PERFORMANCE=" + json.dumps({"status": report["status"], "render_median_ms": report["render_median_ms"]}, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
