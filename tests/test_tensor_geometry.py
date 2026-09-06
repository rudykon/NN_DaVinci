from __future__ import annotations

import unittest

from nn_davinci.tensor_geometry import (
    TensorGeometrySpec,
    operator_symbol,
    route_around,
    shape_transition,
    tensor_geometry,
    tensor_geometry_many,
)


class TensorGeometryTests(unittest.TestCase):
    def test_required_shapes_generate_real_polygons_and_authoritative_labels(self) -> None:
        cases = [
            ([1, 3, 224, 224], "NCHW"),
            ([1, 64, 56, 56], "NCHW"),
            ([1, 197, 768], "BTD"),
            (["B", 3, 224, 224], "NCHW"),
            ([1, "T", 768], "BTD"),
            ([1, None, 768], "BTD"),
            ([768, 768], "matrix"),
            ([768], "vector"),
            ([], "scalar"),
        ]
        for shape, layout in cases:
            for mode in ("linear", "sqrt", "log", "normalized"):
                with self.subTest(shape=shape, layout=layout, mode=mode):
                    geometry = tensor_geometry(TensorGeometrySpec(shape, layout=layout, scale_mode=mode))
                    self.assertEqual({"front", "top", "side"}, set(geometry.faces))
                    self.assertTrue(all(len(points) == 4 for points in geometry.faces.values()))
                    self.assertEqual("[" + ", ".join("?" if item is None else str(item) for item in shape) + "]", geometry.shape_label)
                    self.assertTrue(geometry.metadata["scale_is_visual_only"])
                    self.assertFalse(geometry.metadata["css_perspective_used"])

    def test_manual_geometry_and_multi_input_output(self) -> None:
        geometry = tensor_geometry(TensorGeometrySpec(["B", "T", "D"], layout="BTD", scale_mode="manual", manual_size=[30, 18, 6]))
        self.assertEqual({"width": 30.0, "height": 18.0, "depth": 6.0, "visible_depth": 3.0}, geometry.visual_size)
        multiple = tensor_geometry_many(([1, 3, 224, 224], [1, 64, 56, 56], [1, None, 768]))
        self.assertEqual(3, len(multiple))
        self.assertLess(multiple[0].bounds["x"], multiple[1].bounds["x"])

    def test_operator_families_routes_and_transitions(self) -> None:
        for family in ("convolution", "pooling", "upsample", "concatenate", "addition", "attention", "normalization", "routing", "expert"):
            with self.subTest(family=family):
                self.assertTrue(operator_symbol(family, 10, 10)["editable"])
        route = route_around((0, 10), (100, 10), [{"x": 40, "y": 5, "width": 20, "height": 20}], residual=True)
        self.assertGreaterEqual(len(route), 6)
        self.assertLess(route[2][1], 5)
        self.assertEqual("shape-change", shape_transition([1, 64, 56, 56], [1, 128, 28, 28])["status"])
        self.assertEqual("unknown", shape_transition(["B", "T", 768], ["B", "T", 768])["status"])


if __name__ == "__main__":
    unittest.main()
