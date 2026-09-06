#!/usr/bin/env python3
"""Deterministic large-graph and rectangle corpora for 0.2.1 gates."""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Iterable

from nn_davinci.ir import Edge, GraphIR, Node
from nn_davinci.layout import NodePlacement


GENERATOR_VERSION = "0.2.1-stress-v1"
SEED = 20260825


def _graph(name: str, node_count: int, pairs: Iterable[tuple[int, int]]) -> GraphIR:
    nodes = [Node(f"n{index:05d}", f"Node {index}", "Operation") for index in range(node_count)]
    edges = [Edge(f"e{index:06d}", f"n{source:05d}", f"n{target:05d}") for index, (source, target) in enumerate(pairs)]
    return GraphIR(name=name, nodes=nodes, edges=edges).validate()


def deep_chain(node_count: int) -> GraphIR:
    return _graph(f"deep-chain-{node_count}", node_count, ((index, index + 1) for index in range(node_count - 1)))


def wide_layer_dag(width: int = 100) -> GraphIR:
    # Two wide layers plus source/sink. Each inner node has two deterministic
    # connections, exercising ordering without an unnecessarily dense SVG.
    node_count = 2 * width + 2
    sink = node_count - 1
    pairs = [(0, index) for index in range(1, width + 1)]
    pairs += [(index, width + 1 + index % width) for index in range(1, width + 1)]
    pairs += [(width + index, sink) for index in range(1, width + 1)]
    return _graph(f"wide-layer-{width}", node_count, pairs)


def strongly_connected(node_count: int = 1000) -> GraphIR:
    return _graph(
        f"strongly-connected-{node_count}",
        node_count,
        ((index, (index + 1) % node_count) for index in range(node_count)),
    )


def sparse_skip(node_count: int = 1000, stride: int = 97) -> GraphIR:
    pairs = [(index, index + 1) for index in range(node_count - 1)]
    pairs += [(index, index + stride) for index in range(0, node_count - stride, stride)]
    return _graph(f"sparse-skip-{node_count}-{stride}", node_count, pairs)


def locally_dense(clusters: int = 20, cluster_size: int = 20) -> GraphIR:
    pairs: list[tuple[int, int]] = []
    for cluster in range(clusters):
        start = cluster * cluster_size
        pairs.extend(
            (start + source, start + target)
            for source in range(cluster_size)
            for target in range(source + 1, cluster_size)
        )
        if cluster + 1 < clusters:
            pairs.append((start + cluster_size - 1, start + cluster_size))
    return _graph(f"locally-dense-{clusters}x{cluster_size}", clusters * cluster_size, pairs)


def canonical_graph_hash(graph: GraphIR) -> str:
    payload = {
        "generator_version": GENERATOR_VERSION,
        "name": graph.name,
        "nodes": sorted(node.id for node in graph.nodes),
        "edges": sorted((edge.id, edge.source, edge.target) for edge in graph.edges),
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def corpus() -> dict[str, GraphIR]:
    return {
        "deep_chain_100": deep_chain(100),
        "deep_chain_1000": deep_chain(1000),
        "deep_chain_10000": deep_chain(10000),
        "wide_layer_dag": wide_layer_dag(),
        "strongly_connected": strongly_connected(),
        "sparse_skip": sparse_skip(),
        "locally_dense": locally_dense(),
    }


def deterministic_rectangles(count: int, *, seed: int = SEED) -> dict[str, NodePlacement]:
    randomizer = random.Random(seed)
    return {
        f"r{index:05d}": NodePlacement(
            randomizer.uniform(0, 100_000),
            randomizer.uniform(0, 100_000),
            randomizer.uniform(8, 80),
            randomizer.uniform(8, 80),
        )
        for index in range(count)
    }


if __name__ == "__main__":
    print(json.dumps({
        "generator_version": GENERATOR_VERSION,
        "seed": SEED,
        "corpora": {
            name: {"nodes": len(graph.nodes), "edges": len(graph.edges), "sha256": canonical_graph_hash(graph)}
            for name, graph in corpus().items()
        },
    }, indent=2, sort_keys=True))
