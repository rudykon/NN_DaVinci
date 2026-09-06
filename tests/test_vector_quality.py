from __future__ import annotations

import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch

from nn_davinci.ir import Annotation, Edge, GraphIR, Node, Port, Subgraph, TensorSpec
from nn_davinci.labels import node_label_lines, required_label_text
from nn_davinci.layout import EdgeRoute, LayoutEngine, NodePlacement
from nn_davinci.render import SvgRenderer, TikzRenderer, export_graph
from nn_davinci.themes import get_theme


ROOT = Path(__file__).parents[1]


class LabelDensityTests(unittest.TestCase):
    def setUp(self):
        output = Port("out", "out", "output", TensorSpec(shape=[1, 128, 32, 32], dtype="float32"))
        self.node = Node(
            "a", "A deliberately long convolution label", "Conv2D", "convolution",
            outputs=[output], parameters=1_234_567, analysis={"flops": 9_876_543, "activation_bytes": 4096},
            attributes={"bias": 64},
        )
        self.theme = get_theme()

    def test_compact_paper_detailed_required_content_and_wrapping(self):
        compact = node_label_lines(self.node, self.theme, density="compact", max_width=80)
        paper = node_label_lines(self.node, self.theme, density="paper", max_width=80)
        detailed = node_label_lines(self.node, self.theme, density="detailed", max_width=80)
        self.assertEqual({line.role for line in compact}, {"name", "op-type"})
        self.assertTrue({"name", "op-type", "shape", "parameters", "flops"} <= {line.role for line in paper})
        self.assertIn("analysis-activation_bytes", {line.role for line in detailed})
        self.assertIn("bias", {line.role for line in detailed})
        self.assertGreater(len(compact), 2, "long names must wrap instead of compressing glyphs")
        self.assertEqual(required_label_text(self.node, self.theme), [line.text for line in node_label_lines(self.node, self.theme)])
        with self.assertRaises(ValueError):
            node_label_lines(self.node, self.theme, density="unknown")

    def test_svg_and_tikz_render_option_branches_without_glyph_compression(self):
        self.node.attributes.update({"icon_href": "data:image/png;base64,AA==", "fill": "#abcdef", "opacity": 0.7})
        self.node.tags.extend(["diff-added", "collapsed"])
        removed = Node("b", "Removed", "Add", "merge", tags=["diff-removed"], analysis={"flops": 2})
        changed = Node("c", "Changed", "Output", "output", tags=["diff-changed"], visible=True)
        edge = Edge("ab", "a", "b", kind="control", label="control", attributes={"arrow": "both", "color": "#123456", "line_width": 2, "dashed": True})
        graph = GraphIR(
            "renderer branches", [self.node, removed, changed], [edge],
            subgraphs=[Subgraph("g", "First group", ["a"]), Subgraph("g2", "Second group", ["b"])],
            annotations=[
                Annotation("text", "title", "Heading", geometry={"x": 2, "y": 4}),
                Annotation("region", "region", "Region", geometry={"x": 1, "y": 2, "width": 30, "height": 20}),
                Annotation("image", "image", style={"href": "data:image/png;base64,AA=="}, geometry={"x": 5, "y": 6}),
                Annotation("arrow", "arrow", "Note", geometry={"x": 1, "y": 2, "x2": 20, "y2": 22}),
                Annotation("unknown", "unknown", "ignored"),
                Annotation("panel", "panel-label", "Panel", panel="left"),
            ],
        ).validate()
        theme = get_theme(page="fit-content")
        layout = LayoutEngine().layout(graph, page=theme["page"], page_preset="fit-content", label_density="detailed")
        layout.metadata["panels"] = {"left": {"x": 0, "y": 0, "width": 220, "height": 130}}
        layout.groups["g2"] = dict(layout.groups["g"])
        layout.groups["missing"] = {"x": 0, "y": 0, "width": 10, "height": 10}
        layout.edges["missing"] = EdgeRoute([(0, 0), (1, 1)])
        layout.nodes["missing"] = NodePlacement(0, 0, 1, 1)
        svg = SvgRenderer().render(
            graph, layout, theme, title="Options", transparent=True, embed_metadata=False,
            analysis_metric="flops", label_density="detailed", crop=True,
        )
        self.assertNotIn("textLength=", svg)
        self.assertNotIn("lengthAdjust=", svg)
        self.assertIn('data-horizontal-scale-estimate="1"', svg)
        self.assertIn('data-label-density="detailed"', svg)
        self.assertIn('marker-start="url(#arrow)"', svg)
        self.assertIn("annotation-image", svg)
        self.assertNotIn("<metadata>", svg)
        tikz = TikzRenderer().render(graph, layout, theme, standalone=False, title="Options", show_legend=False, label_density="detailed")
        self.assertIn(r"$\times$", tikz)
        self.assertNotIn("\\documentclass", tikz)
        self.assertIn("NNDV-LABEL a analysis-activation_bytes", tikz)
        self.assertIn("\\draw[<->", tikz)
        with_legend = TikzRenderer().render(graph, layout, theme, label_density="compact")
        self.assertIn("\\documentclass", with_legend)

    def test_publication_layer_removes_editor_controls_but_preserves_moe_provenance(self):
        node = Node("expert", "Expert ×4", "ExpertMLP", "operation", tags=["collapsed"], attributes={"repeat_count": 4})
        graph = GraphIR("MoE publication", [node]).validate()
        theme = get_theme(page="fit-content")
        layout = LayoutEngine().layout(graph, page=theme["page"], page_preset="fit-content")
        publication = SvgRenderer().render(graph, layout, theme)
        editor = SvgRenderer().render(graph, layout, theme, publication=False)
        self.assertIn("Expert ×4", publication)
        self.assertNotIn("⊞", publication)
        self.assertNotIn("editor-control", publication)
        self.assertIn("⊞", editor)
        captured: dict[str, bytes] = {}

        def fake_png(**kwargs):
            captured["source"] = kwargs["bytestring"]
            Path(kwargs["write_to"]).write_bytes(b"\x89PNG\r\n\x1a\npublication-test")

        with tempfile.TemporaryDirectory() as directory, patch("cairosvg.svg2png", side_effect=fake_png):
            export_graph(graph, layout, theme, Path(directory) / "moe", formats=["png"])
        source = captured["source"].decode("utf-8")
        self.assertIn("Expert ×4", source)
        self.assertNotIn("⊞", source)


class OracleSourceIsolationTests(unittest.TestCase):
    def test_oracle_has_fixed_tolerances_and_no_layout_quality_import(self):
        source = (ROOT / "scripts/svg_quality_oracle.mjs").read_text(encoding="utf-8")
        self.assertIn("bboxPx: 0.5", source)
        self.assertIn("safetyGapPx: 1.0", source)
        self.assertIn("fontPt: 0.05", source)
        self.assertIn("occupancy: 0.01", source)
        self.assertIn("endpointRadiusPx: 1.0", source)
        self.assertNotIn("nn_davinci.layout", source)
        self.assertNotIn("nn_davinci.quality", source)
        flattener = (ROOT / "scripts/svg_path_flatten.js").read_text(encoding="utf-8")
        self.assertIn("controlHullFlatness", flattener)
        self.assertIn("deCasteljau", flattener)
        self.assertNotIn("getPointAtLength", flattener)
        fixture_source = (ROOT / "scripts/generate_svg_oracle_fixtures.py").read_text(encoding="utf-8")
        for name in ("s-curve", "loop-curve", "multi-turn-curve"):
            self.assertIn(name, fixture_source)


if __name__ == "__main__":
    unittest.main()
