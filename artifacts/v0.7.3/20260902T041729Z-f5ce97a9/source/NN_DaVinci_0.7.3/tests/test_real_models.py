from __future__ import annotations

import unittest

from nn_davinci.real_models import (
    REAL_MODEL_VIEWS,
    build_real_model_compatibility_report,
    import_real_model,
    real_model_registry,
)
from nn_davinci.semantic import derive_semantic_view


class RealModelCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            import torch  # noqa: F401
            import torchvision  # noqa: F401
        except ImportError as exc:
            raise unittest.SkipTest(f"real-model optional dependencies unavailable: {exc}") from exc

    def test_seven_models_import_with_evidence_backed_semantics(self) -> None:
        registry = real_model_registry()
        self.assertEqual(7, len(registry))
        for key, spec in registry.items():
            with self.subTest(model=key):
                graph = import_real_model(key, view="operation")
                self.assertTrue(graph.nodes)
                self.assertEqual("operation", graph.metadata["graph_view"])
                self.assertEqual(spec.seed, graph.metadata["random_seed"])
                self.assertEqual("random-initialization; no downloaded weights", graph.metadata["weights"])
                semantic = derive_semantic_view(graph)
                detected = {item["semantic_type"] for item in semantic.detections if not item.get("unknown")}
                self.assertTrue(set(spec.expected_semantics).issubset(detected), (key, spec.expected_semantics, detected))
                for item in semantic.detections:
                    self.assertTrue(item["reasons"])
                    self.assertGreaterEqual(item["confidence"], 0.0)
                    self.assertLessEqual(item["confidence"], 1.0)
                    self.assertIn("source_node_ids", item["provenance"])
                    self.assertIn("source_edge_ids", item["provenance"])

    def test_framework_module_operation_views_are_traceable(self) -> None:
        for view in REAL_MODEL_VIEWS:
            with self.subTest(view=view):
                graph = import_real_model("vision_transformer", view=view)
                self.assertEqual(view, graph.metadata["graph_view"])
                self.assertTrue(graph.nodes)
                for node in graph.nodes:
                    if view != "operation":
                        self.assertTrue(node.attributes["operation_ids"])

    def test_acyclic_diffusion_unet_is_not_falsely_called_a_loop(self) -> None:
        graph = import_real_model("diffusion_unet")
        semantic = derive_semantic_view(graph)
        detected = {item["semantic_type"] for item in semantic.detections if not item.get("unknown")}
        self.assertIn("diffusion_component", detected)
        self.assertIn("timestep_conditioning", detected)
        self.assertNotIn("diffusion_loop", detected)

    def test_resnet50_parameter_total_and_shapes_are_stable(self) -> None:
        graph = import_real_model("resnet50")
        self.assertEqual(25_557_032, sum(node.parameters for node in graph.nodes))
        self.assertEqual([1, 3, 64, 64], graph.inputs[0].shape)
        self.assertEqual([1, 1000], graph.outputs[0].shape)
        report = build_real_model_compatibility_report(repeats=1, names=["vision_transformer"])
        self.assertTrue(report["compatible"])
        self.assertEqual(report["compatible"], report["passed"])


if __name__ == "__main__":
    unittest.main()
