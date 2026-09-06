from __future__ import annotations

from copy import deepcopy
import unittest

from nn_davinci.figure_export import render_figure_svg
from nn_davinci.figure_ir import FigureIR, FigureObject, FigureProvenance, figure_from_graph, new_figure
from nn_davinci.ir import Edge, GraphIR, Node, Port, Subgraph, TensorSpec
from nn_davinci.model_figure import model_figure_from_graph, structure_lens_panel_preview, validate_model_figure_provenance
from nn_davinci.project import Project
from nn_davinci.semantic import derive_semantic_view
from nn_davinci.structure_lens import StructureLens
from nn_davinci.viewport import Viewport


def tensor(name: str, shape: list[int | str | None]) -> TensorSpec:
    return TensorSpec(name, shape, "float32")


def branched_graph() -> GraphIR:
    source = Node(
        "source", "Source", "Input", category="input",
        outputs=[
            Port("source:values", "values", "output", tensor("values", [1, "T", 8])),
            Port("source:indices", "indices", "output", TensorSpec("indices", [1, "T"], "int64")),
        ],
        source={"fixture": "model-figure"},
    )
    left = Node(
        "left", "Left branch", "Linear",
        inputs=[Port("left:in", "input", "input", tensor("values", [1, "T", 8]))],
        outputs=[Port("left:out", "output", "output", tensor("left", [1, "T", 4]))],
        source={"fixture": "model-figure"},
    )
    right = Node(
        "right", "Right branch", "Gather",
        inputs=[Port("right:indices", "indices", "input", TensorSpec("indices", [1, "T"], "int64"))],
        outputs=[Port("right:out", "output", "output", tensor("right", [1, "T", 4]))],
        source={"fixture": "model-figure"},
    )
    merge = Node(
        "merge", "Merge", "Concatenate",
        inputs=[
            Port("merge:left", "left", "input", tensor("left", [1, "T", 4])),
            Port("merge:right", "right", "input", tensor("right", [1, "T", 4])),
        ],
        outputs=[Port("merge:out", "output", "output", tensor("merged", [1, "T", 8]))],
        source={"fixture": "model-figure"},
    )
    return GraphIR(
        "Branched evidence",
        [source, left, right, merge],
        [
            Edge("values-edge", source.id, left.id, "source:values", "left:in", tensor("values", [1, "T", 8])),
            Edge("indices-edge", source.id, right.id, "source:indices", "right:indices", TensorSpec("indices", [1, "T"], "int64")),
            Edge("left-edge", left.id, merge.id, "left:out", "merge:left", tensor("left", [1, "T", 4])),
            Edge("right-edge", right.id, merge.id, "right:out", "merge:right", tensor("right", [1, "T", 4])),
        ],
        metadata={"source_format": "fixture"},
    ).validate()


class ModelFigurePipelineTests(unittest.TestCase):
    def test_graph_semantic_layout_figure_keeps_all_outputs_and_bindings(self) -> None:
        graph = branched_graph()
        figure = figure_from_graph(graph, mode="mixed")

        tensors = [item for item in figure.iter_objects() if item.kind == "tensor-glyph"]
        self.assertEqual(5, len(tensors))
        source_ports = {item.metadata["port_id"] for item in tensors if item.name.startswith("Source")}
        self.assertEqual({"source:values", "source:indices"}, source_ports)
        indices = next(item for item in tensors if item.metadata["port_id"] == "source:indices")
        self.assertEqual([1, "T"], indices.metadata["tensor_shape"])
        self.assertTrue(indices.metadata["unknown_dimensions_preserved"])

        connectors = [item for item in figure.iter_objects() if item.kind == "edge"]
        binding_pairs = {(item.metadata["source_port"], item.metadata["target_port"]) for item in connectors}
        self.assertIn(("source:values", "left:in"), binding_pairs)
        self.assertIn(("source:indices", "right:indices"), binding_pairs)
        self.assertIn(("right:out", "merge:right"), binding_pairs)
        self.assertTrue(all(item.metadata["route_origin"] == "layout-engine" for item in connectors))

        node_y = {
            round(float(item.geometry["y"]), 3)
            for item in figure.iter_objects()
            if item.kind in {"node-glyph", "operator-glyph"}
        }
        self.assertGreater(len(node_y), 1, "a branch-aware layout must not be a single horizontal placeholder row")
        provenance = validate_model_figure_provenance(figure, graph)
        self.assertTrue(provenance["passed"], provenance)
        self.assertTrue(figure.metadata["model_figure_pipeline"]["graph_to_semantic_to_figure"])

        tampered = deepcopy(figure)
        tampered_tensor = next(item for item in tampered.iter_objects() if item.kind == "tensor-glyph")
        tampered_tensor.metadata["tensor_shape"] = [999]
        report = validate_model_figure_provenance(tampered, graph)
        self.assertFalse(report["passed"])
        self.assertTrue(any(
            "tensor_shape_disagrees_with_provenance" in failure
            for failure in report["failures"]
        ))

        coherently_tampered = deepcopy(figure)
        coherent_tensor = next(
            item for item in coherently_tampered.iter_objects()
            if item.kind == "tensor-glyph"
        )
        coherent_tensor.metadata["tensor_shape"] = [999]
        coherent_tensor.metadata["shape_label"] = "[999]"
        coherent_tensor.provenance.evidence["tensor"]["shape"] = [999]
        report = validate_model_figure_provenance(coherently_tampered, graph)
        self.assertFalse(report["passed"])
        self.assertTrue(any(
            "tensor_evidence_disagrees_with_graph_port" in failure
            for failure in report["failures"]
        ))

        source_port_tampered = deepcopy(figure)
        source_port_tensor = next(
            item for item in source_port_tampered.iter_objects()
            if item.kind == "tensor-glyph"
        )
        source_port_tensor.provenance.evidence["source_port_id"] = "orphan-port"
        report = validate_model_figure_provenance(source_port_tampered, graph)
        self.assertFalse(report["passed"])
        self.assertTrue(any(
            "tensor_evidence_source_port_mismatch" in failure
            for failure in report["failures"]
        ))

        binding_tampered = deepcopy(figure)
        binding_edge = next(item for item in binding_tampered.iter_objects() if item.kind == "edge")
        binding_edge.metadata["source_port"], binding_edge.metadata["target_port"] = (
            binding_edge.metadata["target_port"],
            binding_edge.metadata["source_port"],
        )
        report = validate_model_figure_provenance(binding_tampered, graph)
        self.assertFalse(report["passed"])
        self.assertTrue(any(
            "figure_edge_port_binding_disagrees_with_graph" in failure
            for failure in report["failures"]
        ))

        binding_record_tampered = deepcopy(figure)
        binding_record_edge = next(
            item for item in binding_record_tampered.iter_objects()
            if item.kind == "edge"
        )
        binding_record_edge.metadata["source_port_binding"] = {
            "source_node_id": binding_record_edge.provenance.graph_ir_ids[0],
            "source_port_id": "orphan-port",
            "status": "exact",
        }
        report = validate_model_figure_provenance(binding_record_tampered, graph)
        self.assertFalse(report["passed"])
        self.assertTrue(any(
            "figure_edge_source_binding_disagrees_with_graph" in failure
            for failure in report["failures"]
        ))

        overridden = deepcopy(figure)
        overridden_tensor = next(item for item in overridden.iter_objects() if item.kind == "tensor-glyph")
        source_shape = list(overridden_tensor.metadata["tensor_shape"])
        overridden_tensor.metadata.update({
            "author_shape_override": [1, 32, 112, 112],
            "author_shape_override_label": "[1, 32, 112, 112]",
            "shape_label_origin": "author_override",
        })
        overridden.validate()
        self.assertEqual(source_shape, overridden_tensor.metadata["tensor_shape"])
        self.assertTrue(validate_model_figure_provenance(overridden, graph)["passed"])
        overridden_svg = render_figure_svg(overridden)
        self.assertIn('data-shape-label-origin="author_override"', overridden_svg)

        author_figure = new_figure("Author tensor")
        next(author_figure.iter_panels()).layers[2].objects.append(FigureObject.create(
            "tensor-glyph",
            "Author tensor",
            {"x": 10, "y": 10, "width": 12, "height": 8, "depth": 3},
            FigureProvenance.author(),
            metadata={
                "tensor_shape": ["B", "T", "D"],
                "shape_label": "[B, T, D]",
                "shape_label_origin": "author_annotation",
                "geometry_scale": "manual",
            },
        ))
        author_svg = render_figure_svg(author_figure.validate())
        self.assertIn('data-shape-label-origin="author_annotation"', author_svg)
        self.assertNotIn('data-real-shape="true"', author_svg)

    def test_rebuild_preserves_locked_geometry_and_author_route(self) -> None:
        graph = branched_graph()
        original = figure_from_graph(graph, mode="schematic")
        node = next(item for item in original.iter_objects() if item.kind in {"node-glyph", "operator-glyph"})
        node.geometry["x"] += 9.0
        node.locked = True
        edge = next(item for item in original.iter_objects() if item.kind == "edge")
        edge.manual_route = [[12.0, 13.0], [25.0, 18.0], [31.0, 22.0]]
        edge.metadata["author_manual_route"] = True

        rebuilt = figure_from_graph(graph, mode="schematic", existing_figure=original)
        rebuilt_node = rebuilt.find_object(node.id)[2]
        rebuilt_edge = rebuilt.find_object(edge.id)[2]
        self.assertEqual(node.geometry, rebuilt_node.geometry)
        self.assertTrue(rebuilt_node.locked)
        self.assertEqual(edge.manual_route, rebuilt_edge.manual_route)
        self.assertEqual("author", rebuilt_edge.metadata["route_origin"])

    def test_focus_and_viewport_boundaries_retain_exact_node_edge_and_port_evidence(self) -> None:
        graph = branched_graph()
        semantic = derive_semantic_view(graph)
        known_graph_ids = {
            *(node.id for node in graph.nodes),
            *(edge.id for edge in graph.edges),
            *(port.id for node in graph.nodes for port in [*node.inputs, *node.outputs]),
        }
        cases = {
            "focus": {"focus_ids": ["left"], "focus_hops": 0},
            "viewport": {"viewport": Viewport(x=0, y=0, width=200, height=100, padding=0)},
        }
        for name, options in cases.items():
            with self.subTest(slice=name):
                figure = model_figure_from_graph(
                    graph,
                    semantic_view=semantic,
                    mode="mixed",
                    **options,
                )
                report = validate_model_figure_provenance(figure, graph, semantic)
                self.assertTrue(report["passed"], report)
                claims = {
                    source_id
                    for item in figure.iter_objects()
                    for source_id in item.provenance.graph_ir_ids
                }
                self.assertLessEqual(claims, known_graph_ids)
                bindings = {
                    (item.metadata["source_port"], item.metadata["target_port"])
                    for item in figure.iter_objects()
                    if item.kind == "edge"
                }
                self.assertTrue(
                    bindings.intersection(
                        {
                            ("source:values", "left:in"),
                            ("source:indices", "right:indices"),
                            ("left:out", "merge:left"),
                        }
                    )
                )

    def test_provenance_validator_rejects_orphan_semantics_and_reverse_index_tampering(self) -> None:
        graph = branched_graph()
        semantic = derive_semantic_view(graph)
        figure = model_figure_from_graph(graph, semantic_view=semantic, mode="mixed")
        self.assertTrue(validate_model_figure_provenance(figure, graph, semantic)["passed"])

        semantic_object = next(
            item for item in figure.iter_objects()
            if item.provenance.kind == "semantic_view"
        )
        orphaned = deepcopy(figure)
        orphaned.find_object(semantic_object.id)[2].provenance.source_id = "orphan-semantic-entity"
        orphan_report = validate_model_figure_provenance(orphaned, graph, semantic)
        self.assertFalse(orphan_report["passed"])
        self.assertTrue(any("orphan_semantic_entity_ids" in failure for failure in orphan_report["failures"]))

        semantic_index_tampered = deepcopy(figure)
        semantic_index_tampered.metadata["provenance_index"]["semantic_to_figure"]["orphan-semantic-entity"] = [semantic_object.id]
        self.assertFalse(validate_model_figure_provenance(semantic_index_tampered, graph, semantic)["passed"])

        reverse_tampered = deepcopy(figure)
        reverse_tampered.metadata["provenance_index"]["figure_to_source"][semantic_object.id]["semantic_id"] = "orphan-semantic-entity"
        self.assertFalse(validate_model_figure_provenance(reverse_tampered, graph, semantic)["passed"])

        coherently_reindexed = deepcopy(figure)
        reindexed_object = coherently_reindexed.find_object(semantic_object.id)[2]
        original_semantic_id = reindexed_object.provenance.source_id
        wrong_semantic_id = next(
            entity.id for entity in semantic.entities_at("operation")
            if entity.id != original_semantic_id
        )
        reindexed_object.provenance.source_id = wrong_semantic_id
        reindexed_object.provenance.evidence["semantic_entity_ids"] = [wrong_semantic_id]
        semantic_index = coherently_reindexed.metadata["provenance_index"]["semantic_to_figure"]
        semantic_index[original_semantic_id].remove(semantic_object.id)
        if not semantic_index[original_semantic_id]:
            del semantic_index[original_semantic_id]
        semantic_index.setdefault(wrong_semantic_id, []).append(semantic_object.id)
        reverse = coherently_reindexed.metadata["provenance_index"]["figure_to_source"][semantic_object.id]
        reverse["semantic_id"] = wrong_semantic_id
        reverse["semantic_ids"] = [wrong_semantic_id]
        coherent_report = validate_model_figure_provenance(coherently_reindexed, graph, semantic)
        self.assertFalse(coherent_report["passed"])
        self.assertTrue(any(
            failure.get("semantic_entity_has_no_claimed_graph_node_evidence") == wrong_semantic_id
            for failure in coherent_report["failures"]
        ))

        tensor_object = next(item for item in figure.iter_objects() if item.kind == "tensor-glyph")
        port_tampered = deepcopy(figure)
        port_tampered.metadata["provenance_index"]["figure_to_source"][tensor_object.id]["graph_port_ids"] = []
        self.assertFalse(validate_model_figure_provenance(port_tampered, graph, semantic)["passed"])

    def test_large_operation_request_uses_bounded_summary_first(self) -> None:
        nodes = [Node(f"n{index}", f"Operation {index}", "Identity") for index in range(81)]
        graph = GraphIR(
            "Large",
            nodes,
            [Edge(f"e{index}", nodes[index].id, nodes[index + 1].id) for index in range(80)],
            metadata={"source_format": "fixture"},
        ).validate()
        figure = figure_from_graph(graph, mode="schematic", level="operation")
        semantic = figure.metadata["semantic_view"]
        self.assertTrue(semantic["summary_first"])
        self.assertEqual("operation", semantic["requested_level"])
        self.assertEqual("stage", semantic["selected_level"])
        self.assertLessEqual(figure.metadata["model_figure_pipeline"]["bounded_visible_nodes"], 80)

    def test_paper_group_uses_persisted_semantic_ids_and_auditable_abbreviation(self) -> None:
        nodes = [
            Node("conv1", "Conv 1", "Conv2d"),
            Node("conv2", "Conv 2", "Conv2d"),
        ]
        graph = GraphIR(
            "Repeated paper blocks",
            nodes,
            subgraphs=[
                Subgraph(
                    "block1",
                    "Extremely Long Repeated Bottleneck Component 1",
                    ["conv1"],
                    level="block",
                ),
                Subgraph(
                    "block2",
                    "Extremely Long Repeated Bottleneck Component 2",
                    ["conv2"],
                    level="block",
                ),
            ],
        ).validate()
        semantic = derive_semantic_view(graph)
        figure = model_figure_from_graph(
            graph,
            semantic_view=semantic,
            level="block",
            view="paper",
        )
        report = validate_model_figure_provenance(figure, graph, semantic)
        self.assertTrue(report["passed"], report)
        known_semantic_ids = {entity.id for entity in semantic.entities}
        claimed_semantic_ids = {
            semantic_id
            for item in figure.iter_objects()
            for semantic_id in item.provenance.evidence.get("semantic_entity_ids", [])
        }
        self.assertTrue(claimed_semantic_ids)
        self.assertLessEqual(claimed_semantic_ids, known_semantic_ids)
        svg = render_figure_svg(figure)
        self.assertIn('data-abbreviated="true"', svg)
        self.assertIn(
            'data-full-text="Extremely Long Repeated Bottleneck Component ×2"',
            svg,
        )

    def test_structure_lens_preview_is_side_effect_free_and_requires_explicit_add(self) -> None:
        graph = branched_graph()
        before = graph.to_dict()
        result = StructureLens(graph).bounded_paths("source", "merge")
        preview = structure_lens_panel_preview(graph, result)

        self.assertEqual(before, graph.to_dict())
        self.assertTrue(preview["available"])
        self.assertTrue(preview["preview_only"])
        self.assertTrue(preview["requires_explicit_add"])
        self.assertFalse(preview["mutated_figure"])
        self.assertGreater(
            sum(len(layer["objects"]) for layer in preview["panel"]["layers"]),
            0,
        )
        self.assertTrue(
            all(
                item["metadata"].get("structure_lens_preview")
                for layer in preview["panel"]["layers"]
                for item in layer["objects"]
            )
        )
        known_graph_ids = {
            *(node.id for node in graph.nodes),
            *(edge.id for edge in graph.edges),
            *(
                port.id
                for node in graph.nodes
                for port in [*node.inputs, *node.outputs]
            ),
        }
        preview_objects = [
            item
            for layer in preview["panel"]["layers"]
            for item in layer["objects"]
        ]
        self.assertTrue(all(
            item["provenance"]["kind"] == "graph_ir"
            for item in preview_objects
        ))
        self.assertTrue(all(
            set(item["provenance"]["graph_ir_ids"]) <= known_graph_ids
            for item in preview_objects
        ))
        self.assertTrue(all(
            item["provenance"]["evidence"].get("structure_lens_graph_evidence")
            for item in preview_objects
        ))
        semantic_identity_keys = {
            "semantic_view_id",
            "source_semantic_ids",
            "semantic_connection_id",
            "semantic_connection_ids",
            "semantic_source_port",
            "semantic_target_port",
            "semantic_port_id",
        }
        self.assertTrue(all(
            semantic_identity_keys.isdisjoint(item["metadata"])
            for item in preview_objects
        ))
        self.assertTrue(all(
            item["provenance"]["source_locator"].get("format") != "semantic-view"
            for item in preview_objects
        ))

        figure_payload = new_figure("Graph-only Structure Lens panel").to_dict()
        figure_payload["pages"][0]["panels"] = [preview["panel"]]
        figure = FigureIR.from_dict(figure_payload)
        graph_to_figure: dict[str, list[str]] = {}
        figure_to_source: dict[str, dict[str, list[str]]] = {}
        known_port_ids = {
            port.id
            for node in graph.nodes
            for port in [*node.inputs, *node.outputs]
        }
        for item in figure.iter_objects():
            graph_ids = list(item.provenance.graph_ir_ids)
            for graph_id in graph_ids:
                graph_to_figure.setdefault(graph_id, []).append(item.id)
            figure_to_source[item.id] = {
                "graph_ir_ids": graph_ids,
                "graph_port_ids": [
                    graph_id for graph_id in graph_ids
                    if graph_id in known_port_ids
                ],
            }
        figure.metadata["provenance_index"] = {
            "graph_to_figure": {
                graph_id: sorted(set(object_ids))
                for graph_id, object_ids in sorted(graph_to_figure.items())
            },
            "semantic_to_figure": {},
            "figure_to_source": dict(sorted(figure_to_source.items())),
        }
        report = validate_model_figure_provenance(figure, graph)
        self.assertTrue(report["passed"], report)
        project = Project(
            "Graph-only Structure Lens project",
            graph,
            figure_ir=figure.to_dict(),
        )
        self.assertIsNone(project.persisted_semantic_view())


if __name__ == "__main__":
    unittest.main()
