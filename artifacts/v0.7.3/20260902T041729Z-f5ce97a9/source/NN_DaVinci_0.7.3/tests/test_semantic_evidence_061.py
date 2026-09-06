from __future__ import annotations

import unittest

from nn_davinci.errors import ValidationError
from nn_davinci.ir import Edge, GraphIR, Node, Port, TensorSpec
from nn_davinci.semantic import SemanticView, derive_semantic_view, normalize_semantic_level


def _tensor(name: str, shape: list[int | str | None]) -> TensorSpec:
    return TensorSpec(
        name=name,
        shape=shape,
        dtype="float32",
        semantic="activation",
        dynamic_axes={0: "batch"},
    )


def _bound_graph() -> GraphIR:
    source = Node(
        "source",
        "Source",
        "CustomSource",
        outputs=[
            Port("source:out:0", "main", "output", _tensor("main", [None, 4])),
            Port("source:out:1", "side", "output", _tensor("side", [None, 8])),
        ],
        attributes={"declared_schema": {"revision": 2}},
    )
    target = Node(
        "target",
        "Target",
        "CustomTarget",
        inputs=[
            Port("target:in:0", "main", "input", _tensor("main", [None, 4])),
            Port("target:in:1", "side", "input", _tensor("side", [None, 8])),
        ],
    )
    exact = Edge(
        "exact-edge",
        source.id,
        target.id,
        source_port="source:out:1",
        target_port="target:in:1",
        tensor=_tensor("side-edge", [None, 8]),
        kind="data",
        label="side channel",
        attributes={"quantization": {"bits": 8}},
    )
    unknown = Edge(
        "unknown-edge",
        source.id,
        target.id,
        tensor=_tensor("unbound-edge", [None, "features"]),
        kind="control",
        label="unbound by importer",
    )
    return GraphIR(
        "Evidence graph",
        [source, target],
        [exact, unknown],
        inputs=[_tensor("model-input", [None, 4])],
        outputs=[_tensor("model-output", [None, 8])],
    ).validate()


class SemanticEvidence061Tests(unittest.TestCase):
    def test_framework_and_module_selection_aliases_preserve_persisted_levels(self) -> None:
        graph = _bound_graph()
        semantic = derive_semantic_view(graph)

        framework = semantic.materialize(graph, level="framework", view="faithful")
        model = semantic.materialize(graph, level="model", view="faithful")
        module = semantic.materialize(graph, level="module", view="faithful")
        layer = semantic.materialize(graph, level="layer", view="faithful")

        self.assertEqual(model.to_dict(), framework.to_dict())
        self.assertEqual(layer.to_dict(), module.to_dict())
        self.assertEqual("model", normalize_semantic_level("framework"))
        self.assertEqual("layer", normalize_semantic_level("module"))

    def test_materialize_preserves_parallel_edges_exact_bindings_and_unknowns(self) -> None:
        graph = _bound_graph()
        before = graph.to_dict()
        semantic = derive_semantic_view(graph)

        first = semantic.materialize(graph, level="operation", view="faithful")
        second = semantic.materialize(graph, level="operation", view="faithful")

        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(graph.to_dict(), before)
        self.assertEqual(len(first.edges), 2, "parallel source edges must not be evidence-losing aggregates")
        by_source = {edge.attributes["source_edge_id"]: edge for edge in first.edges}

        exact = by_source["exact-edge"]
        exact_source = first.node_map()[exact.source]
        exact_target = first.node_map()[exact.target]
        source_port = next(port for port in exact_source.outputs if port.id == exact.source_port)
        target_port = next(port for port in exact_target.inputs if port.id == exact.target_port)
        self.assertEqual(source_port.tensor, graph.nodes[0].outputs[1].tensor)
        self.assertEqual(target_port.tensor, graph.nodes[1].inputs[1].tensor)
        self.assertEqual(exact.tensor, graph.edges[0].tensor)
        self.assertEqual(exact.label, graph.edges[0].label)
        self.assertEqual(exact.kind, graph.edges[0].kind)
        self.assertEqual(exact.attributes["source_edge_attributes"], graph.edges[0].attributes)
        self.assertEqual(exact.attributes["source_port_binding"]["source_port_id"], "source:out:1")
        self.assertEqual(exact.attributes["target_port_binding"]["source_port_id"], "target:in:1")
        self.assertEqual(exact.attributes["source_port_binding"]["status"], "exact")

        unknown = by_source["unknown-edge"]
        self.assertIsNone(unknown.source_port)
        self.assertIsNone(unknown.target_port)
        self.assertEqual(unknown.attributes["source_port_binding"]["source_port_id"], None)
        self.assertEqual(unknown.attributes["target_port_binding"]["source_port_id"], None)
        self.assertEqual(unknown.attributes["source_port_binding"]["status"], "unknown")
        self.assertEqual(unknown.attributes["target_port_binding"]["status"], "unknown")
        self.assertEqual(unknown.tensor, graph.edges[1].tensor)
        self.assertEqual(first.inputs, graph.inputs)
        self.assertEqual(first.outputs, graph.outputs)
        first.validate()

        model = semantic.materialize(graph, level="model", view="faithful")
        self.assertEqual(len(model.nodes), 1)
        bindings = model.nodes[0].attributes["boundary_port_bindings"]
        graph_input_ids = {
            port_id for port_id, item in bindings.items()
            if item["tensor_source"] == "graph-input"
        }
        graph_output_ids = {
            port_id for port_id, item in bindings.items()
            if item["tensor_source"] == "graph-output"
        }
        self.assertEqual(
            [port.tensor for port in model.nodes[0].inputs if port.id in graph_input_ids],
            graph.inputs,
        )
        self.assertEqual(
            [port.tensor for port in model.nodes[0].outputs if port.id in graph_output_ids],
            graph.outputs,
        )
        self.assertTrue(
            all(bindings[port_id]["status"] == "exact-graph-boundary" for port_id in graph_input_ids | graph_output_ids)
        )

    def test_digest_covers_ports_tensors_edge_bindings_and_nested_schema(self) -> None:
        graph = _bound_graph()
        semantic = derive_semantic_view(graph)

        changed_shape = graph.copy()
        changed_shape.nodes[0].outputs[1].tensor.shape[1] = 9
        with self.assertRaisesRegex(ValidationError, "source digest"):
            semantic.materialize(changed_shape, level="operation")

        changed_binding = graph.copy()
        changed_binding.edges[0].source_port = "source:out:0"
        changed_binding.edges[0].target_port = "target:in:0"
        with self.assertRaisesRegex(ValidationError, "source digest"):
            semantic.materialize(changed_binding, level="operation")

        changed_nested_attribute = graph.copy()
        changed_nested_attribute.edges[0].attributes["quantization"]["bits"] = 4
        with self.assertRaisesRegex(ValidationError, "source digest"):
            semantic.materialize(changed_nested_attribute, level="operation")

    def test_validation_rejects_inconsistent_indexes_and_unknown_source_ids(self) -> None:
        graph = _bound_graph()
        original = derive_semantic_view(graph)

        bad_index = SemanticView.from_dict(original.to_dict())
        source_id = graph.nodes[0].id
        bad_index.source_to_semantic["block"][source_id].append("semantic_missing")
        with self.assertRaises(ValidationError) as context:
            bad_index.validate(graph)
        self.assertTrue(
            any("source-to-semantic" in error for error in context.exception.details["errors"])
        )

        bad_provenance = SemanticView.from_dict(original.to_dict())
        block = bad_provenance.entities_at("block")[0]
        block.provenance.source_node_ids.append("ghost-source-node")
        bad_provenance.semantic_to_source[block.id].source_node_ids.append("ghost-source-node")
        bad_provenance.source_to_semantic["block"]["ghost-source-node"] = [block.id]
        with self.assertRaises(ValidationError) as context:
            bad_provenance.validate(graph)
        self.assertTrue(
            any("unknown source nodes" in error for error in context.exception.details["errors"])
        )

        bad_reverse = SemanticView.from_dict(original.to_dict())
        bad_reverse.semantic_to_source.pop(bad_reverse.entities_at("operation")[0].id)
        with self.assertRaisesRegex(ValidationError, "Semantic View contains"):
            bad_reverse.validate(graph)

    def test_keyword_only_display_names_do_not_create_structural_claims(self) -> None:
        graph = GraphIR(
            "Keyword trap",
            [
                Node(
                    "keyword-node",
                    "Attention Router Expert Encoder Decoder Diffusion Fusion Timestep",
                    "OpaqueCustomOperation",
                    category="operation",
                )
            ],
        ).validate()
        semantic = derive_semantic_view(graph)

        blocks = semantic.entities_at("block")
        stages = semantic.entities_at("stage")
        self.assertEqual(len(blocks), 1)
        self.assertTrue(blocks[0].unknown)
        self.assertEqual(blocks[0].semantic_type, "unknown")
        self.assertEqual(len(stages), 1)
        self.assertTrue(stages[0].unknown)
        positive_types = {
            "attention",
            "moe_router_experts",
            "encoder",
            "decoder",
            "diffusion_loop",
            "diffusion_component",
            "modality_fusion",
            "timestep_conditioning",
        }
        self.assertFalse(positive_types.intersection(item["semantic_type"] for item in semantic.detections))


if __name__ == "__main__":
    unittest.main()
