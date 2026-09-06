from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from nn_davinci.adapters.pytorch import PyTorchAdapter
from nn_davinci.analysis import compare_graphs, visualize_diff
from nn_davinci.diff_corpus import generate_diff_corpus_report
from nn_davinci.paper_production import (
    PAPER_FIGURE_TEMPLATES,
    generate_paper_figure,
    generate_real_paper_examples,
)
from nn_davinci.real_models import import_real_model


class PaperProductionTests(unittest.TestCase):
    def test_eight_templates_and_three_reviewable_opt_in_candidates(self) -> None:
        self.assertEqual(8, len(PAPER_FIGURE_TEMPLATES))
        source = import_real_model("vision_transformer")
        session = generate_paper_figure(source)
        self.assertEqual("transformer-block", session.recommendation.template)
        self.assertEqual(3, len(session.candidates))
        for candidate in session.candidates:
            self.assertGreaterEqual(candidate.minimum_font_pt, 0)
            self.assertGreaterEqual(candidate.crossing, 0)
            self.assertGreaterEqual(candidate.collision, 0)
            self.assertGreaterEqual(candidate.critical_structure_coverage, 0)
            self.assertGreaterEqual(candidate.aggregated_content, 0)
            if candidate.minimum_font_pt < 7:
                self.assertTrue(candidate.warnings)
        before = session.current_layout.to_dict()
        session.apply(session.candidates[0].id)
        self.assertIsNotNone(session.applied_candidate)
        restored = session.undo()
        self.assertEqual(before, restored.to_dict())
        self.assertIn("Graph IR", session.caption)
        self.assertNotIn(str(source.metadata["parameter_total"]), session.caption)

        # Exercise the complete publication path in the existing product test:
        # a semantic overview, bounded detail, final-size vector outputs, and
        # an independent 300 DPI rendering of each landed PDF.
        with tempfile.TemporaryDirectory() as directory:
            report = generate_real_paper_examples(directory)
            self.assertTrue(report["passed"])
            self.assertEqual(3, len(report["examples"]))
            for name, example in report["examples"].items():
                self.assertTrue(example["proof"]["paper_ready"])
                self.assertGreaterEqual(example["proof"]["minimum_font_pt"], 7.0)
                self.assertTrue(example["detail_selection"]["source_node_ids"])
                self.assertGreaterEqual(example["detail_selection"]["repeat_count"], 1)
                scientific = json.loads(
                    (Path(directory) / example["scientific_fidelity"]).read_text(encoding="utf-8")
                )
                self.assertTrue(scientific["passed"])
                self.assertTrue(scientific["invariants"]["all_source_paths_forward"])
                self.assertNotIn("output_0", [item["name"] for item in scientific["source_graph"]["inputs"]])
                if name == "resnet50_overview_bottleneck":
                    self.assertEqual(
                        {"bottleneck_body": 16, "identity_bottleneck": 12, "projection_transition": 4},
                        scientific["repetition"]["family_counts"],
                    )
                    self.assertEqual(2, scientific["panels"]["detail"]["merge_indegree"]["residual_merge"])
                elif name == "vision_transformer_attention":
                    merges = scientific["panels"]["detail"]["merge_indegree"]
                    self.assertEqual(2, merges["attention_residual_merge"])
                    self.assertEqual(2, merges["ffn_residual_merge"])
                    # Q, K, and V are three distinct port bindings from the
                    # same normalized tensor.  They remain three real edges,
                    # but MHA is an attention operation, not a residual merge.
                    self.assertEqual(3, merges["attention"])
                    attention_nodes = [
                        node
                        for node in scientific["panels"]["detail"]["nodes"]
                        if node["role"] == "attention"
                    ]
                    self.assertEqual(1, len(attention_nodes))
                    self.assertEqual("MHA", attention_nodes[0]["op_type"])
                else:
                    overview_edges = {
                        (edge["source_role"], edge["target_role"], edge["kind"])
                        for edge in scientific["panels"]["overview"]["edges"]
                    }
                    self.assertTrue({
                        ("encoder_scale_1", "decoder_scale_1", "skip"),
                        ("encoder_scale_2", "decoder_scale_2", "skip"),
                        ("encoder_scale_3", "decoder_scale_3", "skip"),
                    }.issubset(overview_edges))

    def test_matching_confidence_views_and_state_dict_scope(self) -> None:
        before = import_real_model("vision_transformer")
        after = before.copy()
        after.nodes[3].path = "moved.encoder.block"
        after.nodes[4].parameters += 16
        difference = compare_graphs(before, after)
        self.assertTrue(all(item.status in {"exact", "probable"} for item in difference.matches))
        self.assertTrue(all(0 <= item.confidence <= 1 for item in difference.matches))
        self.assertTrue(all(item.before_operation_ids and item.after_operation_ids for item in difference.matches))
        for view in ("side-by-side", "overlay", "change-only", "summary"):
            with self.subTest(view=view):
                self.assertTrue(visualize_diff(before, after, view=view).nodes)

        try:
            import torch
        except ImportError as exc:
            self.skipTest(str(exc))
        state_before = PyTorchAdapter()._state_dict_graph({"layer.weight": torch.zeros(2, 2)}, "checkpoint-a")
        state_after = PyTorchAdapter()._state_dict_graph({"layer.weight": torch.ones(2, 3)}, "checkpoint-b")
        weights = compare_graphs(state_before, state_after)
        self.assertFalse(weights.summary["structure_claimed"])
        self.assertEqual("weight-groups-only", weights.summary["comparison_scope"])
        self.assertIn("not executable topology", weights.summary["warning"])

    def test_three_fixed_real_model_diff_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = generate_diff_corpus_report(directory, export_figures=False)
        self.assertTrue(report["passed"])
        self.assertEqual(
            {"resnet18_to_resnet50", "transformer_to_moe", "unet_to_attention_unet"},
            set(report["comparisons"]),
        )
        self.assertTrue(all(item["bidirectional_provenance"] for item in report["comparisons"].values()))


if __name__ == "__main__":
    unittest.main()
