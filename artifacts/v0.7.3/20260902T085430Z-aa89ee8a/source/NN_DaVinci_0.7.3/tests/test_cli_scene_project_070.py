from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from nn_davinci.errors import ValidationError
from nn_davinci.ir import GraphIR
from nn_davinci.model_scene import scene_template
from nn_davinci.project import Project
from nn_davinci.scene_ir import SceneProvenance


ROOT = Path(__file__).resolve().parents[1]


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    source_path = str(ROOT / "src")
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        source_path
        if not existing_pythonpath
        else os.pathsep.join((source_path, existing_pythonpath))
    )
    return subprocess.run(
        [sys.executable, "-m", "nn_davinci", *arguments],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )


class CliSceneProject070Tests(unittest.TestCase):
    def test_project_scene_boundary_rejects_every_malformed_evidence_envelope(self) -> None:
        graph = GraphIR("Project validation branches", [], []).validate()

        with self.assertRaisesRegex(ValidationError, "Semantic View document must be an object"):
            Project(
                "Invalid semantic document",
                graph,
                semantic_view={"document": []},
            )
        with self.assertRaisesRegex(ValidationError, "semantic_view must be an object"):
            Project("Invalid semantic envelope", graph, semantic_view=[])

        direct_scene = scene_template("cnn")
        self.assertEqual(
            direct_scene.digest(),
            Project("Direct Scene", graph, scene_ir=direct_scene).persisted_scene().digest(),
        )
        with self.assertRaisesRegex(ValidationError, "scene_ir must be a Scene IR object"):
            Project("Invalid Scene envelope", graph, scene_ir=["not-an-object"])

        semantic_scene = scene_template("cnn")
        next(semantic_scene.iter_objects()).provenance = SceneProvenance(
            "semantic_view",
            graph_ir_ids=["missing-graph-evidence"],
            semantic_view_ids=["missing-semantic-evidence"],
        )
        with self.assertRaisesRegex(ValidationError, "requires its persisted Semantic View"):
            Project("Missing Scene semantic document", graph, scene_ir=semantic_scene)

        figure_scene = scene_template("cnn")
        next(figure_scene.iter_objects()).provenance = SceneProvenance(
            "figure_ir",
            figure_ir_ids=["missing-figure-evidence"],
        )
        with self.assertRaisesRegex(ValidationError, "requires the referenced persisted Figure IR"):
            Project("Missing Scene Figure", graph, scene_ir=figure_scene)

        orphan_scene = scene_template("cnn")
        next(orphan_scene.iter_objects()).provenance = SceneProvenance(
            "graph_ir",
            graph_ir_ids=["orphan-graph-evidence"],
        )
        with self.assertRaisesRegex(ValidationError, "Scene IR provenance disagree"):
            Project("Orphan Scene provenance", graph, scene_ir=orphan_scene)

        with self.assertRaisesRegex(ValidationError, "missing its Graph IR"):
            Project.from_dict({"project_version": "1.4"})

    def test_render_summary_accepts_both_trusted_import_flags(self) -> None:
        completed = run_cli(
            "render",
            "examples/resnet.json",
            "--summary",
            "--allow-code",
            "--allow-pickle",
        )

        self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
        summary = json.loads(completed.stdout)
        self.assertEqual("summary", summary["strategy"])
        self.assertFalse(summary["layout_constructed"])
        self.assertFalse(summary["svg_constructed"])

    def test_scene_project_cli_persists_semantics_validates_reproduces_and_roundtrips(self) -> None:
        with tempfile.TemporaryDirectory(prefix="nndv-cli-scene-project-") as directory:
            root = Path(directory)
            project_path = root / "resnet.nndv.json"
            generated = run_cli(
                "project",
                "examples/resnet.json",
                "--workspace",
                "scene",
                "--architecture",
                "resnet",
                "-o",
                str(project_path),
            )
            self.assertEqual(0, generated.returncode, generated.stderr or generated.stdout)
            self.assertTrue(project_path.is_file())

            payload = json.loads(project_path.read_text(encoding="utf-8"))
            self.assertEqual("operation", payload["semantic_view"]["level"])
            self.assertIn("document", payload["semantic_view"])
            self.assertTrue(payload["semantic_view"]["document"]["entities"])

            validated = run_cli("validate", str(project_path))
            self.assertEqual(0, validated.returncode, validated.stderr or validated.stdout)
            self.assertIn("valid Project 1.4", validated.stdout)
            self.assertIn("Scene IR 1.0", validated.stdout)

            reproduced_path = root / "reproduced.svg"
            reproduced = run_cli("reproduce", str(project_path), "-o", str(reproduced_path))
            self.assertEqual(0, reproduced.returncode, reproduced.stderr or reproduced.stdout)
            self.assertTrue(reproduced_path.is_file())
            self.assertIn(str(reproduced_path), reproduced.stdout)

            project = Project.load(project_path)
            semantic = project.persisted_semantic_view()
            self.assertIsNotNone(semantic)
            roundtrip_path = root / "roundtrip.nndv.json"
            project.save(roundtrip_path)
            restored = Project.load(roundtrip_path)
            self.assertEqual(project.persisted_scene().digest(), restored.persisted_scene().digest())
            assert semantic is not None
            restored_semantic = restored.persisted_semantic_view()
            self.assertIsNotNone(restored_semantic)
            assert restored_semantic is not None
            self.assertEqual(semantic.to_dict(), restored_semantic.to_dict())


if __name__ == "__main__":
    unittest.main()
