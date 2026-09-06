from __future__ import annotations

import base64
from copy import deepcopy
import io
import json
import unittest
import zipfile

from nn_davinci.ir import GraphIR, Node
from nn_davinci.server import create_app


class FigureStudioAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = create_app().test_client()

    def test_catalog_template_render_validate_and_project_schema(self) -> None:
        catalog = self.client.get("/api/figure/templates")
        self.assertEqual(200, catalog.status_code)
        self.assertEqual(7, len(catalog.get_json()["templates"]))
        opened = self.client.post("/api/figure/templates/transformer-attention-ffn", json={"page_preset": "178mm"})
        self.assertEqual(200, opened.status_code)
        body = opened.get_json()
        self.assertEqual("1.4", body["project"]["project_version"])
        self.assertIn("<polygon", body["svg"])
        self.assertTrue(body["proof"]["pass"])
        validated = self.client.post("/api/figure/validate", json={"figure": body["figure"]})
        self.assertEqual(200, validated.status_code)
        self.assertEqual("PASS", validated.get_json()["status"])
        project = self.client.post("/api/project", json={"graph": body["graph"], "figure_ir": body["figure"]})
        self.assertEqual("1.4", project.get_json()["project_version"])
        self.assertEqual("1.0", project.get_json()["figure_ir"]["schema_version"])

    def test_persisted_project_validation_canonicalizes_and_rejects_tampering(self) -> None:
        opened = self.client.post("/api/figure/templates/cnn-feature-pipeline", json={}).get_json()
        generated = self.client.post(
            "/api/figure/from-graph",
            json={"graph": opened["graph"], "mode": "schematic"},
        ).get_json()
        authored = self.client.post(
            "/api/project",
            json={
                "name": "Persisted model Figure",
                "graph": opened["graph"],
                "semantic_view": {
                    "version": "1.0",
                    "level": "operation",
                    "view": "faithful",
                    "document": generated["semantic_view"],
                },
                "figure_ir": generated["figure"],
            },
        )
        self.assertEqual(200, authored.status_code)
        persisted = authored.get_json()

        # Canonicalize the compatible prerelease flat Semantic View shape at
        # the persisted-document trust boundary, without changing the legacy
        # unwrapped authoring contract above.
        flat = deepcopy(persisted)
        flat["semantic_view"] = {
            "version": "1.0",
            "level": "operation",
            "view": "faithful",
            **persisted["semantic_view"]["document"],
        }
        validated = self.client.post("/api/project", json={"project": flat})
        self.assertEqual(200, validated.status_code)
        canonical = validated.get_json()
        self.assertEqual(persisted["graph"], canonical["graph"])
        self.assertEqual(
            persisted["semantic_view"]["document"],
            canonical["semantic_view"]["document"],
        )
        self.assertNotIn("entities", canonical["semantic_view"])

        tampered_graph = deepcopy(persisted)
        tampered_graph["graph"]["nodes"][0]["name"] += " (tampered)"
        tampered_semantic = deepcopy(persisted)
        tampered_semantic["semantic_view"]["document"]["source_digest"] = "0" * 64
        tampered_figure = deepcopy(persisted)
        semantic_object = next(
            item
            for page in tampered_figure["figure_ir"]["pages"]
            for panel in page["panels"]
            for layer in panel["layers"]
            for item in layer["objects"]
            if item["provenance"]["kind"] == "semantic_view"
        )
        semantic_object["provenance"]["source_id"] = "orphan-semantic-entity"
        for label, document in {
            "graph": tampered_graph,
            "semantic": tampered_semantic,
            "figure": tampered_figure,
        }.items():
            with self.subTest(tamper=label):
                rejected = self.client.post("/api/project", json={"project": document})
                self.assertEqual(400, rejected.status_code)
                self.assertEqual("validation_error", rejected.get_json()["error"])

        malformed = deepcopy(persisted)
        malformed["unknown_project_field"] = True
        response = self.client.post("/api/project", json={"project": malformed})
        self.assertEqual(400, response.status_code)
        self.assertEqual("Persisted project document is malformed", response.get_json()["message"])

    def test_svg_roundtrip_and_submission_package(self) -> None:
        body = self.client.post("/api/figure/templates/cnn-feature-pipeline", json={}).get_json()
        imported = self.client.post("/api/figure/import-svg", json={"svg": body["svg"]})
        self.assertEqual(200, imported.status_code)
        self.assertTrue(imported.get_json()["native_roundtrip"])
        package = self.client.post("/api/figure/submission-package", json={"figure": body["figure"]})
        self.assertEqual(200, package.status_code)
        with zipfile.ZipFile(io.BytesIO(package.data)) as archive:
            self.assertEqual(
                {
                    "figure.svg", "figure.pdf", "figure.tex", "figure.pptx",
                    "figure.png", "figure.eps", "figure.html",
                    "figure.nndv.json", "caption.md", "provenance.json",
                    "proof.json", "export-policy.json",
                },
                set(archive.namelist()),
            )
            self.assertTrue(json.loads(archive.read("proof.json"))["pass"])
        third_party = self.client.post("/api/figure/import-svg", json={"svg": "<svg xmlns='http://www.w3.org/2000/svg'/>"})
        self.assertFalse(third_party.get_json()["native_roundtrip"])
        self.assertFalse(third_party.get_json()["model_semantics_recovered"])

    def test_structure_lens_http_queries_are_bounded(self) -> None:
        state = self.client.get("/api/state").get_json()
        graph = state["graph"]
        source, target = graph["nodes"][0]["id"], graph["nodes"][-1]["id"]
        trace = self.client.post("/api/structure-lens/downstream", json={"graph": graph, "node_id": source})
        self.assertEqual(200, trace.status_code)
        self.assertIn(trace.get_json()["status"], {"supported", "partial"})
        paths = self.client.post("/api/structure-lens/path", json={
            "graph": graph, "source_id": source, "target_id": target,
            "budget": {"maximum_paths": 2, "maximum_depth": 20, "maximum_visits": 100},
        })
        self.assertEqual(200, paths.status_code)
        self.assertLessEqual(len(paths.get_json()["paths"]), 2)
        self.assertFalse(paths.get_json()["metadata"]["enumerated_all_simple_paths"])

    def test_semantic_cache_rederives_after_supplied_graph_fact_edit(self) -> None:
        state = self.client.get("/api/state").get_json()
        graph = deepcopy(state["graph"])
        cached = self.client.post(
            "/api/semantic",
            json={
                "graph": graph,
                "graph_id": state["graph_id"],
                "level": "operation",
            },
        )
        self.assertEqual(200, cached.status_code)
        cached_digest = cached.get_json()["semantic"]["source_digest"]

        graph["nodes"][0]["name"] += " edited"
        rebuilt = self.client.post(
            "/api/figure/from-graph",
            json={
                "graph": graph,
                "graph_id": state["graph_id"],
                "level": "operation",
                "mode": "mixed",
            },
        )
        self.assertEqual(200, rebuilt.status_code, rebuilt.get_json())
        body = rebuilt.get_json()
        self.assertNotEqual(cached_digest, body["semantic_view"]["source_digest"])
        self.assertTrue(body["provenance_validation"]["passed"])

    def test_structure_lens_http_pathway_prioritizes_semantic_view(self) -> None:
        graph = GraphIR(
            "Semantic attention route",
            [
                Node("input", "Input", "Input"),
                Node("attention", "Attention", "MultiHeadAttention"),
                Node("output", "Output", "Output"),
            ],
        ).validate()
        response = self.client.post(
            "/api/structure-lens/pathway",
            json={"graph": graph.to_dict(), "kind": "attention"},
        )
        self.assertEqual(200, response.status_code)
        result = response.get_json()
        self.assertEqual("supported", result["status"])
        self.assertTrue(result["metadata"]["semantic_view_consulted"])
        self.assertTrue(result["metadata"]["semantic_evidence_prioritized"])
        self.assertTrue(result["metadata"]["positive_claim"])
        self.assertTrue(result["metadata"]["semantic_detection_evidence"])

    def test_complete_figure_and_structure_lens_route_surface(self) -> None:
        opened = self.client.post("/api/figure/templates/cnn-feature-pipeline", json={}).get_json()
        figure, graph = opened["figure"], opened["graph"]
        rendered = self.client.post(
            "/api/figure/render",
            json={"figure": figure, "include_guides": True},
        )
        self.assertEqual(200, rendered.status_code)
        self.assertIn("baseline-guide", rendered.get_json()["svg"])
        self.assertNotIn(
            'id="nndv-figure-ir"',
            rendered.get_json()["svg"],
            "the editor preview must not duplicate the complete Figure IR metadata payload",
        )
        self.assertIn(
            'id="nndv-figure-ir"',
            opened["svg"],
            "persisted/exportable SVG remains metadata-bearing by default",
        )

        encoded = base64.b64encode(opened["svg"].encode("utf-8")).decode("ascii")
        imported = self.client.post("/api/figure/import-svg", json={"data_base64": encoded})
        self.assertEqual(200, imported.status_code)
        self.assertTrue(imported.get_json()["native_roundtrip"])
        malformed = self.client.post("/api/figure/import-svg", json={"data_base64": "%%%"})
        self.assertEqual(400, malformed.status_code)

        expected_signatures = {
            "svg": b"<?xml",
            "pdf": b"%PDF",
            "tikz": b"\\documentclass",
            "tex": b"\\documentclass",
            "pptx": b"PK",
            "png": b"\x89PNG\r\n\x1a\n",
            "eps": b"%!PS-Adobe-3.0 EPSF-3.0",
            "html": b"<!doctype html>",
        }
        for format_name, signature in expected_signatures.items():
            with self.subTest(format=format_name):
                exported = self.client.post(
                    f"/api/figure/export/{format_name}", json={"figure": figure}
                )
                self.assertEqual(200, exported.status_code)
                self.assertTrue(exported.data.startswith(signature))
        with_project = self.client.post(
            "/api/figure/submission-package",
            json={"figure": figure, "project": opened["project"]},
        )
        self.assertEqual(200, with_project.status_code)

        small = self.client.post(
            "/api/figure/from-graph", json={"graph": graph, "mode": "schematic"}
        ).get_json()["figure"]
        self.assertNotIn("large_graph", small["metadata"])
        node_ids = [node["id"] for node in graph["nodes"]]
        operations = {
            "upstream": {"node_id": node_ids[-1]},
            "pathway": {"kind": "residual"},
            "shape-timeline": {"path": node_ids[:2]},
            "warnings": {},
            "overlay": {"metric": "parameters"},
            "repeats": {},
            "unknown": {"node_id": node_ids[0]},
        }
        for operation, payload in operations.items():
            with self.subTest(operation=operation):
                response = self.client.post(
                    f"/api/structure-lens/{operation}",
                    json={"graph": graph, **payload},
                )
                self.assertEqual(200, response.status_code)
                self.assertIn(
                    response.get_json()["status"],
                    {"supported", "partial", "unknown", "unsupported"},
                )
        self.assertEqual(
            400,
            self.client.post("/api/structure-lens/unbounded", json={"graph": graph}).status_code,
        )

    def test_graph_to_figure_forwards_slices_and_reconciles_existing_edits(self) -> None:
        opened = self.client.post("/api/figure/templates/cnn-feature-pipeline", json={}).get_json()
        graph = opened["graph"]
        focus_id = graph["nodes"][1]["id"]

        focused = self.client.post(
            "/api/figure/from-graph",
            json={
                "graph": graph,
                "mode": "schematic",
                "focus_ids": [focus_id, focus_id],
                "focus_hops": 0,
            },
        )
        self.assertEqual(200, focused.status_code)
        focused_body = focused.get_json()
        focus_metadata = focused_body["figure"]["metadata"]["semantic_view"]
        self.assertEqual([focus_id], focus_metadata["focus_ids"])
        self.assertEqual(0, focus_metadata["focus_hops"])
        self.assertTrue(focus_metadata["materialized_focus_ids"])
        self.assertTrue(focused_body["provenance_validation"]["passed"])

        alias = self.client.post(
            "/api/figure/from-graph",
            json={"graph": graph, "mode": "schematic", "focus": [focus_id], "focus_hops": 0},
        )
        self.assertEqual(200, alias.status_code)
        self.assertEqual(
            [focus_id],
            alias.get_json()["figure"]["metadata"]["semantic_view"]["focus_ids"],
        )

        viewport = self.client.post(
            "/api/figure/from-graph",
            json={
                "graph": graph,
                "mode": "schematic",
                "viewport": {"x": 0, "y": 0, "width": 500, "height": 300, "padding": 0},
            },
        )
        self.assertEqual(200, viewport.status_code)
        viewport_body = viewport.get_json()
        viewport_metadata = viewport_body["figure"]["metadata"]["semantic_view"]["viewport"]
        self.assertGreater(viewport_metadata["boundary_proxies"], 0)
        self.assertTrue(viewport_body["provenance_validation"]["passed"])

        initial = self.client.post(
            "/api/figure/from-graph", json={"graph": graph, "mode": "schematic"}
        ).get_json()["figure"]
        node = next(
            item
            for page in initial["pages"]
            for panel in page["panels"]
            for layer in panel["layers"]
            for item in layer["objects"]
            if item["kind"] in {"node-glyph", "operator-glyph"}
        )
        node["geometry"]["x"] += 17.0
        node["locked"] = True
        node["style"]["overrides"]["fill"] = "#123456"
        edge = next(
            item
            for page in initial["pages"]
            for panel in page["panels"]
            for layer in panel["layers"]
            for item in layer["objects"]
            if item["kind"] == "edge"
        )
        edge["manual_route"] = [[12.0, 13.0], [25.0, 18.0], [31.0, 22.0]]
        edge["metadata"]["author_manual_route"] = True
        reconciled = self.client.post(
            "/api/figure/from-graph",
            json={"graph": graph, "mode": "schematic", "existing_figure": initial},
        )
        self.assertEqual(200, reconciled.status_code)
        rebuilt = reconciled.get_json()["figure"]
        rebuilt_objects = {
            item["id"]: item
            for page in rebuilt["pages"]
            for panel in page["panels"]
            for layer in panel["layers"]
            for item in layer["objects"]
        }
        self.assertEqual(node["geometry"], rebuilt_objects[node["id"]]["geometry"])
        self.assertTrue(rebuilt_objects[node["id"]]["locked"])
        self.assertEqual("#123456", rebuilt_objects[node["id"]]["style"]["overrides"]["fill"])
        self.assertEqual(edge["manual_route"], rebuilt_objects[edge["id"]]["manual_route"])
        self.assertEqual("author", rebuilt_objects[edge["id"]]["metadata"]["route_origin"])

        malformed_requests = (
            {"focus_ids": focus_id},
            {"focus_hops": -1},
            {"viewport": []},
            {"viewport": {"unknown": 1}},
            {"existing_figure": []},
        )
        for malformed_payload in malformed_requests:
            with self.subTest(malformed=malformed_payload):
                rejected = self.client.post(
                    "/api/figure/from-graph",
                    json={"graph": graph, "mode": "schematic", **malformed_payload},
                )
                self.assertEqual(400, rejected.status_code)
                self.assertEqual("validation_error", rejected.get_json()["error"])
        non_object = self.client.post("/api/figure/from-graph", json=[])
        self.assertEqual(400, non_object.status_code)
        self.assertEqual("Graph-to-Figure request must be an object", non_object.get_json()["message"])


if __name__ == "__main__":
    unittest.main()
