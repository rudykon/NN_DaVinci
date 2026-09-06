#!/usr/bin/env python3
"""Deterministic 0.2.2 graph, SCC, spatial, CPU/RSS, and size gates."""

from __future__ import annotations

import argparse
import json
import platform
import random
import resource
import statistics
import time
from pathlib import Path
from typing import Callable

from nn_davinci.layout import LayoutEngine, NodePlacement, focus_graph
from nn_davinci.layout.engine import (
    LayoutResult,
    _boxes_overlap,
    _node_overlap_query,
    _strongly_connected_components,
)
from nn_davinci.render import SvgRenderer
from nn_davinci.scaling import summarize_graph_structure
from nn_davinci.themes import get_theme

from stress_graphs import SEED, canonical_graph_hash, corpus, deep_chain


ADVERSARIAL_GENERATOR_VERSION = "0.2.2-adversarial-v1"
MAX_SPATIAL_SECONDS = 2.0


def rss_bytes() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)


def timed_query(nodes: dict[str, NodePlacement], *, max_pairs: int | None = 1_000_000) -> dict[str, object]:
    wall_started = time.perf_counter()
    cpu_started = time.process_time()
    query = _node_overlap_query(LayoutResult("spatial-benchmark", "LR", nodes=nodes), max_pairs=max_pairs)
    return {
        "rectangles": len(nodes), "pairs": query.pair_count, "retained_pairs": len(query.pairs),
        "complete": query.complete, "truncated": query.truncated, "lower_bound": query.lower_bound,
        "max_pairs": query.max_pairs, "algorithm": query.algorithm,
        "wall_seconds": time.perf_counter() - wall_started,
        "cpu_seconds": time.process_time() - cpu_started,
        "peak_rss_bytes": rss_bytes(),
    }


def naive_pairs(nodes: dict[str, NodePlacement]) -> list[list[str]]:
    ordered = sorted(nodes.items())
    return [
        [first_id, second_id]
        for index, (first_id, first) in enumerate(ordered)
        for second_id, second in ordered[index + 1 :]
        if _boxes_overlap(first, second)
    ]


def same_x_y_disjoint(count: int) -> dict[str, NodePlacement]:
    return {f"r{index:05d}": NodePlacement(0, index * 2, 1, 1) for index in range(count)}


def same_y_x_disjoint(count: int) -> dict[str, NodePlacement]:
    return {f"r{index:05d}": NodePlacement(index * 2, 0, 1, 1) for index in range(count)}


def nested_x_y_filtered(count: int) -> dict[str, NodePlacement]:
    # X ranges share a common center and are nested; y bands are disjoint, so
    # an implementation indexing only x still performs quadratic work.
    return {
        f"r{index:05d}": NodePlacement(index * 0.001, index * 2, 20_000 - index * 0.002, 1)
        for index in range(count)
    }


def distribution(kind: str, count: int, seed: int) -> dict[str, NodePlacement]:
    rng = random.Random(seed)
    nodes: dict[str, NodePlacement] = {}
    for index in range(count):
        if kind == "striped":
            x, y, width, height = (index % 32) * 80 + rng.random(), (index // 32) * 5, 25, 2
        elif kind == "clustered":
            cluster = index % 64
            x, y = cluster * 300 + rng.random() * 20, (index // 64) * 30 + rng.random() * 4
            width, height = 8, 8
        elif kind == "axis-swapped":
            x, y, width, height = (index // 40) * 4, (index % 40) * 120, 2, 35
        elif kind == "extreme-aspect":
            x, y, width, height = index * 3, index * 2, 10_000 if index % 2 else 1, 0.5
        elif kind == "permuted":
            coordinate = (index * 7919 + seed) % (count * 8)
            x, y, width, height = coordinate * 3, ((coordinate * 104729) % (count * 8)) * 3, 2, 2
        else:
            raise ValueError(kind)
        nodes[f"r{index:05d}"] = NodePlacement(x, y, width, height)
    return nodes


def full_graph(factory: Callable[[], object], *, name: str) -> dict[str, object]:
    started = time.perf_counter()
    graph = factory()
    imported = time.perf_counter()
    layout = LayoutEngine().layout(graph)
    laid_out = time.perf_counter()
    svg = SvgRenderer().render(graph, layout, get_theme(), show_legend=False, label_density="compact")
    finished = time.perf_counter()
    return {
        "corpus": name, "nodes": len(graph.nodes), "edges": len(graph.edges),
        "rendered_nodes": len(layout.nodes), "rendered_edges": len(layout.edges),
        "graph_sha256": canonical_graph_hash(graph), "import_seconds": imported - started,
        "layout_seconds": laid_out - imported, "render_seconds": finished - laid_out,
        "total_seconds": finished - started, "peak_rss_bytes": rss_bytes(),
        "svg_bytes": len(svg.encode("utf-8")),
    }


def ten_thousand_focus() -> dict[str, object]:
    started = time.perf_counter()
    graph = deep_chain(10_000)
    imported = time.perf_counter()
    summary = summarize_graph_structure(graph)
    view = focus_graph(graph, {"n05000"}, hops=120)
    layout = LayoutEngine().layout(view)
    laid_out = time.perf_counter()
    svg = SvgRenderer().render(view, layout, get_theme(), show_legend=False, label_density="compact")
    finished = time.perf_counter()
    return {
        "nodes": len(graph.nodes), "edges": len(graph.edges),
        "rendered_nodes": len(layout.nodes), "rendered_edges": len(layout.edges),
        "graph_sha256": canonical_graph_hash(graph), "degradation": "summary+focus(hops=120)+boundary-proxies",
        "summary": summary, "import_seconds": imported - started,
        "layout_seconds": laid_out - imported, "render_seconds": finished - laid_out,
        "total_seconds": finished - started, "peak_rss_bytes": rss_bytes(),
        "svg_bytes": len(svg.encode("utf-8")),
    }


def aggregate(runs: list[dict[str, object]], field: str = "total_seconds") -> dict[str, object]:
    values = [float(item[field]) for item in runs]
    return {"runs": runs, "median_seconds": statistics.median(values), "maximum_seconds": max(values)}


def reference_scc(nodes: set[str], outgoing: dict[str, set[str]]) -> set[frozenset[str]]:
    def reachable(source: str) -> set[str]:
        pending, seen = [source], {source}
        while pending:
            current = pending.pop()
            for target in outgoing[current]:
                if target not in seen:
                    seen.add(target)
                    pending.append(target)
        return seen

    reach = {node: reachable(node) for node in nodes}
    remaining = set(nodes)
    result: set[frozenset[str]] = set()
    while remaining:
        first = min(remaining)
        component = frozenset(node for node in remaining if node in reach[first] and first in reach[node])
        result.add(component)
        remaining -= component
    return result


def condensation_signature(
    components: set[frozenset[str]],
    outgoing: dict[str, set[str]],
) -> set[tuple[frozenset[str], frozenset[str]]]:
    component_of = {node: component for component in components for node in component}
    return {
        (component_of[source], component_of[target])
        for source, targets in outgoing.items()
        for target in targets
        if component_of[source] != component_of[target]
    }


def scc_differential() -> dict[str, object]:
    rng = random.Random(SEED)
    partition_failures: list[int] = []
    condensation_failures: list[int] = []
    for sample in range(100):
        nodes = {f"n{index}" for index in range(2 + sample % 12)}
        outgoing = {node: set() for node in nodes}
        for source in sorted(nodes):
            for target in sorted(nodes):
                if rng.random() < 0.17:
                    outgoing[source].add(target)
        actual = {frozenset(item) for item in _strongly_connected_components(nodes, outgoing)}
        expected = reference_scc(nodes, outgoing)
        if actual != expected:
            partition_failures.append(sample)
        if condensation_signature(actual, outgoing) != condensation_signature(expected, outgoing):
            condensation_failures.append(sample)
    chain = deep_chain(10_000)
    outgoing = {node.id: set() for node in chain.nodes}
    for edge in chain.edges:
        outgoing[edge.source].add(edge.target)
    deep_components = _strongly_connected_components(set(outgoing), outgoing)
    return {
        "samples": 100, "seed": SEED,
        "partition_failures": partition_failures,
        "condensation_dag_failures": condensation_failures,
        "deep_chain_components": len(deep_components),
        "deep_chain_without_recursion": len(deep_components) == 10_000,
        "passed": not partition_failures and not condensation_failures and len(deep_components) == 10_000,
    }


def named_graph_runs() -> dict[str, object]:
    generated = corpus()
    output: dict[str, object] = {}
    for name in ("wide_layer_dag", "strongly_connected", "sparse_skip", "locally_dense"):
        graph = generated[name]
        runs = [full_graph(lambda graph=graph: graph.copy(), name=name) for _ in range(3)]
        layout = LayoutEngine().layout(graph)
        input_edges = {edge.id for edge in graph.edges}
        observed_edges = set(layout.edges)
        if name == "wide_layer_dag":
            ranks = {node_id: item.rank for node_id, item in layout.nodes.items()}
            structure = {
                "source_rank": ranks["n00000"], "sink_rank": ranks[max(ranks)],
                "rank_values": sorted(set(ranks.values())),
                "edge_set_exact": observed_edges == input_edges,
            }
            structure_passed = structure == {"source_rank": 0, "sink_rank": 3, "rank_values": [0, 1, 2, 3], "edge_set_exact": True}
        elif name == "strongly_connected":
            outgoing = {node.id: set() for node in graph.nodes}
            for edge in graph.edges:
                outgoing[edge.source].add(edge.target)
            components = _strongly_connected_components(set(outgoing), outgoing)
            structure = {"component_count": len(components), "component_size": len(components[0]), "edge_set_exact": observed_edges == input_edges}
            structure_passed = structure == {"component_count": 1, "component_size": len(graph.nodes), "edge_set_exact": True}
        elif name == "sparse_skip":
            ranks = {node_id: item.rank for node_id, item in layout.nodes.items()}
            monotonic = all(ranks[edge.target] > ranks[edge.source] for edge in graph.edges)
            structure = {"rank_monotonic": monotonic, "edge_set_exact": observed_edges == input_edges}
            structure_passed = monotonic and observed_edges == input_edges
        else:
            overlap = _node_overlap_query(layout)
            structure = {
                "node_set_exact": set(layout.nodes) == {node.id for node in graph.nodes},
                "edge_set_exact": observed_edges == input_edges,
                "pair_budget_complete": overlap.complete,
                "pair_budget_truncated": overlap.truncated,
            }
            structure_passed = all((structure["node_set_exact"], structure["edge_set_exact"], structure["pair_budget_complete"])) and not structure["pair_budget_truncated"]
        performance = all(
            float(run["total_seconds"]) <= 5
            and int(run["peak_rss_bytes"]) <= 2**30
            and int(run["svg_bytes"]) <= 20 * 2**20
            for run in runs
        )
        output[name] = {
            **aggregate(runs), "structure": structure,
            "structure_passed": structure_passed, "performance_passed": performance,
            "passed": structure_passed and performance,
        }
    return output


def spatial_report() -> dict[str, object]:
    named: dict[str, object] = {}
    for name, generator in {
        "same_x_y_disjoint": same_x_y_disjoint,
        "same_y_x_disjoint": same_y_x_disjoint,
        "nested_x_y_filtered": nested_x_y_filtered,
    }.items():
        runs = [timed_query(generator(10_000)) for _ in range(3)]
        named[name] = {
            **aggregate(runs, "wall_seconds"),
            "passed": all(run["complete"] and run["pairs"] == 0 and float(run["wall_seconds"]) <= MAX_SPATIAL_SECONDS for run in runs),
            "threshold_seconds_each_run": MAX_SPATIAL_SECONDS,
        }
    dense_small = {
        f"r{index:04d}": NodePlacement((index % 20) * 3, (index // 20) * 3, 7, 7)
        for index in range(200)
    }
    dense_query = timed_query(dense_small, max_pairs=None)
    dense_naive = naive_pairs(dense_small)
    dense_query["naive_pairs"] = len(dense_naive)
    dense_query["pair_set_exact"] = _node_overlap_query(LayoutResult("dense", "LR", nodes=dense_small), max_pairs=None).pair_lists() == dense_naive
    budget_nodes = {f"r{index:04d}": NodePlacement(0, 0, 10, 10) for index in range(1500)}
    budget = timed_query(budget_nodes)
    budget["passed"] = not budget["complete"] and budget["truncated"] and int(budget["lower_bound"]) >= 1_000_001
    differential: list[dict[str, object]] = []
    for offset, kind in enumerate(("striped", "clustered", "axis-swapped", "extreme-aspect", "permuted") * 4):
        seed = SEED + offset
        small = distribution(kind, 1000, seed)
        query = _node_overlap_query(LayoutResult("small", "LR", nodes=small), max_pairs=None)
        exact = query.pair_lists() == naive_pairs(small)
        large = timed_query(distribution(kind, 10_000, seed))
        differential.append({
            "seed": seed, "distribution": kind, "small_pair_set_exact": exact,
            "small_pairs": query.pair_count, "large": large,
            "passed": exact and large["complete"] and float(large["wall_seconds"]) <= MAX_SPATIAL_SECONDS and int(large["peak_rss_bytes"]) <= 2**30,
        })
    passed = all(item["passed"] for item in named.values()) and dense_query["pair_set_exact"] and budget["passed"] and all(item["passed"] for item in differential)
    return {
        "generator_version": ADVERSARIAL_GENERATOR_VERSION,
        "seed": SEED, "named": named, "dense_small": dense_query,
        "million_pair_budget": budget, "differential_distributions": differential,
        "passed": passed,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    chain_100 = aggregate([full_graph(lambda: deep_chain(100), name="deep_chain_100") for _ in range(3)])
    chain_1k = aggregate([full_graph(lambda: deep_chain(1000), name="deep_chain_1000") for _ in range(3)])
    focus_10k = aggregate([ten_thousand_focus() for _ in range(3)])
    hundred_ok = all(float(run["total_seconds"]) <= 5 and int(run["peak_rss_bytes"]) <= 2**30 and int(run["svg_bytes"]) <= 20 * 2**20 for run in chain_100["runs"])
    one_ok = all(float(run["total_seconds"]) <= 5 and int(run["peak_rss_bytes"]) <= 2**30 and int(run["svg_bytes"]) <= 20 * 2**20 for run in chain_1k["runs"])
    ten_ok = all(float(run["total_seconds"]) <= 20 and int(run["peak_rss_bytes"]) <= 2 * 2**30 and int(run["rendered_nodes"]) <= 500 and int(run["svg_bytes"]) <= 10 * 2**20 for run in focus_10k["runs"])
    named = named_graph_runs()
    spatial = spatial_report()
    scc = scc_differential()
    hard_failures = []
    if not hundred_ok:
        hard_failures.append("deep_chain_100")
    if not one_ok:
        hard_failures.append("deep_chain_1000")
    if not ten_ok:
        hard_failures.append("deep_chain_10000_focus")
    hard_failures.extend(name for name, item in named.items() if not item["passed"])
    if not spatial["passed"]:
        hard_failures.append("spatial_adversarial")
    if not scc["passed"]:
        hard_failures.append("scc_differential")
    report = {
        "schema_version": "2.0.2", "generator_version": ADVERSARIAL_GENERATOR_VERSION,
        "legacy_generator_version": "0.2.1-stress-v1", "seed": SEED,
        "platform": {"python": platform.python_version(), "system": platform.platform(), "machine": platform.machine()},
        "deep_chain_100": {**chain_100, "passed": hundred_ok, "threshold": {"seconds": 5, "rss_bytes": 2**30, "svg_bytes": 20 * 2**20}},
        "deep_chain_1000": {**chain_1k, "passed": one_ok, "threshold": {"seconds": 5, "rss_bytes": 2**30, "svg_bytes": 20 * 2**20}},
        "deep_chain_10000_focus": {**focus_10k, "passed": ten_ok, "threshold": {"seconds": 20, "rss_bytes": 2 * 2**30, "rendered_nodes": 500, "svg_bytes": 10 * 2**20}},
        "named_graph_corpora": named, "spatial_index": spatial, "scc_differential": scc,
        "hard_failures": hard_failures, "passed": not hard_failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "hard_failures": hard_failures}, sort_keys=True))
    if hard_failures:
        raise SystemExit(f"large-graph release gates failed: {hard_failures}")


if __name__ == "__main__":
    main()
