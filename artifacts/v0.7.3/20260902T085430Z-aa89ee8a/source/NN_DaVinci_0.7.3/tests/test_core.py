from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from nn_davinci.adapters.manual import ManualAdapter
from nn_davinci.analysis import analyze_graph, compare_graphs
from nn_davinci.editor import GraphEditor
from nn_davinci.ir import Annotation, GraphIR, Node, ValidationError
from nn_davinci.layout import LayoutEngine, collapse_graph
from nn_davinci.project import Project
from nn_davinci.render import SvgRenderer, TikzRenderer, export_graph
from nn_davinci.themes import get_theme


ROOT = Path(__file__).parents[1]


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.graph = ManualAdapter().load(ROOT / "examples" / "resnet.json")

    def test_graph_roundtrip_and_validation(self):
        restored = GraphIR.from_dict(self.graph.to_dict())
        self.assertEqual(len(restored.nodes), 10)
        self.assertEqual(len(restored.edges), 10)
        restored.edges[0].source = "missing"
        with self.assertRaises(ValidationError):
            restored.validate()
        invalid = self.graph.copy()
        invalid.annotations.append(Annotation("bad", "text", target_ids=["missing"]))
        with self.assertRaises(ValidationError):
            invalid.validate()
        incompatible = self.graph.copy()
        incompatible.ir_version = "2.0"
        with self.assertRaises(ValidationError):
            incompatible.validate()

    def test_import_options_apply_semantics_dynamic_shapes_and_visibility(self):
        from nn_davinci.api import load_graph
        graph = self.graph.copy()
        graph.inputs[0].shape[0] = "batch"
        graph.inputs[0].dynamic_axes = {0: "batch"}
        hidden_path = graph.nodes[2].path
        result = load_graph(
            graph, dynamic_dimensions={"batch": 8}, input_names=["image"],
            input_semantics={"image": "RGB image"}, hidden_modules=[hidden_path],
            collapsed_modules=[graph.subgraphs[0].name],
        )
        self.assertEqual(result.inputs[0].shape[0], 8)
        self.assertEqual(result.inputs[0].name, "image")
        self.assertEqual(result.inputs[0].semantic, "RGB image")
        self.assertFalse(result.nodes[2].visible)
        self.assertTrue(result.subgraphs[0].collapsed)

    def test_static_analysis(self):
        result = analyze_graph(self.graph)
        summary = result["summary"]
        self.assertEqual(summary["total_parameters"], 148392)
        self.assertGreater(summary["flops"], 1_000_000)
        self.assertGreaterEqual(summary["depth"], 8)
        self.assertTrue(summary["bottlenecks"]["parameters"])
        self.assertIn("receptive_field", result["graph"].nodes[2].analysis)

    def test_layout_is_deterministic_and_routes_residual(self):
        engine = LayoutEngine()
        first = engine.layout(self.graph, algorithm="resnet")
        second = engine.layout(self.graph, algorithm="resnet")
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(len(first.nodes), len(self.graph.nodes))
        self.assertEqual(len(first.edges), len(self.graph.edges))
        self.assertEqual(engine.detect_domain(self.graph), "resnet")

    def test_domain_layout_examples_and_all_directions(self):
        engine = LayoutEngine()
        for name in ("transformer", "unet", "moe", "multimodal", "diffusion"):
            graph = ManualAdapter().load(ROOT / "examples" / f"{name}.json")
            self.assertEqual(engine.detect_domain(graph), name)
            for direction in ("LR", "RL", "TB", "BT"):
                result = engine.layout(graph, algorithm="auto", direction=direction)
                self.assertEqual(result.engine, name)
                self.assertEqual(set(result.nodes), {node.id for node in graph.nodes})
                self.assertEqual(result.direction, direction)

    def test_recurrent_time_unroll(self):
        from nn_davinci.layout import unroll_recurrent_graph
        graph = ManualAdapter().load({
            "name": "LSTM sequence", "layers": [
                {"name": "Tokens", "type": "Input"},
                {"name": "Memory", "type": "LSTM"},
                {"name": "Prediction", "type": "Output"},
            ],
        })
        recurrent_id = graph.nodes[1].id
        view = unroll_recurrent_graph(graph, steps=4)
        copies = [node for node in view.nodes if node.attributes.get("unrolled_from") == recurrent_id]
        self.assertEqual(len(copies), 4)
        self.assertEqual(sum(edge.kind == "recurrent" for edge in view.edges), 3)
        self.assertEqual(LayoutEngine().detect_domain(view), "rnn")

    def test_locked_position_survives_relayout(self):
        node_id = self.graph.nodes[2].id
        self.graph.constraints.append(__import__("nn_davinci.ir", fromlist=["LayoutConstraint"]).LayoutConstraint([node_id], "position", {"x": 777, "y": 123}, True))
        layout = LayoutEngine().layout(self.graph)
        self.assertEqual((layout.nodes[node_id].x, layout.nodes[node_id].y), (777, 123))
        self.assertTrue(layout.nodes[node_id].locked)
        repeated = LayoutEngine().layout(self.graph, previous=layout)
        self.assertEqual((repeated.nodes[node_id].x, repeated.nodes[node_id].y), (777, 123))

    def test_manual_edge_route_survives_relayout(self):
        layout = LayoutEngine().layout(self.graph, algorithm="resnet")
        edge_id = self.graph.edges[0].id
        points = [list(point) for point in layout.edges[edge_id].points]
        points[1][1] += 73
        editor = GraphEditor(self.graph)
        editor.set_edge_route(edge_id, points)
        restored = LayoutEngine().layout(editor.graph, algorithm="resnet")
        self.assertEqual(restored.edges[edge_id].points[1], tuple(points[1]))
        self.assertEqual(restored.edges[edge_id].points[0], layout.edges[edge_id].points[0])

    def test_panel_constraints_create_separate_panel_geometry(self):
        from nn_davinci.ir import LayoutConstraint
        self.graph.constraints.append(LayoutConstraint([self.graph.nodes[0].id, self.graph.nodes[1].id], "panel", "Panel A"))
        self.graph.constraints.append(LayoutConstraint([self.graph.nodes[-2].id, self.graph.nodes[-1].id], "panel", "Panel B"))
        layout = LayoutEngine().layout(self.graph)
        self.assertEqual(set(layout.metadata["panels"]), {"Panel A", "Panel B"})
        self.assertLess(layout.metadata["panels"]["Panel A"]["x"], layout.metadata["panels"]["Panel B"]["x"])

    def test_plugin_registration_points(self):
        from nn_davinci.adapters.onnx import _category
        from nn_davinci.layout import LayoutResult, NodePlacement
        from nn_davinci.operators import OPERATOR_TYPES, register_operator_type
        from nn_davinci.themes import THEMES, register_theme
        name = "unit-test-layout"
        LayoutEngine.register(name, lambda graph, **_: LayoutResult(name, "LR", {node.id: NodePlacement(i * 20, 0, 10, 10) for i, node in enumerate(graph.nodes)}), replace=True)
        try:
            result = LayoutEngine().layout(self.graph, algorithm=name)
            self.assertEqual(result.engine, name)
        finally:
            LayoutEngine.PLUGIN_ENGINES.pop(name, None)
        register_theme("unit-test-theme", {"accent": "#123456"}, replace=True)
        try:
            self.assertEqual(get_theme("unit-test-theme")["accent"], "#123456")
        finally:
            THEMES.pop("unit-test-theme", None)
        register_operator_type("UnitTestAttention", {"category": "attention"}, replace=True)
        try:
            self.assertEqual(_category("UnitTestAttention"), "attention")
        finally:
            OPERATOR_TYPES.pop("unittestattention", None)

    def test_local_plugin_template_discovery_and_load(self):
        from nn_davinci.plugins import PluginManager
        from nn_davinci.themes import THEMES
        manager = PluginManager()
        manifests = manager.discover([ROOT / "examples" / "plugins"])
        self.assertIn("paper-style-example", {item.name for item in manifests})
        try:
            negotiation = manager.negotiate("paper-style-example")
            self.assertTrue(negotiation["accepted"])
            with self.assertRaisesRegex(Exception, "explicit confirmation"):
                manager.load("paper-style-example")
            manager.load("paper-style-example", allow_local_code=True)
            self.assertEqual(THEMES["paper-style-example"]["accent"], "#7c3aed")
            self.assertTrue(next(item for item in manager.describe() if item["name"] == "paper-style-example")["loaded"])
        finally:
            THEMES.pop("paper-style-example", None)

    def test_collapse_preserves_external_edges(self):
        group = self.graph.subgraphs[1]
        external = next(edge for edge in self.graph.edges if (edge.source in group.node_ids) != (edge.target in group.node_ids))
        self.graph.constraints.append(__import__("nn_davinci.ir", fromlist=["LayoutConstraint"]).LayoutConstraint(
            [external.id], "edge-route", {"points": [[0, 0], [50, 80], [100, 0]]}, True,
        ))
        view = collapse_graph(self.graph, {group.id})
        proxy = next(node for node in view.nodes if node.attributes.get("collapsed_group") == group.id)
        self.assertGreater(proxy.parameters, 0)
        self.assertTrue(proxy.inputs)
        self.assertTrue(proxy.outputs)
        self.assertTrue(any(edge.source == proxy.id or edge.target == proxy.id for edge in view.edges))
        route_constraint = next(item for item in view.constraints if item.kind == "edge-route")
        self.assertIn(route_constraint.target_ids[0], view.edge_map())
        self.assertLess(len(view.nodes), len(self.graph.nodes))

    def test_focus_view_is_bounded_and_preserves_boundary_connections(self):
        from nn_davinci.layout import focus_graph
        focus = self.graph.nodes[4].id
        view = focus_graph(self.graph, {focus}, hops=1)
        self.assertIn(focus, view.node_map())
        self.assertLess(len(view.nodes), len(self.graph.nodes))
        self.assertTrue(any("boundary" in node.tags for node in view.nodes))
        self.assertTrue(view.metadata["focus"]["total_nodes"] > len(view.nodes))
        view.validate()

    def test_svg_and_tikz_are_vector_and_stable(self):
        import xml.etree.ElementTree as ET
        graph = analyze_graph(self.graph)["graph"]
        graph.annotations.append(Annotation("note", "text", "Paper note", geometry={"x": 12, "y": 24}))
        layout = LayoutEngine().layout(graph, algorithm="resnet")
        svg = SvgRenderer().render(graph, layout, get_theme("neurips"), title="Residual CNN")
        tikz = TikzRenderer().render(graph, layout, get_theme("ieee"))
        self.assertIn('class="nodes"', svg)
        self.assertIn('id="node-', svg)
        self.assertIn("Paper note", svg)
        self.assertNotIn("<canvas", svg)
        root = ET.fromstring(svg)
        parents = {child: parent for parent in root.iter() for child in parent}
        for element in root.iter("{http://www.w3.org/2000/svg}text"):
            self.assertIn("text-group", parents[element].attrib.get("class", ""))
        custom = get_theme(overrides={
            "parameter_format": "raw", "flops_format": "scientific",
            "shape_separator": ", ", "shape_brackets": True,
            "edge_arrow": "none", "edge_dash": "3 2",
            "node_opacity": 0.75, "font_weight": 700,
        })
        custom_graph = graph.copy()
        custom_graph.nodes[0].attributes.update({"fill": "#123456", "opacity": 0.5})
        custom_svg = SvgRenderer().render(custom_graph, layout, custom, show_legend=False)
        self.assertIn("P 9,408", custom_svg)
        self.assertIn("[1, 64, 112, 112]", custom_svg)
        self.assertIn('fill-opacity="0.75"', custom_svg)
        self.assertIn('font-weight="700"', custom_svg)
        self.assertIn('stroke-dasharray="3 2"', custom_svg)
        self.assertIn('fill="#123456" fill-opacity="0.375"', custom_svg)
        self.assertNotIn('marker-end="url(#arrow)"', custom_svg)
        self.assertIn("\\begin{tikzpicture}", tikz)
        self.assertEqual(tikz, TikzRenderer().render(graph, layout, get_theme("ieee")))

    def test_project_roundtrip(self):
        self.graph.inputs[0].dynamic_axes = {0: "batch"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper.nndv.json"
            Project("paper", self.graph, model_source={"path": "model.onnx"}, theme="ieee").save(path)
            restored = Project.load(path)
            self.assertEqual(restored.graph.to_dict(), self.graph.to_dict())
            self.assertEqual(restored.environment["graph_ir"], "1.0")
            payload = restored.to_dict()
            payload["project_version"] = "2.0"
            with self.assertRaises(ValidationError):
                Project.from_dict(payload)

    def test_project_reproduction_is_stable(self):
        from nn_davinci.api import render_project
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = Project("stable", self.graph, export={"formats": ["svg"], "output": str(root / "stable.svg"), "page": "auto", "options": {}})
            path = root / "stable.nndv.json"
            project.save(path)
            first = render_project(path)[0].read_bytes()
            second = render_project(path)[0].read_bytes()
            self.assertEqual(first, second)

    def test_project_reproduction_respects_collapsed_groups(self):
        from nn_davinci.api import render_project
        graph = self.graph.copy()
        group = graph.subgraphs[0]
        group.collapsed = True
        hidden_name = graph.node_map()[group.node_ids[0]].name
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "collapsed.svg"
            project = Project("collapsed", graph, export={"formats": ["svg"], "output": str(output)})
            render_project(project)
            svg = output.read_text(encoding="utf-8")
            self.assertIn("CollapsedModule", svg)
            self.assertNotIn(f">{hidden_name}</text>", svg)

    def test_literal_python_config_does_not_execute_code(self):
        from nn_davinci.adapters.config import PythonConfigAdapter
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model_config.py"
            marker = Path(directory) / "must-not-exist"
            path.write_text(
                "GRAPH = {'name': 'safe', 'layers': ['Input', 'Output']}\n"
                f"open({str(marker)!r}, 'w').write('executed')\n",
                encoding="utf-8",
            )
            adapter = PythonConfigAdapter()
            self.assertTrue(adapter.accepts(path))
            graph = adapter.load(path)
            self.assertEqual(graph.name, "safe")
            self.assertFalse(marker.exists())

    def test_failures_include_actionable_hints(self):
        from nn_davinci.adapters import registry
        from nn_davinci.errors import AdapterError
        with self.assertRaises(AdapterError) as context:
            registry.get("does-not-exist")
        payload = context.exception.to_dict()
        self.assertIn("Available adapters", payload["hint"])
        with self.assertRaises(AdapterError) as context:
            ManualAdapter().load({"name": "broken"})
        self.assertIn("examples/resnet.json", context.exception.to_dict()["hint"])

    def test_editor_history(self):
        editor = GraphEditor(self.graph)
        original = len(editor.graph.nodes)
        node = Node.create("Extra", "Linear")
        editor.add_node(node)
        self.assertEqual(len(editor.graph.nodes), original + 1)
        editor.undo()
        self.assertEqual(len(editor.graph.nodes), original)
        editor.redo()
        editor.update_node(node.id, name="Changed")
        self.assertEqual(editor.graph.node_map()[node.id].name, "Changed")
        editor.distribute([item.id for item in editor.graph.nodes[:3]], "x")
        self.assertEqual(editor.graph.constraints[-1].kind, "distribute-x")

    def test_editor_duplicate_preserves_internal_ports_and_edges(self):
        editor = GraphEditor(self.graph)
        original = editor.graph.edges[0]
        duplicated = editor.duplicate_nodes([original.source, original.target])
        self.assertEqual(len(duplicated), 2)
        copied = editor.graph.edges[-1]
        self.assertIn(copied.source, duplicated)
        self.assertIn(copied.target, duplicated)
        source = editor.graph.node_map()[copied.source]
        target = editor.graph.node_map()[copied.target]
        if copied.source_port:
            self.assertIn(copied.source_port, {port.id for port in source.outputs})
        if copied.target_port:
            self.assertIn(copied.target_port, {port.id for port in target.inputs})
        editor.graph.validate()

    def test_diff(self):
        after = self.graph.copy()
        after.nodes[1].parameters += 10
        self.graph.nodes[1].analysis.update({"duration_ms": 1.25, "peak_memory_bytes": 2048})
        after.nodes[1].analysis.update({"duration_ms": 2.75, "peak_memory_bytes": 4096})
        after.nodes.pop()
        after.edges = [edge for edge in after.edges if edge.target in after.node_map()]
        diff = compare_graphs(self.graph, after)
        self.assertEqual(len(diff.removed_nodes), 1)
        self.assertEqual(len(diff.changed_nodes), 1)
        self.assertEqual(diff.summary["metrics"]["total_parameters"]["delta"], 10)
        self.assertEqual(diff.summary["metrics"]["duration_ms"]["delta"], 1.5)
        self.assertEqual(diff.summary["metrics"]["peak_memory_bytes"]["delta"], 2048)
        from nn_davinci.analysis import visualize_diff
        visual = visualize_diff(self.graph, after)
        self.assertTrue(any("diff-removed" in node.tags for node in visual.nodes))
        self.assertTrue(any("diff-changed" in node.tags for node in visual.nodes))

    def test_multi_format_export(self):
        layout = LayoutEngine().layout(self.graph)
        with tempfile.TemporaryDirectory() as directory:
            paths = export_graph(self.graph, layout, get_theme(), Path(directory) / "model.svg", formats=["svg", "tikz", "html"])
            self.assertEqual({path.suffix for path in paths}, {".svg", ".tex", ".html"})
            self.assertTrue(all(path.stat().st_size > 100 for path in paths))

    def test_caption_and_report(self):
        from nn_davinci.reporting import generate_caption, generate_markdown_report
        caption = generate_caption(self.graph)
        report = generate_markdown_report(self.graph)
        self.assertIn("Residual CNN", caption)
        self.assertIn("## Bottlenecks", report)

    def test_torchlens_trace_translation_without_dependency(self):
        from types import SimpleNamespace
        from nn_davinci.analysis.torchlens import TorchLensAnalyzer
        first = SimpleNamespace(layer_label="input_1", layer_label_short="input", func_name="input", shape=[1, 4], dtype="float32", is_input=True, is_output=False, parents=[], num_params=0, num_params_trainable=0, num_passes=1, modules=[])
        second = SimpleNamespace(layer_label="linear_1", layer_label_short="linear", func_name="linear", shape=[1, 2], dtype="float32", is_input=False, is_output=True, parents=["input_1"], num_params=10, num_params_trainable=10, num_passes=1, modules=[])
        trace = SimpleNamespace(layer_list=[first, second], model_class_qualname="Tiny", forward_duration=.002)
        graph = TorchLensAnalyzer().from_trace(trace)
        self.assertEqual(len(graph.nodes), 2)
        self.assertEqual(len(graph.edges), 1)
        self.assertEqual(graph.metadata["forward_duration_ms"], 2.0)


if __name__ == "__main__":
    unittest.main()
