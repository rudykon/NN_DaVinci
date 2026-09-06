#!/usr/bin/env python3
"""Measure the 0.4 lazy-canvas and isolated-panel product gates."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from functools import partial
import json
import os
from pathlib import Path
import platform
import resource
import statistics
import time
from typing import Any, Callable

from nn_davinci.api import load_graph
from nn_davinci.composer import FigureComposer, FigurePanel
from nn_davinci.viewport import Viewport, coarse_semantic_graph, lazy_summary, viewport_slice

from stress_graphs import deep_chain


REPEATS = 3


def _rss_mb() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value / (1024.0 if platform.system() != "Darwin" else 1024.0 * 1024.0)


def _timed(function: Callable[[], Any]) -> tuple[Any, float]:
    started = time.perf_counter()
    result = function()
    return result, (time.perf_counter() - started) * 1000.0


def _summary(values: list[float]) -> dict[str, Any]:
    return {
        "runs_ms": [round(value, 3) for value in values],
        "median_ms": round(statistics.median(values), 3),
        "maximum_ms": round(max(values), 3),
    }


def _lazy_case(node_count: int) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    for _ in range(REPEATS):
        graph, construct_ms = _timed(partial(deep_chain, node_count))
        summary, summary_ms = _timed(partial(lazy_summary, graph))
        if node_count >= 50_000:
            screen_graph, semantic_ms = _timed(partial(coarse_semantic_graph, graph, level="model"))
        else:
            screen_graph, semantic_ms = graph, 0.0
        first_slice, viewport_ms = _timed(
            partial(viewport_slice, screen_graph, Viewport(width=960, height=540, padding=120))
        )
        updated_slice, update_ms = _timed(
            partial(
                viewport_slice,
                screen_graph,
                Viewport(x=1_200, y=720, width=960, height=540, padding=120),
            )
        )
        runs.append(
            {
                "nodes": node_count,
                "edges": len(graph.edges),
                "construct_ms": round(construct_ms, 3),
                "summary_ms": round(summary_ms, 3),
                "semantic_summary_ms": round(semantic_ms, 3),
                "first_viewport_ms": round(viewport_ms, 3),
                "first_interactive_backend_ms": round(construct_ms + summary_ms + semantic_ms + viewport_ms, 3),
                "viewport_update_ms": round(update_ms, 3),
                "rendered_nodes": first_slice.rendered_node_count,
                "rendered_edges": first_slice.rendered_edge_count,
                "dom_object_estimate": first_slice.dom_object_estimate,
                "updated_nodes": updated_slice.rendered_node_count,
                "semantic_index_deferred": summary["semantic_index_deferred"],
                "recommended_level": summary["recommended_level"],
                "peak_rss_mb": round(_rss_mb(), 3),
            }
        )
    return {
        "runs": runs,
        "first_interactive_backend": _summary([item["first_interactive_backend_ms"] for item in runs]),
        "viewport_update": _summary([item["viewport_update_ms"] for item in runs]),
        "passed": all(
            item["rendered_nodes"] <= 500
            and item["dom_object_estimate"] <= 2_000
            and item["viewport_update_ms"] <= 200.0
            and item["first_interactive_backend_ms"] <= 2_000.0
            and item["semantic_index_deferred"]
            for item in runs
        ),
    }


def _composer_case(root: Path) -> dict[str, Any]:
    source_a = load_graph(root / "examples/resnet.json", adapter="manual")
    source_b = load_graph(root / "examples/transformer.json", adapter="manual")
    template = FigureComposer(
        "Isolated panel relayout benchmark",
        [
            FigurePanel("A", "Overview", source_a, "stage", "paper"),
            FigurePanel("B", "Attention detail", source_b, "block", "paper"),
        ],
    )
    template.compose()
    runs: list[dict[str, Any]] = []
    for _ in range(REPEATS):
        composer = FigureComposer.from_dict(deepcopy(template.to_dict()))
        _, before, _ = composer.compose()
        prior = dict(before.metadata["panel_layout_digests"])
        (_, changed, _), elapsed_ms = _timed(
            partial(composer.compose, relayout_panels={"B"})
        )
        after = changed.metadata["panel_layout_digests"]
        runs.append(
            {
                "changed_panel": "B",
                "elapsed_ms": round(elapsed_ms, 3),
                "panel_a_unchanged": prior["A"] == after["A"],
                "unmodified_panel_layouts_stable": changed.metadata["unmodified_panel_layouts_stable"],
                "panel_count": 2,
            }
        )
    return {
        "runs": runs,
        "relayout": _summary([item["elapsed_ms"] for item in runs]),
        "passed": all(item["panel_a_unchanged"] and item["unmodified_panel_layouts_stable"] for item in runs),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    report: dict[str, Any] = {
        "schema_version": "0.4.0-product-performance-1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "hardware": {
            "platform": platform.platform(),
            "processor": platform.processor() or "unknown",
            "logical_cpus": os.cpu_count(),
            "python": platform.python_version(),
        },
        "repeats": REPEATS,
        "thresholds": {
            "first_interactive_ms": 2_000,
            "viewport_update_ms": 200,
            "visible_nodes": 500,
            "dom_objects": 2_000,
        },
        "lazy_10k": _lazy_case(10_000),
        "summary_50k": _lazy_case(50_000),
        "isolated_panel_relayout": _composer_case(root),
    }
    report["passed"] = all(
        report[key]["passed"] for key in ("lazy_10k", "summary_50k", "isolated_panel_relayout")
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "NNDV_PRODUCT_PERFORMANCE "
        + json.dumps(
            {
                "passed": report["passed"],
                "10k_median_ms": report["lazy_10k"]["first_interactive_backend"]["median_ms"],
                "50k_median_ms": report["summary_50k"]["first_interactive_backend"]["median_ms"],
                "viewport_50k_max_ms": report["summary_50k"]["viewport_update"]["maximum_ms"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
