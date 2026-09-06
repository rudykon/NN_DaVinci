from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

from nn_davinci.api import load_graph, render, semantic_view
from nn_davinci.import_wizard import inspect_import, saved_import_config
from nn_davinci.ir import LayoutConstraint
from nn_davinci.layout import LayoutEngine
from nn_davinci.optimizer import PaperOptimizer, apply_suggestion, assess_paper_metrics, proof_preview
from nn_davinci.project import PROJECT_VERSION, Project
from nn_davinci.semantic import SEMANTIC_LEVELS, SemanticView, derive_semantic_view
from nn_davinci.server import create_app
from nn_davinci.tasks import TaskManager
from nn_davinci.themes import get_theme
from nn_davinci.viewport import lazy_summary, viewport_slice
from scripts.stress_graphs import deep_chain


ROOT = Path(__file__).parents[1]


class SemanticViewTests(unittest.TestCase):
    def test_five_levels_are_independent_versioned_and_bidirectionally_traceable(self):
        graph = load_graph(ROOT / "examples" / "resnet.json")
        original = graph.to_dict()
        semantic = derive_semantic_view(graph)
        self.assertEqual(tuple(SEMANTIC_LEVELS), ("model", "stage", "block", "layer", "operation"))
        self.assertEqual(semantic.semantic_version, "1.0")
        self.assertTrue(all(semantic.entities_at(level) for level in SEMANTIC_LEVELS))
        self.assertEqual(graph.to_dict(), original)
        source_id = graph.nodes[3].id
        block_ids = semantic.trace_semantic(source_id, level="block")
        self.assertTrue(block_ids)
        self.assertIn(source_id, semantic.trace_source(block_ids[0]).source_node_ids)
        restored = SemanticView.from_dict(semantic.to_dict())
        self.assertEqual(restored.to_dict(), semantic.to_dict())

    def test_required_semantics_have_confidence_reasons_and_provenance(self):
        expected = {
            "resnet": "residual_block",
            "transformer": "attention",
            "unet": "unet_skip",
            "moe": "moe_router_experts",
            "diffusion": "diffusion_loop",
        }
        for fixture, semantic_type in expected.items():
            with self.subTest(fixture=fixture):
                graph = load_graph(ROOT / "examples" / f"{fixture}.json")
                detections = [item for item in derive_semantic_view(graph).detections if item["semantic_type"] == semantic_type]
                self.assertTrue(detections)
                self.assertGreater(detections[0]["confidence"], 0.5)
                self.assertTrue(detections[0]["reasons"])
                provenance = detections[0]["provenance"]
                self.assertTrue(provenance["source_node_ids"])
                if semantic_type == "unet_skip":
                    self.assertTrue(provenance["source_edge_ids"])

    def test_unknown_is_explicit_and_faithful_paper_views_do_not_mutate_source(self):
        graph = load_graph({"name": "Opaque", "layers": [{"name": "x", "type": "CustomThing"}]})
        semantic = derive_semantic_view(graph)
        unknown = [entity for entity in semantic.entities_at("block") if entity.unknown]
        self.assertEqual(len(unknown), 1)
        self.assertLess(unknown[0].confidence, 0.5)
        before = graph.to_dict()
        faithful = semantic.materialize(graph, level="block", view="faithful")
        paper = semantic.materialize(graph, level="block", view="paper")
        self.assertTrue(faithful.metadata["semantic_view"]["faithful"])
        self.assertFalse(paper.metadata["semantic_view"]["faithful"])
        self.assertEqual(graph.to_dict(), before)

    def test_python_api_and_project_migrate_level_view_state(self):
        graph = load_graph(ROOT / "examples" / "transformer.json")
        self.assertIsInstance(semantic_view(graph), SemanticView)
        legacy = Project("legacy", graph).to_dict()
        legacy["project_version"] = "1.0"
        for key in ("semantic_view", "canvas_state", "import_configurations", "task_history", "paper_workflow"):
            legacy.pop(key, None)
        migrated = Project.from_dict(legacy)
        self.assertEqual(migrated.project_version, PROJECT_VERSION)
        self.assertIn("project_schema_migrations", migrated.environment)
        self.assertIsNone(migrated.semantic_view["level"])
        with tempfile.TemporaryDirectory() as directory:
            outputs = render(
                graph, Path(directory) / "block.svg", level="block", view="paper",
                formats=("svg",), analyze=False,
            )
            self.assertIn("Block", outputs[0].read_text(encoding="utf-8"))


class LazyCanvasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = deep_chain(10_000)

    def test_10k_summary_first_view_and_viewport_budgets(self):
        started = time.perf_counter()
        summary = lazy_summary(self.graph)
        first_seconds = time.perf_counter() - started
        # coverage.py traces every Python line and is not a meaningful wall-clock
        # environment. The uninstrumented unit run and real-Chrome E2E retain the
        # actual two-second product gate.
        self.assertLessEqual(first_seconds, 5.0 if sys.gettrace() else 2.0)
        self.assertIn(summary["recommended_level"], {"model", "stage", "block"})
        started = time.perf_counter()
        result = viewport_slice(self.graph, {"x": 0, "y": 0, "width": 960, "height": 540})
        wall_ms = (time.perf_counter() - started) * 1000
        self.assertLessEqual(result.rendered_node_count, 500)
        self.assertLessEqual(result.dom_object_estimate, 2_000)
        self.assertLessEqual(result.elapsed_ms, 200)
        self.assertLessEqual(wall_ms, 200)
        self.assertTrue(result.layout.metadata["lazy"])

    def test_boundary_proxies_are_stable_and_source_traceable(self):
        first = viewport_slice(self.graph, {"x": 0, "y": 0, "width": 200, "height": 160, "padding": 0})
        second = viewport_slice(self.graph, {"x": 0, "y": 0, "width": 200, "height": 160, "padding": 0})
        first_proxies = {node.id: node.attributes for node in first.graph.nodes if node.attributes.get("boundary_proxy")}
        second_proxies = {node.id: node.attributes for node in second.graph.nodes if node.attributes.get("boundary_proxy")}
        self.assertTrue(first_proxies)
        self.assertEqual(first_proxies, second_proxies)
        self.assertTrue(all(item["stable_stub"] for item in first_proxies.values()))


class ImportWizardTests(unittest.TestCase):
    def test_safe_formats_and_restricted_code_pickle(self):
        manual = inspect_import("model.json", json.dumps({"layers": [{"name": "x", "type": "Linear"}]}))
        self.assertEqual(manual.detected_format, "manual-config")
        self.assertEqual(manual.safety["level"], "safe-data")
        factory = inspect_import("model.py", "def make_model(): pass")
        self.assertTrue(factory.safety["confirmation_required"])
        checkpoint = inspect_import("weights-state.pth", b"not-a-safe-pickle")
        self.assertEqual(checkpoint.detected_format, "pytorch-state-dict")
        self.assertFalse(checkpoint.topology_available)
        self.assertIn("cannot recover model topology", checkpoint.diagnostics[0]["message"])

    def test_sample_multi_dynamic_scale_recommendation_and_saved_config(self):
        payload = {"nodes": [{"name": f"n{i}", "op_type": "Linear"} for i in range(2_501)], "edges": []}
        plan = inspect_import("large.json", json.dumps(payload))
        self.assertTrue(plan.sample_input["supports_multiple_inputs"])
        self.assertIn("dynamic", plan.sample_input["dynamic_dimension_syntax"].lower())
        self.assertTrue(plan.recommendation["summary_first"])
        self.assertIn(plan.recommendation["semantic_level"], {"stage", "block"})
        saved = saved_import_config(plan, {"sample_inputs": [{"shape": [1, 3, 32, 32]}], "allow_code": False})
        self.assertEqual(saved["source"]["filename"], "large.json")
        self.assertEqual(saved["options"]["sample_inputs"][0]["shape"], [1, 3, 32, 32])


class LocalTaskTests(unittest.TestCase):
    def test_success_failure_cancel_retry_and_refresh_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = TaskManager(directory, workers=1)
            success = manager.submit("analyze", lambda context: (context.report("done", 0.9), {"value": 7})[1])
            succeeded = self._wait(manager, success.id)
            self.assertEqual(succeeded["status"], "succeeded")
            self.assertEqual(manager.get(success.id, include_result=True)["result"]["value"], 7)

            attempts = {"count": 0}

            def flaky(_context):
                attempts["count"] += 1
                if attempts["count"] == 1:
                    raise ValueError("sample input shape missing")
                return {"recovered": True}

            failed = manager.submit("import", flaky)
            failure = self._wait(manager, failed.id)
            self.assertEqual(failure["status"], "failed")
            self.assertTrue(any(item["id"] == "sample-input" for item in failure["recovery_actions"]))
            retried = manager.retry(failed.id)
            self.assertEqual(self._wait(manager, retried.id)["status"], "succeeded")

            def cooperative(context):
                for index in range(200):
                    context.report("loop", index / 200)
                    time.sleep(0.01)
                return {}

            cancelled = manager.submit("layout", cooperative)
            time.sleep(0.04)
            cancelled_at = time.perf_counter()
            manager.cancel(cancelled.id)
            result = self._wait(manager, cancelled.id)
            self.assertEqual(result["status"], "cancelled")
            self.assertLess(time.perf_counter() - cancelled_at, 1.0)
            manager.shutdown(wait=True)

            restored = TaskManager(directory)
            self.assertEqual(restored.get(success.id)["status"], "succeeded")
            restored.shutdown()

            cleanup_root = Path(directory) / "cleanup"
            cleanup_root.mkdir()
            expired = cleanup_root / "expired.json"
            recent = cleanup_root / "recent.json"
            expired.write_text("{}", encoding="utf-8")
            recent.write_text("{}", encoding="utf-8")
            expired_time = time.time() - 120
            os.utime(expired, (expired_time, expired_time))
            cleanup_manager = TaskManager(cleanup_root, retention_seconds=60)
            self.assertFalse(expired.exists())
            self.assertTrue(recent.exists())
            cleanup_manager.shutdown()

    @staticmethod
    def _wait(manager: TaskManager, task_id: str) -> dict:
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            record = manager.get(task_id)
            if record["status"] not in {"queued", "running"}:
                return record
            time.sleep(0.01)
        raise AssertionError("task did not finish")


class PaperOptimizerTests(unittest.TestCase):
    def test_three_reviewable_candidates_metrics_proof_apply_undo_and_protection(self):
        graph = load_graph(ROOT / "examples" / "resnet.json")
        base = LayoutEngine().layout(graph, algorithm="resnet")
        node_id = graph.nodes[2].id
        edge_id = graph.edges[0].id
        graph.constraints.extend([
            LayoutConstraint([node_id], "position", {"x": base.nodes[node_id].x, "y": base.nodes[node_id].y}, True),
            LayoutConstraint([edge_id], "edge-route", {"points": [list(point) for point in base.edges[edge_id].points]}, True),
        ])
        base = LayoutEngine().layout(graph, algorithm="resnet", previous=base)
        style = get_theme("neurips", page="double-column")
        suggestions = PaperOptimizer().suggest(graph, base, style, maximum_candidates=3)
        self.assertEqual(len(suggestions), 3)
        for suggestion in suggestions:
            self.assertEqual(set(suggestion.before.to_dict()), {
                "node_overlap", "edge_node_collision", "crossing", "bend_count", "path_length",
                "symmetry", "whitespace_balance", "label_overflow", "minimum_font", "critical_edge_salience",
            })
            self.assertEqual(suggestion.layout.nodes[node_id].x, base.nodes[node_id].x)
            self.assertEqual(suggestion.layout.edges[edge_id].points[1:-1], base.edges[edge_id].points[1:-1])
            self.assertIn(node_id, suggestion.diff.protected_nodes)
            self.assertIn(edge_id, suggestion.diff.protected_edges)
            self.assertIn("body_font_pt", proof_preview(suggestion.layout))
        applied, undo = apply_suggestion(base, suggestions[0])
        self.assertEqual(undo.to_dict(), base.to_dict())
        self.assertEqual(applied.to_dict(), suggestions[0].layout.to_dict())
        self.assertIsNotNone(assess_paper_metrics(graph, applied))


class SemanticServerTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        self.state = self.client.get("/api/state").get_json()

    def test_semantic_summary_viewport_neighborhood_optimizer_and_tasks_api(self):
        graph_id = self.state["graph_id"]
        summary = self.client.post("/api/summary", json={"graph_id": graph_id})
        self.assertEqual(summary.status_code, 200)
        semantic = self.client.post("/api/semantic", json={"graph_id": graph_id, "level": "block", "view": "paper"})
        self.assertEqual(semantic.status_code, 200)
        self.assertTrue(semantic.get_json()["semantic"]["source_to_semantic"]["block"])
        viewport = self.client.post("/api/viewport", json={
            "graph_id": graph_id, "level": "operation", "view": "faithful",
            "viewport": {"x": 0, "y": 0, "width": 320, "height": 240},
        })
        self.assertEqual(viewport.status_code, 200)
        self.assertLessEqual(viewport.get_json()["dom_object_estimate"], 2_000)
        node_id = self.state["graph"]["nodes"][0]["id"]
        neighborhood = self.client.post("/api/neighborhood", json={"graph_id": graph_id, "node_ids": [node_id], "hops": 1})
        self.assertEqual(neighborhood.status_code, 200)

        task = self.client.post("/api/tasks", json={"kind": "analyze", "graph_id": graph_id})
        self.assertEqual(task.status_code, 202)
        task_id = task.get_json()["id"]
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            record = self.client.get(f"/api/tasks/{task_id}?result=1").get_json()
            if record["status"] not in {"queued", "running"}:
                break
            time.sleep(0.01)
        self.assertEqual(record["status"], "succeeded")
        self.assertIn("summary", record["result"])

    def test_import_inspection_and_capabilities_expose_workflow(self):
        response = self.client.post("/api/import/inspect", json={
            "filename": "model.py", "text": "def make_model(): pass",
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["plan"]["safety"]["confirmation_required"])
        capabilities = self.state["capabilities"]
        self.assertEqual(capabilities["semantic_levels"], list(SEMANTIC_LEVELS))
        self.assertEqual(capabilities["lazy_canvas"]["maximum_dom_objects"], 2_000)
        self.assertEqual(set(capabilities["task_kinds"]), {"import", "analyze", "layout", "runtime", "export"})

    def test_complete_server_workflow_recovery_and_artifacts(self):
        graph_id = self.state["graph_id"]
        graph = self.state["graph"]

        uploaded = self.client.post(
            "/api/import/inspect",
            data={"model": (io.BytesIO(b'{"layers": []}'), "tiny.json")},
            content_type="multipart/form-data",
        )
        self.assertEqual(uploaded.status_code, 200)
        malformed = self.client.post(
            "/api/import/inspect", json={"filename": "bad.json", "data_base64": "%%%"},
        )
        self.assertEqual(malformed.status_code, 400)
        config = self.client.post(
            "/api/import/config",
            json={"filename": "tiny.json", "text": '{"layers": []}', "options": {"allow_code": False}},
        )
        self.assertEqual(config.get_json()["source"]["filename"], "tiny.json")
        imported = self.client.post(
            "/api/import", json={"source": {"name": "Tiny", "layers": [{"name": "x", "type": "Linear"}]}, "adapter": "manual"},
        )
        self.assertEqual(imported.status_code, 200)

        search = self.client.post("/api/search", json={"graph_id": graph_id, "query": "stem", "limit": 1})
        self.assertEqual(len(search.get_json()["matches"]), 1)
        self.assertFalse(self.client.post("/api/search", json={"graph_id": graph_id, "query": ""}).get_json()["matches"])
        analyzed = self.client.post("/api/analyze", json={"graph_id": graph_id})
        self.assertEqual(analyzed.status_code, 200)
        semantic = self.client.post(
            "/api/semantic", json={"graph_id": graph_id, "level": "block", "view": "faithful"},
        ).get_json()
        semantic_id = semantic["graph"]["nodes"][0]["id"]
        provenance = self.client.post(
            "/api/semantic/provenance", json={"graph_id": graph_id, "semantic_id": semantic_id},
        ).get_json()
        self.assertTrue(provenance["source_node_ids"])

        layout_response = self.client.post(
            "/api/layout",
            json={"graph_id": graph_id, "level": "block", "view": "paper", "page": "double-column", "aggregate_repeats": False},
        )
        self.assertEqual(layout_response.status_code, 200)
        layout_body = layout_response.get_json()
        rendered = self.client.post(
            "/api/render",
            json={"graph": layout_body["graph"], "layout": layout_body["layout"], "use_layout": True},
        )
        self.assertIn("<svg", rendered.get_json()["svg"])
        exported = self.client.post(
            "/api/export/svg",
            json={"graph_id": graph_id, "level": "block", "view": "paper", "page": "single-column"},
        )
        self.assertEqual(exported.mimetype, "image/svg+xml")

        missing_layout = self.client.post("/api/paper/suggestions", json={"graph": layout_body["graph"]})
        self.assertEqual(missing_layout.status_code, 400)
        candidates = self.client.post(
            "/api/paper/suggestions",
            json={"graph": layout_body["graph"], "layout": layout_body["layout"], "page": "double-column"},
        ).get_json()
        self.assertLessEqual(len(candidates["suggestions"]), 3)
        readability = self.client.post(
            "/api/paper/readability",
            json={"graph": layout_body["graph"], "layout": layout_body["layout"], "page": "wide-two-column"},
        ).get_json()
        applied = self.client.post(
            "/api/paper/apply",
            json={"current_layout": layout_body["layout"], "suggestion": readability["suggestion"]},
        )
        self.assertEqual(applied.status_code, 200)
        compared = self.client.post("/api/diff", json={"before": graph, "after": graph})
        self.assertEqual(compared.get_json()["summary"]["changed"], 0)
        edited_graph = json.loads(json.dumps(graph))
        edited_graph["constraints"].append({
            "target_ids": [edited_graph["edges"][0]["id"]],
            "kind": "edge-route",
            "value": {"points": [[0, 0], [20, 30], [40, 0]]},
            "locked": True,
        })
        project = self.client.post(
            "/api/project", json={"graph_id": graph_id, "graph": edited_graph, "name": "Edited"},
        ).get_json()
        self.assertEqual(project["graph"]["constraints"][-1]["kind"], "edge-route")
        lazy_descriptor = {
            **edited_graph,
            "nodes": [],
            "edges": [],
            "subgraphs": [],
            "annotations": [],
            "metadata": {"lazy_reference": True},
        }
        lazy_project = self.client.post(
            "/api/project", json={"graph_id": graph_id, "graph": lazy_descriptor, "name": "Lazy edited"},
        ).get_json()
        self.assertEqual(len(lazy_project["graph"]["nodes"]), len(graph["nodes"]))
        self.assertEqual(lazy_project["graph"]["constraints"][-1]["kind"], "edge-route")

        task_import = self.client.post(
            "/api/tasks",
            json={"kind": "import", "source": {"name": "Task import", "layers": [{"name": "x", "type": "Linear"}]}, "adapter": "manual"},
        ).get_json()
        imported_task = self._wait_task(task_import["id"])
        self.assertEqual(imported_task["status"], "succeeded")
        task_layout = self.client.post(
            "/api/tasks", json={"kind": "layout", "graph_id": graph_id, "level": "stage", "view": "faithful"},
        ).get_json()
        self.assertEqual(self._wait_task(task_layout["id"])["status"], "succeeded")
        runtime = self.client.post("/api/tasks", json={"kind": "runtime", "graph_id": graph_id}).get_json()
        failed_runtime = self._wait_task(runtime["id"])
        self.assertEqual(failed_runtime["status"], "failed")
        retried = self.client.post(f"/api/tasks/{runtime['id']}/retry")
        self.assertEqual(retried.status_code, 202)
        self.assertEqual(self._wait_task(retried.get_json()["id"])["status"], "failed")
        cancelled_terminal = self.client.post(f"/api/tasks/{task_import['id']}/cancel")
        self.assertEqual(cancelled_terminal.get_json()["status"], "succeeded")

        task_export = self.client.post(
            "/api/tasks", json={"kind": "export", "graph_id": graph_id, "format": "svg"},
        ).get_json()
        finished_export = self._wait_task(task_export["id"])
        self.assertEqual(finished_export["status"], "succeeded")
        artifact = self.client.get(f"/api/tasks/{task_export['id']}/artifact")
        self.assertEqual(artifact.mimetype, "image/svg+xml")
        no_artifact = self.client.get(f"/api/tasks/{task_import['id']}/artifact")
        self.assertEqual(no_artifact.status_code, 400)
        self.assertTrue(self.client.get("/api/tasks").get_json()["tasks"])
        self.assertEqual(
            self.client.post("/api/summary", json={"graph_id": "missing"}).status_code,
            400,
        )

    def _wait_task(self, task_id: str) -> dict:
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            record = self.client.get(f"/api/tasks/{task_id}?result=1").get_json()
            if record["status"] not in {"queued", "running"}:
                return record
            time.sleep(0.01)
        self.fail(f"task {task_id} did not finish")


if __name__ == "__main__":
    unittest.main()
