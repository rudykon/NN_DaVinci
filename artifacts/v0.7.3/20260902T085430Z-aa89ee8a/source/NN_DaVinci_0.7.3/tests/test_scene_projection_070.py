from __future__ import annotations

import math
import unittest

from nn_davinci.scene_ir import Material3D, Object3D, SceneProvenance, Transform3D, new_scene
from nn_davinci.scene_projection import (
    ProjectionOptions,
    look_at_matrix,
    orthographic_matrix,
    perspective_matrix,
    project_point,
    project_scene,
)


def _object(kind: str, name: str, geometry: dict, position: list[float] | None = None) -> Object3D:
    return Object3D.create(
        kind,
        name,
        geometry,
        SceneProvenance.template("projection-tests"),
        transform=Transform3D(position=position or [0.0, 0.0, 0.0]),
        material=Material3D(base_color="#93c5fd", face_colors={"top": "#dbeafe"}),
        identity=f"projection-tests:{name}",
    )


def _depth_scene():
    scene = new_scene("Depth sorting")
    camera = scene.cameras[0]
    camera.position = [0.0, 0.0, 10.0]
    camera.target = [0.0, 0.0, 0.0]
    camera.up = [0.0, 1.0, 0.0]
    camera.ortho_height = 8.0
    near = _object("tensor-volume", "near", {"size": [2.0, 2.0, 1.0]}, [0.0, 0.0, 2.0])
    far = _object("tensor-volume", "far", {"size": [2.0, 2.0, 1.0]}, [0.0, 0.0, -2.0])
    scene.layers[0].objects = [near, far]
    scene.validate()
    return scene, near, far


class SceneProjection070Tests(unittest.TestCase):
    def test_camera_matrices_project_the_view_target_to_page_center(self) -> None:
        view = look_at_matrix((0.0, 0.0, 10.0), (0.0, 0.0, 0.0))
        orthographic = orthographic_matrix(-5.0, 5.0, -5.0, 5.0, 0.1, 100.0)
        projected = project_point((0.0, 0.0, 0.0), view, orthographic, width_mm=100.0, height_mm=100.0, margin_mm=0.0)
        self.assertIsNotNone(projected)
        assert projected is not None
        self.assertAlmostEqual(projected[0], 50.0)
        self.assertAlmostEqual(projected[1], 50.0)
        self.assertAlmostEqual(projected[2], 10.0)
        perspective = perspective_matrix(90.0, 1.0, 0.1, 100.0)
        centre = project_point((0.0, 0.0, 0.0), view, perspective, width_mm=100.0, height_mm=100.0, margin_mm=0.0)
        right = project_point((1.0, 0.0, 0.0), view, perspective, width_mm=100.0, height_mm=100.0, margin_mm=0.0)
        self.assertIsNotNone(centre)
        self.assertIsNotNone(right)
        assert centre is not None and right is not None
        self.assertAlmostEqual(centre[0], 50.0)
        self.assertGreater(right[0], centre[0])
        self.assertIsNone(project_point((0.0, 0.0, 20.0), view, perspective))
        self.assertIsNone(project_point((0.0, 0.0, -200.0), view, perspective))

    def test_projector_uses_scene_camera_matrices_including_rotation(self) -> None:
        scene, _near, _far = _depth_scene()
        scene.cameras[0].rotation = [0.0, 4.0, 0.0]
        scene.validate()
        projection = project_scene(scene)
        self.assertEqual(projection.view_matrix, scene.active_camera().view_matrix())
        self.assertEqual(projection.projection_matrix, scene.active_camera().projection_matrix())

    def test_camera_changes_reverse_depth_order(self) -> None:
        scene, near, far = _depth_scene()
        first = project_scene(scene)
        face_order = [primitive.object_id for primitive in first.primitives if primitive.kind == "face"]
        self.assertTrue(face_order)
        self.assertEqual(face_order[0], far.id)
        scene.cameras[0].position = [0.0, 0.0, -10.0]
        scene.cameras[0].target = [0.0, 0.0, 0.0]
        scene.validate()
        reversed_projection = project_scene(scene)
        reversed_order = [primitive.object_id for primitive in reversed_projection.primitives if primitive.kind == "face"]
        self.assertTrue(reversed_order)
        self.assertEqual(reversed_order[0], near.id)

    def test_orthographic_and_perspective_produce_different_extents(self) -> None:
        scene, near, _far = _depth_scene()
        scene.layers[0].objects = [near]
        scene.validate()
        orthographic = project_scene(scene)
        scene.cameras[0].projection = "perspective"
        scene.cameras[0].fov_y_deg = 45.0
        scene.validate()
        perspective = project_scene(scene)

        def width(projection) -> float:
            values = [x for item in projection.primitives if item.object_id == near.id and item.kind == "face" for x, _y in item.points]
            return max(values) - min(values)

        self.assertFalse(math.isclose(width(orthographic), width(perspective), rel_tol=1.0e-4))

    def test_backface_culling_and_hidden_edges_are_real_visibility_options(self) -> None:
        scene, near, _far = _depth_scene()
        scene.layers[0].objects = [near]
        scene.validate()
        hidden = project_scene(scene, options=ProjectionOptions(hidden_edges=True, backface_culling=True))
        transparent = project_scene(scene, options=ProjectionOptions(hidden_edges=False, backface_culling=False))
        hidden_faces = [item for item in hidden.primitives if item.object_id == near.id and item.kind == "face"]
        all_faces = [item for item in transparent.primitives if item.object_id == near.id and item.kind == "face"]
        hidden_lines = [item for item in hidden.primitives if item.object_id == near.id and item.kind == "edge"]
        all_lines = [item for item in transparent.primitives if item.object_id == near.id and item.kind == "edge"]
        self.assertEqual(len(hidden_faces), 1)
        self.assertEqual(len(all_faces), 6)
        self.assertEqual(len(hidden_lines), 4)
        self.assertEqual(len(all_lines), 12)

    def test_nearer_opaque_face_occludes_far_edges(self) -> None:
        scene, _near, far = _depth_scene()
        removed = project_scene(scene, options=ProjectionOptions(hidden_edges=True))
        retained = project_scene(scene, options=ProjectionOptions(hidden_edges=False))
        removed_count = sum(item.object_id == far.id and item.kind == "edge" for item in removed.primitives)
        retained_count = sum(item.object_id == far.id and item.kind == "edge" for item in retained.primitives)
        self.assertLess(removed_count, retained_count)

    def test_routes_arrows_beziers_and_collision_free_billboard_labels(self) -> None:
        scene = new_scene("Routes and labels")
        camera = scene.cameras[0]
        camera.position = [5.0, 4.0, 8.0]
        camera.target = [0.0, 0.0, 0.0]
        arrow = _object("arrow", "flow", {"points": [[-2.0, 0.0, 0.0], [2.0, 0.0, 1.0]]})
        bezier = _object(
            "bezier-route",
            "skip",
            {"points": [[-2.0, -1.0, 0.0], [-1.0, 2.0, 1.0], [1.0, 2.0, 1.0], [2.0, -1.0, 0.0]]},
        )
        first = Object3D.create("annotation", "first", {"text": "same anchor A"}, SceneProvenance.author(), identity="label-a")
        second = Object3D.create("annotation", "second", {"text": "same anchor B"}, SceneProvenance.author(), identity="label-b")
        scene.layers[0].objects = [arrow, bezier, first, second]
        scene.validate()
        projection = project_scene(scene)
        kinds = {(item.object_id, item.kind) for item in projection.primitives}
        self.assertIn((arrow.id, "arrow"), kinds)
        self.assertIn((bezier.id, "bezier"), kinds)
        bezier_item = next(item for item in projection.primitives if item.object_id == bezier.id and item.kind == "bezier")
        self.assertEqual(len(bezier_item.points), 4)
        self.assertEqual("template", bezier_item.metadata["provenance"]["kind"])
        labels = [item for item in projection.primitives if item.kind == "label" and item.object_id in {first.id, second.id}]
        self.assertEqual(len(labels), 2)
        self.assertTrue(all(item.style["font_size_pt"] >= 7.0 for item in labels))
        self.assertTrue(all(item.metadata["billboard"] for item in labels))
        boxes = [item.style["text_bbox_mm"] for item in labels]
        overlaps = not (boxes[0][2] <= boxes[1][0] or boxes[1][2] <= boxes[0][0] or boxes[0][3] <= boxes[1][1] or boxes[1][3] <= boxes[0][1])
        self.assertFalse(overlaps)

    def test_strokes_are_physical_and_projection_is_deterministic(self) -> None:
        scene, _near, _far = _depth_scene()
        options = ProjectionOptions(stroke_width_pt=0.65, min_label_pt=7.0)
        first = project_scene(scene, options=options)
        second = project_scene(scene, options=options)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertTrue(first.primitives)
        self.assertTrue(all(item.style["stroke_width_pt"] == 0.65 for item in first.primitives))
        self.assertTrue(all(item.style["font_size_pt"] >= 7.0 for item in first.primitives if item.kind == "label"))

    def test_hidden_layer_objects_do_not_leak_into_projection(self) -> None:
        scene, near, _far = _depth_scene()
        scene.layers[0].objects = [near]
        scene.layers[0].visible = False
        scene.validate()
        projection = project_scene(scene)
        self.assertFalse(any(item.object_id == near.id for item in projection.primitives))


if __name__ == "__main__":
    unittest.main()
