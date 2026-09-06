from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from nn_davinci.errors import ValidationError
from nn_davinci.ir import Edge, GraphIR, Node, Port, TensorSpec
from nn_davinci.model_figure import model_figure_from_graph
from nn_davinci.model_scene import (
    ARCHITECTURE_FAMILIES,
    model_scene_from_graph,
    scene_template,
    validate_model_scene_provenance,
)
from nn_davinci.project import PROJECT_VERSION, Project
from nn_davinci.scene_ir import Scene
from nn_davinci.semantic import derive_semantic_view


ROOT = Path(__file__).resolve().parents[1]


def architecture_graph(family: str) -> GraphIR:
    tensor = TensorSpec("features", ["B", None, 32], "float32")
    source = Node(
        "source",
        "Input",
        "Input",
        category="input",
        outputs=[Port("source:out", "features", "output", tensor)],
        attributes={"scene_role": "tensor-volume", "architecture_stage": "input"},
    )
    role = {
        "cnn": "convolution-window",
        "resnet": "operation-block",
        "unet": "downsample",
        "transformer": "attention-head",
        "moe": "router",
        "multimodal-fusion": "modality",
        "diffusion-unet": "time",
    }[family]
    middle = Node(
        "middle",
        "Evidence-backed middle",
        "OpaqueOperation",
        inputs=[Port("middle:in", "features", "input", tensor)],
        outputs=[Port("middle:out", "features", "output", tensor)],
        attributes={
            "scene_role": role,
            "architecture_stage": "encoder" if family in {"unet", "diffusion-unet"} else "body",
            "modality": "image" if family == "multimodal-fusion" else "",
            "head_index": 0,
            "expert_index": 0,
        },
    )
    output = Node(
        "output",
        "Output",
        "Output",
        category="output",
        inputs=[Port("output:in", "features", "input", tensor)],
        attributes={"scene_role": "merge", "architecture_stage": "output"},
    )
    special_route = {
        "cnn": "arrow",
        "resnet": "residual-skip",
        "unet": "unet-skip",
        "transformer": "attention-ribbon",
        "moe": "expert-branch",
        "multimodal-fusion": "multimodal-stream",
        "diffusion-unet": "polyline",
    }[family]
    first = Edge(
        "source-middle",
        source.id,
        middle.id,
        "source:out",
        "middle:in",
        tensor,
        attributes={"scene_role": special_route},
    )
    second = Edge(
        "middle-output",
        middle.id,
        output.id,
        "middle:out",
        "output:in",
        tensor,
    )
    return GraphIR(
        f"Evidence fixture {family}",
        [source, middle, output],
        [first, second],
        metadata={
            "architecture_evidence": {
                "family": family,
                "graph_ir_ids": [middle.id, first.id],
                "reason": "Fixture supplies a structured architecture record tied to exact Graph IR IDs.",
            }
        },
    ).validate()


def linear_graph(count: int) -> GraphIR:
    nodes = [Node(f"n{index}", f"Operation {index}", "Opaque") for index in range(count)]
    edges = [Edge(f"e{index}", nodes[index].id, nodes[index + 1].id) for index in range(count - 1)]
    return GraphIR("Large bounded scene", nodes, edges).validate()


class ModelScene070Tests(unittest.TestCase):
    def test_seven_templates_are_editable_true_3d_and_template_provenance_only(self) -> None:
        required_kind = {
            "cnn": "convolution-window",
            "resnet": "residual-skip",
            "unet": "unet-skip",
            "transformer": "attention-head",
            "moe": "moe-router",
            "multimodal-fusion": "fusion",
            "diffusion-unet": "timestep-conditioning",
        }
        for family in ARCHITECTURE_FAMILIES:
            with self.subTest(family=family):
                first, second = scene_template(family), scene_template(family)
                objects = list(first.iter_objects())
                self.assertTrue(objects)
                self.assertIn(required_kind[family], {item.kind for item in objects})
                self.assertIn("group-frame", {item.kind for item in objects})
                self.assertIn("legend", {item.kind for item in objects})
                self.assertTrue(all(item.provenance.kind == "template" for item in objects))
                self.assertTrue(all(not item.provenance.graph_ir_ids for item in objects))
                self.assertEqual(first.digest(), second.digest())
                self.assertTrue(any(float(item.geometry.get("size", [0, 0, 0])[2]) > 0.0 for item in objects if "size" in item.geometry))
                self.assertTrue(all(len(item.world.matrix) == 4 for item in objects))
                legend = next(item for item in objects if item.kind == "legend")
                self.assertFalse(legend.metadata["visual_geometry_is_literal_tensor_size"])
                self.assertTrue(first.metadata["template_provenance_only"])
                self.assertFalse(first.metadata["contains_model_evidence"])

    def test_seven_evidence_backed_model_families_generate_bounded_editable_scenes(self) -> None:
        required_route = {
            "cnn": "arrow",
            "resnet": "residual-skip",
            "unet": "unet-skip",
            "transformer": "attention-ribbon",
            "moe": "expert-branch",
            "multimodal-fusion": "multimodal-stream",
            "diffusion-unet": "polyline",
        }
        for family in ARCHITECTURE_FAMILIES:
            with self.subTest(family=family):
                graph = architecture_graph(family)
                scene = model_scene_from_graph(graph, architecture=family)
                objects = list(scene.iter_objects())
                self.assertEqual(family, scene.metadata["evidenced_architecture_family"])
                self.assertFalse(scene.metadata["architecture_name_inference_used"])
                self.assertIn(required_route[family], {item.kind for item in objects})
                self.assertTrue(all(item.provenance.kind == "graph_ir" for item in objects))
                self.assertTrue(validate_model_scene_provenance(scene, graph)["passed"])

    def test_names_do_not_infer_residual_attention_moe_or_diffusion_semantics(self) -> None:
        graph = GraphIR(
            "ResNet Attention MoE Diffusion by name only",
            [
                Node("a", "Residual Router Attention", "DiffusionLoop"),
                Node("b", "Expert Skip", "MultiHeadAttention"),
            ],
            [Edge("edge", "a", "b")],
        ).validate()
        scene = model_scene_from_graph(graph)
        self.assertEqual("unknown", scene.metadata["evidenced_architecture_family"])
        self.assertEqual("cnn", scene.metadata["layout_family"])
        node_objects = [item for item in scene.iter_objects() if item.metadata.get("graph_ir_node_ids")]
        self.assertEqual({"operation-block"}, {item.kind for item in node_objects})
        self.assertTrue(all(item.metadata["architecture_role"] == "unknown" for item in node_objects))
        self.assertNotIn("residual-skip", {item.kind for item in scene.iter_objects()})
        self.assertNotIn("attention-ribbon", {item.kind for item in scene.iter_objects()})

        requested = model_scene_from_graph(graph, architecture="resnet")
        self.assertEqual("unknown", requested.metadata["evidenced_architecture_family"])
        self.assertEqual("resnet", requested.metadata["requested_layout_family"])
        self.assertNotIn("residual-skip", {item.kind for item in requested.iter_objects()})

    def test_symbolic_dynamic_and_unknown_shapes_remain_symbolic(self) -> None:
        graph = architecture_graph("cnn")
        scene = model_scene_from_graph(graph)
        source = next(
            item for item in scene.iter_objects()
            if item.metadata.get("graph_ir_node_ids") == ["source"]
        )
        self.assertEqual(["B", None, 32], source.metadata["tensor_shape"])
        self.assertEqual("[B, ?, 32]", source.metadata["shape_label"])
        self.assertTrue(source.metadata["unknown_dimensions_preserved"])
        self.assertFalse(source.metadata["visual_geometry_is_literal_tensor_size"])

        unknown_graph = GraphIR("Unknown shape", [Node("unknown", "Unknown", "Opaque")], []).validate()
        unknown_scene = model_scene_from_graph(unknown_graph)
        unknown = next(unknown_scene.iter_objects())
        self.assertEqual([None], unknown.metadata["tensor_shape"])
        self.assertEqual("[?]", unknown.metadata["shape_label"])

    def test_large_graph_is_summary_first_and_focus_is_bounded(self) -> None:
        graph = linear_graph(120)
        summary = model_scene_from_graph(graph, maximum_objects=20)
        self.assertTrue(summary.metadata["model_scene_pipeline"]["summary_first"])
        self.assertLessEqual(len(list(summary.iter_objects())), 20)
        self.assertEqual(120, summary.metadata["model_scene_pipeline"]["source_node_count"])
        summary_objects = [item for item in summary.iter_objects() if item.metadata.get("summary")]
        self.assertTrue(summary_objects)
        self.assertEqual(
            set(node.id for node in graph.nodes),
            {
                node_id
                for item in summary_objects
                for node_id in item.metadata["graph_ir_node_ids"]
            },
        )

        focused = model_scene_from_graph(graph, focus_ids=["n60"], focus_hops=1, maximum_objects=20)
        pipeline = focused.metadata["model_scene_pipeline"]
        self.assertFalse(pipeline["summary_first"])
        self.assertEqual(["n60"], pipeline["focus_ids"])
        focused_node_ids = {
            node_id
            for item in focused.iter_objects()
            for node_id in item.metadata.get("graph_ir_node_ids", [])
        }
        self.assertEqual({"n59", "n60", "n61"}, focused_node_ids)
        self.assertLessEqual(len(list(focused.iter_objects())), 20)

    def test_graph_semantic_figure_scene_bidirectional_provenance_and_tamper_rejection(self) -> None:
        graph = architecture_graph("transformer")
        semantic = derive_semantic_view(graph)
        figure = model_figure_from_graph(graph, semantic_view=semantic, mode="mixed")
        scene = model_scene_from_graph(
            graph,
            semantic_view=semantic,
            figure_ir=figure,
            architecture="transformer",
        )
        report = validate_model_scene_provenance(scene, graph, semantic, figure)
        self.assertTrue(report["passed"], report)
        claimed = [item for item in scene.iter_objects() if item.provenance.kind == "semantic_view"]
        self.assertTrue(claimed)
        self.assertTrue(any(item.provenance.figure_ir_ids for item in claimed))
        index = scene.metadata["provenance_index"]
        self.assertTrue(index["graph_to_scene"])
        self.assertTrue(index["semantic_to_scene"])
        self.assertTrue(index["figure_to_scene"])
        self.assertEqual({item.id for item in claimed}, set(index["scene_to_source"]))

        tampered = Scene.from_dict(scene.to_dict())
        item = next(tampered.iter_objects())
        item.provenance.graph_ir_ids[0] = "orphan-graph-id"
        tampered_report = validate_model_scene_provenance(tampered, graph, semantic, figure)
        self.assertFalse(tampered_report["passed"])
        self.assertTrue(any("missing_graph_ir_ids" in failure for failure in tampered_report["failures"]))

        with self.assertRaisesRegex(ValidationError, "persisted Semantic View"):
            Project("Missing semantic", graph, figure_ir=figure.to_dict(), scene_ir=scene.to_dict())

        project = Project(
            "Complete provenance",
            graph,
            semantic_view={
                "version": "1.0",
                "level": "operation",
                "view": "faithful",
                "document": semantic.to_dict(),
            },
            figure_ir=figure.to_dict(),
            scene_ir=scene.to_dict(),
        )
        self.assertEqual(scene.digest(), project.persisted_scene().digest())

    def test_project_13_migration_adds_only_an_explicit_empty_scene(self) -> None:
        graph = architecture_graph("cnn")
        original = Project("Legacy project", graph).to_dict()
        original["project_version"] = "1.3"
        original.pop("scene_ir")

        migrated = Project.from_dict(original)
        scene = migrated.persisted_scene()
        self.assertEqual("1.4", PROJECT_VERSION)
        self.assertEqual(PROJECT_VERSION, migrated.project_version)
        self.assertEqual([], list(scene.iter_objects()))
        self.assertEqual([], scene.layers)
        self.assertTrue(scene.metadata["empty"])
        self.assertFalse(scene.metadata["model_geometry_inferred"])
        self.assertFalse(scene.metadata["model_semantics_inferred"])
        self.assertFalse(scene.metadata["provenance_inferred"])
        self.assertIn("no 3D geometry", scene.migrations[0]["reason"])
        self.assertIn("empty Scene IR", migrated.environment["project_schema_migrations"][-1]["reason"])

        with tempfile.TemporaryDirectory(prefix="nndv-scene-project-") as directory:
            target = Path(directory) / "migrated.nndv.json"
            migrated.save(target)
            restored = Project.load(target)
            self.assertEqual(scene.digest(), restored.persisted_scene().digest())

    def test_materialized_template_files_match_factories_and_packaged_copies(self) -> None:
        for family in ARCHITECTURE_FAMILIES:
            with self.subTest(family=family):
                public_path = ROOT / "templates" / "scene_studio" / f"{family}.scene.json"
                packaged_path = ROOT / "src" / "nn_davinci" / "scene_templates" / f"{family}.scene.json"
                self.assertTrue(public_path.is_file())
                self.assertTrue(packaged_path.is_file())
                public = Scene.from_dict(json.loads(public_path.read_text(encoding="utf-8")))
                packaged = Scene.from_dict(json.loads(packaged_path.read_text(encoding="utf-8")))
                self.assertEqual(scene_template(family).digest(), public.digest())
                self.assertEqual(public.digest(), packaged.digest())

    def test_schema_documents_are_strict_versioned_json(self) -> None:
        scene_schema = json.loads((ROOT / "schemas" / "scene-ir-1.0.schema.json").read_text(encoding="utf-8"))
        project_schema = json.loads((ROOT / "schemas" / "project-1.4.schema.json").read_text(encoding="utf-8"))
        self.assertEqual("1.0", scene_schema["properties"]["schema_version"]["const"])
        self.assertFalse(scene_schema["additionalProperties"])
        self.assertEqual("1.4", project_schema["properties"]["project_version"]["const"])
        self.assertIn("scene_ir", project_schema["required"])
        self.assertEqual("scene-ir-1.0.schema.json", project_schema["properties"]["scene_ir"]["$ref"])


if __name__ == "__main__":
    unittest.main()
