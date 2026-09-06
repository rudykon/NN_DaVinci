from __future__ import annotations

from pathlib import Path
import re
import unittest

from nn_davinci.ir import GraphIR
from nn_davinci.model_scene import ARCHITECTURE_FAMILIES
from nn_davinci.scene_ir import Scene
from nn_davinci.server import create_app


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "nn_davinci" / "web"


class SceneTemplateStartCenterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = create_app().test_client()

    def test_start_center_wires_exact_scene_template_catalog_to_open_action(self) -> None:
        index = (WEB / "index.html").read_text(encoding="utf-8")
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn('data-start-section="scene-templates"', index)
        self.assertIn('id="scene-template-list"', index)
        self.assertIn("从可编辑 3D Scene 模板开始", index)
        self.assertIn('api("/api/scene/templates")', app)
        self.assertIn("data-scene-template=", app)
        self.assertIn("openSceneTemplate(", app)
        self.assertIn("`/api/scene/templates/${encodeURIComponent(family)}`", app)
        self.assertIn('state.workspaceMode = "scene"', app)

        match = re.search(
            r"const SCENE_TEMPLATE_FAMILIES = Object\.freeze\((\[[\s\S]*?\])\);",
            app,
        )
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(
            list(ARCHITECTURE_FAMILIES),
            re.findall(r'"([a-z-]+)"', match.group(1)),
        )

    def test_all_seven_open_as_template_only_scene_in_empty_project_1_4(self) -> None:
        catalog_response = self.client.get("/api/scene/templates")
        self.assertEqual(200, catalog_response.status_code)
        catalog = catalog_response.get_json()
        self.assertEqual(
            list(ARCHITECTURE_FAMILIES),
            [item["family"] for item in catalog["templates"]],
        )
        catalog_digests = {
            item["family"]: item["digest"] for item in catalog["templates"]
        }

        for family in ARCHITECTURE_FAMILIES:
            with self.subTest(family=family):
                opened_response = self.client.post(
                    f"/api/scene/templates/{family}", json={}
                )
                self.assertEqual(200, opened_response.status_code)
                opened = opened_response.get_json()
                self.assertEqual(family, opened["family"])
                self.assertEqual(catalog_digests[family], opened["digest"])
                scene = Scene.from_dict(opened["scene"])
                objects = list(scene.iter_objects())
                self.assertGreater(len(objects), 0)
                self.assertTrue(scene.metadata["template_provenance_only"])
                self.assertFalse(scene.metadata["contains_model_evidence"])
                self.assertTrue(
                    all(
                        item.provenance.kind == "template"
                        and not item.provenance.graph_ir_ids
                        and not item.provenance.semantic_view_ids
                        and not item.provenance.figure_ir_ids
                        for item in objects
                    )
                )

                empty_graph = GraphIR(
                    f"{scene.name} · Empty Graph",
                    metadata={
                        "source_format": "manual",
                        "contains_model_evidence": False,
                    },
                ).to_dict()
                saved_response = self.client.post(
                    "/api/project",
                    json={
                        "name": scene.name,
                        "graph": empty_graph,
                        "semantic_view": {
                            "version": "1.0",
                            "level": None,
                            "view": "faithful",
                        },
                        "figure_ir": {},
                        "scene_ir": opened["scene"],
                        "canvas_state": {
                            "workspace_mode": "scene",
                            "scene_selection": [],
                            "scene_camera_id": scene.active_camera_id,
                        },
                    },
                )
                self.assertEqual(200, saved_response.status_code)
                saved = saved_response.get_json()
                self.assertEqual("1.4", saved["project_version"])
                self.assertEqual([], saved["graph"]["nodes"])
                self.assertEqual([], saved["graph"]["edges"])
                self.assertNotIn("document", saved["semantic_view"])
                self.assertEqual(opened["scene"], saved["scene_ir"])

                canonical_response = self.client.post(
                    "/api/project", json={"project": saved}
                )
                self.assertEqual(200, canonical_response.status_code)
                self.assertEqual(saved, canonical_response.get_json())


if __name__ == "__main__":
    unittest.main()
