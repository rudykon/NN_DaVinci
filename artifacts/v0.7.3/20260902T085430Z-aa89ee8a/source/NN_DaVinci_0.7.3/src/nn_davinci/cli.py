from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .adapters import registry
from .analysis import analyze_graph, compare_graphs
from .api import capture_runtime, explain_model, load_graph, render, scene_from_graph
from .errors import NNDaVinciError, ValidationError
from .model_scene import ARCHITECTURE_FAMILIES, model_scene_from_graph, scene_template
from .project import Project
from .scene_export import export_scene
from .scene_ir import Scene
from .themes import PAGE_PRESETS
from .semantic import SEMANTIC_LEVELS, VIEW_MODES, derive_semantic_view


def _dimensions(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(item.strip()) for item in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("dimensions must be comma-separated integers, e.g. 1,3,224,224") from exc


def _sample(shape: tuple[int, ...] | None) -> Any:
    if not shape:
        return None
    try:
        import torch
    except ImportError:
        return None
    return torch.zeros(shape)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="nnviz", description="NN_DaVinci neural-network visualizer")
    from . import __version__
    root.add_argument("--version", action="version", version=f"NN_DaVinci {__version__}")
    root.add_argument("--plugin-path", action="append", default=[], help="discover local plugin manifests below this directory")
    root.add_argument("--plugin", action="append", default=[], help="explicitly load a discovered plugin")
    commands = root.add_subparsers(dest="command", required=True)
    render_cmd = commands.add_parser("render", help="import, analyze, layout, and export a model")
    render_cmd.add_argument("model")
    render_cmd.add_argument("-o", "--output", default="network.svg")
    render_cmd.add_argument("--adapter", help="adapter name, including a loaded plugin adapter")
    render_cmd.add_argument("--input", type=_dimensions, dest="input_shape")
    render_cmd.add_argument("--preset", default="neurips", help="theme name, including a loaded plugin theme")
    render_cmd.add_argument("--page", default="auto", choices=sorted(PAGE_PRESETS))
    render_cmd.add_argument("--layout", default="auto")
    render_cmd.add_argument("--direction", default="LR", choices=("LR", "RL", "TB", "BT"))
    render_cmd.add_argument("--time-steps", type=int, default=1, help="unroll RNN/LSTM/GRU nodes across time")
    render_cmd.add_argument("--format", default="svg", help="comma-separated: svg,pdf,tikz,png,eps,pptx,html")
    render_cmd.add_argument("--label-density", default="paper", choices=("compact", "paper", "detailed"))
    render_cmd.add_argument("--level", choices=SEMANTIC_LEVELS, help="derive and render model/stage/block/layer/operation semantics")
    render_cmd.add_argument("--view", default="faithful", choices=VIEW_MODES, help="faithful structure or conceptual paper aggregation")
    render_cmd.add_argument("--focus", action="append", default=[], metavar="NODE_ID", help="render a bounded neighborhood around this node (repeatable)")
    render_cmd.add_argument("--focus-hops", type=int, default=1, metavar="N", help="focus-neighborhood hop count")
    render_cmd.add_argument("--summary", action="store_true", help="print a structural summary without layout or SVG construction")
    render_cmd.add_argument("--transparent", action="store_true")
    render_cmd.add_argument("--allow-pickle", action="store_true")
    render_cmd.add_argument("--allow-code", action="store_true", help="allow execution of a trusted model.py:factory")
    render_cmd.add_argument("--no-analysis", action="store_true")
    render_cmd.add_argument("--no-shapes", action="store_true")
    render_cmd.add_argument("--no-parameters", action="store_true")
    render_cmd.add_argument("--no-flops", action="store_true")

    analyze_cmd = commands.add_parser("analyze", help="print static graph analysis as JSON")
    analyze_cmd.add_argument("model")
    analyze_cmd.add_argument("--adapter")
    analyze_cmd.add_argument("--input", type=_dimensions, dest="input_shape")
    analyze_cmd.add_argument("--allow-code", action="store_true")
    analyze_cmd.add_argument("--allow-pickle", action="store_true")
    analyze_cmd.add_argument("--level", choices=SEMANTIC_LEVELS)
    analyze_cmd.add_argument("--view", default="faithful", choices=VIEW_MODES)
    analyze_cmd.add_argument("-o", "--output")

    runtime_cmd = commands.add_parser("runtime", help="capture actual PyTorch execution, tensors, timings, and gradients")
    runtime_cmd.add_argument("model", help="trusted model.py:factory or PyTorch model file")
    runtime_cmd.add_argument("--input", type=_dimensions, dest="input_shape", required=True)
    runtime_cmd.add_argument("--operations", action="store_true", help="use TorchLens operation-level capture")
    runtime_cmd.add_argument("--gradients", action="store_true")
    runtime_cmd.add_argument("--save-activations", action="store_true")
    runtime_cmd.add_argument("--allow-code", action="store_true")
    runtime_cmd.add_argument("--allow-pickle", action="store_true")
    runtime_cmd.add_argument("-o", "--output")

    explain_cmd = commands.add_parser("explain", help="generate CAM or input-gradient heatmaps")
    explain_cmd.add_argument("model", help="trusted model.py:factory or PyTorch model file")
    explain_cmd.add_argument("--input", type=_dimensions, dest="input_shape", required=True)
    explain_cmd.add_argument("--method", default="grad-cam")
    explain_cmd.add_argument("--target-layer")
    explain_cmd.add_argument("--target-class", type=int)
    explain_cmd.add_argument("--input-image")
    explain_cmd.add_argument("--allow-code", action="store_true")
    explain_cmd.add_argument("--allow-pickle", action="store_true")
    explain_cmd.add_argument("-o", "--output", required=True, help="heatmap PNG path prefix")

    compare_cmd = commands.add_parser("compare", help="compare two models or projects")
    compare_cmd.add_argument("before")
    compare_cmd.add_argument("after")
    compare_cmd.add_argument("-o", "--output")
    compare_cmd.add_argument("--diagram", help="also render a color-coded diff diagram")

    project_cmd = commands.add_parser("project", help="create a reproducible .nndv.json project")
    project_cmd.add_argument("model")
    project_cmd.add_argument("-o", "--output", required=True)
    project_cmd.add_argument("--adapter")
    project_cmd.add_argument("--input", type=_dimensions, dest="input_shape")
    project_cmd.add_argument("--allow-code", action="store_true")
    project_cmd.add_argument("--allow-pickle", action="store_true")
    project_cmd.add_argument("--preset", default="neurips", help="theme name, including a loaded plugin theme")
    project_cmd.add_argument("--level", choices=SEMANTIC_LEVELS)
    project_cmd.add_argument("--view", default="faithful", choices=VIEW_MODES)
    project_cmd.add_argument("--workspace", default="graph", choices=("graph", "scene"))
    project_cmd.add_argument("--architecture", choices=ARCHITECTURE_FAMILIES)

    scene_cmd = commands.add_parser("scene", help="create and export an editable Scene IR 1.0 document")
    scene_cmd.add_argument("model", nargs="?", help="model/Graph source; omit when --template is used")
    scene_cmd.add_argument("-o", "--output", required=True)
    scene_cmd.add_argument("--template", choices=ARCHITECTURE_FAMILIES)
    scene_cmd.add_argument("--adapter")
    scene_cmd.add_argument("--input", type=_dimensions, dest="input_shape")
    scene_cmd.add_argument("--allow-code", action="store_true")
    scene_cmd.add_argument("--allow-pickle", action="store_true")
    scene_cmd.add_argument("--architecture", choices=ARCHITECTURE_FAMILIES)
    scene_cmd.add_argument("--projection", default="orthographic", choices=("orthographic", "perspective"))
    scene_cmd.add_argument("--format", default="svg", help="comma-separated: svg,pdf,tikz,png,eps,pptx,html,json,gltf,glb")
    scene_cmd.add_argument("--level", default="operation", choices=SEMANTIC_LEVELS)
    scene_cmd.add_argument("--view", default="faithful", choices=VIEW_MODES)
    scene_cmd.add_argument("--focus", action="append", default=[], metavar="SOURCE_ID")
    scene_cmd.add_argument("--focus-hops", type=int, default=1)
    scene_cmd.add_argument("--maximum-objects", type=int, default=250)
    scene_cmd.add_argument("--camera-id")

    reproduce_cmd = commands.add_parser("reproduce", help="regenerate outputs from a saved project")
    reproduce_cmd.add_argument("project")
    reproduce_cmd.add_argument("-o", "--output")
    reproduce_cmd.add_argument("--update-project", action="store_true")

    validate_cmd = commands.add_parser("validate", help="validate Graph IR or a project")
    validate_cmd.add_argument("file")
    commands.add_parser("plugins", help="list adapter/plugin capabilities")

    batch_cmd = commands.add_parser("batch", help="render every job in a JSON manifest")
    batch_cmd.add_argument("manifest")
    batch_cmd.add_argument("--workers", type=int, default=1)
    batch_cmd.add_argument("-o", "--output", help="write the batch result report")

    report_cmd = commands.add_parser("report", help="generate a Markdown model summary and caption")
    report_cmd.add_argument("model")
    report_cmd.add_argument("--adapter")
    report_cmd.add_argument("--input", type=_dimensions, dest="input_shape")
    report_cmd.add_argument("--allow-code", action="store_true")
    report_cmd.add_argument("--allow-pickle", action="store_true")
    report_cmd.add_argument("-o", "--output")

    serve_cmd = commands.add_parser("serve", help="start the local Web editor")
    serve_cmd.add_argument("model", nargs="?")
    serve_cmd.add_argument("--host", default="127.0.0.1")
    serve_cmd.add_argument("--port", type=int, default=8765)
    serve_cmd.add_argument("--no-browser", action="store_true")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        from .plugins import manager
        manager.discover(args.plugin_path)
        for plugin_name in args.plugin:
            manager.load(plugin_name)
        if args.command == "render":
            if args.summary:
                from .scaling import summarize_graph_structure
                graph = load_graph(
                    args.model, adapter=args.adapter, sample_input=_sample(args.input_shape),
                    allow_code=args.allow_code, allow_pickle=args.allow_pickle,
                )
                print(json.dumps(summarize_graph_structure(graph), ensure_ascii=False, indent=2))
                return 0
            outputs = render(
                args.model, args.output, adapter=args.adapter, sample_input=_sample(args.input_shape),
                theme=args.preset, page=args.page, layout=args.layout, direction=args.direction,
                time_steps=max(1, args.time_steps),
                formats=args.format.split(","), transparent=args.transparent, allow_pickle=args.allow_pickle,
                allow_code=args.allow_code,
                analyze=not args.no_analysis, show_shapes=not args.no_shapes,
                show_parameters=not args.no_parameters, show_flops=not args.no_flops,
                label_density=args.label_density,
                level=args.level, view=args.view,
                focus=args.focus, focus_hops=max(0, args.focus_hops), recovery_source=args.model,
            )
            print("\n".join(str(item) for item in outputs))
        elif args.command == "analyze":
            analyzed_graph = load_graph(
                args.model, adapter=args.adapter, sample_input=_sample(args.input_shape),
                allow_code=args.allow_code, allow_pickle=args.allow_pickle,
            )
            if args.level:
                semantic = derive_semantic_view(analyzed_graph)
                analyzed_graph = semantic.materialize(analyzed_graph, level=args.level, view=args.view)
            result = analyze_graph(analyzed_graph)
            text = json.dumps(result["summary"], ensure_ascii=False, indent=2)
            if args.output:
                Path(args.output).write_text(text + "\n", encoding="utf-8")
            else:
                print(text)
        elif args.command == "runtime":
            result = capture_runtime(
                args.model, _sample(args.input_shape), operation_level=args.operations,
                capture_gradients=args.gradients, save_activations=args.save_activations,
                allow_code=args.allow_code, allow_pickle=args.allow_pickle,
            )
            payload = {"summary": result["summary"], "graph": result["graph"].to_dict()}
            if "records" in result:
                payload["records"] = result["records"]
            text = json.dumps(payload, ensure_ascii=False, indent=2)
            if args.output:
                Path(args.output).write_text(text + "\n", encoding="utf-8")
            else:
                print(text)
        elif args.command == "explain":
            result = explain_model(
                args.model, _sample(args.input_shape), method=args.method,
                target_layer=args.target_layer, target_class=args.target_class,
                output=args.output, input_image=args.input_image,
                allow_code=args.allow_code, allow_pickle=args.allow_pickle,
            )
            explanation = result["result"]
            print(json.dumps({
                "method": explanation.method, "target_layer": explanation.target_layer,
                "target_class": explanation.target_class, "metadata": explanation.metadata,
                "artifacts": [str(path) for path in result["artifacts"]],
            }, ensure_ascii=False, indent=2))
        elif args.command == "compare":
            before, after = load_graph(args.before), load_graph(args.after)
            diff = compare_graphs(before, after).to_dict()
            text = json.dumps(diff, ensure_ascii=False, indent=2)
            if args.output:
                Path(args.output).write_text(text + "\n", encoding="utf-8")
            else:
                print(text)
            if args.diagram:
                from .analysis import visualize_diff
                render(visualize_diff(before, after), args.diagram, theme="colorblind")
        elif args.command == "project":
            graph = analyze_graph(load_graph(
                args.model, adapter=args.adapter, sample_input=_sample(args.input_shape),
                allow_code=args.allow_code, allow_pickle=args.allow_pickle,
            ))["graph"]
            sample_inputs = [{"shape": list(args.input_shape)}] if args.input_shape else []
            scene = None
            export_settings: dict[str, Any] = {"formats": ["svg"], "transparent": False}
            semantic_settings: dict[str, Any] = {
                "version": "1.0",
                "level": args.level,
                "view": args.view,
            }
            if args.workspace == "scene":
                semantic = derive_semantic_view(graph)
                semantic_level = args.level or "operation"
                scene = model_scene_from_graph(
                    graph,
                    semantic_view=semantic,
                    architecture=args.architecture,
                    level=semantic_level,
                    view=args.view,
                )
                semantic_settings.update({
                    "level": semantic_level,
                    "document": semantic.to_dict(),
                })
                export_settings = {"workspace": "scene", "formats": ["svg"], "transparent": False}
            Project(
                graph.name, graph, model_source={"path": args.model, "adapter": args.adapter},
                sample_inputs=sample_inputs, theme=args.preset,
                semantic_view=semantic_settings,
                scene_ir=scene.to_dict() if scene else {},
                export=export_settings,
            ).save(args.output)
            print(args.output)
        elif args.command == "scene":
            if args.template:
                if args.model:
                    raise ValidationError("Scene accepts either a model source or --template, not both")
                scene = scene_template(args.template)
                scene.cameras[0].projection = args.projection
                scene.validate()
            else:
                if not args.model:
                    raise ValidationError("Scene requires a model source or --template")
                scene = scene_from_graph(
                    args.model,
                    adapter=args.adapter,
                    sample_input=_sample(args.input_shape),
                    allow_code=args.allow_code,
                    allow_pickle=args.allow_pickle,
                    architecture=args.architecture,
                    level=args.level,
                    view=args.view,
                    focus=args.focus,
                    focus_hops=max(0, args.focus_hops),
                    maximum_objects=args.maximum_objects,
                    projection=args.projection,
                )
            paths = export_scene(
                scene,
                args.output,
                formats=[item.strip() for item in args.format.split(",") if item.strip()],
                camera_id=args.camera_id,
            )
            print("\n".join(str(path) for path in paths))
        elif args.command == "reproduce":
            from .api import render_project
            print("\n".join(str(path) for path in render_project(args.project, args.output, save_project=args.update_project)))
        elif args.command == "validate":
            path = Path(args.file)
            if path.suffix.lower() == ".json":
                document = json.loads(path.read_text(encoding="utf-8"))
            else:
                document = None
            if isinstance(document, dict) and document.get("project_version"):
                project = Project.from_dict(document)
                print(
                    f"valid Project {project.project_version}: Graph IR {project.graph.ir_version}, "
                    f"Scene IR {project.persisted_scene().schema_version}"
                )
            elif isinstance(document, dict) and document.get("schema_version") and "cameras" in document and "layers" in document:
                scene = Scene.from_dict(document)
                print(
                    f"valid Scene IR {scene.schema_version}: "
                    f"{sum(1 for _ in scene.iter_objects())} objects, {len(scene.layers)} layers"
                )
            else:
                graph = load_graph(args.file)
                graph.validate()
                print(f"valid Graph IR {graph.ir_version}: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
        elif args.command == "plugins":
            print(json.dumps({"adapters": registry.describe(), "plugins": manager.describe()}, ensure_ascii=False, indent=2))
        elif args.command == "batch":
            from .batch import batch_render
            result = batch_render(args.manifest, workers=max(1, args.workers))
            text = json.dumps(result, ensure_ascii=False, indent=2)
            if args.output:
                Path(args.output).write_text(text + "\n", encoding="utf-8")
            else:
                print(text)
            return 1 if result["failed"] else 0
        elif args.command == "report":
            from .reporting import generate_markdown_report
            text = generate_markdown_report(load_graph(
                args.model, adapter=args.adapter, sample_input=_sample(args.input_shape),
                allow_code=args.allow_code, allow_pickle=args.allow_pickle,
            ))
            if args.output:
                Path(args.output).write_text(text, encoding="utf-8")
            else:
                print(text, end="")
        elif args.command == "serve":
            from .server import serve
            serve(args.model, host=args.host, port=args.port, open_browser=not args.no_browser)
        return 0
    except NNDaVinciError as exc:
        print(json.dumps(exc.to_dict(), ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
