from __future__ import annotations

import unittest

from nn_davinci.metamorphic_corpus import architecture_variants, run_generalization_corpus
from nn_davinci.semantic import derive_semantic_view


class Generalization073Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = run_generalization_corpus(seed=7300)

    def test_seven_renamed_reidentified_reordered_graphs_preserve_claims(self) -> None:
        self.assertEqual("PASS", self.report["status"], self.report["failures"])
        self.assertEqual(7, len(self.report["real_model_metamorphisms"]))
        for key, case in self.report["real_model_metamorphisms"].items():
            with self.subTest(key=key):
                self.assertTrue(case["signature_equal"])
                self.assertTrue(case["provenance_rebound"])

    def test_deleted_family_evidence_degrades_every_claim(self) -> None:
        for key, case in self.report["real_model_metamorphisms"].items():
            with self.subTest(key=key):
                mutation = case["negative_mutation"]
                self.assertGreater(mutation["removed_edge_count"], 0)
                self.assertTrue(mutation["degraded"])

    def test_two_depth_or_width_variants_per_supported_pattern(self) -> None:
        variants = self.report["architecture_variants"]
        for prefix in ("resnet_", "transformer_", "unet_", "moe_", "fusion_"):
            with self.subTest(prefix=prefix):
                self.assertGreaterEqual(sum(name.startswith(prefix) for name in variants), 2)
        for name, result in variants.items():
            with self.subTest(name=name):
                self.assertEqual(result["expected_family"], result["evidence"]["family"])

    def test_variant_counts_follow_structure_instead_of_fixed_corpus_specs(self) -> None:
        evidence = {
            name: derive_semantic_view(graph).architecture_evidence
            for name, graph in architecture_variants().items()
        }
        self.assertEqual(
            [2, 2, 2, 2],
            [role.repeat_count for role in evidence["resnet_repeat_2_2_2_2"].detected_roles if role.role == "residual-stage"],
        )
        self.assertEqual(5, next(role.repeat_count for role in evidence["transformer_depth_5_width_128"].detected_roles if role.role == "attention"))
        self.assertEqual(4, sum(role.role == "encoder-level" for role in evidence["unet_levels_4_width_20"].detected_roles))
        self.assertEqual(6, next(role.repeat_count for role in evidence["moe_experts_6_top2_width80"].detected_roles if role.role == "experts"))
        self.assertIn("top-2", next(role.label for role in evidence["moe_experts_6_top2_width80"].detected_roles if role.role == "router"))
        self.assertEqual(
            {"image-lane", "text-lane", "fusion", "output-head"},
            {role.role for role in evidence["fusion_text_first_width96"].detected_roles},
        )


if __name__ == "__main__":
    unittest.main()
