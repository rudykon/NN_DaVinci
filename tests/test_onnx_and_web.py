from __future__ import annotations

import io
import json
import unittest

from nn_davinci.adapters.onnx import OnnxAdapter


class OptionalIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(__import__("importlib").util.find_spec("onnx"), "onnx is optional")
    def test_onnx_adapter(self):
        from onnx import TensorProto, helper
        x = helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 4])
        y = helper.make_tensor_value_info("y", TensorProto.FLOAT, [1, 3])
        weight = helper.make_tensor("weight", TensorProto.FLOAT, [4, 3], [0.1] * 12)
        node = helper.make_node("MatMul", ["x", "weight"], ["y"], name="projection")
        model = helper.make_model(helper.make_graph([node], "tiny", [x], [y], [weight]))
        graph = OnnxAdapter().load(model)
        self.assertEqual(graph.metadata["source_format"], "onnx")
        self.assertEqual(sum(item.parameters for item in graph.nodes), 12)
        self.assertEqual(len(graph.edges), 2)

    @unittest.skipUnless(__import__("importlib").util.find_spec("flask"), "flask is optional")
    def test_web_api(self):
        from nn_davinci.server import create_app
        client = create_app().test_client()
        state = client.get("/api/state")
        self.assertEqual(state.status_code, 200)
        state_body = state.get_json()
        graph = state_body["graph"]
        app_asset = client.get("/app.js")
        index_asset = client.get("/")
        self.assertIn("beginEdgeDrag", app_asset.get_data(as_text=True))
        self.assertIn("style-parameter-format", index_asset.get_data(as_text=True))
        app_asset.close()
        index_asset.close()
        self.assertIn("tensorflow", {item["name"] for item in state_body["capabilities"]["adapters"]})
        self.assertIn("operator_types", state_body["capabilities"])
        analyzed = client.post("/api/analyze", json={"graph": graph})
        self.assertEqual(analyzed.status_code, 200)
        rendered = client.post("/api/render", json={"graph": graph, "theme": "neurips", "options": {}})
        self.assertEqual(rendered.status_code, 200)
        self.assertIn("<svg", rendered.get_json()["svg"])
        focused = client.post("/api/layout", json={"graph": graph, "focus": [graph["nodes"][2]["id"]], "focus_hops": 0})
        self.assertEqual(focused.status_code, 200)
        self.assertLess(len(focused.get_json()["graph"]["nodes"]), len(graph["nodes"]))
        signatures = {"svg": b"<?xml", "pdf": b"%PDF", "png": b"\x89PNG", "eps": b"%!PS", "pptx": b"PK", "html": b"<!doctype"}
        for format_name, signature in signatures.items():
            exported = client.post(f"/api/export/{format_name}", json={"graph": graph, "theme": "neurips", "options": {}})
            self.assertEqual(exported.status_code, 200, format_name)
            self.assertTrue(exported.data.startswith(signature), format_name)
        tikz = client.post("/api/export/tikz", json={"graph": graph, "theme": "neurips", "options": {}})
        self.assertIn(b"\\begin{tikzpicture}", tikz.data)
        project = client.post("/api/project", json={
            "name": "team", "graph": graph, "focus": [graph["nodes"][2]["id"]],
            "comments": [{"id": "c1", "author": "Ada", "text": "Review", "target_ids": [], "resolved": False}],
            "collaboration": {"members": ["Ada", "Lin"]},
            "presentation": {"teaching_animation": True, "perspective_mode": True},
        })
        body = project.get_json()
        self.assertEqual(body["comments"][0]["author"], "Ada")
        self.assertTrue(body["presentation"]["perspective_mode"])
        self.assertEqual(body["layout"]["focus"], [graph["nodes"][2]["id"]])
        uploaded = client.post("/api/import", data={
            "model": (io.BytesIO(json.dumps(body).encode("utf-8")), "team.nndv"),
        }, content_type="multipart/form-data")
        self.assertEqual(uploaded.status_code, 200)
        self.assertEqual(uploaded.get_json()["graph"]["name"], graph["name"])


if __name__ == "__main__":
    unittest.main()
