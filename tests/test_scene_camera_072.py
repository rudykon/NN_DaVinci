from __future__ import annotations

import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
VIEWPORTS = (
    (1920, 1080),
    (1440, 900),
    (1024, 768),
    (800, 600),
    (568, 320),
    (390, 844),
)


class SceneCamera072Tests(unittest.TestCase):
    def test_editor_frame_scene_is_aspect_aware_across_six_required_viewports(self) -> None:
        script = r"""
const fs = require("fs"), vm = require("vm");
global.window = global;
global.CustomEvent = class CustomEvent extends Event {
  constructor(type, options = {}) { super(type); this.detail = options.detail; }
};
const requested = JSON.parse(process.argv[1]);
let viewport = { width: 800, height: 600 };
const canvas = {
  width: 800,
  height: 600,
  getContext: () => null,
  getBoundingClientRect: () => ({ left: 0, top: 0, ...viewport }),
};
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"));
const renderer = new NNDVSceneRenderer.SceneRenderer(canvas);
const object = (id, position) => ({
  id, visible: true, locked: false,
  transform: { position, rotation: [0, 0, 0], scale: [1, 1, 1] },
  geometry: { size: [2, 2, 2] }, material: {},
});
const scene = {
  metadata: { content_density: "paper" },
  cameras: [{
    id: "camera", projection: "orthographic", position: [12, 10, 14],
    target: [0, 0, 0], up: [0, 1, 0], ortho_height: 18,
    fov_y_deg: 45, near: 0.1, far: 10000, locked: false,
  }],
  active_camera_id: "camera", selection_ids: [],
  layers: [{ visible: true, locked: false, objects: [
    object("left", [-10, -2, -1]), object("middle", [0, 4, 3]), object("right", [10, 1, 0]),
  ] }],
};
const corners = [
  ...[-1, 1].flatMap(x => [-1, 1].flatMap(y => [-1, 1].map(z => [-10+x, -2+y, -1+z]))),
  ...[-1, 1].flatMap(x => [-1, 1].flatMap(y => [-1, 1].map(z => [x, 4+y, 3+z]))),
  ...[-1, 1].flatMap(x => [-1, 1].flatMap(y => [-1, 1].map(z => [10+x, 1+y, z]))),
];
const reports = [];
for (const [width, height] of requested) {
  viewport = { width, height };
  canvas.width = width; canvas.height = height;
  renderer.setScene(scene, "camera");
  const framed = renderer.frameObjects();
  const points = corners.map(point => renderer.projectPoint(point));
  const xs = points.map(point => point.x), ys = points.map(point => point.y);
  reports.push({
    width, height, framed,
    bounds: [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)],
    occupancy: [(Math.max(...xs)-Math.min(...xs))/width, (Math.max(...ys)-Math.min(...ys))/height],
  });
}
renderer.camera.locked = true;
const before = JSON.stringify(renderer.getCameraState());
const lockedFrame = renderer.frameObjects();
reports.push({ lockedFrame, lockedUnchanged: before === JSON.stringify(renderer.getCameraState()) });
process.stdout.write(JSON.stringify(reports));
"""
        completed = subprocess.run(
            [
                "node",
                "-e",
                script,
                json.dumps(VIEWPORTS),
                str(ROOT / "src/nn_davinci/web/scene-renderer.js"),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        reports = json.loads(completed.stdout)
        for report in reports[:-1]:
            with self.subTest(viewport=(report["width"], report["height"])):
                self.assertTrue(report["framed"])
                left, top, right, bottom = report["bounds"]
                self.assertGreaterEqual(left, -0.5)
                self.assertGreaterEqual(top, -0.5)
                self.assertLessEqual(right, report["width"] + 0.5)
                self.assertLessEqual(bottom, report["height"] + 0.5)
                self.assertGreaterEqual(max(report["occupancy"]), 0.55)
                self.assertLessEqual(max(report["occupancy"]), 0.9)
        self.assertFalse(reports[-1]["lockedFrame"])
        self.assertTrue(reports[-1]["lockedUnchanged"])


if __name__ == "__main__":
    unittest.main()
