from __future__ import annotations

from copy import deepcopy
import math
import unittest

from nn_davinci.errors import ValidationError
from nn_davinci.scene_ir import (
    Camera,
    Group3D,
    Material3D,
    Object3D,
    Scene,
    SceneProvenance,
    Transform3D,
    new_scene,
)
from nn_davinci.scene_math import (
    compose_matrix,
    inverse_matrix,
    matrix_multiply,
    transform_point,
)


def box(
    identity: str,
    position: list[float],
    *,
    size: list[float] | None = None,
) -> Object3D:
    return Object3D.create(
        "tensor-volume",
        identity,
        {"size": size or [2.0, 2.0, 2.0]},
        SceneProvenance.template(f"test:{identity}"),
        transform=Transform3D(position),
        material=Material3D(base_color="#93c5fd"),
        identity=f"test:{identity}",
    )


class SceneIR070Tests(unittest.TestCase):
    def test_roundtrip_has_deterministic_ids_digest_world_and_projection_records(self) -> None:
        first = new_scene("Deterministic scene")
        second = new_scene("Deterministic scene")
        self.assertEqual(first.id, second.id)
        self.assertEqual(first.active_camera_id, second.active_camera_id)
        self.assertEqual(first.layers[0].id, second.layers[0].id)

        item = box("symbolic tensor", [1.0, 2.0, 3.0])
        item.metadata.update({
            "tensor_shape": [1, "T", None, 64],
            "shape_label": "[1, T, ?, 64]",
            "visual_geometry_is_literal_tensor_size": False,
        })
        first.layers[0].objects.append(item)
        first.validate()
        payload = first.to_dict()
        restored = Scene.from_dict(payload)

        self.assertEqual(first.digest(), restored.digest())
        restored_item = next(restored.iter_objects())
        self.assertEqual([1.0, 2.0, 3.0], restored_item.world.position)
        self.assertEqual(len(restored.cameras), len(restored_item.projections))
        self.assertEqual([1, "T", None, 64], restored_item.metadata["tensor_shape"])
        self.assertFalse(restored_item.metadata["visual_geometry_is_literal_tensor_size"])

    def test_camera_rotation_changes_projection_without_changing_world_coordinates(self) -> None:
        scene = new_scene("True camera rotation", projection="perspective")
        item = box("fixed", [2.0, 0.0, 0.0])
        scene.layers[0].objects.append(item)
        scene.refresh_records([1000.0, 800.0])
        before_world = list(item.world.position)
        before_projection = list(item.projections[0].point)

        camera = scene.active_camera()
        camera.rotation = [0.0, 18.0, 0.0]
        scene.refresh_records([1000.0, 800.0])
        after_world = list(item.world.position)
        after_projection = list(item.projections[0].point)

        self.assertEqual(before_world, after_world)
        self.assertNotEqual(before_projection, after_projection)
        self.assertGreater(abs(before_projection[0] - after_projection[0]), 1.0)

    def test_orthographic_and_perspective_are_real_distinct_projections(self) -> None:
        orthographic = Camera.create(
            "Ortho",
            projection="orthographic",
            position=[0.0, 0.0, 10.0],
            target=[0.0, 0.0, 0.0],
            ortho_height=10.0,
            aspect=1.0,
        )
        perspective = Camera.create(
            "Perspective",
            projection="perspective",
            position=[0.0, 0.0, 10.0],
            target=[0.0, 0.0, 0.0],
            fov_y_deg=60.0,
            aspect=1.0,
        )
        near_ortho = orthographic.project([2.0, 0.0, 2.0], [800.0, 800.0])
        far_ortho = orthographic.project([2.0, 0.0, -2.0], [800.0, 800.0])
        near_perspective = perspective.project([2.0, 0.0, 2.0], [800.0, 800.0])
        far_perspective = perspective.project([2.0, 0.0, -2.0], [800.0, 800.0])

        self.assertAlmostEqual(near_ortho.x, far_ortho.x, places=7)
        self.assertGreater(abs(near_perspective.x - far_perspective.x), 20.0)
        self.assertNotEqual(orthographic.projection_matrix(), perspective.projection_matrix())

    def test_ray_picking_returns_nearest_depth_first(self) -> None:
        scene = new_scene("Depth picking", projection="orthographic")
        camera = scene.active_camera()
        camera.position = [0.0, 0.0, 10.0]
        camera.target = [0.0, 0.0, 0.0]
        camera.up = [0.0, 1.0, 0.0]
        camera.ortho_height = 10.0
        front = box("front", [0.0, 0.0, 3.0])
        back = box("back", [0.0, 0.0, -1.0])
        scene.layers[0].objects.extend([back, front])
        scene.validate()

        hits = scene.pick(400.0, 400.0, [800.0, 800.0])
        self.assertEqual([front.id, back.id], [hit.object_id for hit in hits[:2]])
        self.assertLess(hits[0].distance, hits[1].distance)

    def test_xyz_object_and_group_transforms_are_composed_and_locks_are_enforced(self) -> None:
        scene = new_scene("Transforms")
        layer = scene.layers[0]
        group = Group3D.create(
            "Rotated group",
            identity="transform-group",
            transform=Transform3D([10.0, 0.0, 0.0], [0.0, 0.0, 90.0]),
            provenance=SceneProvenance.author("Test-authored transform group."),
        )
        item = box("group child", [1.0, 0.0, 0.0])
        item.parent_group_id = group.id
        group.object_ids.append(item.id)
        layer.groups.append(group)
        layer.objects.append(item)
        scene.validate()

        self.assertAlmostEqual(10.0, item.world.position[0], places=7)
        self.assertAlmostEqual(1.0, item.world.position[1], places=7)
        self.assertAlmostEqual(0.0, item.world.position[2], places=7)

        scene.translate_object(item.id, [0.0, 0.0, 2.0])
        self.assertAlmostEqual(2.0, item.world.position[2], places=7)
        scene.rotate_object(item.id, [90.0, 0.0, 0.0])
        scene.scale_object(item.id, [2.0, 1.0, 0.5])
        self.assertEqual([90.0, 0.0, 0.0], item.transform.rotation)
        self.assertEqual([2.0, 1.0, 0.5], item.transform.scale)

        group.locked = True
        with self.assertRaisesRegex(ValidationError, "locked layer or group"):
            scene.translate_object(item.id, [1.0, 0.0, 0.0])

    def test_matrix_inverse_reconstructs_identity(self) -> None:
        transform = compose_matrix([4.0, -3.0, 2.0], [20.0, -15.0, 45.0], [2.0, 0.5, 1.5])
        inverse = inverse_matrix(transform)
        identity = matrix_multiply(transform, inverse)
        for row in range(4):
            for column in range(4):
                self.assertAlmostEqual(1.0 if row == column else 0.0, identity[row][column], places=7)
        point = [1.0, 2.0, 3.0]
        self.assertTrue(all(
            math.isclose(a, b, abs_tol=1.0e-7)
            for a, b in zip(point, transform_point(inverse, transform_point(transform, point)))
        ))

    def test_strict_parser_rejects_malicious_nonfinite_and_inconsistent_payloads(self) -> None:
        payload = new_scene("Safe parse").to_dict()

        polluted = deepcopy(payload)
        polluted["metadata"]["__proto__"] = {"polluted": True}
        with self.assertRaisesRegex(ValidationError, "unsafe key"):
            Scene.from_dict(polluted)

        unsupported = deepcopy(payload)
        unsupported["execute"] = "rm -rf /"
        with self.assertRaisesRegex(ValidationError, "unsupported fields"):
            Scene.from_dict(unsupported)

        nonfinite = deepcopy(payload)
        nonfinite["cameras"][0]["position"][0] = float("nan")
        with self.assertRaisesRegex(ValidationError, "finite number"):
            Scene.from_dict(nonfinite)

        nested: dict[str, object] = {}
        cursor = nested
        for _ in range(40):
            child: dict[str, object] = {}
            cursor["child"] = child
            cursor = child
        excessive_depth = deepcopy(payload)
        excessive_depth["metadata"]["nested"] = nested
        with self.assertRaisesRegex(ValidationError, "maximum nesting depth"):
            Scene.from_dict(excessive_depth)

        bad_version = deepcopy(payload)
        bad_version["schema_version"] = "2.0"
        with self.assertRaisesRegex(ValidationError, "Unsupported Scene IR schema"):
            Scene.from_dict(bad_version)

        scene = new_scene("Cycle")
        first = Group3D.create("first", identity="cycle:first")
        second = Group3D.create("second", identity="cycle:second")
        first.parent_group_id = second.id
        second.parent_group_id = first.id
        scene.layers[0].groups.extend([first, second])
        with self.assertRaisesRegex(ValidationError, "cycle"):
            scene.validate()

    def test_selection_visibility_and_lock_state_roundtrip(self) -> None:
        scene = new_scene("Selection")
        first, second = box("first selection", [0.0, 0.0, 0.0]), box("second selection", [4.0, 0.0, 0.0])
        scene.layers[0].objects.extend([first, second])
        scene.set_selection([second.id])
        first.visible = False
        second.locked = True
        restored = Scene.from_dict(scene.to_dict())
        restored_first, restored_second = list(restored.iter_objects())
        self.assertFalse(restored_first.visible)
        self.assertTrue(restored_second.locked)
        self.assertTrue(restored_second.selected)
        self.assertEqual([second.id], restored.selection_ids)


if __name__ == "__main__":
    unittest.main()
