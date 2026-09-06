from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

from nn_davinci.server import create_app


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("service_lifecycle_073", ROOT / "scripts" / "service_lifecycle_0_7_3.py")
assert SPEC is not None and SPEC.loader is not None
LIFECYCLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LIFECYCLE)


class ServiceLifecycle073Tests(unittest.TestCase):
    def test_health_is_machine_readable_and_identity_bound(self) -> None:
        app = create_app(
            service_host="0.0.0.0",
            service_port=9876,
            source_identity="test-source",
            build_identity="test-build",
        )
        response = app.test_client().get("/api/health")
        self.assertEqual(200, response.status_code)
        health = response.get_json()
        self.assertEqual("0.7.3", health["product_version"])
        self.assertEqual(os.getpid(), health["pid"])
        self.assertEqual("0.0.0.0", health["host"])
        self.assertEqual(9876, health["port"])
        self.assertEqual("test-source", health["source_identity"])
        self.assertEqual("test-build", health["build_identity"])
        self.assertTrue(health["readiness"])
        self.assertTrue(health["lan_risk"])
        self.assertFalse(health["authentication"])
        self.assertGreaterEqual(health["uptime_seconds"], 0)

    def test_forged_pid_identity_is_rejected_before_health_or_signal(self) -> None:
        process = LIFECYCLE._process_record(os.getpid())
        self.assertIsNotNone(process)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path, _log = LIFECYCLE._paths(root, 8766)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps({
                "pid": os.getpid(),
                "process_start_ticks": "forged",
                "cmdline_digest": "forged",
                "host": "127.0.0.1",
                "port": 8766,
            }), encoding="utf-8")
            valid, reason, health = LIFECYCLE._identity_status(LIFECYCLE._load_state(state_path))
            self.assertFalse(valid)
            self.assertEqual("pid-reused-start-time-mismatch", reason)
            self.assertIsNone(health)

    def test_four_wrappers_default_to_localhost_lifecycle_controller(self) -> None:
        for action in ("start", "status", "stop", "restart"):
            with self.subTest(action=action):
                source = (ROOT / "scripts" / f"{action}-0.7.3.sh").read_text(encoding="utf-8")
                self.assertIn("service_lifecycle_0_7_3.py", source)
                self.assertIn(action, source)
        parser_source = (ROOT / "scripts" / "service_lifecycle_0_7_3.py").read_text(encoding="utf-8")
        self.assertIn('"127.0.0.1"', parser_source)
        self.assertIn("PID identity was not proven; no signal was sent.", parser_source)


if __name__ == "__main__":
    unittest.main()
