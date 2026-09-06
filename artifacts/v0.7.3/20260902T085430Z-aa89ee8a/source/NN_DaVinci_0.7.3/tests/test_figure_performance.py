from __future__ import annotations

from statistics import median
import time
import unittest

from nn_davinci.figure_export import render_figure_svg
from nn_davinci.figure_ir import FigureIR, FigureObject, FigureProvenance, new_figure
from nn_davinci.server import create_app
from scripts.stress_graphs import deep_chain


class FigurePerformanceTests(unittest.TestCase):
    def test_one_thousand_figure_objects_remain_serializable_and_operable(self) -> None:
        figure = new_figure("One thousand objects")
        # The stress case uses a large authoring canvas so every required label
        # still has a physically valid >=7 pt lane.  Performance evidence must
        # not rely on the old renderer's silent text compression.
        figure.pages[0].width_mm = 600
        figure.pages[0].height_mm = 300
        panel = next(figure.iter_panels())
        panel.geometry.update({"x": 4, "y": 4, "width": 592, "height": 292})
        model_layer, author_layer = panel.layers[0], panel.layers[2]
        for index in range(1_000):
            x = panel.geometry["x"] + 2 + (index % 40) * 14
            y = panel.geometry["y"] + 5 + (index // 40) * 10
            model_layer.objects.append(
                FigureObject.create(
                    "node-glyph",
                    f"N{index}",
                    {"x": x, "y": y, "width": 12, "height": 8},
                    FigureProvenance(
                        "graph_ir", source_id=f"n{index}", graph_ir_ids=[f"n{index}"]
                    ),
                    identity=f"performance:{index}",
                    order=index,
                )
            )
        figure.validate()
        render_samples: list[float] = []
        for _ in range(3):
            started = time.perf_counter()
            svg = render_figure_svg(figure)
            render_samples.append((time.perf_counter() - started) * 1_000)
        self.assertEqual(1_000, svg.count('data-text-role="node-label"'))
        self.assertEqual(1_000, len(list(figure.iter_objects())))
        self.assertLess(median(render_samples), 2_000)

        moved = model_layer.objects[500]
        started = time.perf_counter()
        figure.move_object(moved.id, author_layer.id)
        self.assertLess(time.perf_counter() - started, 2.0)
        restored = FigureIR.from_dict(figure.to_dict())
        self.assertEqual(author_layer.id, restored.find_object(moved.id)[1].id)

    def test_eight_panels_are_valid_and_locked_panel_identity_roundtrips(self) -> None:
        figure = new_figure(
            "A through H",
            panel_modes=(
                "schematic",
                "tensor-geometry",
                "mixed",
                "schematic",
                "tensor-geometry",
                "mixed",
                "schematic",
                "tensor-geometry",
            ),
        )
        panels = list(figure.iter_panels())
        panels[3].locked = True
        frozen_geometry = dict(panels[3].geometry)
        restored = FigureIR.from_dict(figure.to_dict())
        restored_panels = list(restored.iter_panels())
        self.assertEqual(list("ABCDEFGH"), [panel.label for panel in restored_panels])
        self.assertTrue(restored_panels[3].locked)
        self.assertEqual(frozen_geometry, restored_panels[3].geometry)

    def test_large_graph_figure_entry_uses_bounded_summary_not_full_expansion(self) -> None:
        graph = deep_chain(1_001)
        client = create_app().test_client()
        started = time.perf_counter()
        response = client.post(
            "/api/figure/from-graph",
            json={"graph": graph.to_dict(), "mode": "mixed"},
        )
        self.assertEqual(200, response.status_code)
        body = response.get_json()
        document = body["figure"]
        recovery = document["metadata"]["large_graph"]
        self.assertEqual(1_001, recovery["source_node_count"])
        self.assertEqual(
            "bounded Semantic View summary of the original Graph IR",
            recovery["figure_source"],
        )
        self.assertFalse(recovery["synthetic_coarse_graph_used"])
        self.assertIn("lazy summary", recovery["full_graph_available_via"])
        semantic_ids = {item["id"] for item in body["semantic_view"]["entities"]}
        semantic_sources = {
            item["provenance"]["source_id"]
            for page in document["pages"]
            for panel in page["panels"]
            for layer in panel["layers"]
            for item in layer["objects"]
            if item["provenance"]["kind"] == "semantic_view"
        }
        self.assertTrue(semantic_sources)
        self.assertLessEqual(semantic_sources, semantic_ids)
        self.assertTrue(body["provenance_validation"]["passed"])
        object_count = sum(
            len(layer["objects"])
            for page in document["pages"]
            for panel in page["panels"]
            for layer in panel["layers"]
        )
        self.assertLess(object_count, 1_001)
        self.assertLess(time.perf_counter() - started, 3.0)

    def test_large_graph_figure_focus_is_bounded_and_keeps_only_exact_source_ids(self) -> None:
        graph = deep_chain(1_001)
        focus_id = graph.nodes[500].id
        client = create_app().test_client()
        response = client.post(
            "/api/figure/from-graph",
            json={
                "graph": graph.to_dict(),
                "mode": "schematic",
                "focus_ids": [focus_id],
                "focus_hops": 2,
            },
        )
        self.assertEqual(200, response.status_code)
        body = response.get_json()
        figure = body["figure"]
        semantic_metadata = figure["metadata"]["semantic_view"]
        self.assertEqual([focus_id], semantic_metadata["focus_ids"])
        self.assertEqual(2, semantic_metadata["focus_hops"])
        self.assertEqual("operation", semantic_metadata["selected_level"])
        self.assertTrue(semantic_metadata["materialized_focus_ids"])
        self.assertEqual(1_001, figure["metadata"]["large_graph"]["source_node_count"])
        self.assertFalse(figure["metadata"]["large_graph"]["synthetic_coarse_graph_used"])
        self.assertTrue(body["provenance_validation"]["passed"])

        known_graph_ids = {
            *(node.id for node in graph.nodes),
            *(edge.id for edge in graph.edges),
            *(port.id for node in graph.nodes for port in [*node.inputs, *node.outputs]),
        }
        claimed_graph_ids = {
            source_id
            for page in figure["pages"]
            for panel in page["panels"]
            for layer in panel["layers"]
            for item in layer["objects"]
            for source_id in item["provenance"]["graph_ir_ids"]
        }
        self.assertTrue(claimed_graph_ids)
        self.assertLessEqual(claimed_graph_ids, known_graph_ids)
        object_count = sum(
            len(layer["objects"])
            for page in figure["pages"]
            for panel in page["panels"]
            for layer in panel["layers"]
        )
        self.assertLess(object_count, 20)


if __name__ == "__main__":
    unittest.main()
