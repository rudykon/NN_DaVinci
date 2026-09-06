from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from nn_davinci.figure_export import (
    export_figure,
    export_submission_package,
    figure_proof,
    import_figure_svg,
    render_figure_svg,
)
from nn_davinci.figure_ir import FigureGroup, FigureObject, FigureProvenance, FigureStyle, figure_from_graph, new_figure
from nn_davinci.figure_templates import TEMPLATE_SPECS, instantiate_template, template_project
from nn_davinci.ir import GraphIR
from nn_davinci.project import PROJECT_VERSION, Project


ROOT = Path(__file__).resolve().parents[1]


class FigureIRTests(unittest.TestCase):
    def test_deterministic_roundtrip_layers_groups_and_lock_boundary(self) -> None:
        figure = new_figure("Layer test", panel_modes=("mixed",))
        panel = next(figure.iter_panels())
        source = panel.layers[0]
        target = panel.layers[2]
        first = FigureObject.create(
            "node-glyph", "Evidence node", {"x": 12, "y": 16, "width": 20, "height": 10},
            FigureProvenance("graph_ir", source_id="node-1", graph_ir_ids=["node-1"]), identity="first",
        )
        second = FigureObject.create(
            "annotation", "Author note", {"x": 20, "y": 42}, FigureProvenance.author(), identity="second",
        )
        source.objects.extend([first, second])
        source.groups.append(FigureGroup("group-1", "Evidence", [first.id], FigureProvenance.author()))
        encoded = figure.canonical_json()
        restored = type(figure).from_dict(json.loads(encoded))
        self.assertEqual(encoded, restored.canonical_json())
        restored.move_object(second.id, target.id)
        self.assertEqual(target.role, restored.find_object(second.id)[1].role)
        restored.find_object(second.id)[2].locked = True
        with self.assertRaisesRegex(Exception, "Locked"):
            restored.move_object(second.id, source.id)

    def test_schema_1_2_migration_adds_empty_figure_ir_without_inventing_facts(self) -> None:
        old = Project("legacy", GraphIR("legacy")).to_dict()
        old["project_version"] = "1.2"
        old.pop("figure_ir", None)
        migrated = Project.from_dict(old)
        self.assertEqual("1.4", PROJECT_VERSION)
        self.assertEqual({}, migrated.figure_ir)
        marker = migrated.environment["project_schema_migrations"][-1]
        self.assertEqual("1.2", marker["from"])
        self.assertIn("no tensor shape", marker["reason"])
        self.assertEqual([], migrated.graph.nodes)

    def test_project_1_3_roundtrip_preserves_independent_page_settings_and_order(self) -> None:
        _, first = instantiate_template("cnn-feature-pipeline")
        _, second = instantiate_template("transformer-attention-ffn")
        first_page = first.pages[0]
        second_page = second.pages[0]
        first_page.title = "Portrait evidence"
        first_page.width_mm = 88
        first_page.height_mm = 118
        first_page.margin_mm = 5.5
        first_page.columns = 1
        first_page.column_gap_mm = 3.0
        first_page.baseline_grid_pt = 3.5
        first_page.order = 20
        second_page.title = "Landscape synthesis"
        second_page.width_mm = 178
        second_page.height_mm = 118
        second_page.margin_mm = 7.0
        second_page.columns = 3
        second_page.column_gap_mm = 4.5
        second_page.baseline_grid_pt = 4.0
        second_page.order = 10
        first.pages = [first_page, second_page]
        project = Project("Multi-page", GraphIR("Multi-page"), figure_ir=first.to_dict())
        restored = Project.from_dict(project.to_dict())
        figure = type(first).from_dict(restored.figure_ir)
        self.assertEqual(
            ["Landscape synthesis", "Portrait evidence"],
            [page.title for page in sorted(figure.pages, key=lambda item: item.order)],
        )
        self.assertEqual(
            [
                (178, 118, 7.0, 3, 4.5, 4.0, 10),
                (88, 118, 5.5, 1, 3.0, 3.5, 20),
            ],
            [
                (
                    page.width_mm,
                    page.height_mm,
                    page.margin_mm,
                    page.columns,
                    page.column_gap_mm,
                    page.baseline_grid_pt,
                    page.order,
                )
                for page in sorted(figure.pages, key=lambda item: item.order)
            ],
        )

    def test_svg_metadata_roundtrip_preserves_figure_semantics(self) -> None:
        _, figure = instantiate_template("transformer-attention-ffn")
        tensor = next(item for item in figure.iter_objects() if item.kind == "tensor-glyph")
        tensor.locked = True
        tensor.style = FigureStyle(overrides={"front_fill": "#123456", "font_size": 7.5})
        svg = render_figure_svg(figure)
        self.assertIn("<polygon", svg)
        self.assertNotIn("perspective(", svg)
        restored, native = import_figure_svg(svg)
        self.assertTrue(native)
        recovered = restored.find_object(tensor.id)[2]
        self.assertTrue(recovered.locked)
        self.assertEqual(["B", "T", "D"], recovered.metadata["tensor_shape"])
        self.assertEqual("#123456", recovered.style.overrides["front_fill"])
        self.assertEqual(figure.digest(), restored.digest())

    def test_third_party_svg_is_external_vector_without_model_semantics(self) -> None:
        figure, native = import_figure_svg('<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0L1 1"/></svg>')
        self.assertFalse(native)
        item = next(figure.iter_objects())
        self.assertEqual("external-vector-group", item.kind)
        self.assertEqual("external_vector", item.provenance.kind)
        self.assertFalse(item.metadata["semantic_recovery"])

    def test_templates_are_editable_projects_and_pass_spatial_proof(self) -> None:
        self.assertEqual(7, len(TEMPLATE_SPECS))
        for spec in TEMPLATE_SPECS:
            with self.subTest(template=spec.slug):
                project = template_project(spec.slug)
                restored = Project.from_dict(project)
                figure = type(new_figure("x")).from_dict(restored.figure_ir)
                proof = figure_proof(figure)
                self.assertTrue(proof["pass"], proof)
                self.assertEqual(0, proof["overflow"])
                self.assertEqual(0, proof["node_tensor_overlap"])
                self.assertEqual(0, proof["edge_node_collision"])
                self.assertEqual(0, proof["clipping"])
                self.assertEqual(0, proof["unexplained_crossing"])
                self.assertGreaterEqual(proof["minimum_font_pt"], 7)
                self.assertIsNone(proof["horizontal_text_scale"])
                self.assertIsNone(proof["transform_text_scale"])
                self.assertFalse(proof["final_output_verified"])
                self.assertFalse(proof["release_blocker_eligible"])
                self.assertEqual({"schematic", "tensor-geometry"}, {panel.mode for panel in figure.iter_panels()})

    def test_four_vector_formats_and_submission_package(self) -> None:
        _, figure = instantiate_template("cnn-feature-pipeline")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outputs = export_figure(figure, root / "standalone", formats=("svg", "pdf", "tikz", "pptx"))
            self.assertEqual({".svg", ".pdf", ".tex", ".pptx"}, {item.suffix for item in outputs})
            self.assertTrue((root / "standalone.svg").read_text(encoding="utf-8").startswith("<?xml"))
            self.assertTrue((root / "standalone.pdf").read_bytes().startswith(b"%PDF"))
            self.assertIn("\\documentclass", (root / "standalone.tex").read_text(encoding="utf-8"))
            with zipfile.ZipFile(root / "standalone.pptx") as archive:
                slide = archive.read("ppt/slides/slide1.xml")
                self.assertIn(b"NNDV editable", slide)
                self.assertNotIn(b"<p:pic>", slide)
            package = export_submission_package(figure, root / "submission")
            self.assertEqual(
                {
                    "figure.svg", "figure.pdf", "figure.tex", "figure.pptx",
                    "figure.png", "figure.eps", "figure.html",
                    "figure.nndv.json", "caption.md", "provenance.json",
                    "proof.json", "export-policy.json",
                },
                {item.name for item in package},
            )
            project = json.loads((root / "submission" / "figure.nndv.json").read_text(encoding="utf-8"))
            self.assertEqual(PROJECT_VERSION, project["project_version"])
            self.assertEqual("1.0", project["scene_ir"]["schema_version"])

    def test_graph_conversion_preserves_unknown_shapes(self) -> None:
        graph = GraphIR.from_dict({
            "name": "Unknown", "nodes": [{
                "id": "n", "name": "Dynamic", "op_type": "Input", "outputs": [{
                    "id": "p", "name": "out", "direction": "output",
                    "tensor": {"shape": [None, "T", 768], "dtype": "float32"},
                }],
            }],
        })
        figure = figure_from_graph(graph, mode="tensor-geometry")
        tensor = next(item for item in figure.iter_objects() if item.kind == "tensor-glyph")
        self.assertEqual([None, "T", 768], tensor.metadata["tensor_shape"])
        self.assertEqual("[?, T, 768]", tensor.metadata["shape_label"])


if __name__ == "__main__":
    unittest.main()
