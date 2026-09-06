from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET

from nn_davinci.model_figure import model_figure_from_graph
from nn_davinci.model_scene import model_scene_from_graph
from nn_davinci.real_models import import_real_model
from nn_davinci.scene_export import export_scene
from nn_davinci.semantic import derive_semantic_view


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("semantic_presentation_oracle_073", ROOT / "scripts" / "semantic_presentation_oracle_0_7_3.py")
assert SPEC is not None and SPEC.loader is not None
ORACLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ORACLE)


class SemanticPresentationOracle073Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.good = cls.root / "good"
        cls.good.mkdir()
        graph = import_real_model("resnet50", view="module")
        semantic = derive_semantic_view(graph)
        figure = model_figure_from_graph(graph, semantic_view=semantic, level="stage", view="paper")
        scene = model_scene_from_graph(graph, semantic_view=semantic, figure_ir=figure, level="stage", view="paper")
        export_scene(scene, cls.good / "scene", formats=["svg", "pdf", "tikz"])
        (cls.good / "semantic.semantic.json").write_text(json.dumps(semantic.to_dict()), encoding="utf-8")
        cls.evidence = semantic.architecture_evidence

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def _mutation(self, name: str) -> Path:
        destination = self.root / name
        shutil.copytree(self.good, destination)
        return destination

    def _svg(self, destination: Path) -> tuple[ET.ElementTree, ET.Element]:
        tree = ET.parse(destination / "scene.svg")
        return tree, tree.getroot()

    def _codes(self, destination: Path) -> set[str]:
        report = ORACLE.inspect_case(destination, require_pptx=False)
        self.assertEqual("FAIL", report["status"])
        return {item["code"] for item in report["blockers"]}

    def test_complete_landed_svg_pdf_and_tikz_pass(self) -> None:
        report = ORACLE.inspect_case(self.good, require_pptx=False)
        self.assertEqual("PASS", report["status"], report["blockers"])
        self.assertEqual(6, report["expected_role_count"])
        self.assertEqual(4, report["expected_route_count"])

    def test_deleted_role_label_is_blocked(self) -> None:
        destination = self._mutation("deleted-label")
        tree, root = self._svg(destination)
        victim = next(item for item in root.iter() if item.attrib.get("data-kind") == "label")
        for parent in root.iter():
            if victim in list(parent):
                parent.remove(victim)
                break
        tree.write(destination / "scene.svg", encoding="utf-8", xml_declaration=True)
        self.assertIn("svg_missing_role_label", self._codes(destination))

    def test_metadata_only_hidden_label_is_blocked(self) -> None:
        destination = self._mutation("hidden-label")
        tree, root = self._svg(destination)
        victim = next(item for item in root.iter() if item.attrib.get("data-kind") == "label")
        victim.set("style", "display:none")
        tree.write(destination / "scene.svg", encoding="utf-8", xml_declaration=True)
        self.assertIn("svg_hidden_role_label", self._codes(destination))

    def test_off_page_label_is_blocked(self) -> None:
        destination = self._mutation("off-page-label")
        tree, root = self._svg(destination)
        victim = next(item for item in root.iter() if item.attrib.get("data-kind") == "label")
        victim.set("x", "99999")
        tree.write(destination / "scene.svg", encoding="utf-8", xml_declaration=True)
        self.assertIn("svg_role_label_off_page", self._codes(destination))

    def test_wrong_role_binding_is_blocked(self) -> None:
        destination = self._mutation("wrong-binding")
        tree, root = self._svg(destination)
        labels = [item for item in root.iter() if item.attrib.get("data-kind") == "label"]
        labels[0].set("data-architecture-role-id", labels[1].attrib["data-architecture-role-id"])
        tree.write(destination / "scene.svg", encoding="utf-8", xml_declaration=True)
        self.assertIn("svg_role_binding_mismatch", self._codes(destination))

    def test_deleted_and_reversed_routes_are_blocked(self) -> None:
        deleted = self._mutation("deleted-route")
        tree, root = self._svg(deleted)
        route_id = self.evidence.critical_routes[0].id
        for parent in root.iter():
            for child in list(parent):
                if child.attrib.get("data-architecture-route-id") == route_id:
                    parent.remove(child)
        tree.write(deleted / "scene.svg", encoding="utf-8", xml_declaration=True)
        self.assertIn("svg_missing_route", self._codes(deleted))

        reversed_route = self._mutation("reversed-route")
        tree, root = self._svg(reversed_route)
        arrow = next(
            item for item in root.iter()
            if item.attrib.get("data-kind") == "arrow" and item.attrib.get("data-architecture-route-id")
        )
        endpoints = json.loads(arrow.attrib["data-endpoint-role-ids"])
        arrow.set("data-architecture-direction", "target-to-source")
        arrow.set("data-endpoint-role-ids", json.dumps(list(reversed(endpoints))))
        tree.write(reversed_route / "scene.svg", encoding="utf-8", xml_declaration=True)
        codes = self._codes(reversed_route)
        self.assertIn("svg_route_direction_mismatch", codes)
        self.assertIn("svg_route_endpoint_mismatch", codes)

    def test_repeat_count_mutation_is_blocked(self) -> None:
        destination = self._mutation("repeat-count")
        tree, root = self._svg(destination)
        victim = next(item for item in root.iter() if item.attrib.get("data-kind") == "label" and item.attrib.get("data-repeat-count") == "3")
        victim.set("data-repeat-count", "99")
        tree.write(destination / "scene.svg", encoding="utf-8", xml_declaration=True)
        self.assertIn("svg_repeat_count_mismatch", self._codes(destination))

    def test_stale_evidence_digest_is_blocked(self) -> None:
        destination = self._mutation("stale-digest")
        tree, root = self._svg(destination)
        victim = next(item for item in root.iter() if item.attrib.get("data-kind") == "label")
        victim.set("data-evidence-digest", "0" * 64)
        tree.write(destination / "scene.svg", encoding="utf-8", xml_declaration=True)
        self.assertIn("stale_evidence_digest", self._codes(destination))

if __name__ == "__main__":
    unittest.main()
