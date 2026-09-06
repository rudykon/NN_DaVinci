from __future__ import annotations

import unittest

from nn_davinci.adapters.manual import ManualAdapter
from nn_davinci.analysis import RuntimeAnalyzer, analyze_graph
from nn_davinci.reporting import generate_markdown_report


class AnalysisAccuracyTests(unittest.TestCase):
    def test_manual_conv_formula_macs_activation_depth_and_receptive_field(self):
        graph = ManualAdapter().load({
            "name": "hand-checkable",
            "nodes": [
                {"name": "Input", "type": "Input", "category": "input", "outputs": [{"shape": [1, 3, 32, 32], "dtype": "float32"}]},
                {
                    "name": "Conv",
                    "type": "Conv2D",
                    "category": "convolution",
                    "parameters": 224,
                    "inputs": [[1, 3, 32, 32]],
                    "outputs": [{"shape": [1, 8, 30, 30], "dtype": "float32"}],
                    "attributes": {"kernel_size": [3, 3], "stride": 1},
                },
                {
                    "name": "Pool",
                    "type": "MaxPool",
                    "category": "pooling",
                    "inputs": [[1, 8, 30, 30]],
                    "outputs": [{"shape": [1, 8, 15, 15], "dtype": "float32"}],
                    "attributes": {"kernel_size": 2, "stride": 2},
                },
                {"name": "Unknown", "type": "ResearchOp", "inputs": [[1, 8, 15, 15]], "outputs": [[1, 8, 15, 15]]},
                {"name": "Output", "type": "Output", "category": "output", "inputs": [[1, 8, 15, 15]]},
            ],
            "edges": [["Input", "Conv"], ["Conv", "Pool"], ["Pool", "Unknown"], ["Unknown", "Output"]],
        })
        result = analyze_graph(graph)
        summary = result["summary"]
        convolution = next(node for node in result["graph"].nodes if node.name == "Conv")
        pooling = next(node for node in result["graph"].nodes if node.name == "Pool")
        self.assertEqual(convolution.analysis["flops"], 388_800)
        self.assertEqual(convolution.analysis["macs"], 194_400)
        self.assertEqual(summary["macs_estimate"], 194_400)
        self.assertAlmostEqual(summary["flops_coverage"], 2 / 3)
        self.assertFalse(summary["flops_complete"])
        self.assertEqual(len(summary["unknown_flop_nodes"]), 1)
        self.assertEqual(convolution.analysis["activation_bytes"], 1 * 8 * 30 * 30 * 4)
        self.assertEqual(pooling.analysis["receptive_field"]["width"], 4)
        self.assertEqual(summary["depth"], 5)
        self.assertEqual(summary["multiply_add_convention"], "one multiply-add = 2 FLOPs and 1 MAC")

    def test_dynamic_shapes_and_cycles_report_partial_coverage_not_zero_cost(self):
        graph = ManualAdapter().load({
            "name": "dynamic-cycle",
            "nodes": [
                {"name": "A", "type": "ResearchOp", "outputs": [["batch", 4]]},
                {"name": "B", "type": "Add", "inputs": [["batch", 4]], "outputs": [["batch", 4]]},
            ],
            "edges": [["A", "B"], ["B", "A"]],
        })
        summary = analyze_graph(graph)["summary"]
        self.assertEqual(summary["flops"], 0)
        self.assertEqual(summary["flops_coverage"], 0)
        self.assertFalse(summary["flops_complete"])
        self.assertEqual(summary["activation_memory_coverage"], 0)
        self.assertFalse(summary["activation_memory_complete"])
        self.assertTrue(summary["cyclic_nodes"])
        self.assertIn("bounded estimate", summary["depth_label"])
        self.assertTrue(any("not added as zero-cost" in item for item in summary["limitations"]))

    def test_runtime_uses_warmup_repeated_iterations_and_statistics(self):
        import torch

        from nn_davinci.adapters.pytorch import PyTorchAdapter

        model = torch.nn.Sequential(torch.nn.Linear(4, 8), torch.nn.ReLU(), torch.nn.Linear(8, 2)).eval()
        sample = torch.ones(16, 4)
        graph = PyTorchAdapter().load(model, sample_input=sample)
        result = RuntimeAnalyzer().capture(model, sample, graph=graph, warmup=2, iterations=9)
        latency = result["summary"]["latency_ms"]
        self.assertEqual(latency["label"], "measured end-to-end")
        self.assertEqual(latency["warmup_iterations"], 2)
        self.assertEqual(latency["measured_iterations"], 9)
        self.assertGreater(latency["median"], 0)
        self.assertLessEqual(latency["min"], latency["median"])
        self.assertGreaterEqual(latency["max"], latency["median"])
        self.assertGreater(result["summary"]["runtime_coverage"], 0)
        self.assertTrue(result["summary"]["limitations"])

    def test_report_shows_value_coverage_labels_and_limitations(self):
        graph = ManualAdapter().load({
            "name": "report-coverage",
            "layers": [
                {"name": "Input", "type": "Input", "category": "input", "outputs": [[1, 4]]},
                {"name": "Unknown", "type": "UnknownResearchOperator", "outputs": [[1, 4]]},
                {"name": "Output", "type": "Output", "category": "output", "inputs": [[1, 4]]},
            ],
        })
        report = generate_markdown_report(graph)
        self.assertIn("FLOPs known subtotal", report)
        self.assertIn("Coverage / label", report)
        self.assertIn("covered operators only", report)
        self.assertIn("multiply-add", report)
        self.assertIn("## Analysis notes", report)


if __name__ == "__main__":
    unittest.main()
