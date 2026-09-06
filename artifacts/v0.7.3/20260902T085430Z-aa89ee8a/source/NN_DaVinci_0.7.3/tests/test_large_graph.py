from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from nn_davinci.errors import GraphTooLargeError
from nn_davinci.layout import LayoutEngine, LayoutResult, NodePlacement, focus_graph
from nn_davinci.layout.engine import (
    _boxes_overlap,
    _component_ranks,
    _node_overlap_pairs,
    _node_overlap_query,
    _strongly_connected_components,
)
from nn_davinci.scaling import enforce_focus_bound, preflight_graph
from scripts.stress_graphs import SEED, canonical_graph_hash, corpus, deep_chain


ROOT = Path(__file__).parents[1]


def _naive_pairs(nodes: dict[str, NodePlacement]) -> list[list[str]]:
    ordered = sorted(nodes.items())
    return [
        [first_id, second_id]
        for index, (first_id, first) in enumerate(ordered)
        for second_id, second in ordered[index + 1 :]
        if _boxes_overlap(first, second)
    ]


class LargeGraphTests(unittest.TestCase):
    def test_iterative_scc_matches_known_ranks_and_handles_deep_chain(self):
        outgoing = {"a": {"b"}, "b": {"c"}, "c": {"b", "d"}, "d": set()}
        ranks = _component_ranks(set(outgoing), outgoing)
        self.assertEqual(ranks["a"], 0)
        self.assertEqual(ranks["b"], ranks["c"])
        self.assertEqual(ranks["d"], ranks["b"] + 1)
        graph = deep_chain(10_000)
        chain_out = {node.id: set() for node in graph.nodes}
        for edge in graph.edges:
            chain_out[edge.source].add(edge.target)
        chain_ranks = _component_ranks(set(chain_out), chain_out)
        self.assertEqual(chain_ranks["n00000"], 0)
        self.assertEqual(chain_ranks["n09999"], 9999)

    def test_thousand_node_full_layout_no_recursion_error_and_deterministic(self):
        graph = deep_chain(1000)
        first = LayoutEngine().layout(graph, algorithm="generic")
        second = LayoutEngine().layout(graph, algorithm="generic")
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(len(first.nodes), 1000)
        self.assertEqual(len(first.edges), 999)

    def test_stress_corpus_hash_manifest(self):
        manifest = json.loads((ROOT / "verification" / "fixtures" / "stress-corpus-0.2.1.json").read_text())
        generated = corpus()
        self.assertEqual(manifest["seed"], SEED)
        self.assertEqual(set(manifest["corpora"]), set(generated))
        for name, graph in generated.items():
            expected = manifest["corpora"][name]
            self.assertEqual((len(graph.nodes), len(graph.edges)), (expected["nodes"], expected["edges"]))
            self.assertEqual(canonical_graph_hash(graph), expected["sha256"])

    def test_sweep_line_matches_naive_on_one_hundred_random_corpora(self):
        randomizer = random.Random(SEED)
        for sample in range(100):
            nodes = {
                f"n{index}": NodePlacement(
                    randomizer.uniform(-50, 50),
                    randomizer.uniform(-50, 50),
                    randomizer.uniform(0.5, 18),
                    randomizer.uniform(0.5, 18),
                )
                for index in range(5 + sample % 25)
            }
            result = LayoutResult("test", "LR", nodes=nodes)
            self.assertEqual(_node_overlap_pairs(result), _naive_pairs(nodes), f"sample {sample}")

    def test_two_dimensional_index_handles_adversarial_axes_and_boundaries(self):
        special = {
            "zero-width": NodePlacement(2, 1, 0, 3),
            "zero-height": NodePlacement(1, 2, 3, 0),
            "negative": NodePlacement(-4, -4, 3, 3),
            "touching-a": NodePlacement(10, 10, 2, 2),
            "touching-b": NodePlacement(12, 10, 2, 2),
            "nested": NodePlacement(20, 20, 20, 20),
            "duplicate-a": NodePlacement(22, 22, 3, 3),
            "duplicate-b": NodePlacement(22, 22, 3, 3),
        }
        self.assertEqual(
            _node_overlap_pairs(LayoutResult("special", "LR", nodes=special)),
            _naive_pairs(special),
        )
        for axis in ("x", "y"):
            nodes = {
                f"n{index:05d}": NodePlacement(0, index * 2, 1, 1)
                if axis == "x"
                else NodePlacement(index * 2, 0, 1, 1)
                for index in range(10_000)
            }
            started = time.perf_counter()
            query = _node_overlap_query(LayoutResult(f"same-{axis}", "LR", nodes=nodes))
            self.assertTrue(query.complete)
            self.assertEqual(query.pair_count, 0)
            self.assertIn("avl", query.algorithm)
            self.assertNotIn("treap", query.algorithm)
            self.assertLess(time.perf_counter() - started, 2.0)

    def test_dense_pair_budget_is_explicit_and_never_claims_completeness(self):
        nodes = {f"n{index:04d}": NodePlacement(0, 0, 10, 10) for index in range(1500)}
        result = LayoutResult("dense", "LR", nodes=nodes)
        query = _node_overlap_query(result)
        self.assertFalse(query.complete)
        self.assertTrue(query.truncated)
        self.assertEqual(len(query.pairs), 1_000_000)
        self.assertGreaterEqual(query.lower_bound, 1_000_001)
        with self.assertRaisesRegex(ValueError, "full geometry is incomplete"):
            _node_overlap_pairs(result)
        counted = _node_overlap_query(result, max_pairs=10, count_only=True)
        self.assertEqual(counted.pairs, ())
        self.assertEqual(counted.lower_bound, 11)
        self.assertFalse(counted.complete)

    def test_iterative_scc_matches_simple_reference_on_one_hundred_random_graphs(self):
        def reference(nodes: set[str], outgoing: dict[str, set[str]]) -> set[frozenset[str]]:
            reach = {
                source: {
                    target
                    for target in nodes
                    if _reachable(source, target, outgoing)
                }
                for source in nodes
            }
            remaining = set(nodes)
            result: set[frozenset[str]] = set()
            while remaining:
                first = min(remaining)
                component = frozenset(node for node in remaining if node in reach[first] and first in reach[node])
                result.add(component)
                remaining -= component
            return result

        def condensation(
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

        def _reachable(source: str, target: str, outgoing: dict[str, set[str]]) -> bool:
            pending, seen = [source], {source}
            while pending:
                current = pending.pop()
                if current == target:
                    return True
                for neighbor in outgoing[current]:
                    if neighbor not in seen:
                        seen.add(neighbor)
                        pending.append(neighbor)
            return False

        randomizer = random.Random(SEED)
        for sample in range(100):
            nodes = {f"n{index}" for index in range(2 + sample % 11)}
            outgoing = {node: set() for node in nodes}
            for source in sorted(nodes):
                for target in sorted(nodes):
                    if randomizer.random() < 0.18:
                        outgoing[source].add(target)
            actual = {frozenset(item) for item in _strongly_connected_components(nodes, outgoing)}
            expected = reference(nodes, outgoing)
            self.assertEqual(actual, expected, f"partition sample {sample}")
            self.assertEqual(
                condensation(actual, outgoing), condensation(expected, outgoing),
                f"condensation DAG sample {sample}",
            )


class ScalePreflightTests(unittest.TestCase):
    def test_full_large_graph_rejected_but_summary_and_focus_allowed(self):
        graph = deep_chain(10_000)
        with self.assertRaises(GraphTooLargeError) as context:
            preflight_graph(graph, operation="render")
        self.assertEqual(context.exception.status_code, 422)
        self.assertIn("focus", context.exception.hint)
        self.assertEqual(preflight_graph(graph, operation="summary").strategy, "summary")
        self.assertEqual(preflight_graph(graph, focus=["n05000"], operation="render").strategy, "focus")
        view = focus_graph(graph, {"n05000"}, hops=2)
        enforce_focus_bound(view)
        self.assertLessEqual(len(view.nodes), 500)

    def test_web_full_large_graph_returns_actionable_422_under_two_seconds(self):
        from nn_davinci.server import create_app

        graph = deep_chain(10_000)
        client = create_app().test_client()
        started = time.perf_counter()
        response = client.post("/api/render", json={"graph": graph.to_dict()})
        elapsed = time.perf_counter() - started
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["error"], "graph_too_large")
        self.assertIn("summary", response.get_json()["hint"])
        self.assertLess(elapsed, 2.0)

    def test_cli_large_graph_rejection_focus_and_summary_are_executable(self):
        graph = deep_chain(10_000)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "large graph.json"
            output = root / "focus.svg"
            source.write_text(json.dumps(graph.to_dict()), encoding="utf-8")
            environment = {**os.environ, "PYTHONPATH": f"{ROOT / 'src'}:{ROOT}"}
            base = [sys.executable, "-m", "nn_davinci", "render", str(source), "--no-analysis", "--format", "svg"]
            started = time.perf_counter()
            rejected = subprocess.run(base, cwd=ROOT, env=environment, capture_output=True, text=True, check=False)
            self.assertLess(time.perf_counter() - started, 2.0)
            self.assertEqual(rejected.returncode, 2)
            payload = json.loads(rejected.stderr)
            self.assertEqual(payload["error"], "graph_too_large")
            self.assertIn(f"nnviz render '{source}' --focus NODE_ID --focus-hops 2", payload["hint"])
            focused = subprocess.run(
                [*base, "--focus", "n05000", "--focus-hops", "2", "-o", str(output)],
                cwd=ROOT, env=environment, capture_output=True, text=True, check=False,
            )
            self.assertEqual(focused.returncode, 0, focused.stderr)
            self.assertLessEqual(output.read_text(encoding="utf-8").count('class="node '), 500)
            summary = subprocess.run(
                [*base, "--summary"], cwd=ROOT, env=environment, capture_output=True, text=True, check=False,
            )
            self.assertEqual(summary.returncode, 0, summary.stderr)
            structure = json.loads(summary.stdout)
            self.assertEqual((structure["nodes"], structure["edges"]), (10_000, 9_999))
            self.assertFalse(structure["layout_constructed"])
            self.assertFalse(structure["svg_constructed"])


if __name__ == "__main__":
    unittest.main()
