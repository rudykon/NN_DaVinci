from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from PIL import Image

from nn_davinci.model_scene import scene_template
from nn_davinci.scene_export import render_scene_svg
from nn_davinci.scene_projection import ProjectionOptions, project_scene
from scripts.validate_scene_visual_evidence_0_7_1 import SceneVisualEvidenceValidator


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "nn_davinci" / "web"


class ScenePublicationUx071Tests(unittest.TestCase):
    def test_inspector_has_the_required_six_groups_in_order(self) -> None:
        index = (WEB / "index.html").read_text(encoding="utf-8")
        groups = re.findall(r'data-scene-inspector-group="([^"]+)"', index)
        self.assertEqual(groups, ["transform", "geometry", "appearance", "layout", "semantics", "provenance"])
        for label in ("Transform", "Geometry", "Appearance", "Layout", "Semantics", "Provenance"):
            self.assertIn(f"<summary>{label}</summary>", index)
        self.assertGreaterEqual(index.count("data-scene-property-pin="), 6)

    def test_scene_ux_entry_points_are_visible_and_not_test_only(self) -> None:
        index = (WEB / "index.html").read_text(encoding="utf-8")
        app = (WEB / "app.js").read_text(encoding="utf-8")
        for marker in (
            'id="scene-transform-gizmo"',
            'id="scene-tree-search"',
            'id="scene-tree-filter"',
            'id="scene-content-density"',
            'id="scene-batch-export"',
            'data-scene-action="ungroup"',
            'data-scene-action="distribute-y"',
            'data-scene-action="distribute-z"',
        ):
            self.assertIn(marker, index)
        for command in (
            "scene.group",
            "scene.ungroup",
            "scene.frame-all",
            "scene.distribute-${axis}",
            "scene.gizmo-${mode}",
        ):
            self.assertIn(command, app)

    def test_paper_projection_retains_directional_coloured_skip_routes(self) -> None:
        payload = render_scene_svg(scene_template("resnet"), options=ProjectionOptions(auto_frame=True, density="paper"))
        self.assertIn('data-kind="arrowhead"', payload)
        self.assertIn('stroke="#ef4444"', payload)
        self.assertNotIn("group-frame", payload)

    def test_density_levels_are_real_and_monotonic(self) -> None:
        scene = scene_template("transformer")
        counts = []
        for density in ("compact", "paper", "detailed"):
            projection = project_scene(scene, options=ProjectionOptions(auto_frame=True, density=density))
            counts.append(sum(item.kind == "label" for item in projection.primitives))
        self.assertLessEqual(counts[0], counts[1])
        self.assertLessEqual(counts[1], counts[2])
        self.assertGreater(counts[2], counts[0])

    def test_scene_batch_isolates_failure_and_cancels_remaining_work(self) -> None:
        module = WEB / "scene-batch.js"
        program = r"""
const assert = require("node:assert/strict");
const { run } = require(process.argv[1]);
(async () => {
  const visited = [];
  const partial = await run({
    formats: ["svg", "pdf", "png"],
    task: async (format) => {
      visited.push(format);
      if (format === "pdf") throw new Error("intentional fixture failure");
      return format;
    },
  });
  assert.equal(partial.status, "partial");
  assert.deepEqual(visited, ["svg", "pdf", "png"]);
  assert.deepEqual(partial.successes.map((item) => item.format), ["svg", "png"]);
  assert.deepEqual(partial.failures.map((item) => item.format), ["pdf"]);

  const controller = new AbortController();
  const cancelled = await run({
    formats: ["svg", "pdf", "png"],
    signal: controller.signal,
    task: async () => {
      controller.abort();
      const error = new Error("cancelled");
      error.name = "AbortError";
      throw error;
    },
  });
  assert.equal(cancelled.status, "cancelled");
  assert.deepEqual(cancelled.cancelled.map((item) => item.format), ["svg", "pdf", "png"]);
})().catch((error) => { console.error(error); process.exitCode = 1; });
"""
        completed = subprocess.run(
            ["node", "-e", program, str(module)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_visual_oracle_truth_fixtures_cover_known_regressions(self) -> None:
        fixture_root = ROOT / "tests" / "fixtures" / "scene_oracle_071"
        mutations = json.loads((fixture_root / "mutations.json").read_text(encoding="utf-8"))
        names = {item["name"] for item in mutations["mutations"]}
        self.assertTrue(
            {
                "label-stack",
                "label-object",
                "clipped-label",
                "starburst",
                "huge-frame",
                "nonuniform-text-scale",
            }.issubset(names)
        )
        oracle = (ROOT / "scripts" / "scene_svg_oracle_0_7_1.mjs").read_text(encoding="utf-8")
        validator = (ROOT / "scripts" / "validate_visual_oracle_fixtures_0_7_1.mjs").read_text(encoding="utf-8")
        self.assertIn("getBBox()", oracle)
        self.assertIn("getScreenCTM()", oracle)
        self.assertIn("constant_true_rejected", validator)
        self.assertTrue((fixture_root / "toolbar-truncated-negative.html").is_file())

    def test_downloaded_svg_validator_measures_arrow_and_bezier_routes(self) -> None:
        arrow_root = ET.fromstring(render_scene_svg(scene_template("resnet")))
        arrow_result, arrow_failures = SceneVisualEvidenceValidator._inspect_svg_routes(list(arrow_root.iter()))
        self.assertEqual(arrow_failures, [])
        self.assertEqual(arrow_result["status"], "PASS")
        self.assertGreater(arrow_result["route_primitive_count"], 0)

        bezier = ET.fromstring(
            '<svg xmlns="http://www.w3.org/2000/svg"><path id="route" data-kind="bezier" '
            'd="M 0 0 C 2 0, 4 2, 6 2"/></svg>'
        )
        bezier_result, bezier_failures = SceneVisualEvidenceValidator._inspect_svg_routes(list(bezier.iter()))
        self.assertEqual(bezier_failures, [])
        self.assertEqual(bezier_result["status"], "PASS")
        self.assertEqual(bezier_result["segment_count"], 48)

    def test_before_after_proof_preserves_all_fourteen_original_pngs(self) -> None:
        cases = (
            ("templates", "cnn"),
            ("templates", "resnet"),
            ("templates", "unet"),
            ("templates", "transformer"),
            ("templates", "moe"),
            ("templates", "multimodal-fusion"),
            ("templates", "diffusion-unet"),
            ("real-models", "resnet50"),
            ("real-models", "vision_transformer"),
            ("real-models", "bert_encoder"),
            ("real-models", "multiscale_unet"),
            ("real-models", "diffusion_unet"),
            ("real-models", "topk_moe"),
            ("real-models", "image_text"),
        )
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            before_root = temporary / "before"
            after_root = temporary / "after"
            for kind, name in cases:
                for root, color in ((before_root, "#fee2e2"), (after_root, "#dcfce7")):
                    destination = root / kind / name / "scene.png"
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    Image.new("RGB", (32, 20), color).save(destination, dpi=(300, 300))
            output_root = temporary / "proof"
            report_path = temporary / "report.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "generate_scene_before_after_0_7_1.py"),
                    "--before-root",
                    str(before_root),
                    "--after-root",
                    str(after_root),
                    "--output-root",
                    str(output_root),
                    "--report",
                    str(report_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["case_count"], 14)
            self.assertEqual(report["proof_png_count"], 42)
            self.assertEqual(len(list(output_root.rglob("*.png"))), 42)


if __name__ == "__main__":
    unittest.main()
