from __future__ import annotations

import unittest

from nn_davinci.scene_math import (
    Ray,
    identity_matrix,
    inverse_matrix,
    matrix4,
    normalize,
    orthographic_matrix,
    perspective_matrix,
    pick_aabbs,
    project_point,
    project_points,
    ray_aabb_intersection,
    transform_point,
    unproject_point,
    vec3,
)


class SceneMath070Tests(unittest.TestCase):
    def test_numeric_vector_and_matrix_validation_rejects_invalid_values(self) -> None:
        invalid_vectors = (
            ([True, 0.0, 0.0], "finite number"),
            ([object(), 0.0, 0.0], "finite number"),
            ([float("inf"), 0.0, 0.0], "finite number"),
            ("123", "exactly three"),
        )
        for value, message in invalid_vectors:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, message):
                vec3(value)

        with self.assertRaisesRegex(ValueError, "zero vector"):
            normalize((0.0, 0.0, 0.0), name="direction")
        with self.assertRaisesRegex(ValueError, "4 x 4 matrix"):
            matrix4(((1.0, 0.0),))

    def test_degenerate_matrix_and_projection_inputs_fail_explicitly(self) -> None:
        zero_homogeneous_w = (
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 1.0, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.0),
            (0.0, 0.0, 0.0, 0.0),
        )
        with self.assertRaisesRegex(ValueError, "invalid homogeneous coordinate"):
            transform_point(zero_homogeneous_w, (1.0, 2.0, 3.0))
        with self.assertRaisesRegex(ValueError, "singular"):
            inverse_matrix(zero_homogeneous_w)

        swap_x_y = (
            (0.0, 1.0, 0.0, 0.0),
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )
        self.assertEqual(inverse_matrix(swap_x_y), swap_x_y)

        with self.assertRaisesRegex(ValueError, "field of view"):
            perspective_matrix(0.0, 1.0, 0.1, 100.0)
        with self.assertRaisesRegex(ValueError, "clipping planes"):
            perspective_matrix(60.0, 0.0, 0.1, 100.0)
        with self.assertRaisesRegex(ValueError, "orthographic dimensions"):
            orthographic_matrix(0.0, 1.0, 0.1, 100.0)

    def test_projection_guards_keep_camera_plane_results_finite(self) -> None:
        identity = identity_matrix()
        projection = perspective_matrix(60.0, 1.0, 0.1, 100.0)

        with self.assertRaisesRegex(ValueError, "viewport must contain"):
            project_point((0.0, 0.0, -1.0), identity, projection, "100x100")
        with self.assertRaisesRegex(ValueError, "viewport dimensions"):
            project_point((0.0, 0.0, -1.0), identity, projection, (0.0, 100.0))

        camera_plane = project_point((0.0, 0.0, 0.0), identity, projection, (200.0, 100.0))
        self.assertEqual(tuple(camera_plane), (100.0, 50.0, 2.0))
        self.assertEqual(camera_plane.ndc, (0.0, 0.0, 2.0))
        self.assertFalse(camera_plane.visible)

        batch_input = ((0.0, 0.0, -1.0), (0.25, -0.5, -2.0), (0.0, 0.0, 0.0))
        batch = project_points(batch_input, identity, projection, (200.0, 100.0))
        individual = tuple(project_point(point, identity, projection, (200.0, 100.0)) for point in batch_input)
        self.assertEqual(batch, individual)

        with self.assertRaisesRegex(ValueError, "viewport must contain"):
            unproject_point(0.0, 0.0, 0.0, identity, identity, (100.0,))
        with self.assertRaisesRegex(ValueError, "viewport dimensions"):
            unproject_point(0.0, 0.0, 0.0, identity, identity, (100.0, -1.0))

        inverse_with_zero_w = (
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 1.0, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0, -1.0),
        )
        projection_with_zero_w = inverse_matrix(inverse_with_zero_w)
        with self.assertRaisesRegex(ValueError, "invalid homogeneous coordinate"):
            unproject_point(50.0, 50.0, 1.0, identity, projection_with_zero_w, (100.0, 100.0))

    def test_ray_aabb_intersection_covers_parallel_reversed_and_behind_cases(self) -> None:
        bounds_min = (-1.0, -1.0, -1.0)
        bounds_max = (1.0, 1.0, 1.0)

        with self.assertRaisesRegex(ValueError, "minimum must not exceed"):
            ray_aabb_intersection(Ray((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)), (1.0, -1.0, -1.0), (0.0, 1.0, 1.0))

        parallel_outside = Ray((2.0, 0.0, 0.0), (0.0, 1.0, 0.0))
        self.assertIsNone(ray_aabb_intersection(parallel_outside, bounds_min, bounds_max))

        reversed_direction = Ray((2.0, 0.0, 0.0), (-1.0, 0.0, 0.0))
        self.assertEqual(ray_aabb_intersection(reversed_direction, bounds_min, bounds_max), 1.0)
        self.assertEqual(reversed_direction.point_at(1.0), (1.0, 0.0, 0.0))

        disjoint_axis_intervals = Ray((0.0, 2.0, 0.0), (1.0, 1.0, 0.0))
        self.assertIsNone(
            ray_aabb_intersection(
                disjoint_axis_intervals,
                (1.0, -2.0, -1.0),
                (2.0, -1.0, 1.0),
            )
        )

        pointing_away = Ray((2.0, 0.0, 0.0), (1.0, 0.0, 0.0))
        self.assertIsNone(ray_aabb_intersection(pointing_away, bounds_min, bounds_max))

    def test_pick_aabbs_filters_misses_and_sorts_tied_hits_by_identifier(self) -> None:
        ray = Ray((-5.0, 0.0, 0.0), (1.0, 0.0, 0.0))
        boxes = (
            ("far", (2.0, -1.0, -1.0), (3.0, 1.0, 1.0)),
            ("b", (-1.0, -1.0, -1.0), (1.0, 1.0, 1.0)),
            ("miss", (-1.0, 2.0, -1.0), (1.0, 3.0, 1.0)),
            ("a", (-1.0, -1.0, -1.0), (1.0, 1.0, 1.0)),
        )

        self.assertEqual(pick_aabbs(ray, boxes), [("a", 4.0), ("b", 4.0), ("far", 7.0)])


if __name__ == "__main__":
    unittest.main()
