from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import zipfile

from nn_davinci.composer import FigureComposer, FigurePanel, SemanticPanelConnection
from nn_davinci.api import load_graph
from nn_davinci.ir import GraphIR
from nn_davinci.project import PROJECT_VERSION, Project


ROOT = Path(__file__).resolve().parents[1]


class FigureComposerTests(unittest.TestCase):
    def graph(self, name: str) -> GraphIR:
        return load_graph(ROOT / "examples" / name, adapter="manual")

    def test_four_panels_keep_independent_layout_and_semantic_connections(self) -> None:
        source = self.graph("unet.json")
        panels = [
            FigurePanel("A", "Overview", source, "model", "paper"),
            FigurePanel("B", "Encoder and decoder", source, "stage", "paper"),
            FigurePanel("C", "Block detail", source, "block", "faithful"),
            FigurePanel("D", "Operations", source, "operation", "faithful"),
        ]
        resolved = [panel.resolved_graph() for panel in panels]
        connection = SemanticPanelConnection.create("A", resolved[0].nodes[0].id, "B", resolved[1].nodes[0].id, label="zoom-in")
        composer = FigureComposer("U-Net overview and detail", panels, connections=[connection])
        graph, layout, proof = composer.compose()
        self.assertEqual(4, graph.metadata["figure_composer"]["panel_count"])
        semantic_edges = [edge for edge in graph.edges if edge.kind == "semantic-connection"]
        self.assertEqual(1, len(semantic_edges))
        self.assertTrue(semantic_edges[0].attributes["not_model_data_edge"])
        self.assertEqual(4, len(layout.metadata["panels"]))
        self.assertEqual(4, proof["panel_count"])
        prior = dict(layout.metadata["panel_layout_digests"])
        _, changed, _ = composer.compose(relayout_panels={"C"})
        for panel_id in ("A", "B", "D"):
            self.assertEqual(prior[panel_id], changed.metadata["panel_layout_digests"][panel_id])

    def test_project_1_0_and_1_1_migrate_to_composer_schema(self) -> None:
        project = Project("legacy", self.graph("resnet.json"))
        for old_version in ("1.0", "1.1"):
            with self.subTest(version=old_version):
                payload = project.to_dict()
                payload["project_version"] = old_version
                payload.pop("figure_composer", None)
                migrated = Project.from_dict(payload)
                self.assertEqual(PROJECT_VERSION, migrated.project_version)
                self.assertEqual({}, migrated.figure_composer)
                self.assertEqual(old_version, migrated.environment["project_schema_migrations"][-1]["from"])

    def test_project_roundtrip_preserves_composer_recovery_state(self) -> None:
        source = self.graph("transformer.json")
        composer = FigureComposer(
            "Researcher recovery figure",
            [
                FigurePanel("A", "Overview", source, "stage", "paper"),
                FigurePanel("B", "Operation detail", source, "operation", "paper"),
            ],
            page_preset="wide-two-column",
            arrangement="horizontal",
        )
        panel = composer.panels[1]
        panel_layout = composer.layout_panel("B")
        node_id = next(iter(panel_layout.nodes))
        edge_id = next(iter(panel_layout.edges))
        panel.locked_node_ids.append(node_id)
        panel_layout.nodes[node_id].locked = True
        panel.manual_routes[edge_id] = [list(point) for point in panel_layout.edges[edge_id].points]
        composer.set_panel_layout("B", panel_layout)
        graph, layout, _ = composer.compose()
        project = Project(
            "Composer recovery",
            graph,
            layout={"algorithm": "auto", "direction": "LR", "result": layout.to_dict()},
            figure_composer=composer.to_dict(),
            canvas_state={
                "view_box": {"x": 12.0, "y": 18.0, "width": 960.0, "height": 582.3},
                "zoom": 1.25,
                "fixed_layout": True,
            },
        )
        restored = Project.from_dict(project.to_dict())
        restored_composer = FigureComposer.from_dict(restored.figure_composer)
        self.assertEqual("Researcher recovery figure", restored_composer.title)
        self.assertEqual("wide-two-column", restored_composer.page_preset)
        self.assertEqual("horizontal", restored_composer.arrangement)
        self.assertEqual([node_id], restored_composer.panels[1].locked_node_ids)
        self.assertEqual(panel.manual_routes, restored_composer.panels[1].manual_routes)
        self.assertEqual(layout.metadata["panel_layout_digests"], restored.layout["result"]["metadata"]["panel_layout_digests"])
        self.assertEqual(1.25, restored.canvas_state["zoom"])
        self.assertTrue(restored.canvas_state["fixed_layout"])

    def test_full_figure_exports_seven_formats_and_split_tikz(self) -> None:
        source = self.graph("transformer.json")
        composer = FigureComposer(
            "Transformer overview and attention detail",
            [
                FigurePanel("A", "Overview", source, "stage", "paper"),
                FigurePanel("B", "Attention block", source, "block", "paper"),
            ],
        )
        with tempfile.TemporaryDirectory() as directory:
            outputs = composer.export(
                Path(directory) / "figure.svg",
                formats=("svg", "pdf", "tikz", "png", "eps", "pptx"),
                tikz_panels=True,
            )
            names = {path.name for path in outputs}
            self.assertTrue({"figure.svg", "figure.pdf", "figure.tex", "figure.png", "figure.eps", "figure.pptx", "figure_A.tex", "figure_B.tex"}.issubset(names))
            for path in outputs:
                self.assertGreater(path.stat().st_size, 0)
            svg = (Path(directory) / "figure.svg").read_text(encoding="utf-8")
            self.assertIn('width="178mm"', svg)
            self.assertIn('height="118mm"', svg)
            self.assertIn('data-measurement="pillow-glyph-advance"', svg)
            with zipfile.ZipFile(Path(directory) / "figure.pptx") as archive:
                self.assertIn("ppt/slides/slide1.xml", archive.namelist())


if __name__ == "__main__":
    unittest.main()
