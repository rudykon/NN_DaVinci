from __future__ import annotations

import unittest
from pathlib import Path

from nn_davinci.adapters.manual import ManualAdapter
from nn_davinci.editor import GraphEditor
from nn_davinci.ir import LayoutConstraint
from nn_davinci.layout import LayoutEngine, aggregate_repeated_blocks, unroll_recurrent_graph
from nn_davinci.quality import assess_geometry
from nn_davinci.render import SvgRenderer
from nn_davinci.themes import get_theme


ROOT = Path(__file__).parents[1]


class PaperGeometryTests(unittest.TestCase):
    def _assert_architecture(self, name: str, expected_semantic: str, *, unroll: bool = False):
        graph = ManualAdapter().load(ROOT / "examples" / f"{name}.json")
        if unroll:
            graph = unroll_recurrent_graph(graph, steps=3)
        graph = aggregate_repeated_blocks(graph)
        theme = get_theme("neurips", page="double-column")
        first = LayoutEngine().layout(
            graph,
            algorithm="auto",
            page=theme["page"],
            page_preset="double-column",
            font_size=theme["font_size"],
        )
        second = LayoutEngine().layout(
            graph,
            algorithm="auto",
            page=theme["page"],
            page_preset="double-column",
            font_size=theme["font_size"],
        )
        self.assertEqual(first.to_dict(), second.to_dict(), "layout must be deterministic")
        svg = SvgRenderer().render(graph, first, theme)
        quality = assess_geometry(graph, first, svg)
        self.assertTrue(quality.no_clipping, quality.to_dict())
        self.assertEqual(quality.node_overlap_count, 0, quality.to_dict())
        self.assertEqual(quality.text_overflow_count, 0, quality.to_dict())
        self.assertGreaterEqual(quality.final_body_font_pt, 7, quality.to_dict())
        self.assertGreaterEqual(quality.content_occupancy, 0.18, quality.to_dict())
        self.assertEqual(quality.critical_edges_present, quality.critical_edges_expected)
        semantics = {item["semantic"] for item in first.metadata["critical_edges"]}
        self.assertIn(expected_semantic, semantics)
        self.assertTrue(first.metadata["paper_segments"])
        self.assertTrue(quality.passed, quality.to_dict())
        return graph, first, quality

    def test_resnet_double_column_geometry(self):
        _, _, quality = self._assert_architecture("resnet", "residual")
        self.assertGreater(quality.rendered_content_height, 200, "regression: old output was only about 61 px high")

    def test_transformer_double_column_geometry(self):
        self._assert_architecture("transformer", "attention")

    def test_unet_double_column_geometry(self):
        self._assert_architecture("unet", "skip")

    def test_rnn_double_column_geometry(self):
        self._assert_architecture("rnn", "recurrent", unroll=True)

    def test_moe_double_column_geometry(self):
        graph, _, _ = self._assert_architecture("moe", "routing")
        proxy = next(node for node in graph.nodes if node.attributes.get("repeat_count") == 4)
        self.assertIn("×4", proxy.name)

    def test_multimodal_double_column_geometry(self):
        self._assert_architecture("multimodal", "attention")

    def test_diffusion_double_column_geometry(self):
        self._assert_architecture("diffusion", "diffusion-loop")

    def test_page_presets_are_explicit_and_auto_records_reason(self):
        graph = ManualAdapter().load(ROOT / "examples" / "resnet.json")
        for requested in ("single-column", "double-column", "widescreen", "fit-content", "auto"):
            theme = get_theme(page=requested)
            layout = LayoutEngine().layout(
                graph,
                page=theme["page"],
                page_preset=requested,
                font_size=theme["font_size"],
            )
            paper = layout.metadata["paper"]
            self.assertEqual(paper["requested_page"], requested)
            self.assertTrue(paper["selection_reason"])
            if requested != "auto":
                self.assertEqual(paper["selected_page"], requested)

    def test_locked_position_and_manual_route_survive_page_adaptation(self):
        graph = ManualAdapter().load(ROOT / "examples" / "resnet.json")
        node_id = graph.nodes[2].id
        graph.constraints.append(LayoutConstraint([node_id], "position", {"x": 377, "y": 123}, True))
        base = LayoutEngine().layout(graph, algorithm="resnet")
        edge_id = graph.edges[0].id
        points = [list(point) for point in base.edges[edge_id].points]
        points[1] = [points[1][0], points[1][1] + 51]
        editor = GraphEditor(graph)
        editor.set_edge_route(edge_id, points)
        graph = editor.graph
        theme = get_theme(page="double-column")
        layout = LayoutEngine().layout(
            graph,
            algorithm="resnet",
            page=theme["page"],
            page_preset="double-column",
            font_size=theme["font_size"],
        )
        self.assertEqual((layout.nodes[node_id].x, layout.nodes[node_id].y), (377, 123))
        self.assertEqual(layout.edges[edge_id].points[1], tuple(points[1]))

    def test_impossible_locked_extent_emits_actionable_warning(self):
        graph = ManualAdapter().load(ROOT / "examples" / "resnet.json")
        graph.constraints.append(LayoutConstraint([graph.nodes[-1].id], "position", {"x": 4000, "y": 100}, True))
        theme = get_theme(page="single-column")
        layout = LayoutEngine().layout(
            graph,
            page=theme["page"],
            page_preset="single-column",
            font_size=theme["font_size"],
        )
        self.assertFalse(layout.metadata["paper"]["readable"])
        warning = layout.metadata["paper"]["warnings"][0]
        self.assertIn("fit-content", warning)
        svg = SvgRenderer().render(graph, layout, theme)
        self.assertIn('class="layout-warning"', svg)


if __name__ == "__main__":
    unittest.main()
