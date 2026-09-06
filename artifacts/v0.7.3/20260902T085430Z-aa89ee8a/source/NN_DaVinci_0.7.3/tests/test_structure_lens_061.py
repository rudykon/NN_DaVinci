from __future__ import annotations

import unittest
from unittest.mock import patch

from nn_davinci.ir import Edge, GraphIR, Node, Port, TensorSpec
from nn_davinci.semantic import derive_semantic_view
from nn_davinci.structure_lens import AnalysisBudget, StructureLens


def _tensor(shape: list[int | str | None]) -> TensorSpec:
    return TensorSpec("evidence", shape, "float32")


class StructureLensEvidenceTests(unittest.TestCase):
    def test_shape_checks_follow_exact_target_port(self) -> None:
        source = Node(
            "source", "Source", "Input",
            outputs=[Port("source:out", "out", "output", _tensor([1, 4]))],
            source={"fixture": "exact-port"},
        )
        target = Node(
            "target", "Two-input target", "Concatenate",
            inputs=[
                Port("target:input:0", "first", "input", _tensor([1, 4])),
                Port("target:input:1", "second", "input", _tensor([1, 8])),
            ],
            outputs=[Port("target:out", "out", "output", _tensor([1, 12]))],
            source={"fixture": "exact-port"},
        )
        edge = Edge(
            "edge", source.id, target.id,
            source_port="source:out", target_port="target:input:1",
            tensor=_tensor([1, 4]),
        )
        lens = StructureLens(GraphIR("ports", [source, target], [edge], metadata={"source_format": "fixture"}))

        warnings = lens.warnings().warnings
        mismatch = next(item for item in warnings if item["kind"] == "potential-shape-mismatch")
        self.assertEqual("target:input:1", mismatch["target_port"])
        timeline = lens.shape_timeline([source.id, target.id])
        transition = timeline.metadata["transitions"][0]
        self.assertEqual("shape-change", transition["status"])
        self.assertEqual("target:input:1", transition["binding"]["target_port"])

    def test_ambiguous_binding_is_unknown_and_never_guesses_first_port(self) -> None:
        source = Node("source", "Source", "Input", outputs=[Port("out", "out", "output", _tensor([1, 4]))])
        target = Node(
            "target", "Target", "Merge",
            inputs=[Port("a", "a", "input", _tensor([1, 4])), Port("b", "b", "input", _tensor([1, 8]))],
        )
        edge = Edge("edge", source.id, target.id, source_port="out")
        lens = StructureLens(GraphIR("ambiguous", [source, target], [edge], metadata={"source_format": "fixture"}))

        warning = next(item for item in lens.warnings().warnings if item["kind"] == "ambiguous-port-binding")
        self.assertFalse(warning["positive_claim"])
        transition = lens.shape_timeline([source.id, target.id]).metadata["transitions"][0]
        self.assertEqual("unknown", transition["status"])
        self.assertEqual("ambiguous-port", transition["binding"]["target_resolution"])

    def test_keyword_only_pathway_does_not_create_positive_claim(self) -> None:
        graph = GraphIR("placebo", [Node("n", "attention placebo router expert skip", "Identity")])
        lens = StructureLens(graph)
        for kind in ("attention", "moe", "residual"):
            with self.subTest(kind=kind):
                result = lens.pathway(kind)
                self.assertEqual("unknown", result.status)
                self.assertFalse(result.metadata["positive_claim"])
                self.assertFalse(result.metadata["keyword_matches_are_evidence"])
                self.assertEqual(0.0, result.metadata["confidence"])
                self.assertTrue(result.metadata["reason"])
                self.assertEqual(["n"], result.metadata["keyword_candidate_node_ids"])

    def test_queue_generated_state_and_memory_limits_are_hard_and_reported(self) -> None:
        source = Node("source", "Source", "Input")
        targets = [Node(f"n{index}", f"Target {index}", "Identity") for index in range(8)]
        graph = GraphIR("wide", [source, *targets], [Edge(f"e{index}", source.id, node.id) for index, node in enumerate(targets)])
        lens = StructureLens(graph)

        queue_limited = lens.trace(
            source.id,
            direction="downstream",
            budget=AnalysisBudget(maximum_queue_entries=2),
        )
        self.assertEqual("partial", queue_limited.status)
        self.assertEqual("maximum_queue_entries", queue_limited.metadata["terminated_by"])
        self.assertLessEqual(queue_limited.metadata["peak_queue_entries"], 2)

        generated_limited = lens.trace(
            source.id,
            direction="downstream",
            budget=AnalysisBudget(maximum_generated_states=2),
        )
        self.assertEqual("maximum_generated_states", generated_limited.metadata["terminated_by"])
        self.assertEqual(3, generated_limited.metadata["generated_states"])

        memory_limited = lens.bounded_paths(
            source.id,
            targets[-1].id,
            budget=AnalysisBudget(maximum_memory_bytes=1024),
        )
        self.assertEqual("partial", memory_limited.status)
        self.assertEqual("maximum_memory_bytes", memory_limited.metadata["terminated_by"])
        self.assertLessEqual(memory_limited.metadata["peak_estimated_memory_bytes"], 1024)

    def test_cycle_scc_depth_and_elapsed_time_are_bounded(self) -> None:
        nodes = [Node(name, name.upper(), "Identity") for name in ("a", "b", "c", "exit")]
        graph = GraphIR(
            "cycle",
            nodes,
            [
                Edge("ab", "a", "b"),
                Edge("bc", "b", "c"),
                Edge("ca", "c", "a"),
                Edge("ce", "c", "exit"),
            ],
            metadata={"source_format": "fixture"},
        )
        lens = StructureLens(graph)
        trace = lens.trace("a", direction="downstream")
        self.assertEqual("supported", trace.status)
        self.assertEqual({"a", "b", "c", "exit"}, set(trace.node_ids))
        paths = lens.bounded_paths("a", "exit")
        self.assertEqual([["a", "b", "c", "exit"]], paths.paths)
        self.assertTrue(all(len(path) == len(set(path)) for path in paths.paths))

        depth = lens.trace(
            "a", direction="downstream", budget=AnalysisBudget(maximum_depth=1)
        )
        self.assertEqual("partial", depth.status)
        self.assertEqual("maximum_depth", depth.metadata["terminated_by"])

        with patch(
            "nn_davinci.structure_lens.time.perf_counter",
            side_effect=[0.0, 0.02],
        ):
            elapsed = lens.trace(
                "a",
                direction="downstream",
                budget=AnalysisBudget(timeout_seconds=0.01),
            )
        self.assertEqual("partial", elapsed.status)
        self.assertEqual("timeout", elapsed.metadata["terminated_by"])

    def test_multi_input_output_shared_node_preserves_parallel_paths_and_ports(self) -> None:
        left = Node("left", "Left", "Input", outputs=[Port("left:o", "left", "output", _tensor([1, 4]))])
        right = Node("right", "Right", "Input", outputs=[Port("right:o", "right", "output", _tensor([1, 8]))])
        shared = Node(
            "shared",
            "Shared",
            "Split",
            inputs=[
                Port("shared:i0", "left", "input", _tensor([1, 4])),
                Port("shared:i1", "right", "input", _tensor([1, 8])),
            ],
            outputs=[
                Port("shared:o0", "values", "output", _tensor([1, 4])),
                Port("shared:o1", "indices", "output", TensorSpec("indices", [1, 2], "int64")),
            ],
        )
        values = Node("values", "Values", "Identity", inputs=[Port("values:i", "values", "input", _tensor([1, 4]))])
        indices = Node("indices", "Indices", "Identity", inputs=[Port("indices:i", "indices", "input", TensorSpec("indices", [1, 2], "int64"))])
        sink = Node("sink", "Sink", "Concatenate")
        graph = GraphIR(
            "shared multi-port",
            [left, right, shared, values, indices, sink],
            [
                Edge("ls", "left", "shared", "left:o", "shared:i0", _tensor([1, 4])),
                Edge("rs", "right", "shared", "right:o", "shared:i1", _tensor([1, 8])),
                Edge("sv", "shared", "values", "shared:o0", "values:i", _tensor([1, 4])),
                Edge("si", "shared", "indices", "shared:o1", "indices:i", TensorSpec("indices", [1, 2], "int64")),
                Edge("vs", "values", "sink"),
                Edge("is", "indices", "sink"),
            ],
            metadata={"source_format": "fixture"},
        )
        lens = StructureLens(graph)
        result = lens.bounded_paths("left", "sink")
        self.assertEqual(2, len(result.paths))
        self.assertEqual({"sv", "si"}, set(result.edge_ids).intersection({"sv", "si"}))
        evidence = {item["id"]: item for item in result.evidence if item["kind"] == "graph_ir_edge"}
        self.assertEqual("shared:o0", evidence["sv"]["source_port"])
        self.assertEqual("shared:o1", evidence["si"]["source_port"])
        self.assertEqual("int64", evidence["si"]["tensor"]["dtype"])

    def test_semantic_view_detections_are_consulted_before_graph_fallback(self) -> None:
        source = Node("source", "Source", "Input", outputs=[Port("source:o", "out", "output", _tensor([1, 4]))])
        attention = Node(
            "attention",
            "Opaque authored label",
            "MultiHeadAttention",
            inputs=[Port("attention:i", "in", "input", _tensor([1, 4]))],
            outputs=[Port("attention:o", "out", "output", _tensor([1, 4]))],
        )
        sink = Node("sink", "Sink", "Output", inputs=[Port("sink:i", "in", "input", _tensor([1, 4]))])
        graph = GraphIR(
            "semantic attention",
            [source, attention, sink],
            [
                Edge("sa", "source", "attention", "source:o", "attention:i", _tensor([1, 4])),
                Edge("as", "attention", "sink", "attention:o", "sink:i", _tensor([1, 4])),
            ],
            metadata={"source_format": "fixture"},
        )
        semantic = derive_semantic_view(graph)
        result = StructureLens(graph, semantic_view=semantic).pathway("attention")
        self.assertEqual("supported", result.status)
        self.assertTrue(result.metadata["semantic_view_consulted"])
        self.assertTrue(result.metadata["semantic_evidence_prioritized"])
        self.assertTrue(result.metadata["semantic_detection_evidence"])
        self.assertGreaterEqual(result.metadata["confidence"], 0.9)


if __name__ == "__main__":
    unittest.main()
