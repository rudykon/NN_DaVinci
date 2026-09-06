from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


HAS_TORCH = importlib.util.find_spec("torch") is not None


@unittest.skipUnless(HAS_TORCH, "PyTorch is optional")
class PyTorchRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import torch
        from nn_davinci.adapters.pytorch import PyTorchAdapter
        module_path = Path(__file__).parents[1] / "examples" / "pytorch_tiny.py"
        cls.torch = torch
        cls.sample = torch.randn(1, 3, 16, 16)
        cls.dynamic = PyTorchAdapter()._resolve_model(f"{module_path}:make_model", {"allow_code": True})
        cls.static = PyTorchAdapter()._resolve_model(f"{module_path}:make_static_model", {"allow_code": True})

    def test_fx_and_runtime_fallback(self):
        from nn_davinci.adapters.pytorch import PyTorchAdapter
        adapter = PyTorchAdapter()
        fx_graph = adapter.load(self.static, sample_input=self.sample)
        self.assertEqual(fx_graph.metadata["source_format"], "pytorch_fx")
        self.assertTrue(any(node.op_type == "Conv2d" for node in fx_graph.nodes))
        self.assertEqual(fx_graph.nodes[0].outputs[0].tensor.shape, [1, 3, 16, 16])
        self.assertEqual(fx_graph.nodes[-1].inputs[0].tensor.shape, [1, 3])
        runtime_graph = adapter.load(self.dynamic, sample_input=self.sample)
        self.assertEqual(runtime_graph.metadata["source_format"], "pytorch_runtime")
        self.assertIn("fx_trace_error", runtime_graph.metadata)

    def test_runtime_fallback_counts_reused_weights_once(self):
        from nn_davinci.adapters.pytorch import PyTorchAdapter
        torch = self.torch
        class Reused(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.projection = torch.nn.Linear(4, 4)

            def forward(self, value):
                first = self.projection(value)
                if bool((first.mean() > -100).item()):
                    return self.projection(first)
                return first

        graph = PyTorchAdapter().load(Reused().eval(), sample_input=torch.randn(1, 4))
        self.assertEqual(sum(node.parameters for node in graph.nodes), 20)
        self.assertTrue(any(node.shared_weights for node in graph.nodes))

    def test_fx_tuple_outputs_keep_exact_topk_port_bindings(self):
        import operator

        from nn_davinci.adapters.pytorch import PyTorchAdapter

        torch = self.torch

        class TopKConsumers(torch.nn.Module):
            def forward(self, value):
                values, indices = torch.topk(value, 2, dim=-1)
                return values + indices.to(values.dtype)

        graph = PyTorchAdapter().load(
            TopKConsumers().eval(),
            sample_input=torch.randn(1, 5),
        ).validate()
        topk = next(node for node in graph.nodes if node.name == "topk")
        getitems = [
            node
            for node in graph.nodes
            if node.attributes.get("target") == str(operator.getitem)
        ]
        self.assertEqual(2, len(topk.outputs))
        self.assertEqual(["float32", "int64"], [port.tensor.dtype for port in topk.outputs])
        bindings = {
            graph.node_map()[edge.target].name: (
                edge.source_port,
                edge.target_port,
                edge.tensor.dtype,
            )
            for edge in graph.edges
            if edge.source == topk.id and graph.node_map()[edge.target] in getitems
        }
        self.assertEqual(topk.outputs[0].id, bindings["getitem"][0])
        self.assertEqual("float32", bindings["getitem"][2])
        self.assertEqual(topk.outputs[1].id, bindings["getitem_1"][0])
        self.assertEqual("int64", bindings["getitem_1"][2])

    def test_real_model_module_and_framework_views_preserve_boundaries(self):
        from dataclasses import asdict

        from nn_davinci.adapters.pytorch import PyTorchAdapter
        from nn_davinci.real_models import (
            _framework_view,
            _module_view,
            construct_real_model,
        )

        model, sample, _ = construct_real_model("topk_moe")
        operation = PyTorchAdapter().load(model, sample_input=sample).validate()
        module = _module_view(operation, model)
        originals = operation.edge_map()
        seen_source_edges = []
        for edge in module.edges:
            source_ids = edge.attributes["source_edges"]
            self.assertEqual(1, len(source_ids))
            seen_source_edges.extend(source_ids)
            original = originals[source_ids[0]]
            self.assertEqual(
                {
                    "source_node": original.source,
                    "source_port": original.source_port,
                    "target_node": original.target,
                    "target_port": original.target_port,
                },
                edge.attributes["operation_binding"],
            )
            self.assertIn(edge.source_port, {port.id for port in module.node_map()[edge.source].outputs})
            self.assertIn(edge.target_port, {port.id for port in module.node_map()[edge.target].inputs})
            self.assertEqual(
                asdict(original.tensor) if original.tensor else None,
                asdict(edge.tensor) if edge.tensor else None,
            )
        self.assertEqual(len(seen_source_edges), len(set(seen_source_edges)))

        framework = _framework_view(operation, model)
        self.assertEqual(
            [asdict(tensor) for tensor in operation.inputs],
            [asdict(port.tensor) for port in framework.nodes[0].inputs],
        )
        self.assertEqual(
            [asdict(tensor) for tensor in operation.outputs],
            [asdict(port.tensor) for port in framework.nodes[0].outputs],
        )

    def test_forward_backward_runtime_metrics(self):
        from nn_davinci.adapters.pytorch import PyTorchAdapter
        from nn_davinci.analysis.runtime import RuntimeAnalyzer
        graph = PyTorchAdapter().load(self.dynamic, sample_input=self.sample)
        result = RuntimeAnalyzer().capture(self.dynamic, self.sample, backward_target=lambda output: output.sum(), graph=graph)
        self.assertGreater(result["summary"]["total_duration_ms"], 0)
        self.assertGreater(result["summary"]["gradient_modules"], 0)
        self.assertEqual(result["summary"]["nan_count"], 0)

    def test_input_gradient_and_heatmap_export(self):
        from nn_davinci.analysis.explain import ExplainabilityAnalyzer
        analyzer = ExplainabilityAnalyzer()
        result = analyzer.input_gradient(self.static, self.sample, target_class=1)
        self.assertEqual(list(result.maps[0].shape), list(self.sample.shape))
        with tempfile.TemporaryDirectory() as directory:
            paths = analyzer.save_heatmaps(result, Path(directory) / "saliency.png")
            self.assertTrue(paths[0].exists())

    def test_features_attention_channel_importance_and_pruning(self):
        from nn_davinci.analysis.explain import ExplainabilityAnalyzer
        analyzer = ExplainabilityAnalyzer()
        captured = analyzer.capture_features(self.static, self.sample, target_layers=["conv", "pool"])
        self.assertEqual(set(captured["features"]), {"conv", "pool"})
        scores = analyzer.channel_importance(captured["features"]["conv"][0])
        self.assertEqual(scores.numel(), 6)
        candidates = analyzer.pruning_candidates(captured["features"], fraction=0.25)
        self.assertEqual({item["layer"] for item in candidates}, {"conv", "pool"})
        attention = analyzer.attention(self.static, self.sample, target_layers=["pool"])
        self.assertIn("pool", attention["attention"])

    @unittest.skipUnless(importlib.util.find_spec("torchlens"), "TorchLens is optional")
    def test_torchlens_operation_graph(self):
        from nn_davinci.analysis.torchlens import TorchLensAnalyzer
        result = TorchLensAnalyzer().capture(self.dynamic, self.sample, profile=True)
        self.assertGreater(len(result["graph"].nodes), 5)
        self.assertTrue(result["graph"].metadata["actual_dynamic_path"])

    @unittest.skipUnless(importlib.util.find_spec("torchlens"), "TorchLens is optional")
    def test_torchlens_activations_and_backward_graph(self):
        from nn_davinci.analysis.torchlens import TorchLensAnalyzer
        sample = self.sample.detach().clone().requires_grad_(True)
        result = TorchLensAnalyzer().capture(
            self.static, sample, profile=False, save_activations=True,
            capture_gradients=True, backward_target=lambda output: output.sum(),
        )
        self.assertTrue(getattr(result["trace"], "has_saved_gradients", True))
        self.assertTrue(any(getattr(layer, "out", None) is not None for layer in result["trace"].layer_list))
        self.assertGreater(result["summary"]["gradient_operations"], 0)

    @unittest.skipUnless(importlib.util.find_spec("torchcam"), "TorchCAM is optional")
    def test_gradcam(self):
        from nn_davinci.analysis.explain import ExplainabilityAnalyzer
        result = ExplainabilityAnalyzer().cam(self.static, self.sample, target_layer="conv", target_class=1, method="grad-cam")
        self.assertTrue(result.maps)
        self.assertEqual(result.target_layer, "conv")


if __name__ == "__main__":
    unittest.main()
