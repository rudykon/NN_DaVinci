from __future__ import annotations

from copy import deepcopy
import unittest

from nn_davinci.architecture_evidence import ArchitectureEvidence
from nn_davinci.architecture_parity import (
    validate_figure_scene_architecture_parity,
    validate_landed_architecture_parity,
)
from nn_davinci.errors import ValidationError
from nn_davinci.ir import Edge, GraphIR, Node
from nn_davinci.model_figure import model_figure_from_graph, validate_model_figure_provenance
from nn_davinci.model_scene import model_scene_from_graph, validate_model_scene_provenance
from nn_davinci.real_models import import_real_model
from nn_davinci.semantic import derive_semantic_view


REAL_MODELS = (
    "resnet50",
    "vision_transformer",
    "bert_encoder",
    "multiscale_unet",
    "diffusion_unet",
    "topk_moe",
    "image_text",
)


class ScientificFidelity072Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.documents = {}
        for name in REAL_MODELS:
            graph = import_real_model(name)
            semantic = derive_semantic_view(graph)
            figure = model_figure_from_graph(
                graph,
                semantic_view=semantic,
                level="stage",
                view="paper",
            )
            scene = model_scene_from_graph(
                graph,
                semantic_view=semantic,
                figure_ir=figure,
                level="stage",
                view="paper",
            )
            cls.documents[name] = (graph, semantic, figure, scene)

    def test_seven_real_models_have_source_bound_architecture_evidence(self) -> None:
        expected_families = {
            "resnet50": "resnet",
            "vision_transformer": "transformer",
            "bert_encoder": "transformer",
            "multiscale_unet": "unet",
            "diffusion_unet": "diffusion-unet",
            "topk_moe": "moe",
            "image_text": "multimodal-fusion",
        }
        for name, expected_family in expected_families.items():
            with self.subTest(name=name):
                graph, semantic, _figure, _scene = self.documents[name]
                evidence = semantic.architecture_evidence
                self.assertIsNotNone(evidence)
                self.assertEqual(expected_family, evidence.family)
                self.assertGreaterEqual(evidence.confidence, 0.9)
                self.assertTrue(evidence.provenance_digest)
                self.assertEqual(semantic.source_digest, evidence.source_digest)
                self.assertTrue(evidence.detected_roles)
                evidence.validate(graph, source_digest=semantic.source_digest)

    def test_scientific_roles_repetitions_and_critical_routes_are_explicit(self) -> None:
        evidence = self.documents["resnet50"][1].architecture_evidence
        residual_stages = [role for role in evidence.detected_roles if role.role == "residual-stage"]
        self.assertEqual([3, 4, 6, 3], [role.repeat_count for role in residual_stages])
        self.assertTrue(all("Bottleneck" in role.label for role in residual_stages))
        self.assertEqual(4, sum(route.role == "residual-skip" for route in evidence.critical_routes))

        for name in ("vision_transformer", "bert_encoder"):
            with self.subTest(name=name):
                transformer = self.documents[name][1].architecture_evidence
                roles = {role.role: role for role in transformer.detected_roles}
                self.assertEqual(3, roles["attention"].repeat_count)
                self.assertEqual(3, roles["feed-forward"].repeat_count)
                self.assertEqual(3, roles["residual-norm"].repeat_count)
        self.assertIn("class token", self.documents["vision_transformer"][1].architecture_evidence.detected_roles[0].label)
        self.assertIn("Token + position", self.documents["bert_encoder"][1].architecture_evidence.detected_roles[0].label)
        self.assertNotIn("fx_trace_error", self.documents["bert_encoder"][0].metadata)

        unet = self.documents["multiscale_unet"][1].architecture_evidence
        self.assertEqual(3, sum(role.role == "encoder-level" for role in unet.detected_roles))
        self.assertEqual(3, sum(role.role == "decoder-level" for role in unet.detected_roles))
        self.assertEqual(3, sum(route.role == "unet-skip" for route in unet.critical_routes))

        diffusion = self.documents["diffusion_unet"][1].architecture_evidence
        self.assertEqual(
            {"input", "conditioning", "down-path", "bottleneck", "up-path", "output-head"},
            {role.role for role in diffusion.detected_roles},
        )
        self.assertEqual(3, sum(route.role == "conditioning" for route in diffusion.critical_routes))
        loop_claim = next(item for item in diffusion.uncertain_claims if item["claim"] == "external_sampling_loop")
        self.assertEqual("unknown", loop_claim["status"])

        moe = self.documents["topk_moe"][1].architecture_evidence
        experts = next(role for role in moe.detected_roles if role.role == "experts")
        self.assertEqual(4, experts.repeat_count)
        self.assertEqual(4, sum(route.role == "expert-branch" for route in moe.critical_routes))
        self.assertEqual(1, sum(route.role == "weighted-combine" for route in moe.critical_routes))

        multimodal = self.documents["image_text"][1].architecture_evidence
        self.assertEqual(
            {"image-lane", "text-lane", "fusion", "output-head"},
            {role.role for role in multimodal.detected_roles},
        )
        self.assertEqual(2, sum(route.role == "multimodal-stream" for route in multimodal.critical_routes))
        multimodal_scene = self.documents["image_text"][3]
        lane_kinds = {
            str(item.metadata.get("architecture_role")): item.kind
            for item in multimodal_scene.iter_objects()
            if item.metadata.get("architecture_role") in {"image-lane", "text-lane"}
        }
        self.assertEqual({"image-lane": "tensor-stack", "text-lane": "token-sequence"}, lane_kinds)
        stream_routes = [item for item in multimodal_scene.iter_objects() if item.metadata.get("architecture_route_role") == "multimodal-stream"]
        self.assertEqual(2, len(stream_routes))
        self.assertTrue(all(len(item.geometry.get("points", [])) >= 3 for item in stream_routes))

    def test_seven_landed_figure_scene_pairs_pass_independent_parity(self) -> None:
        for name, (graph, semantic, figure, scene) in self.documents.items():
            with self.subTest(name=name):
                self.assertTrue(validate_model_figure_provenance(figure, graph, semantic)["passed"])
                self.assertTrue(validate_model_scene_provenance(scene, graph, semantic, figure)["passed"])
                report = validate_landed_architecture_parity(graph, semantic, figure, scene)
                self.assertTrue(report["passed"], report["failures"])
                self.assertEqual(0, figure.metadata["semantic_view"]["publication_projection"]["omitted_critical_edges"])
                self.assertEqual(0, scene.metadata["model_scene_pipeline"]["omitted_critical_edges"])
                self.assertTrue(scene.metadata["model_scene_pipeline"]["protected_semantic_summary"])

    def test_parity_oracle_rejects_deleted_critical_routes(self) -> None:
        cases = {
            "resnet50": "residual-skip",
            "multiscale_unet": "unet-skip",
            "topk_moe": "expert-branch",
            "image_text": "multimodal-stream",
        }
        for name, route_role in cases.items():
            with self.subTest(name=name, route_role=route_role):
                _graph, semantic, figure, scene = self.documents[name]
                mutated = deepcopy(scene)
                layer = next(layer for layer in mutated.layers if any(item.metadata.get("architecture_route_role") == route_role for item in layer.objects))
                victim = next(item for item in layer.objects if item.metadata.get("architecture_route_role") == route_role)
                layer.objects.remove(victim)
                report = validate_figure_scene_architecture_parity(
                    figure,
                    mutated,
                    semantic.architecture_evidence,
                )
                self.assertFalse(report["passed"])
                self.assertTrue(any("scene_critical_routes_mismatch" in failure for failure in report["failures"]))

    def test_parity_oracle_rejects_repeat_role_and_evidence_mutations(self) -> None:
        _graph, semantic, figure, scene = self.documents["topk_moe"]
        repeated = deepcopy(scene)
        experts = next(item for item in repeated.iter_objects() if item.metadata.get("architecture_role") == "experts")
        experts.metadata["repeat_count"] = 3
        self.assertFalse(validate_figure_scene_architecture_parity(figure, repeated, semantic.architecture_evidence)["passed"])

        relabeled = deepcopy(figure)
        role = next(item for item in relabeled.iter_objects() if item.metadata.get("architecture_role_id"))
        role.metadata["architecture_role"] = "fabricated-attention"
        self.assertFalse(validate_figure_scene_architecture_parity(relabeled, scene, semantic.architecture_evidence)["passed"])

        tampered = semantic.architecture_evidence.to_dict()
        tampered["family"] = "transformer"
        with self.assertRaises(ValidationError):
            ArchitectureEvidence.from_dict(tampered)

    def test_names_keys_class_like_ops_and_requested_layout_do_not_create_family_evidence(self) -> None:
        graph = GraphIR(
            "ResNet Attention MoE Diffusion by display name only",
            [
                Node("a", "Residual Router Attention", "NamedContainer"),
                Node("b", "Expert Skip Fusion", "NamedContainer"),
            ],
            [Edge("edge", "a", "b")],
            metadata={
                "corpus_key": "resnet50",
                "model_family": "transformer",
                "python_class": "DiffusionUNet",
                "file_name": "topk_moe.py",
                "graph_view": "module",
            },
        ).validate()
        semantic = derive_semantic_view(graph)
        self.assertEqual("unknown", semantic.architecture_evidence.family)
        browser_roundtrip = semantic.architecture_evidence.to_dict()
        browser_roundtrip["confidence"] = 0
        self.assertEqual(
            semantic.architecture_evidence.provenance_digest,
            ArchitectureEvidence.from_dict(browser_roundtrip).provenance_digest,
        )
        figure = model_figure_from_graph(graph, semantic_view=semantic, level="stage", view="paper")
        scene = model_scene_from_graph(
            graph,
            semantic_view=semantic,
            figure_ir=figure,
            architecture="resnet",
            level="stage",
            view="paper",
        )
        self.assertEqual("unknown", scene.metadata["evidenced_architecture_family"])
        self.assertEqual("resnet", scene.metadata["requested_layout_family"])
        self.assertFalse(any(item.metadata.get("architecture_role_id") for item in figure.iter_objects()))
        report = validate_figure_scene_architecture_parity(
            figure,
            scene,
            semantic.architecture_evidence,
        )
        self.assertTrue(report["passed"], report["failures"])


if __name__ == "__main__":
    unittest.main()
