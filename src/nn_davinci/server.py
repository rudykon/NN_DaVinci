from __future__ import annotations

import base64
import binascii
from dataclasses import asdict
import json
import io
import os
from hashlib import sha256
import tempfile
import threading
import time
import webbrowser
import zipfile
from pathlib import Path
from typing import Any

from .adapters import registry
from .analysis import analyze_graph, compare_graphs, visualize_diff
from .api import load_graph
from .errors import AdapterError, NNDaVinciError, OptionalDependencyError, ValidationError
from .figure_export import export_figure, export_submission_package, figure_proof, import_figure_svg, render_figure_svg
from .figure_ir import FigureIR
from .model_figure import (
    model_figure_from_graph,
    structure_lens_panel_preview,
    validate_model_figure_provenance,
)
from .figure_templates import instantiate_template, template_catalog, template_project
from .ir import GraphIR
from .import_wizard import inspect_import, saved_import_config
from .composer import FigureComposer
from .layout import LayoutEngine, LayoutResult, aggregate_repeated_blocks, collapse_graph, focus_graph
from .optimizer import PAPER_PRESETS, PaperOptimizer, apply_suggestion, proof_preview
from .paper_production import PAPER_FIGURE_TEMPLATES, generate_paper_figure
from .plugins import manager
from .project import Project
from .render import SvgRenderer, export_graph
from .real_models import import_real_model, real_model_registry
from .scaling import enforce_focus_bound, preflight_graph
from .model_scene import ARCHITECTURE_FAMILIES, model_scene_from_graph, scene_template, validate_model_scene_provenance
from .scene_export import export_scene, render_scene_svg, scene_export_policy
from .scene_ir import Scene
from .scene_projection import project_scene
from .semantic import (
    SEMANTIC_LEVELS,
    SEMANTIC_SELECTION_LEVELS,
    VIEW_MODES,
    SemanticView,
    derive_semantic_view,
    normalize_semantic_level,
)
from .structure_lens import AnalysisBudget, StructureLens
from .tasks import TaskManager
from .themes import PAGE_PRESETS, THEMES, get_theme
from .trial import TrialRecorder, trial_event_schema
from .trial_models import external_model_case_manifest, import_external_model
from .viewport import Viewport, coarse_semantic_graph, lazy_summary, neighborhood_slice, viewport_slice


def create_app(
    initial_source: str | None = None,
    *,
    trial_root: str | Path | None = None,
    task_root: str | Path | None = None,
    service_host: str | None = None,
    service_port: int | None = None,
    source_identity: str | None = None,
    build_identity: str | None = None,
):
    try:
        from flask import Flask, Response, jsonify, request, send_from_directory
    except ImportError as exc:
        raise OptionalDependencyError("The Web editor requires Flask", hint="Install nn-davinci[web].") from exc
    web_root = Path(__file__).with_name("web")
    from werkzeug.exceptions import HTTPException

    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
    app.config["MAX_FORM_MEMORY_SIZE"] = 2 * 1024 * 1024
    initial_graph = load_graph(initial_source) if initial_source else _demo_graph()
    graph_store: dict[str, GraphIR] = {}
    semantic_cache: dict[str, Any] = {}
    task_manager = TaskManager(task_root or os.environ.get("NNDV_TASK_ROOT"))
    trial_recorder = TrialRecorder(trial_root)
    initial_graph_id = _store_graph(graph_store, initial_graph)
    started_monotonic = time.monotonic()
    started_at_unix = time.time()
    effective_host = service_host or os.environ.get("NNDV_SERVICE_HOST", "127.0.0.1")
    effective_port = int(service_port if service_port is not None else os.environ.get("NNDV_SERVICE_PORT", "8765"))
    module_digest = sha256(Path(__file__).read_bytes()).hexdigest()
    identity = {
        "source": source_identity or os.environ.get("NNDV_SOURCE_IDENTITY") or f"server.py:{module_digest}",
        "build": build_identity or os.environ.get("NNDV_BUILD_IDENTITY") or "development-unsealed",
    }
    app.extensions["nn_davinci_tasks"] = task_manager
    app.extensions["nn_davinci_graphs"] = graph_store
    app.extensions["nn_davinci_trial"] = trial_recorder

    @app.errorhandler(NNDaVinciError)
    def handle_known(error: NNDaVinciError):
        return jsonify(error.to_dict()), error.status_code

    @app.errorhandler(HTTPException)
    def handle_http(error: HTTPException):
        return jsonify({
            "error": error.name.lower().replace(" ", "_"),
            "message": error.description,
            "status": error.code,
        }), error.code

    @app.errorhandler(Exception)
    def handle_unknown(error: Exception):
        app.logger.exception("NN_DaVinci request failed")
        return jsonify({"error": type(error).__name__, "message": str(error), "hint": "Check the request data and local server log."}), 500

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https:; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        )
        return response

    @app.get("/")
    def index():
        return send_from_directory(web_root, "index.html")

    @app.get("/<path:filename>")
    def assets(filename: str):
        return send_from_directory(web_root, filename)

    @app.get("/api/state")
    def state():
        return jsonify({
            "graph": initial_graph.to_dict(), "graph_id": initial_graph_id, "comments": [],
            "capabilities": _capabilities(), "tasks": task_manager.list(),
            "summary": lazy_summary(initial_graph),
            "trial": trial_recorder.status(),
        })

    @app.get("/api/health")
    def health():
        from . import __version__

        return jsonify({
            "schema_version": "nndv-health-1",
            "product": "NN_DaVinci",
            "product_version": __version__,
            "pid": os.getpid(),
            "uptime_seconds": round(max(0.0, time.monotonic() - started_monotonic), 6),
            "started_at_unix": started_at_unix,
            "host": effective_host,
            "port": effective_port,
            "source_identity": identity["source"],
            "build_identity": identity["build"],
            "readiness": True,
            "authentication": False,
            "lan_risk": effective_host not in {"127.0.0.1", "localhost", "::1"},
        })

    @app.get("/api/capabilities")
    def capabilities():
        return jsonify(_capabilities())

    @app.get("/api/trial/status")
    def trial_status():
        return jsonify(trial_recorder.status())

    @app.get("/api/trial/schema")
    def trial_schema():
        return jsonify(trial_event_schema())

    @app.post("/api/trial/consent")
    def trial_consent():
        payload = request.get_json(force=True)
        return jsonify(trial_recorder.set_consent(
            bool(payload.get("accepted")),
            protocol_version=str(payload.get("protocol_version", "")),
            explicit_confirmation=payload.get("explicit_confirmation") is True,
        ))

    @app.post("/api/trial/sessions")
    def trial_session_start():
        payload = request.get_json(silent=True) or {}
        event = trial_recorder.start_session(
            case_key=str(payload.get("case_key", "participant_model")),
            workflow=str(payload.get("workflow", "guided-web")),
        )
        return jsonify({"event": event, "status": trial_recorder.status()}), 201

    @app.post("/api/trial/events")
    def trial_event():
        payload = request.get_json(force=True)
        event_type = str(payload.pop("event_type", ""))
        return jsonify({"event": trial_recorder.record(event_type, payload)})

    @app.post("/api/trial/finish")
    def trial_finish():
        payload = request.get_json(silent=True) or {}
        return jsonify(trial_recorder.finish_session(str(payload.get("status", "completed"))))

    @app.get("/api/trial/export")
    def trial_export():
        body = json.dumps(trial_recorder.export(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        return Response(
            body,
            mimetype="application/json",
            headers={"Content-Disposition": 'attachment; filename="nn-davinci-local-trial.json"'},
        )

    @app.get("/api/trial-cases")
    def trial_cases():
        return jsonify(external_model_case_manifest())

    @app.post("/api/trial-cases/<name>")
    def trial_case(name: str):
        graph, spec = import_external_model(name)
        graph_id = _store_graph(graph_store, graph)
        semantic = derive_semantic_view(graph)
        semantic_cache[graph_id] = semantic
        recommendation = generate_paper_figure(graph, maximum_candidates=1).recommendation
        return jsonify({
            "case": spec.public_dict(),
            "graph": graph.to_dict(),
            "graph_id": graph_id,
            "summary": lazy_summary(graph, semantic),
            "diagnostics": {
                "detections": semantic.detections,
                "unknown_semantics": sum(item.get("unknown", False) for item in semantic.detections),
                "unknown_explanation": (
                    "Unknown means the sampled Graph IR does not contain enough structural evidence for a named semantic pattern; "
                    "it is preserved faithfully and is never guessed from the model or module name."
                ),
            },
            "paper_recommendation": asdict(recommendation),
        })

    @app.post("/api/import/inspect")
    def inspect_model_import():
        if request.files:
            upload = next(iter(request.files.values()))
            data = upload.read(app.config["MAX_CONTENT_LENGTH"] + 1)
            if len(data) > app.config["MAX_CONTENT_LENGTH"]:
                raise ValidationError("Upload exceeds the 16 MiB inspection limit")
            plan = inspect_import(upload.filename or "model", data)
        else:
            payload = request.get_json(force=True)
            encoded = payload.get("data_base64")
            try:
                data = base64.b64decode(encoded, validate=True) if encoded else payload.get("text")
            except (binascii.Error, ValueError) as exc:
                raise ValidationError(
                    "Malformed base64 import sample",
                    hint="Send RFC 4648 base64 without whitespace, or use the text field.",
                ) from exc
            plan = inspect_import(str(payload.get("filename", "model")), data, size_bytes=payload.get("size_bytes"))
        return jsonify({"plan": plan.to_dict()})

    @app.post("/api/import")
    def import_model():
        if request.files:
            upload = next(iter(request.files.values()))
            suffix = Path(upload.filename or "model.json").suffix
            allowed = {".onnx", ".json", ".nndv", ".yaml", ".yml", ".keras", ".h5", ".pb", ".pbtxt", ".mlir", ".py"}
            if suffix.lower() not in allowed:
                raise ValidationError(
                    f"Unsupported upload format {suffix or '<none>'!r}",
                    hint=f"Allowed formats: {', '.join(sorted(allowed))}.",
                )
            data = upload.read(app.config["MAX_CONTENT_LENGTH"] + 1)
            if len(data) > app.config["MAX_CONTENT_LENGTH"]:
                raise ValidationError("Upload exceeds the 16 MiB limit", hint="Reduce the model or import it through the local Python API.")
            if suffix.lower() == ".onnx":
                try:
                    import onnx
                except ImportError as exc:
                    raise OptionalDependencyError("ONNX upload requires onnx", hint="Install nn-davinci[onnx].") from exc
                try:
                    model = onnx.load_model_from_string(data)
                except Exception as exc:
                    raise AdapterError("Malformed ONNX upload", hint="Validate the file with onnx.checker before importing.") from exc
                graph = registry.load(model, adapter="onnx")
            elif suffix.lower() in {".json", ".nndv"}:
                try:
                    mapping = json.loads(data.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
                    raise ValidationError("Malformed JSON upload", hint="Use UTF-8 JSON with a nesting depth below 80.") from exc
                _validate_json_depth(mapping)
                if isinstance(mapping, dict) and mapping.get("project_version") and "graph" in mapping:
                    graph = Project.from_dict(mapping).graph
                elif isinstance(mapping, dict) and "ir_version" in mapping:
                    graph = GraphIR.from_dict(mapping)
                else:
                    graph = registry.load(mapping, adapter="manual")
            else:
                with tempfile.NamedTemporaryFile(prefix="nndavinci-upload-", suffix=suffix, delete=True) as temporary:
                    temporary.write(data)
                    temporary.flush()
                    adapter_name = request.form.get("adapter") or ("tensorflow" if suffix.lower() in {".pb", ".pbtxt"} else None)
                    graph = registry.load(temporary.name, adapter=adapter_name)
        else:
            payload = request.get_json(force=True)
            _validate_json_depth(payload)
            source = payload.get("graph", payload.get("source", payload))
            graph = GraphIR.from_dict(source) if isinstance(source, dict) and "ir_version" in source else registry.load(source, adapter=payload.get("adapter", "manual"))
        large_graph = len(graph.nodes) > 2_000 or len(graph.edges) > 12_000
        graph_id = _store_graph(graph_store, graph)
        semantic = None if large_graph else derive_semantic_view(graph)
        if semantic is not None:
            semantic_cache[graph_id] = semantic
        return jsonify({
            "graph": _graph_descriptor(graph) if large_graph else graph.to_dict(), "graph_id": graph_id,
            "node_count": len(graph.nodes), "edge_count": len(graph.edges), "lazy": large_graph,
            "semantic_summary": lazy_summary(graph, semantic),
            "diagnostics": {
                "unknown_semantics": None if semantic is None else sum(item.get("unknown", False) for item in semantic.detections),
                "detections": [] if semantic is None else semantic.detections,
                "detections_deferred": large_graph,
                "dynamic_sampling_boundary": graph.metadata.get("dynamic_sampling_boundary"),
            },
        })

    @app.post("/api/summary")
    def graph_summary():
        payload = request.get_json(force=True)
        graph = _resolve_graph(payload, graph_store)
        semantic = _cached_semantic_for(graph, payload.get("graph_id"), semantic_cache)
        return jsonify(lazy_summary(graph, semantic))

    @app.post("/api/semantic")
    def semantic_view():
        payload = request.get_json(force=True)
        graph = _resolve_graph(payload, graph_store)
        requested_level = str(payload.get("level", "model"))
        level = normalize_semantic_level(requested_level)
        view_name = str(payload.get("view", "faithful"))
        semantic = _semantic_for(graph, payload.get("graph_id"), semantic_cache)
        materialized = semantic.materialize(graph, level=level, view=view_name)
        graph_id = _store_graph(graph_store, graph)
        return jsonify({
            "graph": materialized.to_dict(), "source_graph_id": graph_id,
            "semantic": semantic.to_dict(), "level": level,
            "requested_level": requested_level, "view": view_name,
            "breadcrumbs": _breadcrumbs(semantic, payload.get("target"), level),
        })

    @app.post("/api/semantic/provenance")
    def semantic_provenance():
        payload = request.get_json(force=True)
        graph = _resolve_graph(payload, graph_store)
        semantic = _semantic_for(graph, payload.get("graph_id"), semantic_cache)
        semantic_id = str(payload.get("semantic_id", ""))
        provenance = semantic.trace_source(semantic_id)
        return jsonify({
            "semantic_id": semantic_id,
            "source_node_ids": provenance.source_node_ids,
            "source_edge_ids": provenance.source_edge_ids,
        })

    @app.post("/api/viewport")
    def lazy_viewport():
        payload = request.get_json(force=True)
        source = _resolve_graph(payload, graph_store)
        requested_level = str(payload.get("level", "operation"))
        level = normalize_semantic_level(requested_level)
        view_name = str(payload.get("view", "faithful"))
        graph = source
        include = list(payload.get("include", []))
        if level in SEMANTIC_LEVELS:
            cached = _cached_semantic_for(source, payload.get("graph_id"), semantic_cache)
            if cached is None and len(source.nodes) > 2_000 and level in {"model", "stage"}:
                graph = coarse_semantic_graph(source, level=level)
                include = []
            else:
                semantic = cached or _semantic_for(source, payload.get("graph_id"), semantic_cache)
                graph = semantic.materialize(source, level=level, view=view_name)
                graph_ids = set(graph.node_map())
                include = list(dict.fromkeys(
                    candidate
                    for requested in include
                    for candidate in ([requested] if requested in graph_ids else semantic.trace_semantic(requested, level=level))
                ))
        result = viewport_slice(
            graph,
            Viewport(**payload.get("viewport", {})),
            include=include,
            maximum_nodes=min(int(payload.get("maximum_nodes", 500)), 500),
            maximum_dom_objects=min(int(payload.get("maximum_dom_objects", 2_000)), 2_000),
        )
        return jsonify(result.to_dict())

    @app.post("/api/neighborhood")
    def neighborhood():
        payload = request.get_json(force=True)
        source = _resolve_graph(payload, graph_store)
        graph = neighborhood_slice(
            source, payload.get("node_ids", []), hops=int(payload.get("hops", 1)),
            maximum_nodes=min(int(payload.get("maximum_nodes", 500)), 500),
        )
        return jsonify({"graph": graph.to_dict(), "summary": lazy_summary(graph)})

    @app.post("/api/search")
    def graph_search():
        payload = request.get_json(force=True)
        graph = _resolve_graph(payload, graph_store)
        query = str(payload.get("query", "")).strip().lower()
        limit = max(1, min(200, int(payload.get("limit", 100))))
        matches = []
        if query:
            for node in graph.nodes:
                if query in f"{node.name} {node.op_type} {node.path} {node.namespace}".lower():
                    matches.append({
                        "id": node.id, "name": node.name, "op_type": node.op_type,
                        "path": node.path, "category": node.category,
                    })
                    if len(matches) >= limit:
                        break
        return jsonify({"query": query, "matches": matches, "truncated": len(matches) == limit})

    @app.post("/api/analyze")
    def analyze():
        payload = request.get_json(force=True)
        graph = _resolve_graph(payload, graph_store)
        preflight_graph(graph, operation="summary")
        result = analyze_graph(graph.copy())
        graph_id = _store_graph(graph_store, result["graph"])
        return jsonify({"graph": result["graph"].to_dict(), "graph_id": graph_id, "summary": result["summary"]})

    @app.post("/api/layout")
    def layout():
        payload = request.get_json(force=True)
        graph = _resolve_graph(payload, graph_store)
        if payload.get("level"):
            graph = _semantic_for(graph, payload.get("graph_id"), semantic_cache).materialize(
                graph, level=str(payload["level"]), view=str(payload.get("view", "faithful")),
            )
        focus_ids = set(payload.get("focus", []))
        preflight_graph(graph, focus=focus_ids, operation="layout")
        collapsed = set(payload.get("collapsed", []))
        view = focus_graph(graph, focus_ids, hops=payload.get("focus_hops", 1))
        if focus_ids:
            enforce_focus_bound(view)
        view = collapse_graph(view, collapsed)
        if payload.get("aggregate_repeats", True):
            view = aggregate_repeated_blocks(view)
        style = get_theme(payload.get("theme", "neurips"), payload.get("theme_overrides"), payload.get("page", "auto"))
        label_density = str(payload.get("options", {}).get("label_density", payload.get("label_density", "paper")))
        geometry = LayoutEngine().layout(
            view, algorithm=payload.get("algorithm", "auto"), direction=payload.get("direction", "LR"),
            node_width=style["node_width"], node_height=style["node_height"], previous=payload.get("previous"),
            page=style["page"], page_preset=style.get("page_preset", payload.get("page", "auto")),
            font_size=style["font_size"], minimum_font_pt=style.get("minimum_font_pt", 7),
            label_density=label_density,
            **{key: value for key, value in payload.get("layout_options", {}).items() if key in {"rank_gap", "node_gap"}},
        )
        return jsonify({"graph": view.to_dict(), "layout": geometry.to_dict()})

    @app.post("/api/render")
    def render_svg():
        payload = request.get_json(force=True)
        graph = _resolve_graph(payload, graph_store)
        if payload.get("level"):
            graph = _semantic_for(graph, payload.get("graph_id"), semantic_cache).materialize(
                graph, level=str(payload["level"]), view=str(payload.get("view", "faithful")),
            )
        focus_ids = set(payload.get("focus", []))
        preflight_graph(graph, focus=focus_ids, operation="render")
        if focus_ids:
            graph = focus_graph(graph, focus_ids, hops=payload.get("focus_hops", 1))
            enforce_focus_bound(graph)
        style = get_theme(payload.get("theme", "neurips"), payload.get("theme_overrides"), payload.get("page", "auto"))
        label_density = str(payload.get("options", {}).get("label_density", payload.get("label_density", "paper")))
        if payload.get("use_layout") and payload.get("layout"):
            geometry = LayoutResult.from_dict(payload["layout"])
        else:
            geometry = LayoutEngine().layout(graph, algorithm=payload.get("algorithm", "auto"), direction=payload.get("direction", "LR"), node_width=style["node_width"], node_height=style["node_height"], previous=payload.get("layout"), page=style["page"], page_preset=style.get("page_preset", payload.get("page", "auto")), font_size=style["font_size"], minimum_font_pt=style.get("minimum_font_pt", 7), label_density=label_density, **{key: value for key, value in payload.get("layout_options", {}).items() if key in {"rank_gap", "node_gap"}})
        options = payload.get("options", {})
        svg = SvgRenderer().render(graph, geometry, style, publication=False, **options)
        return jsonify({"svg": svg, "layout": geometry.to_dict()})

    @app.post("/api/export/<format_name>")
    def export(format_name: str):
        allowed_formats = {"svg", "pdf", "tikz", "png", "eps", "pptx", "html"}
        if format_name not in allowed_formats:
            raise ValidationError(
                f"Unsupported export format {format_name!r}",
                hint=f"Choose one of: {', '.join(sorted(allowed_formats))}.",
            )
        payload = request.get_json(force=True)
        graph = _resolve_graph(payload, graph_store)
        if payload.get("level"):
            graph = _semantic_for(graph, payload.get("graph_id"), semantic_cache).materialize(
                graph, level=str(payload["level"]), view=str(payload.get("view", "paper")),
            )
        focus_ids = set(payload.get("focus", []))
        preflight_graph(graph, focus=focus_ids, operation=f"{format_name} export")
        if focus_ids:
            graph = focus_graph(graph, focus_ids, hops=payload.get("focus_hops", 1))
            enforce_focus_bound(graph)
        style = get_theme(payload.get("theme", "neurips"), payload.get("theme_overrides"), payload.get("page", "auto"))
        label_density = str(payload.get("options", {}).get("label_density", payload.get("label_density", "paper")))
        geometry = LayoutEngine().layout(graph, algorithm=payload.get("algorithm", "auto"), direction=payload.get("direction", "LR"), node_width=style["node_width"], node_height=style["node_height"], previous=payload.get("layout"), page=style["page"], page_preset=style.get("page_preset", payload.get("page", "auto")), font_size=style["font_size"], minimum_font_pt=style.get("minimum_font_pt", 7), label_density=label_density, **{key: value for key, value in payload.get("layout_options", {}).items() if key in {"rank_gap", "node_gap"}})
        with tempfile.TemporaryDirectory(prefix="nndavinci-export-") as directory:
            outputs = export_graph(graph, geometry, style, Path(directory) / "diagram", formats=[format_name], **payload.get("options", {}))
            data = outputs[0].read_bytes()
            suffix = outputs[0].suffix
        content_types = {".svg": "image/svg+xml", ".pdf": "application/pdf", ".png": "image/png", ".eps": "application/postscript", ".tex": "text/x-tex", ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation", ".html": "text/html"}
        return Response(data, mimetype=content_types.get(suffix, "application/octet-stream"), headers={"Content-Disposition": f'attachment; filename="diagram{suffix}"'})

    @app.post("/api/project")
    def project():
        payload = request.get_json(force=True)
        _validate_json_depth(payload)
        if not isinstance(payload, dict):
            raise ValidationError("Project request must be an object")
        persisted = payload.get("project")
        if persisted is not None:
            if not isinstance(persisted, dict):
                raise ValidationError(
                    "Persisted project payload must be an object",
                    hint="Wrap the complete saved project as {'project': <project document>}.",
                )
            try:
                canonical = Project.from_dict(persisted).to_dict()
            except ValidationError:
                raise
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
                raise ValidationError(
                    "Persisted project document is malformed",
                    hint="Send the complete JSON object produced by Project.to_dict().",
                ) from exc
            return jsonify(canonical)
        graph = _resolve_graph(payload, graph_store)
        document = Project(
            payload.get("name", graph.name), graph, model_source=payload.get("model_source", {}),
            sample_inputs=payload.get("sample_inputs", []), theme=payload.get("theme", "neurips"),
            dynamic_dimensions=payload.get("dynamic_dimensions", {}),
            theme_overrides=payload.get("theme_overrides", {}), layout={
                "algorithm": payload.get("algorithm", payload.get("layout", {}).get("engine", "auto")),
                "direction": payload.get("direction", payload.get("layout", {}).get("direction", "LR")),
                "result": payload.get("layout", {}),
                "layout_options": payload.get("layout_options", {}),
                "focus": payload.get("focus", []), "focus_hops": payload.get("focus_hops", 1),
            },
            export=payload.get("export", {}), analysis_options=payload.get("analysis_options", {}),
            comments=payload.get("comments", []),
            collaboration=payload.get("collaboration", {}), presentation=payload.get("presentation", {}),
            artifacts=payload.get("artifacts", []), plugin_requirements=payload.get("plugin_requirements", []),
            environment=payload.get("environment", {}),
            semantic_view=payload.get("semantic_view", {}), canvas_state=payload.get("canvas_state", {}),
            import_configurations=payload.get("import_configurations", []), task_history=payload.get("task_history", []),
            paper_workflow=payload.get("paper_workflow", {}),
            figure_composer=payload.get("figure_composer", {}),
            figure_ir=payload.get("figure_ir", {}),
            scene_ir=payload.get("scene_ir", {}),
        )
        document.stamp_environment()
        return jsonify(document.to_dict())

    @app.get("/api/scene/templates")
    def scene_templates():
        templates = []
        for family in ARCHITECTURE_FAMILIES:
            scene = scene_template(family)
            templates.append({
                "family": family,
                "name": scene.name,
                "object_count": sum(1 for _ in scene.iter_objects()),
                "digest": scene.digest(),
            })
        return jsonify({
            "version": "1.0",
            "templates": templates,
            "network_required": False,
            "provenance_policy": "template geometry makes no model-evidence claim",
        })

    @app.post("/api/scene/templates/<family>")
    def scene_template_open(family: str):
        payload = request.get_json(silent=True) or {}
        _validate_json_depth(payload)
        if not isinstance(payload, dict):
            raise ValidationError("Scene template request must be an object")
        scene = scene_template(family, name=payload.get("name"))
        projection = project_scene(scene, camera_id=payload.get("camera_id"), options=payload.get("projection_options"))
        return jsonify({
            "family": scene.metadata["architecture_family"],
            "digest": scene.digest(),
            "scene": scene.to_dict(),
            "projection": projection.to_dict(),
            "svg": render_scene_svg(projection),
            "export_policy": scene_export_policy(projection),
        })

    @app.post("/api/scene/from-graph")
    def scene_from_current_graph():
        payload = request.get_json(force=True)
        _validate_json_depth(payload)
        if not isinstance(payload, dict):
            raise ValidationError("Graph-to-Scene request must be an object")
        raw_focus_ids = payload.get("focus_ids", payload.get("focus", []))
        if not isinstance(raw_focus_ids, list) or any(not isinstance(item, str) for item in raw_focus_ids):
            raise ValidationError("Scene focus_ids must be an array of strings")
        focus_ids = list(dict.fromkeys(raw_focus_ids))
        focus_hops = payload.get("focus_hops", 1)
        if isinstance(focus_hops, bool) or not isinstance(focus_hops, int) or focus_hops < 0:
            raise ValidationError("Scene focus_hops must be a non-negative integer")
        maximum_objects = payload.get("maximum_objects", 250)
        if isinstance(maximum_objects, bool) or not isinstance(maximum_objects, int):
            raise ValidationError("Scene maximum_objects must be an integer")

        graph = _resolve_graph(payload, graph_store)
        semantic_payload = payload.get("semantic_view")
        if isinstance(semantic_payload, dict) and isinstance(semantic_payload.get("document"), dict):
            semantic_payload = semantic_payload["document"]
        if isinstance(semantic_payload, dict) and semantic_payload.get("entities"):
            semantic = SemanticView.from_dict(semantic_payload).validate(graph)
        else:
            semantic = _semantic_for(graph, payload.get("graph_id"), semantic_cache)

        figure_payload = payload.get("figure_ir", payload.get("figure"))
        figure = FigureIR.from_dict(figure_payload) if isinstance(figure_payload, dict) else None
        existing_payload = payload.get("existing_scene")
        existing = Scene.from_dict(existing_payload) if isinstance(existing_payload, dict) else None
        scene = model_scene_from_graph(
            graph,
            semantic_view=semantic,
            figure_ir=figure,
            architecture=payload.get("architecture"),
            level=str(payload.get("level", "operation")),
            view=str(payload.get("view", "faithful")),
            focus_ids=focus_ids,
            focus_hops=focus_hops,
            maximum_objects=maximum_objects,
            existing_scene=existing,
            projection=str(payload.get("projection", "orthographic")),
        )
        provenance = validate_model_scene_provenance(scene, graph, semantic, figure)
        if not provenance.get("passed"):
            raise ValidationError(
                "Graph IR ↔ Semantic View ↔ Figure IR ↔ Scene IR provenance validation failed",
                details={"failures": provenance.get("failures", [])},
            )
        projection = project_scene(scene, camera_id=payload.get("camera_id"), options=payload.get("projection_options"))
        return jsonify({
            "scene": scene.to_dict(),
            "semantic_view": semantic.to_dict(),
            "provenance_validation": provenance,
            "projection": projection.to_dict(),
            "svg": render_scene_svg(projection),
            "export_policy": scene_export_policy(projection),
        })

    @app.post("/api/scene/validate")
    def scene_validate():
        payload = request.get_json(force=True)
        _validate_json_depth(payload)
        scene = Scene.from_dict(payload.get("scene", payload))
        return jsonify({"status": "PASS", "scene": scene.to_dict(), "digest": scene.digest()})

    @app.post("/api/scene/project")
    def scene_project():
        payload = request.get_json(force=True)
        _validate_json_depth(payload)
        scene = Scene.from_dict(payload.get("scene", payload))
        projection = project_scene(scene, camera_id=payload.get("camera_id"), options=payload.get("projection_options"))
        return jsonify({
            "scene": scene.to_dict(),
            "projection": projection.to_dict(),
            "svg": render_scene_svg(projection),
            "export_policy": scene_export_policy(projection),
        })

    @app.post("/api/scene/pick")
    def scene_pick():
        payload = request.get_json(force=True)
        _validate_json_depth(payload)
        scene = Scene.from_dict(payload.get("scene", {}))
        viewport = payload.get("viewport", scene.metadata.get("viewport", [1200.0, 800.0]))
        if not isinstance(viewport, list) or len(viewport) != 2:
            raise ValidationError("Scene pick viewport must be [width, height]")
        hits = scene.pick(
            payload.get("x"), payload.get("y"), viewport,
            camera_id=payload.get("camera_id"),
            include_locked=bool(payload.get("include_locked", True)),
        )
        if bool(payload.get("select", False)):
            scene.set_selection([hits[0].object_id] if hits else [])
        return jsonify({"hits": [asdict(hit) for hit in hits], "scene": scene.to_dict()})

    @app.post("/api/scene/transform")
    def scene_transform():
        payload = request.get_json(force=True)
        _validate_json_depth(payload)
        scene = Scene.from_dict(payload.get("scene", {}))
        object_ids = payload.get("object_ids", scene.selection_ids)
        if not isinstance(object_ids, list) or any(not isinstance(item, str) for item in object_ids):
            raise ValidationError("Scene transform object_ids must be an array of strings")
        operation = str(payload.get("operation", ""))
        value = payload.get("value")
        if not isinstance(value, list) or len(value) != 3:
            raise ValidationError("Scene transform value must be a three-number vector")
        for object_id in object_ids:
            if operation == "translate":
                scene.translate_object(object_id, value)
            elif operation == "rotate":
                scene.rotate_object(object_id, value)
            elif operation == "scale":
                scene.scale_object(object_id, value)
            else:
                raise ValidationError("Scene transform operation must be translate, rotate, or scale")
        scene.set_selection(object_ids)
        projection = project_scene(scene, camera_id=payload.get("camera_id"), options=payload.get("projection_options"))
        return jsonify({"scene": scene.to_dict(), "projection": projection.to_dict(), "svg": render_scene_svg(projection)})

    @app.post("/api/scene/export/<format_name>")
    def scene_export(format_name: str):
        allowed = {"svg", "pdf", "tikz", "tex", "pptx", "png", "eps", "html", "json", "gltf", "glb"}
        if format_name not in allowed:
            raise ValidationError(f"Scene IR format must be selected from {sorted(allowed)}")
        payload = request.get_json(force=True)
        _validate_json_depth(payload)
        scene = Scene.from_dict(payload.get("scene", payload))
        with tempfile.TemporaryDirectory(prefix="nndavinci-scene-") as directory:
            outputs = export_scene(
                scene,
                Path(directory) / "scene",
                formats=(format_name,),
                camera_id=payload.get("camera_id"),
                options=payload.get("projection_options"),
            )
            output = outputs[0]
            data, suffix = output.read_bytes(), output.suffix
            filename = f"scene{suffix}"
        return Response(
            data,
            mimetype=_content_type(suffix),
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/figure/templates")
    def figure_templates():
        return jsonify({"version": "1.0", "templates": template_catalog(), "network_required": False})

    @app.post("/api/figure/templates/<slug>")
    def figure_template(slug: str):
        payload = request.get_json(silent=True) or {}
        page_preset = str(payload.get("page_preset", "double-column"))
        graph, figure = instantiate_template(slug, page_preset=page_preset)
        graph_id = _store_graph(graph_store, graph)
        return jsonify({
            "project": template_project(slug, page_preset=page_preset),
            "graph": graph.to_dict(), "graph_id": graph_id,
            "figure": figure.to_dict(), "svg": render_figure_svg(figure), "proof": figure_proof(figure),
        })

    @app.post("/api/figure/from-graph")
    def figure_from_current_graph():
        payload = request.get_json(force=True)
        _validate_json_depth(payload)
        if not isinstance(payload, dict):
            raise ValidationError("Graph-to-Figure request must be an object")
        raw_focus_ids = payload.get("focus_ids", payload.get("focus", []))
        if not isinstance(raw_focus_ids, list) or any(not isinstance(item, str) for item in raw_focus_ids):
            raise ValidationError(
                "Figure focus_ids must be an array of strings",
                hint="Send Graph IR node IDs under focus_ids (or the backward-compatible focus alias).",
            )
        focus_ids = list(dict.fromkeys(raw_focus_ids))
        focus_hops = payload.get("focus_hops", 1)
        if isinstance(focus_hops, bool) or not isinstance(focus_hops, int) or focus_hops < 0:
            raise ValidationError("Figure focus_hops must be a non-negative integer")

        viewport = payload.get("viewport")
        if viewport is not None:
            if not isinstance(viewport, dict):
                raise ValidationError("Figure viewport must be an object")
            try:
                viewport = Viewport(**viewport).validate()
            except TypeError as exc:
                raise ValidationError(
                    "Figure viewport contains unsupported fields",
                    hint="Use only x, y, width, height, and padding.",
                ) from exc

        existing_figure = payload.get("existing_figure")
        if existing_figure is not None:
            if not isinstance(existing_figure, dict):
                raise ValidationError("Figure existing_figure must be a Figure IR object")
            try:
                existing_figure = FigureIR.from_dict(existing_figure)
            except ValidationError:
                raise
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
                raise ValidationError(
                    "Figure existing_figure is malformed",
                    hint="Send a complete FigureIR.to_dict() document.",
                ) from exc

        graph = _resolve_graph(payload, graph_store)
        source_node_count = len(graph.nodes)
        semantic = _semantic_for(graph, payload.get("graph_id"), semantic_cache)
        figure = model_figure_from_graph(
            graph,
            semantic_view=semantic,
            level=str(payload.get("level", "operation")),
            view=str(payload.get("view", "faithful")),
            mode=str(payload.get("mode", "mixed")),
            page_preset=str(payload.get("page_preset", "double-column")),
            focus_ids=focus_ids,
            focus_hops=focus_hops,
            viewport=viewport,
            existing_figure=existing_figure,
        )
        provenance = validate_model_figure_provenance(figure, graph, semantic)
        if not provenance.get("passed"):
            raise ValidationError(
                "Graph IR ↔ Semantic View ↔ Figure IR provenance validation failed",
                details={"failures": provenance.get("failures", [])},
            )
        if source_node_count > 1_000 or len(graph.edges) > 8_000:
            figure.metadata["large_graph"] = {
                "source_node_count": source_node_count,
                "source_edge_count": len(graph.edges),
                "figure_source": "bounded Semantic View summary of the original Graph IR",
                "synthetic_coarse_graph_used": False,
                "full_graph_available_via": "lazy summary / focus / search",
                "positive_semantics_only_when_proven": True,
            }
        return jsonify({
            "figure": figure.to_dict(),
            "semantic_view": semantic.to_dict(),
            "provenance_validation": provenance,
            "svg": render_figure_svg(figure),
            "proof": figure_proof(figure),
        })

    @app.post("/api/figure/validate")
    def figure_validate():
        payload = request.get_json(force=True)
        _validate_json_depth(payload)
        figure = FigureIR.from_dict(payload.get("figure", payload))
        return jsonify({"status": "PASS", "figure": figure.to_dict(), "digest": figure.digest(), "proof": figure_proof(figure)})

    @app.post("/api/figure/render")
    def figure_render():
        payload = request.get_json(force=True)
        _validate_json_depth(payload)
        figure = FigureIR.from_dict(payload.get("figure", payload))
        return jsonify({
            "svg": render_figure_svg(
                figure,
                include_guides=bool(payload.get("include_guides", False)),
                embed_metadata=False,
            ),
            "figure": figure.to_dict(), "proof": figure_proof(figure),
        })

    @app.post("/api/figure/import-svg")
    def figure_import_svg():
        payload = request.get_json(force=True)
        encoded = payload.get("data_base64")
        try:
            source = base64.b64decode(encoded, validate=True) if encoded else str(payload.get("svg", ""))
        except (binascii.Error, ValueError) as exc:
            raise ValidationError("Malformed SVG base64 payload") from exc
        figure, native = import_figure_svg(source, name=str(payload.get("name", "Imported SVG")))
        return jsonify({
            "native_roundtrip": native, "model_semantics_recovered": native,
            "figure": figure.to_dict(), "svg": render_figure_svg(figure), "proof": figure_proof(figure),
        })

    @app.post("/api/figure/export/<format_name>")
    def figure_export(format_name: str):
        allowed = {"svg", "pdf", "tikz", "tex", "pptx", "png", "eps", "html"}
        if format_name not in allowed:
            raise ValidationError(f"Figure IR format must be selected from {sorted(allowed)}")
        payload = request.get_json(force=True)
        figure = FigureIR.from_dict(payload.get("figure", payload))
        with tempfile.TemporaryDirectory(prefix="nndavinci-figure-") as directory:
            outputs = export_figure(figure, Path(directory) / "figure", formats=(format_name,))
            if len(outputs) == 1:
                output = outputs[0]
                data, suffix = output.read_bytes(), output.suffix
                filename = f"figure{suffix}"
                mimetype = _content_type(suffix)
            else:
                archive = io.BytesIO()
                with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
                    for output in outputs:
                        bundle.write(output, output.name)
                data, filename, mimetype = archive.getvalue(), f"figure-{format_name}-pages.zip", "application/zip"
        return Response(data, mimetype=mimetype, headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @app.post("/api/figure/submission-package")
    def figure_submission_package():
        payload = request.get_json(force=True)
        figure = FigureIR.from_dict(payload.get("figure", payload))
        project_payload = payload.get("project")
        if project_payload is not None:
            Project.from_dict(project_payload)
        with tempfile.TemporaryDirectory(prefix="nndavinci-submission-") as directory:
            outputs = export_submission_package(
                figure, directory, project=project_payload,
                caption=payload.get("caption"),
            )
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
                for output in outputs:
                    bundle.write(output, output.name)
            data = archive.getvalue()
        return Response(data, mimetype="application/zip", headers={"Content-Disposition": 'attachment; filename="nn-davinci-submission-package.zip"'})

    @app.post("/api/structure-lens/<operation>")
    def structure_lens(operation: str):
        payload = request.get_json(force=True)
        graph = _resolve_graph(payload, graph_store)
        semantic_payload = payload.get("semantic_view")
        if isinstance(semantic_payload, dict) and isinstance(semantic_payload.get("document"), dict):
            semantic_payload = semantic_payload["document"]
        if isinstance(semantic_payload, dict) and semantic_payload.get("entities"):
            semantic = SemanticView.from_dict(semantic_payload).validate(graph)
        else:
            semantic = _semantic_for(graph, payload.get("graph_id"), semantic_cache)
        lens = StructureLens(graph, semantic_view=semantic)
        budget_payload = payload.get("budget", {})
        budget = AnalysisBudget(
            maximum_visits=min(1_000_000, int(budget_payload.get("maximum_visits", 10_000))),
            maximum_depth=min(1_000, int(budget_payload.get("maximum_depth", 64))),
            maximum_paths=min(1_000, int(budget_payload.get("maximum_paths", 25))),
            maximum_queue_entries=min(1_000_000, int(budget_payload.get("maximum_queue_entries", 10_000))),
            maximum_generated_states=min(10_000_000, int(budget_payload.get("maximum_generated_states", 50_000))),
            maximum_memory_bytes=min(8 * 1024 * 1024 * 1024, int(budget_payload.get("maximum_memory_bytes", 64 * 1024 * 1024))),
            timeout_seconds=min(60.0, float(budget_payload.get("timeout_seconds", 1.0))),
        )
        if operation in {"upstream", "downstream"}:
            result = lens.trace(str(payload.get("node_id", "")), direction=operation, budget=budget)
        elif operation == "path":
            result = lens.bounded_paths(str(payload.get("source_id", "")), str(payload.get("target_id", "")), budget=budget)
        elif operation == "pathway":
            result = lens.pathway(str(payload.get("kind", "")))
        elif operation == "shape-timeline":
            result = lens.shape_timeline(payload.get("path", []))
        elif operation == "warnings":
            result = lens.warnings()
        elif operation == "overlay":
            result = lens.metric_overlay(str(payload.get("metric", "parameters")))
        elif operation == "repeats":
            result = lens.repeated_structures()
        elif operation == "unknown":
            result = lens.explain_unknown(str(payload.get("node_id", "")))
        else:
            raise ValidationError("Unknown Structure Lens operation")
        response = result.to_dict()
        if bool(payload.get("preview_panel", False)):
            response["figure_panel_preview"] = structure_lens_panel_preview(
                graph,
                result,
                page_preset=str(payload.get("page_preset", "double-column")),
            )
        return jsonify(response)

    @app.post("/api/import/config")
    def import_config():
        payload = request.get_json(force=True)
        plan = inspect_import(
            str(payload.get("filename", "model")), payload.get("text"), size_bytes=payload.get("size_bytes"),
        )
        return jsonify(saved_import_config(plan, payload.get("options", {})))

    @app.post("/api/paper/suggestions")
    def paper_suggestions():
        payload = request.get_json(force=True)
        graph = _resolve_graph(payload, graph_store)
        layout_result = payload.get("layout")
        if not layout_result:
            raise ValidationError("Paper suggestions require the current layout")
        style = get_theme(payload.get("theme", "neurips"), payload.get("theme_overrides"), payload.get("page", "double-column"))
        suggestions = PaperOptimizer().suggest(
            graph, layout_result, style, page=payload.get("page", "double-column"),
            preset=payload.get("preset", "paper"), maximum_candidates=int(payload.get("maximum_candidates", 3)),
        )
        return jsonify({
            "suggestions": [item.to_dict() for item in suggestions],
            "presets": sorted(PAPER_PRESETS),
            "proofs": {item.id: proof_preview(item.layout) for item in suggestions},
        })

    @app.post("/api/paper/readability")
    def paper_readability():
        payload = request.get_json(force=True)
        graph = _resolve_graph(payload, graph_store)
        style = get_theme(payload.get("theme", "neurips"), payload.get("theme_overrides"), payload.get("page", "double-column"))
        suggestion = PaperOptimizer().one_click_readability(
            graph, payload["layout"], style, page=payload.get("page", "double-column"),
        )
        return jsonify({"suggestion": suggestion.to_dict(), "proof": proof_preview(suggestion.layout)})

    @app.post("/api/paper/apply")
    def paper_apply():
        payload = request.get_json(force=True)
        applied, undo = apply_suggestion(payload["current_layout"], payload["suggestion"])
        return jsonify({"layout": applied.to_dict(), "undo": undo.to_dict()})

    @app.get("/api/real-models")
    def real_models():
        return jsonify({
            "corpus_version": "1.0",
            "models": [
                {
                    "key": spec.key,
                    "name": spec.display_name,
                    "family": spec.family,
                    "seed": spec.seed,
                    "sample_input": spec.sample_description,
                    "parameters": spec.expected_parameters,
                    "weights": "not downloaded",
                }
                for spec in real_model_registry().values()
            ],
        })

    @app.post("/api/real-models/<name>")
    def real_model(name: str):
        payload = request.get_json(silent=True) or {}
        graph = import_real_model(name, view=str(payload.get("view", "operation")))
        graph_id = _store_graph(graph_store, graph)
        semantic = derive_semantic_view(graph)
        semantic_cache[graph_id] = semantic
        recommendation = generate_paper_figure(graph, maximum_candidates=1).recommendation
        return jsonify({
            "graph": graph.to_dict(),
            "graph_id": graph_id,
            "summary": lazy_summary(graph, semantic),
            "diagnostics": {
                "detections": semantic.detections,
                "unknown_semantics": sum(item.get("unknown", False) for item in semantic.detections),
            },
            "paper_recommendation": asdict(recommendation),
        })

    @app.post("/api/paper/generate")
    def paper_generate():
        payload = request.get_json(force=True)
        graph = _resolve_graph(payload, graph_store)
        session = generate_paper_figure(graph, maximum_candidates=int(payload.get("maximum_candidates", 3)))
        return jsonify({
            "version": "1.0",
            "recommendation": asdict(session.recommendation),
            "paper_graph": session.paper_graph.to_dict(),
            "initial_layout": session.initial_layout.to_dict(),
            "candidates": [item.to_dict() for item in session.candidates],
            "caption": session.caption,
            "semantic": session.semantic.to_dict(),
        })

    @app.post("/api/composer/compose")
    def composer_compose():
        payload = request.get_json(force=True)
        composer = FigureComposer.from_dict(payload.get("composer", payload))
        graph, layout, proof = composer.compose(relayout_panels=payload.get("relayout_panels", []))
        return jsonify({"graph": graph.to_dict(), "layout": layout.to_dict(), "proof": proof, "composer": composer.to_dict()})

    @app.post("/api/composer/export")
    def composer_export():
        payload = request.get_json(force=True)
        composer = FigureComposer.from_dict(payload["composer"])
        formats = tuple(payload.get("formats", ["svg", "pdf", "tikz", "png", "eps", "pptx"]))
        allowed = {"svg", "pdf", "tikz", "png", "eps", "pptx"}
        if not formats or not set(formats).issubset(allowed):
            raise ValidationError(f"Composer formats must be selected from {sorted(allowed)}")
        with tempfile.TemporaryDirectory(prefix="nndavinci-composer-") as directory:
            outputs = composer.export(
                Path(directory) / "figure.svg",
                formats=formats,
                tikz_panels=bool(payload.get("tikz_panels", False)),
            )
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
                for output in outputs:
                    bundle.write(output, output.name)
            data = archive.getvalue()
        return Response(data, mimetype="application/zip", headers={"Content-Disposition": 'attachment; filename="paper-figure.zip"'})

    @app.get("/api/tasks")
    def tasks_list():
        return jsonify({"tasks": task_manager.list()})

    @app.get("/api/tasks/<task_id>")
    def task_status(task_id: str):
        return jsonify(task_manager.get(task_id, include_result=request.args.get("result") == "1"))

    @app.post("/api/tasks/<task_id>/cancel")
    def task_cancel(task_id: str):
        return jsonify(task_manager.cancel(task_id))

    @app.post("/api/tasks/<task_id>/retry")
    def task_retry(task_id: str):
        return jsonify(task_manager.retry(task_id).to_dict()), 202

    @app.get("/api/tasks/<task_id>/artifact")
    def task_artifact(task_id: str):
        record = task_manager.get(task_id, include_result=True)
        artifact_path = record.get("result", {}).get("artifact_path")
        if not artifact_path:
            raise ValidationError("Task has no downloadable artifact")
        target = Path(artifact_path).resolve()
        if target.parent != task_manager.root.resolve() or not target.is_file():
            raise ValidationError("Task artifact is missing or outside the task store")
        return Response(
            target.read_bytes(), mimetype=_content_type(target.suffix),
            headers={"Content-Disposition": f'attachment; filename="{target.name}"'},
        )

    @app.post("/api/tasks")
    def task_submit():
        payload = request.get_json(force=True)
        kind = str(payload.get("kind", ""))
        source_graph = _resolve_graph(payload, graph_store) if kind != "import" or "graph" in payload or "graph_id" in payload else None

        def execute(context):
            context.report("preflight", 0.08)
            if kind == "import":
                source = payload.get("source")
                graph = GraphIR.from_dict(source) if isinstance(source, dict) and "ir_version" in source else registry.load(source, adapter=payload.get("adapter", "manual"))
                context.report("semantic-index", 0.65)
                semantic = derive_semantic_view(graph)
                context.report("persist", 0.92)
                return {"graph": graph.to_dict(), "graph_id": _store_graph(graph_store, graph), "summary": lazy_summary(graph, semantic)}
            if source_graph is None:
                raise ValidationError("Task requires a graph or graph_id")
            if kind == "analyze":
                context.report("static-analysis", 0.25)
                result = analyze_graph(source_graph.copy())
                context.report("summarize", 0.9)
                return {"graph": result["graph"].to_dict(), "summary": result["summary"]}
            if kind == "runtime":
                context.report("runtime-provenance", 0.3)
                runtime_nodes = [node.id for node in source_graph.nodes if any(key in node.analysis for key in ("duration_ms", "runtime", "activation"))]
                if not runtime_nodes:
                    raise ValidationError(
                        "No captured runtime is attached to this graph",
                        hint="Provide a trusted model and sample input through the Python/CLI runtime command, then reopen the project.",
                    )
                return {"graph": source_graph.to_dict(), "runtime_nodes": runtime_nodes}
            level = payload.get("level")
            graph = source_graph
            if level:
                context.report("semantic-view", 0.18)
                graph = derive_semantic_view(source_graph).materialize(
                    source_graph, level=str(level), view=str(payload.get("view", "faithful")),
                )
            style = get_theme(payload.get("theme", "neurips"), payload.get("theme_overrides"), payload.get("page", "auto"))
            context.report("layout", 0.38)
            geometry = LayoutEngine().layout(
                graph, algorithm=payload.get("algorithm", "auto"), direction=payload.get("direction", "LR"),
                node_width=style["node_width"], node_height=style["node_height"], previous=payload.get("layout"),
                page=style["page"], page_preset=style.get("page_preset", payload.get("page", "auto")),
                font_size=style["font_size"], minimum_font_pt=style.get("minimum_font_pt", 7),
                label_density=str(payload.get("label_density", "paper")),
            )
            context.check_cancelled()
            if kind == "layout":
                context.report("serialize", 0.94)
                return {"graph": graph.to_dict(), "layout": geometry.to_dict()}
            if kind == "export":
                format_name = str(payload.get("format", "svg"))
                if format_name not in {"svg", "pdf", "tikz", "png", "eps", "pptx", "html"}:
                    raise ValidationError(f"Unsupported export format {format_name!r}")
                context.report("vector-export", 0.7)
                target = task_manager.root / f"{context.task_id}-diagram"
                outputs = export_graph(graph, geometry, style, target, formats=[format_name], **payload.get("options", {}))
                context.report("persist-artifact", 0.96)
                return {"artifact_path": str(outputs[0]), "format": format_name, "size_bytes": outputs[0].stat().st_size}
            raise ValidationError(f"Unsupported task kind {kind!r}")

        input_graph = source_graph
        record = task_manager.submit(
            kind, execute,
            input_size={
                "nodes": len(input_graph.nodes) if input_graph else int(payload.get("input_nodes", 0)),
                "edges": len(input_graph.edges) if input_graph else int(payload.get("input_edges", 0)),
                "bytes": len(request.data),
            },
            resource_budget=payload.get("resource_budget"),
        )
        return jsonify(record.to_dict()), 202

    @app.post("/api/diff")
    def diff():
        payload = request.get_json(force=True)
        before = GraphIR.from_dict(payload["before"])
        after = GraphIR.from_dict(payload["after"])
        result = compare_graphs(before, after)
        view = str(payload.get("view", "overlay"))
        return jsonify({**result.to_dict(), "view": view, "visual_graph": visualize_diff(before, after, view=view).to_dict()})

    return app


def _validate_json_depth(value: Any, *, maximum: int = 80) -> None:
    stack = [(value, 0)]
    while stack:
        current, depth = stack.pop()
        if depth > maximum:
            raise ValidationError(
                f"JSON nesting exceeds the supported depth of {maximum}",
                hint="Flatten deeply nested metadata before importing.",
            )
        if isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, (list, tuple)):
            stack.extend((item, depth + 1) for item in current)


def _store_graph(store: dict[str, GraphIR], graph: GraphIR) -> str:
    digest = sha256()
    digest.update(f"{graph.ir_version}:{graph.name}:".encode("utf-8"))
    for node in graph.nodes:
        digest.update(f"n:{node.id}:{node.op_type};".encode("utf-8"))
    for edge in graph.edges:
        digest.update(f"e:{edge.id}:{edge.source}:{edge.target}:{edge.kind};".encode("utf-8"))
    graph_id = f"graph_{digest.hexdigest()[:20]}"
    store[graph_id] = graph
    return graph_id


def _resolve_graph(payload: dict[str, Any], store: dict[str, GraphIR]) -> GraphIR:
    if "graph" in payload and payload["graph"] is not None:
        supplied_data = payload["graph"]
        lazy_reference = isinstance(supplied_data, dict) and supplied_data.get("metadata", {}).get("lazy_reference")
        if lazy_reference and payload.get("graph_id"):
            graph = store.get(str(payload["graph_id"]))
            if graph is not None:
                merged = graph.to_dict()
                merged["constraints"] = supplied_data.get("constraints", [])
                merged["annotations"] = supplied_data.get("annotations", [])
                merged["analysis"] = {**merged.get("analysis", {}), **supplied_data.get("analysis", {})}
                merged["metadata"] = {
                    **merged.get("metadata", {}),
                    **{
                        key: value for key, value in supplied_data.get("metadata", {}).items()
                        if key not in {"lazy_reference", "source_node_count", "source_edge_count"}
                    },
                }
                return GraphIR.from_dict(merged)
        return GraphIR.from_dict(supplied_data)
    if payload.get("graph_id"):
        graph = store.get(str(payload["graph_id"]))
        if graph is None:
            raise ValidationError(
                f"Unknown graph_id {payload['graph_id']!r}",
                hint="Re-import the model or send the Graph IR in this request.",
            )
        return graph
    raise ValidationError("Request requires graph or graph_id")


def _cached_semantic_for(graph: GraphIR, graph_id: Any, cache: dict[str, Any]):
    key = str(graph_id) if graph_id else None
    semantic = cache.get(key) if key else None
    if semantic is not None:
        try:
            semantic.validate(graph)
        except ValidationError:
            if key:
                cache.pop(key, None)
            semantic = None
    return semantic


def _semantic_for(graph: GraphIR, graph_id: Any, cache: dict[str, Any]):
    key = str(graph_id) if graph_id else None
    semantic = _cached_semantic_for(graph, graph_id, cache)
    if semantic is None:
        semantic = derive_semantic_view(graph)
        if key:
            cache[key] = semantic
    return semantic


def _breadcrumbs(semantic, target: Any, level: str) -> list[dict[str, Any]]:
    entities = {entity.id: entity for entity in semantic.entities}
    current = entities.get(str(target)) if target else None
    if current is None:
        return [{"level": item, "label": item.title(), "active": item == level} for item in SEMANTIC_LEVELS]
    result: list[dict[str, Any]] = []
    while current:
        result.append({"id": current.id, "level": current.level, "label": current.name, "active": current.level == level})
        current = entities.get(current.parent_id or "")
    return list(reversed(result))


def _content_type(suffix: str) -> str:
    return {
        ".svg": "image/svg+xml", ".pdf": "application/pdf", ".png": "image/png",
        ".eps": "application/postscript", ".tex": "text/x-tex",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".html": "text/html", ".json": "application/json",
        ".gltf": "model/gltf+json", ".glb": "model/gltf-binary",
    }.get(suffix.lower(), "application/octet-stream")


def _graph_descriptor(graph: GraphIR) -> dict[str, Any]:
    return {
        "name": graph.name,
        "nodes": [], "edges": [], "subgraphs": [], "annotations": [], "constraints": [],
        "inputs": [], "outputs": [],
        "metadata": {
            **graph.metadata,
            "lazy_reference": True,
            "source_node_count": len(graph.nodes),
            "source_edge_count": len(graph.edges),
        },
        "analysis": dict(graph.analysis),
        "ir_version": graph.ir_version,
    }


def serve(initial_source: str | None = None, *, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    app = create_app(initial_source, service_host=host, service_port=port)
    if host not in {"127.0.0.1", "localhost", "::1"}:
        import sys

        print(
            "WARNING: NN_DaVinci is binding beyond localhost without authentication. "
            "Anyone on the reachable LAN may access the service; this is not a public-deployment security claim.",
            file=sys.stderr,
            flush=True,
        )
    if open_browser:
        threading.Timer(0.7, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    app.run(host=host, port=port, debug=False, use_reloader=False)


def _capabilities() -> dict[str, Any]:
    from .operators import OPERATOR_TYPES

    manager.discover()
    return {
        "adapters": registry.describe(), "plugins": manager.describe(),
        "themes": sorted(THEMES), "pages": sorted(PAGE_PRESETS),
        "theme_values": {name: {key: value for key, value in theme.items() if key in {
            "font_family", "font_size", "font_weight", "node_radius", "node_opacity",
            "background", "accent", "node_fill", "border", "edge", "edge_width",
            "edge_arrow", "edge_dash", "parameter_format", "flops_format", "shape_brackets",
        }} for name, theme in THEMES.items()},
        "layouts": sorted(LayoutEngine.available()),
        "operator_types": {key: dict(value) for key, value in sorted(OPERATOR_TYPES.items())},
        "exports": ["svg", "pdf", "tikz", "png", "eps", "pptx", "html", "json", "gltf", "glb"],
        "semantic_levels": list(SEMANTIC_LEVELS),
        "semantic_selection_levels": list(SEMANTIC_SELECTION_LEVELS),
        "semantic_views": list(VIEW_MODES),
        "lazy_canvas": {"maximum_visible_nodes": 500, "maximum_dom_objects": 2_000},
        "task_kinds": ["import", "analyze", "layout", "runtime", "export"],
        "paper_presets": sorted(PAPER_PRESETS),
        "paper_templates": PAPER_FIGURE_TEMPLATES,
        "figure_composer": {"version": "1.2", "panels": list("ABCDEFGH"), "formats": ["svg", "pdf", "tikz", "png", "eps", "pptx"], "arrangements": ["grid", "horizontal", "vertical", "free"]},
        "figure_studio": {
            "version": "1.0", "project_schema": "1.4", "figure_ir": "1.0",
            "panel_modes": ["schematic", "tensor-geometry", "mixed"],
            "maximum_panels": 8, "templates": template_catalog(),
            "exports": ["svg", "pdf", "tikz", "png", "eps", "pptx", "html"],
            "submission_package": True,
            "svg_roundtrip_metadata": "nndv-figure-svg-metadata-1",
        },
        "scene_studio": {
            "version": "1.0", "project_schema": "1.4", "scene_ir": "1.0",
            "architecture_families": list(ARCHITECTURE_FAMILIES),
            "projections": ["orthographic", "perspective"],
            "maximum_model_scene_objects": 250,
            "exports": ["svg", "pdf", "tikz", "png", "eps", "pptx", "html", "json", "gltf", "glb"],
            "cpu_projection": True, "picking": True, "editable_transforms": True,
        },
        "structure_lens": {
            "version": "1.0", "bounded_paths": True, "cancellable_client_requests": True,
            "operations": ["upstream", "downstream", "path", "pathway", "shape-timeline", "warnings", "overlay", "repeats", "unknown"],
        },
        "analysis": ["parameters", "flops", "tensor-shapes", "activation-memory", "depth", "receptive-field", "runtime", "gradients", "cam", "attention", "model-diff"],
    }


def _demo_graph() -> GraphIR:
    data = {
        "name": "NN_DaVinci Demo",
        "nodes": [
            {"name": "Image", "type": "Input", "category": "input", "outputs": [[1, 3, 224, 224]]},
            {"name": "Stem", "type": "Conv2D", "category": "convolution", "parameters": 9408, "inputs": [[1, 3, 224, 224]], "outputs": [[1, 64, 112, 112]], "attributes": {"kernel_size": [7, 7], "stride": 2}},
            {"name": "Residual A", "type": "ResidualBlock", "category": "convolution", "parameters": 73728, "inputs": [[1, 64, 56, 56]], "outputs": [[1, 64, 56, 56]], "tags": ["residual"]},
            {"name": "Attention", "type": "MultiHeadAttention", "category": "attention", "parameters": 16640, "inputs": [[1, 196, 64]], "outputs": [[1, 196, 64]]},
            {"name": "Classifier", "type": "Linear", "category": "linear", "parameters": 65000, "inputs": [[1, 64]], "outputs": [[1, 1000]]},
            {"name": "Prediction", "type": "Output", "category": "output", "inputs": [[1, 1000]]},
        ],
        "edges": [["Image", "Stem"], ["Stem", "Residual A"], ["Residual A", "Attention"], ["Attention", "Classifier"], ["Classifier", "Prediction"], ["Stem", "Attention"]],
        "groups": [{"name": "Backbone", "nodes": ["Stem", "Residual A", "Attention"]}],
    }
    return analyze_graph(registry.load(data, adapter="manual"))["graph"]
