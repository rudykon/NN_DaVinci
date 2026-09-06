from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from nn_davinci.errors import ValidationError
from nn_davinci.server import create_app
from nn_davinci.trial import TRIAL_PROTOCOL_VERSION, TrialRecorder, trial_event_schema
from nn_davinci.trial_models import (
    EXTERNAL_MODEL_CASE_KEYS,
    build_external_model_compatibility_report,
    external_model_case_manifest,
    import_external_model,
)


class TrialModeTests(unittest.TestCase):
    def test_recorder_is_off_and_creates_nothing_before_explicit_consent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "trial"
            recorder = TrialRecorder(root)
            self.assertFalse(root.exists())
            self.assertFalse(recorder.status()["enabled"])
            with self.assertRaises(ValidationError):
                recorder.start_session(case_key="dynamic_pytorch")
            with self.assertRaises(ValidationError):
                recorder.set_consent(True, protocol_version=TRIAL_PROTOCOL_VERSION, explicit_confirmation=False)
            self.assertFalse(root.exists())

    def test_privacy_allowlist_roundtrip_refresh_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "trial"
            recorder = TrialRecorder(root)
            recorder.set_consent(True, protocol_version=TRIAL_PROTOCOL_VERSION, explicit_confirmation=True)
            recorder.start_session(case_key="custom_unknown")
            with self.assertRaises(ValidationError):
                recorder.record("import_started", {"format": "pytorch", "safety_level": "local-fixture", "path": "/private/model.py"})
            recorder.record("import_started", {"format": "pytorch", "safety_level": "local-fixture"})
            recorder.record("import_succeeded", {"format": "pytorch", "node_count": 7, "edge_count": 7, "unknown_count": 4})
            recorder.record("first_interactive_view", {"elapsed_ms": 900, "visible_nodes": 7, "dom_objects": 80, "semantic_level": "block"})
            recorder.record("paper_ready", {"elapsed_ms": 2500, "minimum_font_pt": 7.079, "panel_count": 2})
            recorder.record("edit_summary", {"semantic_changes": 2, "node_changes": 1, "edge_changes": 1, "label_changes": 1})
            for format_name in ("svg", "pdf", "tikz", "pptx"):
                recorder.record("export", {"format": format_name, "succeeded": True, "error_code": "none"})
            restored = TrialRecorder(root)
            self.assertIsNotNone(restored.status()["active_session_id"])
            completed = restored.finish_session()
            self.assertTrue(completed["summary"]["core_task_success"])
            exported = restored.export()
            self.assertTrue(exported["privacy"]["local_only"])
            serialized = json.dumps(exported)
            self.assertNotIn("/private/model.py", serialized)
            for path in root.rglob("*.json"):
                self.assertEqual(0o600, path.stat().st_mode & 0o777)

    def test_landed_machine_schema_matches_runtime_contract(self) -> None:
        landed = json.loads((Path(__file__).parents[1] / "docs" / "trial" / "trial-event.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(trial_event_schema(), landed)
        event_variants = landed["properties"]["sessions"]["items"]["properties"]["events"]["items"]["oneOf"]
        self.assertEqual(10, len(event_variants))
        self.assertTrue(all(item["additionalProperties"] is False for item in event_variants))
        self.assertFalse(landed["properties"]["sessions"]["items"]["additionalProperties"])
        self.assertFalse(landed["properties"]["aggregate"]["additionalProperties"])

    def test_six_external_cases_complete_editable_paper_workflow(self) -> None:
        self.assertEqual(6, len(EXTERNAL_MODEL_CASE_KEYS))
        self.assertEqual(6, external_model_case_manifest()["case_count"])
        with tempfile.TemporaryDirectory() as directory:
            report = build_external_model_compatibility_report(directory)
            self.assertTrue(report["passed"], report["failures"])
            self.assertEqual(set(EXTERNAL_MODEL_CASE_KEYS), set(report["models"]))
            for item in report["models"].values():
                self.assertTrue(item["paper"]["paper_ready"])
                self.assertGreaterEqual(item["paper"]["minimum_font_pt"], 7.0)

    def test_dynamic_input_output_roles_and_trial_http_contract(self) -> None:
        graph, _ = import_external_model("dynamic_pytorch")
        self.assertEqual(["image"], [item.name for item in graph.inputs])
        self.assertEqual(["output_0"], [item.name for item in graph.outputs])
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(trial_root=Path(directory) / "trial")
            client = app.test_client()
            self.assertFalse(client.get("/api/trial/status").get_json()["enabled"])
            self.assertEqual(6, client.get("/api/trial-cases").get_json()["case_count"])
            consent = client.post("/api/trial/consent", json={
                "accepted": True,
                "protocol_version": TRIAL_PROTOCOL_VERSION,
                "explicit_confirmation": True,
            })
            self.assertEqual(200, consent.status_code)
            started = client.post("/api/trial/sessions", json={"case_key": "custom_unknown", "workflow": "guided-web"})
            self.assertEqual(201, started.status_code)
            self.assertEqual(
                "0.5.0-trial-events-1",
                client.get("/api/trial/schema").get_json()["properties"]["schema_version"]["const"],
            )
            event = client.post("/api/trial/events", json={
                "event_type": "import_started", "format": "pytorch", "safety_level": "local-fixture",
            })
            self.assertEqual(200, event.status_code)
            case = client.post("/api/trial-cases/custom_unknown", json={})
            self.assertEqual(200, case.status_code)
            self.assertIn("never guessed", case.get_json()["diagnostics"]["unknown_explanation"])
            exported = client.get("/api/trial/export")
            self.assertEqual(200, exported.status_code)
            self.assertIn('"local_only": true', exported.get_data(as_text=True))
            self.assertEqual(200, client.post("/api/trial/finish", json={"status": "abandoned"}).status_code)


if __name__ == "__main__":
    unittest.main()
