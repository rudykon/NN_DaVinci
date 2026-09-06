from __future__ import annotations

import io
import json
import unittest

from nn_davinci.server import create_app


class WebSecurityTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()

    def test_missing_assets_and_favicon_preserve_http_status(self):
        favicon = self.client.get("/favicon.svg")
        self.assertEqual(favicon.status_code, 200)
        favicon.close()
        missing = self.client.get("/favicon.ico")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.get_json()["status"], 404)
        traversal = self.client.get("/../../etc/passwd")
        self.assertEqual(traversal.status_code, 404)

    def test_security_headers_are_present(self):
        response = self.client.get("/")
        self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        response.close()

    def test_malformed_json_is_400_not_500(self):
        response = self.client.post("/api/import", data=b'{"broken":', content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertNotEqual(response.get_json()["error"], "internal_server_error")

    def test_deep_json_is_rejected_with_actionable_400(self):
        value: object = {"name": "leaf"}
        for _ in range(82):
            value = {"nested": value}
        response = self.client.post("/api/import", json=value)
        self.assertEqual(response.status_code, 400)
        self.assertIn("depth", response.get_json()["message"])

    def test_upload_whitelist_and_malformed_onnx(self):
        blocked = self.client.post(
            "/api/import",
            data={"model": (io.BytesIO(b"not executable"), "../../payload.exe")},
            content_type="multipart/form-data",
        )
        self.assertEqual(blocked.status_code, 400)
        malformed = self.client.post(
            "/api/import",
            data={"model": (io.BytesIO(b"not an ONNX protobuf"), "broken.onnx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(malformed.status_code, 400)
        self.assertIn("Malformed ONNX", malformed.get_json()["message"])
        graph = self.client.get("/api/state").get_json()["graph"]
        traversing_name = self.client.post(
            "/api/import",
            data={"model": (io.BytesIO(json.dumps(graph).encode()), "../../model.json")},
            content_type="multipart/form-data",
        )
        self.assertEqual(traversing_name.status_code, 200)
        self.assertEqual(traversing_name.get_json()["graph"]["name"], graph["name"])

    def test_request_size_limit_returns_413(self):
        self.app.config["MAX_CONTENT_LENGTH"] = 512
        response = self.client.post(
            "/api/import",
            data={"model": (io.BytesIO(b"x" * 2048), "large.json")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 413)

    def test_export_format_whitelist(self):
        graph = self.client.get("/api/state").get_json()["graph"]
        response = self.client.post("/api/export/../../secret", json={"graph": graph})
        self.assertGreaterEqual(response.status_code, 400)
        self.assertLess(response.status_code, 500)
        direct = self.client.post("/api/export/exe", json={"graph": graph})
        self.assertEqual(direct.status_code, 400)

    def test_malicious_name_is_text_in_vector_and_html(self):
        graph = self.client.get("/api/state").get_json()["graph"]
        attack = '<img src=x onerror="window.__nndvXss=1"><script>alert(1)</script>'
        graph["nodes"][0]["name"] = attack
        for format_name in ("svg", "html"):
            response = self.client.post(
                f"/api/export/{format_name}",
                json={"graph": graph, "theme": "neurips", "page": "fit-content", "options": {}},
            )
            self.assertEqual(response.status_code, 200)
            text = response.data.decode("utf-8")
            self.assertNotIn(attack, text)
            self.assertNotIn("<script>alert(1)</script>", text)
        html = response.data.decode("utf-8")
        self.assertIn("Content-Security-Policy", html)
        self.assertIn("info.replaceChildren", html)
        self.assertNotIn("info.innerHTML", html)

    def test_project_api_preserves_page_layout_comments_and_presentation(self):
        graph = self.client.get("/api/state").get_json()["graph"]
        response = self.client.post("/api/project", json={
            "name": "roundtrip",
            "graph": graph,
            "theme": "ieee",
            "theme_overrides": {"font_size": 13},
            "layout": {"engine": "resnet", "direction": "TB", "nodes": {}, "edges": {}},
            "layout_options": {"rank_gap": 77, "node_gap": 31},
            "export": {"page": "double-column"},
            "comments": [{"id": "c", "author": "Ada", "text": "review", "target_ids": [], "resolved": False}],
            "presentation": {"teaching_animation": True, "perspective_mode": True},
        })
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["export"]["page"], "double-column")
        self.assertEqual(body["layout"]["layout_options"], {"rank_gap": 77, "node_gap": 31})
        self.assertEqual(body["comments"][0]["author"], "Ada")
        self.assertTrue(body["presentation"]["perspective_mode"])
        imported = self.client.post(
            "/api/import",
            data={"model": (io.BytesIO(json.dumps(body).encode()), "roundtrip.nndv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(imported.status_code, 200)
        self.assertEqual(imported.get_json()["graph"], body["graph"])

    def test_legacy_3d_project_key_migrates_without_being_rewritten(self):
        graph = self.client.get("/api/state").get_json()["graph"]
        response = self.client.post("/api/project", json={
            "name": "legacy-presentation",
            "graph": graph,
            "presentation": {"three_dimensional": True},
        })
        self.assertEqual(response.status_code, 200)
        presentation = response.get_json()["presentation"]
        self.assertTrue(presentation["perspective_mode"])
        self.assertNotIn("three_dimensional", presentation)


if __name__ == "__main__":
    unittest.main()
