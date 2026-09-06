from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from nn_davinci.api import render_project, scene_from_graph
from nn_davinci.model_scene import (
    ARCHITECTURE_FAMILIES,
    model_scene_from_graph,
    scene_template,
    validate_model_scene_provenance,
)
from nn_davinci.project import Project
from nn_davinci.scene_ir import Scene
from nn_davinci.server import create_app


class SceneStudioAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = create_app().test_client()

    def test_template_catalog_projection_validation_and_capabilities(self) -> None:
        catalog = self.client.get("/api/scene/templates")
        self.assertEqual(200, catalog.status_code)
        self.assertEqual(list(ARCHITECTURE_FAMILIES), [item["family"] for item in catalog.get_json()["templates"]])

        opened = self.client.post("/api/scene/templates/transformer", json={})
        self.assertEqual(200, opened.status_code)
        body = opened.get_json()
        self.assertEqual("1.0", body["scene"]["schema_version"])
        self.assertEqual("nndv-scene-projection-1", body["projection"]["schema_version"])
        self.assertIn("<svg", body["svg"])
        self.assertTrue(body["scene"]["metadata"]["template_provenance_only"])
        self.assertTrue(all(item.provenance.kind == "template" for item in Scene.from_dict(body["scene"]).iter_objects()))

        validated = self.client.post("/api/scene/validate", json={"scene": body["scene"]})
        self.assertEqual(200, validated.status_code)
        self.assertEqual("PASS", validated.get_json()["status"])
        capabilities = self.client.get("/api/capabilities").get_json()
        self.assertEqual("1.4", capabilities["scene_studio"]["project_schema"])
        self.assertTrue(capabilities["scene_studio"]["cpu_projection"])

    def test_graph_to_scene_has_exact_provenance_and_persists_in_project_1_4(self) -> None:
        state = self.client.get("/api/state").get_json()
        generated = self.client.post(
            "/api/scene/from-graph",
            json={
                "graph_id": state["graph_id"],
                "architecture": "transformer",
                "level": "operation",
                "view": "faithful",
                "projection": "orthographic",
            },
        )
        self.assertEqual(200, generated.status_code)
        body = generated.get_json()
        self.assertTrue(body["provenance_validation"]["passed"])
        self.assertTrue(body["scene"]["metadata"]["provenance_index"]["graph_to_scene"])

        saved = self.client.post(
            "/api/project",
            json={
                "name": "Scene project",
                "graph": state["graph"],
                "semantic_view": {
                    "version": "1.0",
                    "level": "operation",
                    "view": "faithful",
                    "document": body["semantic_view"],
                },
                "scene_ir": body["scene"],
                "export": {"workspace": "scene", "formats": ["svg", "json"]},
            },
        )
        self.assertEqual(200, saved.status_code)
        project = saved.get_json()
        self.assertEqual("1.4", project["project_version"])
        self.assertEqual(body["scene"], project["scene_ir"])
        canonical = self.client.post("/api/project", json={"project": project})
        self.assertEqual(200, canonical.status_code)
        self.assertEqual(project["scene_ir"], canonical.get_json()["scene_ir"])

    def test_pick_transform_and_every_scene_download_surface(self) -> None:
        scene = scene_template("cnn")
        first = next(scene.iter_objects())
        transformed = self.client.post(
            "/api/scene/transform",
            json={
                "scene": scene.to_dict(),
                "object_ids": [first.id],
                "operation": "translate",
                "value": [1.0, 2.0, 3.0],
            },
        )
        self.assertEqual(200, transformed.status_code)
        restored = Scene.from_dict(transformed.get_json()["scene"])
        _, moved = restored.find_object(first.id)
        self.assertEqual([1.0, 2.0, 3.0], moved.transform.position)
        self.assertEqual([first.id], restored.selection_ids)

        picked = self.client.post(
            "/api/scene/pick",
            json={"scene": restored.to_dict(), "x": 600, "y": 400, "viewport": [1200, 800]},
        )
        self.assertEqual(200, picked.status_code)
        self.assertIsInstance(picked.get_json()["hits"], list)

        expected_types = {
            "svg": "image/svg+xml",
            "eps": "application/postscript",
            "json": "application/json",
            "gltf": "model/gltf+json",
            "glb": "model/gltf-binary",
        }
        for format_name, content_type in expected_types.items():
            with self.subTest(format=format_name):
                response = self.client.post(f"/api/scene/export/{format_name}", json={"scene": scene.to_dict()})
                self.assertEqual(200, response.status_code)
                self.assertGreater(len(response.data), 32)
                self.assertEqual(content_type, response.content_type.split(";", 1)[0])

    def test_scene_routes_reject_malformed_or_unsupported_documents(self) -> None:
        scene = scene_template("resnet").to_dict()
        malformed = deepcopy(scene)
        malformed["unexpected"] = True
        rejected = self.client.post("/api/scene/validate", json={"scene": malformed})
        self.assertEqual(400, rejected.status_code)
        self.assertIn("unexpected", rejected.get_json()["message"].lower())

        unsupported = self.client.post("/api/scene/export/obj", json={"scene": scene})
        self.assertEqual(400, unsupported.status_code)
        missing_graph = self.client.post("/api/scene/from-graph", json={"focus_ids": [1]})
        self.assertEqual(400, missing_graph.status_code)


class ScenePythonIntegrationTests(unittest.TestCase):
    def test_fifty_thousand_node_scene_stays_bounded_and_focus_recovers_exact_ids(self) -> None:
        from scripts.stress_graphs import deep_chain

        graph = deep_chain(50_000)
        summary = model_scene_from_graph(graph, architecture="cnn", maximum_objects=250)
        pipeline = summary.metadata["model_scene_pipeline"]
        self.assertTrue(pipeline["summary_first"])
        self.assertEqual(50_000, pipeline["source_node_count"])
        self.assertEqual("digest-and-bounded-representatives", pipeline["summary_provenance_mode"])
        self.assertLessEqual(sum(1 for _ in summary.iter_objects()), 250)
        self.assertLess(len(summary.canonical_json()), 1_500_000)
        summary_sources = [
            item.metadata["summary_source"]
            for item in summary.iter_objects()
            if item.metadata.get("summary_source")
        ]
        self.assertTrue(summary_sources)
        self.assertTrue(all(not source["representatives_are_complete_membership"] for source in summary_sources))
        self.assertTrue(all(len(source["source_node_ids_sha256"]) == 64 for source in summary_sources))
        self.assertTrue(validate_model_scene_provenance(summary, graph)["passed"])

        focused = model_scene_from_graph(
            graph,
            architecture="cnn",
            focus_ids=["n25000"],
            focus_hops=1,
            maximum_objects=250,
        )
        focused_ids = {
            identifier
            for item in focused.iter_objects()
            for identifier in item.metadata.get("graph_ir_node_ids", [])
        }
        self.assertEqual({"n24999", "n25000", "n25001"}, focused_ids)
        self.assertEqual("exact-source-ids", focused.metadata["model_scene_pipeline"]["summary_provenance_mode"])

    def test_python_scene_api_and_explicit_project_workspace_export(self) -> None:
        from nn_davinci.ir import GraphIR, Node
        from nn_davinci.semantic import derive_semantic_view

        graph = GraphIR(
            "API Scene",
            nodes=[Node.create("Input", "Input"), Node.create("Dense", "Linear")],
        ).validate()
        semantic = derive_semantic_view(graph)
        scene = scene_from_graph(graph, architecture="cnn")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = Project(
                "API Scene",
                graph,
                semantic_view={
                    "version": "1.0",
                    "level": "operation",
                    "view": "faithful",
                    "document": semantic.to_dict(),
                },
                scene_ir=scene.to_dict(),
                export={
                    "workspace": "scene",
                    "output": str(root / "api-scene.svg"),
                    "formats": ["svg", "json", "glb"],
                },
            )
            outputs = render_project(project)
            self.assertEqual([".svg", ".json", ".glb"], [path.suffix for path in outputs])
            self.assertTrue(all(path.is_file() and path.stat().st_size > 32 for path in outputs))
            scene_document = json.loads(outputs[1].read_text(encoding="utf-8"))
            self.assertEqual("1.0", scene_document["schema_version"])


if __name__ == "__main__":
    unittest.main()
