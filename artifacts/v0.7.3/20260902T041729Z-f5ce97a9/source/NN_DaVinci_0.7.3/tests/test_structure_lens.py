from __future__ import annotations

import unittest

from nn_davinci.ir import Edge, GraphIR, Node, Port, TensorSpec
from nn_davinci.structure_lens import AnalysisBudget, StructureLens


def graph_fixture() -> GraphIR:
    shapes = ([1, 64, 56, 56], [1, 64, 56, 56], [1, 128, 28, 28], [1, 128, 28, 28])
    names = ("Input", "Residual attention", "Router", "Expert")
    ops = ("Input", "MultiHeadAttention", "Router", "Expert")
    nodes = []
    for index, (name, op, shape) in enumerate(zip(names, ops, shapes)):
        tensor = TensorSpec("t", list(shape), "float32")
        nodes.append(Node(
            f"n{index}", name, op, parameters=index * 100,
            inputs=[] if index == 0 else [Port(f"i{index}", "in", "input", tensor)],
            outputs=[Port(f"o{index}", "out", "output", tensor)],
            source={"file": "fixture.py", "line": index + 1},
            analysis={"flops": index * 1_000}, tags=[op.lower()],
        ))
    edges = [
        Edge("e01", "n0", "n1"), Edge("e12", "n1", "n2"), Edge("e23", "n2", "n3", kind="routing"),
        Edge("skip", "n0", "n2", kind="skip", attributes={"residual": True}),
    ]
    return GraphIR("lens", nodes, edges, metadata={"source_format": "fixture"}).validate()


class StructureLensTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lens = StructureLens(graph_fixture())

    def test_upstream_downstream_and_bounded_paths(self) -> None:
        upstream = self.lens.trace("n3", direction="upstream")
        self.assertEqual({"n0", "n1", "n2", "n3"}, set(upstream.node_ids))
        paths = self.lens.bounded_paths("n0", "n3", budget=AnalysisBudget(maximum_paths=4))
        self.assertEqual("supported", paths.status)
        self.assertEqual(2, len(paths.paths))
        self.assertFalse(paths.metadata["enumerated_all_simple_paths"])
        bounded = self.lens.bounded_paths("n0", "n3", budget=AnalysisBudget(maximum_visits=1, maximum_paths=1))
        self.assertEqual("partial", bounded.status)

    def test_pathway_timeline_warning_overlay_repeat_and_unknown(self) -> None:
        self.assertEqual("supported", self.lens.pathway("residual").status)
        self.assertEqual("supported", self.lens.pathway("attention").status)
        self.assertEqual("supported", self.lens.pathway("moe").status)
        timeline = self.lens.shape_timeline(["n0", "n1", "n2", "n3"])
        self.assertEqual("shape-change", timeline.metadata["transitions"][1]["status"])
        warnings = self.lens.warnings()
        self.assertTrue(any(item["kind"] == "potential-shape-mismatch" for item in warnings.warnings))
        parameters = self.lens.metric_overlay("parameters")
        self.assertEqual("supported", parameters.status)
        self.assertEqual(300, parameters.metadata["maximum"])
        self.assertIn(self.lens.repeated_structures().status, {"supported", "unknown"})
        self.assertEqual("unsupported", self.lens.explain_unknown("n1").status)

    def test_cancelled_query_returns_partial_without_positive_completion_claim(self) -> None:
        result = self.lens.trace("n0", direction="downstream", cancelled=lambda: True)
        self.assertEqual("partial", result.status)
        self.assertEqual("cancelled", result.metadata["terminated_by"])


if __name__ == "__main__":
    unittest.main()
