from __future__ import annotations

from collections import Counter
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from nn_davinci.figure_export import export_figure, figure_proof
from nn_davinci.model_figure import model_figure_from_graph, validate_model_figure_provenance
from nn_davinci.project import Project
from nn_davinci.real_models import import_real_model, real_model_registry
from nn_davinci.semantic import derive_semantic_view


PROJECT = Path(__file__).resolve().parents[1]
ORACLE = PROJECT / "scripts/figure_svg_oracle.mjs"


def _browser_environment() -> dict[str, str]:
    if shutil.which(os.environ.get("NNDV_BROWSER", "google-chrome")) is None:
        raise unittest.SkipTest("Google Chrome is unavailable")
    environment = dict(os.environ)
    local_playwright = PROJECT / "node_modules/playwright-core/index.mjs"
    configured = environment.get("NNDV_PLAYWRIGHT_MODULE")
    if local_playwright.is_file():
        environment.pop("NNDV_PLAYWRIGHT_MODULE", None)
    elif not configured or not Path(configured).is_file():
        raise unittest.SkipTest("playwright-core is unavailable; install npm dependencies or set NNDV_PLAYWRIGHT_MODULE")
    return environment


class RealModelFigure061Tests(unittest.TestCase):
    generated: dict[str, dict]
    temporary: tempfile.TemporaryDirectory[str]

    @classmethod
    def setUpClass(cls) -> None:
        if importlib.util.find_spec("torch") is None or importlib.util.find_spec("torchvision") is None:
            raise unittest.SkipTest("torch and torchvision are required")
        cls.temporary = tempfile.TemporaryDirectory(prefix="nndv-real-model-figures-061-")
        destination = Path(cls.temporary.name)
        cls.generated = {}
        for name in real_model_registry():
            graph = import_real_model(name, view="module")
            semantic = derive_semantic_view(graph)
            figure = model_figure_from_graph(
                graph,
                semantic_view=semantic,
                level="operation",
                view="faithful",
                mode="mixed",
            )
            svg = export_figure(figure, destination / name, formats=("svg",))[0]
            cls.generated[name] = {"graph": graph, "semantic": semantic, "figure": figure, "svg": svg}

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_all_seven_module_graphs_have_bounded_traceable_publication_projections(self) -> None:
        self.assertEqual(set(self.generated), set(real_model_registry()))
        self.assertEqual(len(self.generated), 7)
        for name, item in self.generated.items():
            graph = item["graph"]
            semantic = item["semantic"]
            figure = item["figure"]
            pipeline = figure.metadata["semantic_view"]
            projection = pipeline["publication_projection"]
            self.assertEqual(pipeline["requested_level"], "operation")
            self.assertEqual(pipeline["selected_level"], "stage")
            self.assertIs(pipeline["summary_first"], True)
            self.assertIs(projection["semantic_view_was_executed"], True)
            self.assertEqual(projection["source_node_count"], len(graph.nodes))
            self.assertEqual(projection["source_edge_count"], len(graph.edges))
            self.assertIs(projection["all_source_nodes_mapped"], True)
            self.assertLessEqual(projection["visible_node_count"], 6)
            self.assertEqual(
                projection["output_tensor_inventory_count"],
                sum(len(node.outputs) for node in graph.nodes),
            )
            self.assertIs(validate_model_figure_provenance(figure, graph, semantic)["passed"], True)

            entity_ids = {entity.id for entity in semantic.entities}
            stage_entity_ids = {entity.id for entity in semantic.entities_at("stage")}
            semantic_objects = [
                object_ for object_ in figure.iter_objects()
                if object_.provenance.kind == "semantic_view"
            ]
            self.assertTrue(semantic_objects, name)
            self.assertTrue(all(object_.provenance.source_id in entity_ids for object_ in semantic_objects), name)
            self.assertTrue(all(
                set(object_.provenance.evidence["semantic_entity_ids"]) <= stage_entity_ids
                for object_ in semantic_objects
            ), name)

            provenance_index = figure.metadata["provenance_index"]
            graph_to_figure = provenance_index["graph_to_figure"]
            semantic_to_figure = provenance_index["semantic_to_figure"]
            figure_to_source = provenance_index["figure_to_source"]
            known_graph_ids = {
                *(node.id for node in graph.nodes),
                *(edge.id for edge in graph.edges),
                *(port.id for node in graph.nodes for port in [*node.inputs, *node.outputs]),
            }
            known_port_ids = {
                port.id for node in graph.nodes for port in [*node.inputs, *node.outputs]
            }
            self.assertEqual(known_graph_ids, set(graph_to_figure), name)
            self.assertEqual(stage_entity_ids, set(semantic_to_figure), name)
            for source_id, object_ids in graph_to_figure.items():
                for object_id in object_ids:
                    self.assertIn(source_id, figure_to_source[object_id]["graph_ir_ids"], name)
            for semantic_id, object_ids in semantic_to_figure.items():
                self.assertIn(semantic_id, entity_ids, name)
                for object_id in object_ids:
                    self.assertIn(semantic_id, figure_to_source[object_id]["semantic_ids"], name)
            for object_ in semantic_objects:
                reverse = figure_to_source[object_.id]
                self.assertEqual(object_.provenance.source_id, reverse["semantic_id"], name)
                for semantic_id in reverse["semantic_ids"]:
                    self.assertIn(object_.id, semantic_to_figure[semantic_id], name)
                for graph_id in reverse["graph_ir_ids"]:
                    self.assertIn(object_.id, graph_to_figure[graph_id], name)
                self.assertEqual(
                    set(reverse.get("graph_port_ids", [])),
                    set(reverse["graph_ir_ids"]).intersection(known_port_ids),
                    name,
                )

            linked_ids = {graph_id for object_ in figure.iter_objects() for graph_id in object_.provenance.graph_ir_ids}
            self.assertTrue({node.id for node in graph.nodes} <= linked_ids, name)
            self.assertTrue({edge.id for edge in graph.edges} <= linked_ids, name)
            self.assertTrue(
                {port.id for node in graph.nodes for port in [*node.inputs, *node.outputs]} <= linked_ids,
                name,
            )
            tensor_glyphs = [object_ for object_ in figure.iter_objects() if object_.kind == "tensor-glyph"]
            self.assertTrue(tensor_glyphs)
            self.assertTrue(all(object_.metadata["all_source_output_tensors_preserved"] for object_ in tensor_glyphs))
            self.assertTrue(item["svg"].read_text(encoding="utf-8").startswith("<?xml"))

    def test_all_operation_graph_block_paper_entries_are_compact_traceable_and_spatially_valid(self) -> None:
        for name in real_model_registry():
            with self.subTest(model=name):
                graph = import_real_model(name, view="operation")
                semantic = derive_semantic_view(graph)
                figure = model_figure_from_graph(
                    graph,
                    semantic_view=semantic,
                    level="block",
                    view="paper",
                    mode="mixed",
                )
                pipeline = figure.metadata["semantic_view"]
                projection = pipeline["publication_projection"]
                self.assertEqual("block", pipeline["requested_level"])
                self.assertEqual("block", pipeline["selected_level"])
                self.assertTrue(pipeline["summary_first"])
                self.assertEqual("operation", projection["source_view"])
                self.assertEqual("block", projection["semantic_level"])
                self.assertTrue(projection["all_source_nodes_mapped"])
                self.assertTrue(projection["all_selected_semantic_entities_mapped"])
                self.assertLessEqual(projection["visible_node_count"], 6)
                self.assertLessEqual(len(list(figure.iter_objects())), 30)
                report = validate_model_figure_provenance(figure, graph, semantic)
                self.assertTrue(report["passed"], report)
                proof = figure_proof(figure)
                self.assertTrue(proof["pass"], proof)

    def test_all_seven_persisted_svgs_pass_the_independent_chrome_oracle(self) -> None:
        report_path = Path(self.temporary.name) / "real-model-svg-oracle.json"
        completed = subprocess.run(
            [
                "node",
                str(ORACLE),
                "--output",
                str(report_path),
                *(str(self.generated[name]["svg"]) for name in real_model_registry()),
            ],
            cwd=PROJECT,
            env=_browser_environment(),
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertIs(report["measurement_contract"]["final_dom_only"], True)
        self.assertIs(report["measurement_contract"]["metadata_trusted"], False)
        self.assertEqual(report["summary"], {"files": 7, "passed": 7, "failed": 0, "issues": 0})
        self.assertIs(report["passed"], True)
        for item in report["reports"]:
            self.assertIs(item["passed"], True)
            self.assertEqual(item["issues"], [])
            self.assertGreaterEqual(item["summary"]["minimum_font_pt"], 6.99)
            self.assertLessEqual(item["summary"]["minimum_horizontal_ctm_scale"], 1.001)
            self.assertGreaterEqual(item["summary"]["minimum_horizontal_ctm_scale"], 0.999)
            self.assertGreaterEqual(item["summary"]["minimum_stroke_pt"], 0.1)
            self.assertGreaterEqual(item["occupancy"][0]["bbox_occupancy"], 0.02)
            self.assertLessEqual(item["occupancy"][0]["bbox_occupancy"], 0.98)
            self.assertEqual(Counter(issue["code"] for issue in item["issues"]), Counter())

    def test_all_seven_publication_projects_persist_the_semantic_view_used_by_the_figure(self) -> None:
        self.assertEqual(7, len(self.generated))
        for name, item in self.generated.items():
            project = Project(
                name=item["figure"].name,
                graph=item["graph"],
                semantic_view={
                    "version": "1.0",
                    "level": "stage",
                    "view": "paper",
                    "document": item["semantic"].to_dict(),
                },
                figure_ir=item["figure"].to_dict(),
            )
            restored = Project.from_dict(project.to_dict())
            semantic = restored.persisted_semantic_view()
            self.assertIsNotNone(semantic, name)
            assert semantic is not None
            self.assertEqual(item["semantic"].to_dict(), semantic.to_dict(), name)
            entity_ids = {entity.id for entity in semantic.entities}
            self.assertTrue(all(
                object_.provenance.source_id in entity_ids
                for object_ in item["figure"].iter_objects()
                if object_.provenance.kind == "semantic_view"
            ), name)
