from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Iterable

from .adapters import registry
from .analysis import ExplainabilityAnalyzer, RuntimeAnalyzer, TorchLensAnalyzer, analyze_graph
from .ir import GraphIR
from .layout import LayoutEngine, aggregate_repeated_blocks, collapse_graph, focus_graph, unroll_recurrent_graph
from .project import Project
from .render import export_graph
from .scaling import enforce_focus_bound, preflight_graph
from .scene_export import export_scene
from .scene_ir import Scene
from .semantic import SemanticView, derive_semantic_view
from .themes import get_theme


def load_graph(source: Any, *, adapter: str | None = None, **options: Any) -> GraphIR:
    if isinstance(source, GraphIR):
        graph = source.validate()
    elif isinstance(source, Project):
        graph = source.graph.validate()
    elif isinstance(source, (str, Path)) and str(source).lower().endswith((".nndv", ".nndv.json", ".nndv.yaml", ".nndv.yml")):
        graph = Project.load(source).graph
    else:
        graph = registry.load(source, adapter=adapter, **options)
    return _apply_import_options(graph, options)


def _apply_import_options(graph: GraphIR, options: dict[str, Any]) -> GraphIR:
    dynamic = options.get("dynamic_dimensions") or {}
    all_specs = [*graph.inputs, *graph.outputs]
    for node in graph.nodes:
        all_specs.extend(port.tensor for port in [*node.inputs, *node.outputs] if port.tensor)
    for spec in all_specs:
        for axis, value in enumerate(spec.shape):
            label = spec.dynamic_axes.get(axis) or (value if isinstance(value, str) else None)
            if label in dynamic:
                spec.shape[axis] = int(dynamic[label])

    input_names = options.get("input_names") or []
    semantics = options.get("input_semantics") or {}
    input_specs = graph.inputs or [
        port.tensor for node in graph.nodes if node.category == "input" for port in node.outputs if port.tensor
    ]
    for index, spec in enumerate(input_specs):
        if index < len(input_names):
            spec.name = str(input_names[index])
        if isinstance(semantics, dict):
            spec.semantic = semantics.get(spec.name, semantics.get(str(index), spec.semantic))
        elif index < len(semantics):
            spec.semantic = str(semantics[index])

    hidden = _patterns(options.get("hidden_modules"))
    expanded = _patterns(options.get("expanded_modules"))
    collapsed = _patterns(options.get("collapsed_modules"))
    for node in graph.nodes:
        if _matches(node.path or node.name, hidden) or _matches(node.name, hidden):
            node.visible = False
    for group in graph.subgraphs:
        identity = group.attributes.get("path", group.name)
        if _matches(identity, hidden) or _matches(group.name, hidden):
            for node_id in group.node_ids:
                if node_id in graph.node_map():
                    graph.node_map()[node_id].visible = False
        if _matches(identity, expanded) or _matches(group.name, expanded):
            group.collapsed = False
        if _matches(identity, collapsed) or _matches(group.name, collapsed):
            group.collapsed = True
    return graph.validate()


def _patterns(value: Any) -> list[str]:
    if not value:
        return []
    return [value] if isinstance(value, str) else [str(item) for item in value]


def _matches(value: str, patterns: list[str]) -> bool:
    return any(value == pattern or fnmatch(value, pattern) for pattern in patterns)


def render(
    source: Any,
    output: str | Path,
    *,
    adapter: str | None = None,
    sample_input: Any = None,
    theme: str = "neurips",
    theme_overrides: dict[str, Any] | None = None,
    page: str = "auto",
    layout: str = "auto",
    direction: str = "LR",
    formats: Iterable[str] | None = None,
    collapsed: Iterable[str] = (),
    focus: Iterable[str] = (),
    focus_hops: int = 1,
    time_steps: int = 1,
    analyze: bool = True,
    previous_layout: dict | None = None,
    label_density: str = "paper",
    level: str | None = None,
    view: str = "faithful",
    recovery_source: str = "MODEL",
    **export_options: Any,
) -> list[Path]:
    graph = load_graph(source, adapter=adapter, sample_input=sample_input, **export_options)
    if analyze:
        graph = analyze_graph(graph)["graph"]
    semantic: SemanticView | None = None
    if level:
        semantic = derive_semantic_view(graph)
        graph = semantic.materialize(graph, level=level, view=view)
    focus_ids = tuple(focus)
    if semantic and focus_ids:
        focus_ids = tuple(dict.fromkeys(
            semantic_id for source_id in focus_ids for semantic_id in semantic.trace_semantic(source_id, level=level)
        )) or focus_ids
    preflight_graph(graph, focus=focus_ids, operation="render", recovery_source=recovery_source)
    render_view = unroll_recurrent_graph(graph, steps=time_steps) if time_steps > 1 else graph.copy()
    render_view = focus_graph(render_view, set(focus_ids), hops=focus_hops)
    if focus_ids:
        enforce_focus_bound(render_view)
    render_view = collapse_graph(render_view, set(collapsed))
    if export_options.pop("aggregate_repeats", True):
        render_view = aggregate_repeated_blocks(render_view)
    style = get_theme(theme, theme_overrides, page)
    style["name"] = theme
    geometry = LayoutEngine().layout(
        render_view, algorithm=layout, direction=direction,
        node_width=style["node_width"], node_height=style["node_height"], previous=previous_layout,
        page=style["page"], page_preset=style.get("page_preset", page),
        font_size=style["font_size"], minimum_font_pt=style.get("minimum_font_pt", 7),
        label_density=label_density,
    )
    return export_graph(render_view, geometry, style, output, formats=formats, label_density=label_density, **export_options)


def semantic_view(source: Any, *, adapter: str | None = None, **options: Any) -> SemanticView:
    """Derive the versioned five-level Semantic View without mutating Graph IR."""
    return derive_semantic_view(load_graph(source, adapter=adapter, **options))


def scene_from_graph(
    source: Any,
    *,
    adapter: str | None = None,
    architecture: str | None = None,
    level: str = "operation",
    view: str = "faithful",
    focus: Iterable[str] = (),
    focus_hops: int = 1,
    maximum_objects: int = 250,
    projection: str = "orthographic",
    figure_ir: Any = None,
    existing_scene: Scene | dict[str, Any] | None = None,
    **options: Any,
) -> Scene:
    """Build an editable Scene IR from exact Graph/Semantic evidence."""

    from .figure_ir import FigureIR
    from .model_scene import model_scene_from_graph

    graph = load_graph(source, adapter=adapter, **options)
    semantic = derive_semantic_view(graph)
    figure = FigureIR.from_dict(figure_ir) if isinstance(figure_ir, dict) else figure_ir
    previous = Scene.from_dict(existing_scene) if isinstance(existing_scene, dict) else existing_scene
    return model_scene_from_graph(
        graph,
        semantic_view=semantic,
        figure_ir=figure,
        architecture=architecture,
        level=level,
        view=view,
        focus_ids=tuple(focus),
        focus_hops=focus_hops,
        maximum_objects=maximum_objects,
        existing_scene=previous,
        projection=projection,
    )


def render_scene(
    source: Scene | Any,
    output: str | Path,
    *,
    formats: Iterable[str] = ("svg",),
    camera_id: str | None = None,
    projection_options: dict[str, Any] | None = None,
    **scene_options: Any,
) -> list[Path]:
    """Export a Scene directly, or derive one from a model/Graph IR first."""

    scene = source if isinstance(source, Scene) else scene_from_graph(source, **scene_options)
    return export_scene(scene, output, formats=formats, camera_id=camera_id, options=projection_options)


def draw(
    model: Any,
    *,
    input_size: tuple[int, ...] | list[int] | None = None,
    sample_input: Any = None,
    output: str | Path = "network.svg",
    **options: Any,
) -> list[Path]:
    if sample_input is None and input_size is not None:
        try:
            import torch
        except ImportError:
            sample_input = None
        else:
            sample_input = torch.zeros(tuple(input_size), device=options.pop("device", "cpu"))
    return render(model, output, sample_input=sample_input, **options)


def capture_runtime(
    model: Any,
    sample_input: Any,
    *,
    operation_level: bool = False,
    capture_gradients: bool = False,
    backward_target: Any = None,
    allow_code: bool = False,
    allow_pickle: bool = False,
    save_activations: bool | str | list[Any] = False,
) -> dict[str, Any]:
    """Capture an actual PyTorch execution and link it to Graph IR."""
    adapter = registry.get("pytorch")
    resolved = adapter.resolve_model(model, allow_code=allow_code, allow_pickle=allow_pickle)
    if operation_level:
        return TorchLensAnalyzer().capture(
            resolved, sample_input, save_activations=save_activations,
            capture_gradients=capture_gradients, backward_target=backward_target,
        )
    graph = adapter.load(resolved, sample_input=sample_input)
    target = backward_target
    if capture_gradients and target is None:
        def first_scalar(output: Any) -> Any:
            return output.flatten()[0]

        target = first_scalar
    result = RuntimeAnalyzer().capture(resolved, sample_input, backward_target=target, graph=graph)
    result["graph"] = graph
    return result


def explain_model(
    model: Any,
    sample_input: Any,
    *,
    method: str = "grad-cam",
    target_layer: str | None = None,
    target_class: int | None = None,
    output: str | Path | None = None,
    input_image: Any = None,
    allow_code: bool = False,
    allow_pickle: bool = False,
) -> dict[str, Any]:
    """Create a CAM or input-gradient explanation and optionally save heatmaps."""
    adapter = registry.get("pytorch")
    resolved = adapter.resolve_model(model, allow_code=allow_code, allow_pickle=allow_pickle)
    analyzer = ExplainabilityAnalyzer()
    if method.lower() in {"input-gradient", "saliency"}:
        result = analyzer.input_gradient(resolved, sample_input, target_class=target_class)
    else:
        if not target_layer:
            from .errors import ValidationError
            raise ValidationError("CAM analysis requires target_layer", hint="Pass a convolutional layer path such as 'features.7'.")
        result = analyzer.cam(resolved, sample_input, target_layer=target_layer, target_class=target_class, method=method)
    paths = analyzer.save_heatmaps(result, output, input_image=input_image) if output else []
    return {"result": result, "artifacts": paths}


def render_project(project: Project | str | Path, output: str | Path | None = None, *, save_project: bool = False) -> list[Path]:
    if isinstance(project, (str, Path)):
        project_path = Path(project)
        source_path: Path | None = project_path
        document = Project.load(project_path)
    else:
        source_path = None
        document = project
    target = Path(output) if output else Path(document.export.get("output", f"{document.name}.svg"))
    formats = document.export.get("formats", [target.suffix.lstrip(".") or "svg"])
    if document.export.get("workspace") == "scene":
        paths = export_scene(
            document.persisted_scene(),
            target,
            formats=formats,
            camera_id=document.export.get("camera_id"),
            options=document.export.get("projection_options", document.export.get("options", {})),
        )
        document.record_artifacts(paths)
        if save_project and source_path:
            document.save(source_path)
        return paths
    style = get_theme(document.theme, document.theme_overrides, document.export.get("page", "auto"))
    style["name"] = document.theme
    previous = document.layout.get("result") if "result" in document.layout else document.layout if "nodes" in document.layout else None
    time_steps = int(document.layout.get("time_steps", 1) or 1)
    view = unroll_recurrent_graph(document.graph, steps=time_steps) if time_steps > 1 else document.graph.copy()
    semantic_level = document.semantic_view.get("level")
    semantic_mode = document.semantic_view.get("view", "faithful")
    semantic: SemanticView | None = None
    if semantic_level:
        semantic = derive_semantic_view(view)
        view = semantic.materialize(view, level=str(semantic_level), view=str(semantic_mode))
    focus_ids = tuple(document.layout.get("focus", []))
    if semantic and focus_ids:
        focus_ids = tuple(dict.fromkeys(
            semantic_id
            for source_id in focus_ids
            for semantic_id in semantic.trace_semantic(source_id, level=str(semantic_level))
        )) or focus_ids
    preflight_graph(view, focus=focus_ids, operation="project render")
    view = focus_graph(view, set(focus_ids), hops=document.layout.get("focus_hops", 1))
    if focus_ids:
        enforce_focus_bound(view)
    view = collapse_graph(view, set(document.layout.get("collapsed", [])))
    if document.layout.get("aggregate_repeats", True):
        view = aggregate_repeated_blocks(view)
    geometry = LayoutEngine().layout(
        view,
        algorithm=document.layout.get("algorithm", "auto"),
        direction=document.layout.get("direction", "LR"),
        node_width=style["node_width"], node_height=style["node_height"],
        previous=previous,
        page=style["page"], page_preset=style.get("page_preset", document.export.get("page", "auto")),
        font_size=style["font_size"], minimum_font_pt=style.get("minimum_font_pt", 7),
        label_density=str(document.export.get("options", {}).get("label_density", "paper")),
    )
    export_options = {key: value for key, value in document.export.items() if key not in {"formats", "output", "page", "options"}}
    export_options.update(document.export.get("options", {}))
    paths = export_graph(view, geometry, style, target, formats=formats, **export_options)
    document.layout.update({"algorithm": geometry.engine, "direction": geometry.direction, "result": geometry.to_dict()})
    document.record_artifacts(paths)
    if save_project and source_path:
        document.save(source_path)
    return paths
