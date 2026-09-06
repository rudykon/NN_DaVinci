from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.verify_scene_migration_0_7 import verify_case
from nn_davinci.errors import ValidationError


ROOT = Path(__file__).resolve().parents[1]


class SceneMigrationReport070Tests(unittest.TestCase):
    def test_all_seven_legacy_projects_migrate_without_inventing_scene_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "migration.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "verify_scene_migration_0_7.py"),
                    "--project-root",
                    str(ROOT),
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
                env={"PYTHONPATH": str(ROOT / "src")},
            )
            self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("PASS", report["status"])
            self.assertEqual({"expected": 7, "checked": 7, "passed": 7, "failed": 0}, report["counts"])
            self.assertEqual([], report["failures"])
            self.assertTrue(all(all(case["checks"].values()) for case in report["cases"]))
            self.assertEqual(
                {
                    "graph_ir_mutated": False,
                    "figure_ir_mutated": False,
                    "scene_geometry_inferred": False,
                    "model_semantics_inferred": False,
                    "provenance_inferred": False,
                },
                report["migration_contract"],
            )

    def test_non_legacy_input_cannot_receive_a_positive_migration_verdict(self) -> None:
        source = ROOT / "src" / "nn_davinci" / "figure_templates" / "cnn-feature-pipeline.nndv.json"
        with tempfile.TemporaryDirectory() as directory:
            mutated = Path(directory) / source.name
            payload = json.loads(source.read_text(encoding="utf-8"))
            payload["project_version"] = "1.4"
            mutated.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ValidationError):
                verify_case(mutated)


if __name__ == "__main__":
    unittest.main()
