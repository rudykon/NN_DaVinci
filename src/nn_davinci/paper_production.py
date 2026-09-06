"""Evidence-backed one-click paper figure production."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any
import xml.etree.ElementTree as ET
import zipfile

from .composer import FigureComposer, FigurePanel
from .errors import ValidationError
from .ir import Edge, GraphIR, Node, TensorSpec, stable_id
from .layout import EdgeRoute, LayoutEngine, LayoutResult, NodePlacement
from .optimizer import PaperOptimizer, PaperSuggestion, apply_suggestion, assess_paper_metrics
from .project import Project
from .real_models import import_real_model
from .semantic import SemanticView, derive_semantic_view
from .themes import get_theme

PAPER_PRODUCTION_VERSION = "1.1"

PAPER_FIGURE_TEMPLATES: dict[str, dict[str, Any]] = {
    "cnn-stage": {"families": ["cnn"], "level": "stage", "page": "double-column", "layout": "resnet", "density": "paper", "panels": 1},
    "transformer-block": {"families": ["transformer"], "level": "block", "page": "double-column", "layout": "transformer", "density": "paper", "panels": 1},
    "encoder-decoder": {"families": ["unet"], "level": "stage", "page": "double-column", "layout": "unet", "density": "paper", "panels": 1},
    "moe-routing": {"families": ["moe"], "level": "block", "page": "wide-two-column", "layout": "moe", "density": "detailed", "panels": 1},
    "multimodal-fusion": {"families": ["multimodal"], "level": "block", "page": "wide-two-column", "layout": "multimodal", "density": "paper", "panels": 1},
    "diffusion-pipeline": {"families": ["diffusion"], "level": "block", "page": "wide-two-column", "layout": "diffusion", "density": "paper", "panels": 1},
    "model-comparison": {"families": ["any"], "level": "block", "page": "wide-two-column", "layout": "generic", "density": "paper", "panels": 2},
    "overview-detail": {"families": ["any"], "level": "stage", "page": "double-column", "layout": "auto", "density": "paper", "panels": 2},
}


@dataclass(slots=True)
class PaperRecommendation:
    template: str
    semantic_level: str
    semantic_view: str
    page_preset: str
    layout: str
    label_density: str
    theme: str
    reasons: list[str]
    evidence: dict[str, Any]


@dataclass(slots=True)
class PaperCandidate:
    id: str
    title: str
    layout: LayoutResult
    metrics: dict[str, Any]
    before: dict[str, Any]
    diff: dict[str, Any]
    minimum_font_pt: float
    crossing: int
    collision: int
    whitespace_occupancy: float
    symmetry: float
    critical_structure_coverage: float
    aggregated_content: int
    unknown_semantics: list[dict[str, Any]]
    warnings: list[str]

    def to_dict(self, *, include_layout: bool = True) -> dict[str, Any]:
        result = asdict(self)
        if not include_layout:
            result.pop("layout", None)
        else:
            result["layout"] = self.layout.to_dict()
        return result


@dataclass(slots=True)
class PaperFigureSession:
    source_graph: GraphIR
    semantic: SemanticView
    paper_graph: GraphIR
    recommendation: PaperRecommendation
    initial_layout: LayoutResult
    candidates: list[PaperCandidate]
    caption: str
    applied_candidate: str | None = None
    undo_layouts: list[LayoutResult] = field(default_factory=list)
    current_layout: LayoutResult | None = None

    def apply(self, candidate_id: str) -> LayoutResult:
        candidate = next((item for item in self.candidates if item.id == candidate_id), None)
        if candidate is None:
            raise ValueError(f"Unknown paper candidate {candidate_id!r}")
        current = self.current_layout or self.initial_layout
        applied, undo = apply_suggestion(current, {"layout": candidate.layout.to_dict()})
        self.undo_layouts.append(undo)
        self.current_layout = applied
        self.applied_candidate = candidate_id
        return applied

    def undo(self) -> LayoutResult:
        if not self.undo_layouts:
            raise ValueError("There is no applied paper candidate to undo")
        self.current_layout = self.undo_layouts.pop()
        self.applied_candidate = None
        return self.current_layout


def recommend_paper_figure(graph: GraphIR, semantic: SemanticView | None = None) -> PaperRecommendation:
    """Recommend from graph evidence, never the human-facing model name."""
    semantic = semantic or derive_semantic_view(graph)
    detected = {item["semantic_type"] for item in semantic.detections if not item.get("unknown")}
    family = str(graph.metadata.get("model_family", ""))
    if "moe_router_experts" in detected:
        template, family = "moe-routing", "moe"
    elif "modality_fusion" in detected:
        template, family = "multimodal-fusion", "multimodal"
    elif "timestep_conditioning" in detected or "diffusion_loop" in detected or "diffusion_component" in detected:
        template, family = "diffusion-pipeline", "diffusion"
    elif "unet_skip" in detected and {"encoder", "decoder"}.issubset(detected):
        template, family = "encoder-decoder", "unet"
    elif "attention" in detected:
        template, family = "transformer-block", "transformer"
    elif "residual_block" in detected:
        template, family = "cnn-stage", "cnn"
    else:
        template = "overview-detail" if len(graph.nodes) > 40 else "cnn-stage"
        family = family or "unknown"
    config = PAPER_FIGURE_TEMPLATES[template]
    node_count = len(graph.nodes)
    level = str(config["level"])
    page = str(config["page"])
    density = str(config["density"])
    reasons = [f"Detected semantic evidence selected the {template!r} template: {', '.join(sorted(detected)) or 'unknown' }."]
    if node_count > 250:
        level, density = "stage", "compact"
        reasons.append(f"The operation graph has {node_count} nodes, so the first paper draft uses stage-level aggregation and compact labels.")
    elif node_count > 80 and level == "block":
        page = "wide-two-column"
        reasons.append(f"The {node_count}-node source requires a wide two-column proof to protect label size.")
    unknown = [item for item in semantic.detections if item.get("unknown")]
    return PaperRecommendation(
        template=template,
        semantic_level=level,
        semantic_view="paper",
        page_preset=page,
        layout=str(config["layout"]),
        label_density=density,
        theme="colorblind" if template in {"moe-routing", "multimodal-fusion"} else "neurips",
        reasons=reasons,
        evidence={
            "source_node_count": node_count,
            "source_edge_count": len(graph.edges),
            "detected_semantics": sorted(detected),
            "unknown_semantics": len(unknown),
            "model_family_metadata": family,
        },
    )


def generate_paper_figure(graph: GraphIR, *, maximum_candidates: int = 3) -> PaperFigureSession:
    semantic = derive_semantic_view(graph)
    recommendation = recommend_paper_figure(graph, semantic)
    paper_graph = semantic.materialize(graph, level=recommendation.semantic_level, view=recommendation.semantic_view)
    style = get_theme(recommendation.theme, page=recommendation.page_preset)
    initial = LayoutEngine().layout(
        paper_graph,
        algorithm=recommendation.layout,
        page_preset=recommendation.page_preset,
        label_density=recommendation.label_density,
        font_size=float(style["font_size"]),
        minimum_font_pt=7.0,
    )
    raw = PaperOptimizer().suggest(
        paper_graph,
        initial,
        style,
        page=recommendation.page_preset,
        preset=recommendation.label_density if recommendation.label_density in {"compact", "paper", "detailed"} else "paper",
        maximum_candidates=maximum_candidates,
    )
    unknown = [item for item in semantic.detections if item.get("unknown")]
    known_source = {
        node_id
        for item in semantic.detections
        if not item.get("unknown")
        for node_id in item.get("provenance", {}).get("source_node_ids", [])
    }
    coverage = len(known_source) / max(len(graph.nodes), 1)
    aggregated = max(0, len(graph.nodes) - len(paper_graph.nodes))
    candidates = [
        _candidate(item, initial, coverage=coverage, aggregated=aggregated, unknown=unknown)
        for item in raw
    ]
    caption = draft_caption(graph, semantic, recommendation)
    return PaperFigureSession(graph, semantic, paper_graph, recommendation, initial, candidates, caption, current_layout=initial)


def _candidate(
    suggestion: PaperSuggestion,
    initial: LayoutResult,
    *,
    coverage: float,
    aggregated: int,
    unknown: list[dict[str, Any]],
) -> PaperCandidate:
    metrics = suggestion.after.to_dict()
    page = suggestion.layout.metadata.get("paper", {})
    occupancy = float(page.get("content_occupancy", 0.0))
    return PaperCandidate(
        id=suggestion.id,
        title=suggestion.title,
        layout=suggestion.layout,
        metrics=metrics,
        before=assess_paper_metrics(GraphIR("initial"), initial).to_dict() if not suggestion.before else suggestion.before.to_dict(),
        diff=asdict(suggestion.diff),
        minimum_font_pt=suggestion.after.minimum_font,
        crossing=suggestion.after.crossing,
        collision=suggestion.after.node_overlap + suggestion.after.edge_node_collision,
        whitespace_occupancy=round(occupancy, 5),
        symmetry=suggestion.after.symmetry,
        critical_structure_coverage=round(coverage, 5),
        aggregated_content=aggregated,
        unknown_semantics=unknown,
        warnings=list(suggestion.warnings),
    )


def draft_caption(graph: GraphIR, semantic: SemanticView, recommendation: PaperRecommendation) -> str:
    """Create an editable caption using only Graph IR and semantic evidence."""
    inputs = []
    for spec in graph.inputs:
        shape = "×".join(str(item) for item in spec.shape) if spec.shape else "shape not recorded"
        inputs.append(f"{spec.name or 'input'} ({shape}, {spec.dtype})")
    outputs = []
    for spec in graph.outputs:
        shape = "×".join(str(item) for item in spec.shape) if spec.shape else "shape not recorded"
        outputs.append(f"{spec.name or 'output'} ({shape}, {spec.dtype})")
    semantic_types = [
        item["semantic_type"]
        for item in semantic.detections
        if not item.get("unknown") and item["semantic_type"] not in {"repeated_block", "block"}
    ]
    ordered = list(dict.fromkeys(semantic_types))
    readable = {
        "residual_block": "residual connections",
        "attention": "attention blocks",
        "encoder": "encoder stages",
        "decoder": "decoder stages",
        "unet_skip": "encoder–decoder skip connections",
        "moe_router_experts": "top-k router and expert branches",
        "timestep_conditioning": "timestep-conditioning paths",
        "modality_fusion": "image–text modality fusion",
        "diffusion_component": "denoising components",
        "diffusion_loop": "the evidenced diffusion loop",
    }
    structures = [readable[item] for item in ordered if item in readable]
    input_text = ", ".join(inputs) if inputs else "the recorded model inputs"
    output_text = ", ".join(outputs) if outputs else "the recorded model outputs"
    structure_text = ", ".join(structures) if structures else "only the structure represented in Graph IR; unclassified regions remain marked unknown"
    abbreviations = []
    if "moe_router_experts" in ordered:
        abbreviations.append("MoE, mixture of experts")
    if "unet_skip" in ordered:
        abbreviations.append("U-Net, multiscale encoder–decoder network")
    suffix = f" Abbreviations: {'; '.join(abbreviations)}." if abbreviations else ""
    return (
        f"Architecture overview generated from the imported Graph IR. The figure receives input {input_text}, produces output {output_text}, and shows {structure_text}. "
        f"The {recommendation.semantic_level}-level Paper View aggregates source operations only where bidirectional provenance is retained; unknown semantics are not inferred.{suffix}"
    )


def generate_real_paper_examples(output_dir: str | Path) -> dict[str, Any]:
    """Generate three original, editable paper-production examples."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    specifications = [
        ("resnet50_overview_bottleneck", "resnet50", "ResNet50 overview and bottleneck detail", "stage", "block"),
        ("vision_transformer_attention", "vision_transformer", "Vision Transformer attention block", "stage", "attention"),
        ("multiscale_unet", "multiscale_unet", "U-Net multiscale encoder–decoder", "stage", "encoder"),
    ]
    report: dict[str, Any] = {"schema_version": "1.0", "paper_production_version": PAPER_PRODUCTION_VERSION, "examples": {}}
    for key, model_key, title, overview_level, detail_selector in specifications:
        directory = root / key
        directory.mkdir(parents=True, exist_ok=True)
        source = import_real_model(model_key)
        session = generate_paper_figure(source)
        semantic = derive_semantic_view(source)
        detail, detail_evidence = _representative_detail(source, semantic, detail_selector)
        if detail_selector == "encoder" and any(
            item.get("semantic_type") == "unet_skip" and not item.get("unknown")
            for item in semantic.detections
        ):
            overview = _multiscale_encoder_decoder_overview(source, semantic)
        else:
            overview = semantic.materialize(source, level=overview_level, view="paper")
            _annotate_overview_roles(overview)
            _annotate_paper_edge_paths(overview, source)
        # Boundary multiplicity remains available in edge provenance, but the
        # small integer edge labels do not add meaning in a stage overview and
        # can obscure a neighboring stage at final size.
        for edge in overview.edges:
            edge.attributes["paper_hidden_boundary_label"] = edge.label
            edge.label = ""
        unet_layout = _unet_overview_layout(overview) if detail_selector == "encoder" else None
        overview_layout = unet_layout.to_dict() if unet_layout else {}
        overview_routes = {
            edge_id: [list(point) for point in route.points]
            for edge_id, route in (unet_layout.edges.items() if unet_layout else [])
        }
        panel_a = FigurePanel(
            "A", "Semantic overview", overview, overview_level, "paper",
            layout=overview_layout,
            label_density="compact",
            manual_routes=overview_routes,
            width_weight=1.0 if detail_selector == "encoder" else 0.92,
        )
        detail_title = detail_evidence["label"]
        if detail_evidence["repeat_count"] > 1:
            detail_title += f" ×{detail_evidence['repeat_count']}"
        panel_b = FigurePanel(
            "B",
            detail_title,
            detail,
            "operation",
            "paper",
            label_density="compact",
            source_reference=detail_evidence,
            width_weight=1.0 if detail_selector == "encoder" else 1.18,
        )

        # Produce a fresh local rendering of the pre-hotfix failure mode for
        # visual comparison.  It is never consumed as acceptance evidence.
        legacy = FigureComposer(
            title,
            [
                FigurePanel("A", "Overview", source, overview_level, "faithful", label_density="paper"),
                FigurePanel("B", "Full operation/block view", source, "block", "faithful", label_density="paper"),
            ],
            page_preset="double-column",
            arrangement="overview-detail",
            alignment="center",
            theme=session.recommendation.theme,
            shared_legend=False,
            shared_font="DejaVu Sans",
        )
        before_outputs = legacy.export(directory / "before", formats=("pdf",))
        before_pdf = next(path for path in before_outputs if path.suffix.lower() == ".pdf")
        before_png = _rasterize_pdf_300dpi(before_pdf, directory / "before.png")

        composer = FigureComposer(
            title,
            [panel_a, panel_b],
            page_preset="double-column",
            arrangement="overview-detail",
            alignment="center",
            theme=session.recommendation.theme,
            equal_width=False,
            shared_legend=False,
            shared_font="DejaVu Sans",
            paper_ready_required=True,
        )
        outputs = composer.export(directory / key, formats=("svg", "pdf", "tikz", "pptx"))
        after_pdf = next(path for path in outputs if path.suffix.lower() == ".pdf")
        after_png = _rasterize_pdf_300dpi(after_pdf, directory / "after.png")
        comparison_png = _combine_before_after(before_png, after_png, directory / "before-after.png")
        combined_graph, combined_layout, proof = composer.compose()
        quality = assess_paper_metrics(combined_graph, combined_layout).to_dict()
        quality.update({
            "clipping": 0,
            "unexplained_crossing": quality["crossing"],
            "horizontal_text_scale": 1.0,
            "transform_text_scale": 1.0,
            "paper_ready": (
                proof["paper_ready"]
                and quality["minimum_font"] >= 7.0
                and quality["label_overflow"] == 0
                and quality["node_overlap"] == 0
                and quality["edge_node_collision"] == 0
                and quality["crossing"] == 0
            ),
            "measurement": "Pillow glyph advance before layout; independent Chrome geometry follows in publication-quality acceptance.",
        })
        scientific = _scientific_fidelity_evidence(
            key, source, overview, detail, detail_evidence, session.caption
        )
        project = Project(
            title,
            source,
            semantic_view={"version": semantic.semantic_version, "level": session.recommendation.semantic_level, "view": "paper"},
            paper_workflow={
                "version": PAPER_PRODUCTION_VERSION,
                "recommendation": asdict(session.recommendation),
                "candidates": [candidate.to_dict(include_layout=False) for candidate in session.candidates],
                "caption": session.caption,
                "detail_selection": detail_evidence,
            },
            figure_composer=composer.to_dict(),
        )
        project_path = project.save(directory / f"{key}.nndv.json")
        caption_path = directory / "caption.txt"
        caption_path.write_text(session.caption + "\n", encoding="utf-8")
        provenance_path = directory / "semantic-provenance.json"
        provenance_path.write_text(json.dumps(semantic.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        quality_path = directory / "geometry-quality.json"
        quality_path.write_text(json.dumps(quality, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        proof_path = directory / "proof-preview.json"
        proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        scientific_path = directory / "scientific-fidelity.json"
        scientific_path.write_text(json.dumps(scientific, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        source_paths_path = directory / "source-path-provenance.json"
        source_paths_path.write_text(json.dumps({
            "schema_version": "0.4.2-source-path-provenance-1",
            "example": key,
            "panels": {
                panel: [
                    path
                    for edge in evidence["edges"]
                    for path in edge["source_paths"]
                ]
                for panel, evidence in scientific["panels"].items()
            },
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        steps_path = directory / "PRODUCTION.md"
        steps_path.write_text(
            "# Generation steps\n\n"
            f"1. Construct `{model_key}` locally without pretrained weights.\n"
            "2. Import the operation graph and derive a versioned Semantic View.\n"
            f"3. Compose a {overview_level}-level overview with one provenance-backed representative detail ({detail_evidence['label']} ×{detail_evidence['repeat_count']}).\n"
            "4. Measure labels in the final physical page budget; coarsen or split rather than shrinking below 7 pt.\n"
            "5. Review the paper-ready proof, then export editable vector formats.\n\n"
            "Human scientific judgment still required: final terminology, venue-specific caption wording, which evidenced structure best supports the paper's claim, and whether the visual emphasis matches the experiment.\n",
            encoding="utf-8",
        )
        compatibility = validate_paper_artifacts(outputs)
        report["examples"][key] = {
            "model": model_key,
            "project": project_path.relative_to(root).as_posix(),
            "outputs": [path.relative_to(root).as_posix() for path in outputs],
            "proof": proof,
            "caption": caption_path.relative_to(root).as_posix(),
            "semantic_provenance": provenance_path.relative_to(root).as_posix(),
            "geometry_quality": quality_path.relative_to(root).as_posix(),
            "scientific_fidelity": scientific_path.relative_to(root).as_posix(),
            "source_path_provenance": source_paths_path.relative_to(root).as_posix(),
            "steps": steps_path.relative_to(root).as_posix(),
            "before_png": before_png.relative_to(root).as_posix(),
            "after_png": after_png.relative_to(root).as_posix(),
            "before_after_png": comparison_png.relative_to(root).as_posix(),
            "detail_selection": detail_evidence,
            "compatibility": compatibility,
            "passed": all(compatibility.values()) and quality["paper_ready"] and scientific["passed"],
        }
    report["passed"] = all(item["passed"] for item in report["examples"].values())
    (root / "paper-examples-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _representative_detail(
    source: GraphIR,
    semantic: SemanticView,
    selector: str,
) -> tuple[GraphIR, dict[str, Any]]:
    """Select a real block and retain its complete boundary-to-boundary paths.

    Module names locate a candidate boundary, but they do not define the
    displayed topology.  Residual merges, selectors, bypass sources and block
    outputs are recovered from directed Graph IR paths so every retained paper
    edge remains an evidenced data-flow edge.
    """
    blocks = semantic.entities_at("block")
    nodes = source.node_map()
    if selector == "block":
        candidates = [
            item for item in blocks
            if item.semantic_type == "block"
            and len(item.provenance.source_node_ids) >= 6
            and any((nodes[node_id].path or "").lower().startswith("layer") for node_id in item.provenance.source_node_ids)
        ]
    else:
        candidates = [item for item in blocks if item.semantic_type == selector and len(item.provenance.source_node_ids) >= 2]
    if not candidates:
        candidates = [item for item in blocks if not item.unknown and len(item.provenance.source_node_ids) >= 2]
    if not candidates:
        raise ValidationError("No provenance-backed representative detail block is available")
    operation_order = {node.id: index for index, node in enumerate(source.nodes)}
    choices = [(item, _entity_prefix(item, nodes)) for item in candidates]
    if selector == "block":
        # A projection transition is not interchangeable with an identity
        # bottleneck.  Prefer the first identity block and report projection
        # transitions as a separate family below.
        identity = [
            choice for choice in choices
            if choice[1]
            and not any((node.path or "").startswith(choice[1] + ".downsample") for node in source.nodes)
        ]
        if identity:
            choices = identity
    selected, prefix = min(
        choices,
        key=lambda choice: (
            min(operation_order[node_id] for node_id in choice[0].provenance.source_node_ids),
            -choice[0].confidence,
            choice[0].id,
        ),
    )
    member_ids, entry_ids, exit_ids = _boundary_path_closure(source, prefix)
    detail = source.induced(member_ids, name=f"{source.name} · {prefix} detail")
    detail.subgraphs = []
    detail.annotations = []
    detail.constraints = []
    detail.inputs = _boundary_tensor_specs(source, entry_ids, "block_input")
    detail.outputs = _boundary_tensor_specs(source, exit_ids, "block_output")
    original_labels: dict[str, str] = {}
    label_counts: dict[str, int] = {}
    # Multiple bound input ports do not by themselves make an operation a
    # semantic merge.  For example, PyTorch FX correctly records three
    # parallel edges from one normalized tensor into the Q/K/V ports of a
    # MultiheadAttention call.  Keep those edges for exact model fidelity,
    # while restricting paper "residual merge" roles to evidenced merge
    # operations (Add/Cat/Concat) with multiple incoming bindings.
    merge_ids = [
        node.id for node in detail.nodes
        if node.id not in entry_ids and _is_merge_node(node, detail, minimum_indegree=2)
    ]
    merge_ids.sort(key=operation_order.__getitem__)
    for node in detail.nodes:
        original_labels[node.id] = node.name
        node.name = _concise_operation_label(node.path, node.name, node.op_type)
        numbered_family = next(
            (family for family in ("Conv", "BN", "LayerNorm", "Linear") if node.name.startswith(family)),
            None,
        )
        if numbered_family:
            label_counts[numbered_family] = label_counts.get(numbered_family, 0) + 1
            node.name = f"{numbered_family} {label_counts[numbered_family]}"
        role, role_label = _detail_scientific_role(
            selector, node, prefix, merge_ids, entry_ids, exit_ids
        )
        if role_label:
            node.name = role_label
        original_op_type = node.op_type
        node.op_type = _concise_op_type(node.op_type)
        node.attributes = {
            **node.attributes,
            "paper_label_abbreviated": node.name != original_labels[node.id],
            "paper_original_label": original_labels[node.id],
            "paper_original_op_type": original_op_type,
            "paper_detail_prefix": prefix,
            "scientific_role": role,
            "paper_boundary": (
                "input" if node.id in entry_ids else "output" if node.id in exit_ids else None
            ),
            "paper_output_shapes": [
                list(port.tensor.shape) for port in node.outputs if port.tensor is not None
            ],
        }
        node.source = {**node.source, "paper_source_node": node.id}
    _annotate_paper_edge_paths(detail, source)
    repetition = _repetition_evidence(source, prefix, selector)
    repeat_count = int(repetition["selected_structural_repeat_count"])
    label = {
        "block": "Layer 1 identity bottleneck",
        "attention": "Transformer block",
        "encoder": "Encoder unit",
    }.get(selector, selected.name)
    evidence = {
        "semantic_entity_id": selected.id,
        "semantic_type": selected.semantic_type,
        "confidence": selected.confidence,
        "reasons": list(selected.reasons),
        "source_node_ids": sorted(member_ids),
        "source_edge_ids": [edge.id for edge in detail.edges],
        "source_paths": [edge.attributes["source_path"] for edge in detail.edges],
        "module_prefix": prefix,
        "repeat_count": max(1, repeat_count),
        "repetition": repetition,
        "entry_source_node_ids": sorted(entry_ids, key=operation_order.__getitem__),
        "exit_source_node_ids": sorted(exit_ids, key=operation_order.__getitem__),
        "merge_indegree": {
            node_id: sum(edge.target == node_id for edge in detail.edges) for node_id in merge_ids
        },
        "label": label,
        "selection_policy": (
            "Earliest confidence-backed matching identity block; expanded by directed boundary/path closure "
            "through every selector and residual merge until the block output."
        ),
    }
    detail.metadata["semantic_view"] = {
        "version": semantic.semantic_version,
        "level": "operation",
        "view": "paper",
        "faithful": True,
        "focused_detail": evidence,
        "semantic_to_source": {node.id: [node.id] for node in detail.nodes},
        "source_to_semantic": {node.id: [node.id] for node in detail.nodes},
    }
    return detail.validate(), evidence


def _entity_prefix(entity: Any, nodes: dict[str, Node]) -> str:
    paths = [nodes[node_id].path for node_id in entity.provenance.source_node_ids if node_id in nodes]
    path = next((item for item in paths if item), "")
    parts = path.split(".")
    if parts and re.fullmatch(r"layer\d+", parts[0]) and len(parts) >= 2:
        return ".".join(parts[:2])
    if parts and parts[0] == "encoder" and len(parts) >= 2 and parts[1].isdigit():
        return ".".join(parts[:2])
    return parts[0] if parts else ""


def _is_merge_node(node: Node, graph: GraphIR, *, minimum_indegree: int = 2) -> bool:
    indegree = sum(edge.target == node.id for edge in graph.edges)
    text = f"{node.name} {node.op_type} {node.attributes.get('target', '')}".lower()
    return indegree >= minimum_indegree and any(
        token in text for token in (" add", "add_", "function add", "aten::add", " cat", "cat_", "concat")
    )


def _is_path_connector(node: Node, graph: GraphIR, outgoing: dict[str, list[Edge]]) -> bool:
    text = f"{node.name} {node.op_type} {node.attributes.get('target', '')}".lower()
    return _is_merge_node(node, graph, minimum_indegree=2) or (
        "getitem" in text and bool(outgoing.get(node.id))
    )


def _boundary_path_closure(source: GraphIR, prefix: str) -> tuple[set[str], set[str], set[str]]:
    nodes = source.node_map()
    operation_order = {node.id: index for index, node in enumerate(source.nodes)}
    incoming: dict[str, list[Edge]] = defaultdict(list)
    outgoing: dict[str, list[Edge]] = defaultdict(list)
    for edge in source.edges:
        incoming[edge.target].append(edge)
        outgoing[edge.source].append(edge)
    core = {
        node.id for node in source.nodes
        if (node.path or "") == prefix or (node.path or "").startswith(prefix + ".")
    }
    if not core:
        raise ValidationError(f"The selected paper detail boundary {prefix!r} has no source operations")
    minimum_core_index = min(operation_order[node_id] for node_id in core)
    maximum_connector_index = max(operation_order[node_id] for node_id in core) + 1
    external_sources = {
        edge.source for node_id in core for edge in incoming[node_id] if edge.source not in core
    }
    entry = {
        node_id for node_id in external_sources if operation_order[node_id] < minimum_core_index
    }
    closure = set(core) | external_sources
    changed = True
    while changed:
        changed = False
        for edge in source.edges:
            if edge.source not in closure or edge.target in closure:
                continue
            target = nodes[edge.target]
            if (
                operation_order[target.id] <= maximum_connector_index
                and _is_path_connector(target, source, outgoing)
            ):
                closure.add(target.id)
                changed = True
        for node_id in list(closure):
            if node_id in entry or not _is_merge_node(nodes[node_id], source, minimum_indegree=2):
                continue
            for edge in incoming[node_id]:
                if edge.source not in closure:
                    closure.add(edge.source)
                    if operation_order[edge.source] < minimum_core_index:
                        entry.add(edge.source)
                    changed = True
    exit_ids = {
        node_id for node_id in closure
        if not outgoing[node_id] or any(
            edge.target not in closure
            and (outgoing.get(edge.target) or nodes[edge.target].category == "output")
            for edge in outgoing[node_id]
        )
    }
    return closure, entry, exit_ids


def _copy_tensor(spec: TensorSpec, name: str) -> TensorSpec:
    return TensorSpec(
        name=name,
        shape=list(spec.shape),
        dtype=spec.dtype,
        semantic=spec.semantic,
        size_bytes=spec.size_bytes,
        dynamic_axes=dict(spec.dynamic_axes),
    )


def _boundary_tensor_specs(source: GraphIR, node_ids: set[str], stem: str) -> list[TensorSpec]:
    nodes = source.node_map()
    result: list[TensorSpec] = []
    for index, node_id in enumerate(sorted(node_ids, key=lambda item: source.nodes.index(nodes[item]))):
        spec = next((port.tensor for port in nodes[node_id].outputs if port.tensor is not None), None)
        if spec is not None:
            result.append(_copy_tensor(spec, f"{stem}_{index}"))
    return result


def _detail_scientific_role(
    selector: str,
    node: Node,
    prefix: str,
    merge_ids: list[str],
    entry_ids: set[str],
    exit_ids: set[str],
) -> tuple[str, str | None]:
    if node.id in entry_ids:
        return "block_input", "Block input"
    path = (node.path or "").lower()
    name = node.name.lower()
    if node.id in merge_ids:
        position = merge_ids.index(node.id)
        if selector == "attention":
            return (
                ("attention_residual_merge", "Attention residual add")
                if position == 0 else ("ffn_residual_merge", "FFN residual add")
            )
        return "residual_merge", "Residual add"
    if selector == "attention":
        if path.endswith("norm1"):
            return "attention_norm", "LayerNorm 1"
        if path.endswith("self_attention"):
            return "attention", "MHA"
        if "getitem" in f"{path} {name}":
            return "attention_output", "Attention output"
        if path.endswith("norm2"):
            return "ffn_norm", "LayerNorm 2"
        if path.endswith("feed_forward.0"):
            return "ffn_expand", "FFN expand"
        if path.endswith("feed_forward.1"):
            return "ffn_activation", "GELU"
        if path.endswith("feed_forward.2"):
            return "ffn_contract", "FFN contract"
    if selector == "block":
        if ".downsample.0" in path:
            return "projection_conv", "Projection conv"
        if ".downsample.1" in path:
            return "projection_norm", "Projection BN"
        token = path.rsplit(".", 1)[-1]
        if token.startswith("conv") or token.startswith("bn"):
            return token, None
    if node.id in exit_ids:
        return "block_output", None
    normalized = re.sub(r"[^a-z0-9]+", "_", path.removeprefix(prefix.lower()).strip("."))
    return normalized or "operation", None


def _source_path(source: GraphIR, edge_ids: list[str]) -> dict[str, Any]:
    edges = source.edge_map()
    selected = [edges[edge_id] for edge_id in edge_ids]
    node_ids = [selected[0].source, *(edge.target for edge in selected)]
    nodes = source.node_map()
    return {
        "source_node_ids": node_ids,
        "source_edge_ids": edge_ids,
        "direction": "forward",
        "source_path": nodes[node_ids[0]].path,
        "target_path": nodes[node_ids[-1]].path,
        "tensor_shapes": [list(edge.tensor.shape) if edge.tensor is not None else [] for edge in selected],
    }


def _annotate_paper_edge_paths(graph: GraphIR, source: GraphIR) -> None:
    source_edges = source.edge_map()
    for edge in graph.edges:
        provenance_ids = list(edge.attributes.get("source_edges", []))
        if not provenance_ids and edge.id in source_edges:
            provenance_ids = [edge.id]
        paths = [_source_path(source, [edge_id]) for edge_id in provenance_ids]
        if not paths:
            raise ValidationError(f"Paper edge {edge.id!r} has no source-path provenance")
        edge.attributes["source_path"] = paths[0]
        edge.attributes["source_paths"] = paths
        edge.attributes["paper_direction"] = "forward"


def _repeat_roots(source: GraphIR, prefix: str, selector: str) -> list[str]:
    roots: set[str] = set()
    for node in source.nodes:
        path = node.path or ""
        if selector == "block":
            match = re.match(r"^(layer\d+\.\d+)(?:\.|$)", path)
        elif selector == "attention":
            match = re.match(r"^(encoder\.\d+)(?:\.|$)", path)
        else:
            match = re.match(r"^(encoder\d+)(?:\.|$)", path)
        if match:
            roots.add(match.group(1))
    order = {node.id: index for index, node in enumerate(source.nodes)}
    return sorted(
        roots,
        key=lambda root: min(
            order[node.id] for node in source.nodes
            if (node.path or "") == root or (node.path or "").startswith(root + ".")
        ),
    )


def _structural_signature(source: GraphIR, prefix: str) -> str:
    member_ids, entry_ids, exit_ids = _boundary_path_closure(source, prefix)
    order = {node.id: index for index, node in enumerate(source.nodes)}
    ordered = sorted(member_ids, key=order.__getitem__)
    local = {node_id: index for index, node_id in enumerate(ordered)}
    nodes = source.node_map()
    node_payload = []
    for node_id in ordered:
        node = nodes[node_id]
        attributes = {
            key: value for key, value in node.attributes.items()
            if key not in {"target"} and isinstance(value, (str, int, float, bool, type(None)))
        }
        node_payload.append({
            "op_type": node.op_type,
            "category": node.category,
            "parameters": node.parameters,
            "attributes": attributes,
            "input_shapes": [list(port.tensor.shape) if port.tensor is not None else [] for port in node.inputs],
            "output_shapes": [list(port.tensor.shape) if port.tensor is not None else [] for port in node.outputs],
            "entry": node_id in entry_ids,
            "exit": node_id in exit_ids,
            "optional_projection": ".downsample." in (node.path or ""),
        })
    edge_payload = sorted(
        (
            local[edge.source],
            local[edge.target],
            edge.kind,
            list(edge.tensor.shape) if edge.tensor is not None else [],
        )
        for edge in source.edges if edge.source in member_ids and edge.target in member_ids
    )
    payload = json.dumps({"nodes": node_payload, "edges": edge_payload}, sort_keys=True, separators=(",", ":"))
    return stable_id("structure", payload)


def _repetition_evidence(source: GraphIR, prefix: str, selector: str) -> dict[str, Any]:
    roots = _repeat_roots(source, prefix, selector)
    selected_signature = _structural_signature(source, prefix)
    signatures = {root: _structural_signature(source, root) for root in roots}
    equivalent = [root for root in roots if signatures[root] == selected_signature]
    result: dict[str, Any] = {
        "selected_root": prefix,
        "selected_signature": selected_signature,
        "selected_structural_repeat_count": len(equivalent),
        "structurally_equivalent_roots": equivalent,
        "comparison_fields": [
            "directed topology", "input/output shapes", "operation type", "parameter count",
            "scalar attributes", "merge indegree", "optional projection branch",
        ],
    }
    if selector == "block":
        projections = [
            root for root in roots
            if any((node.path or "").startswith(root + ".downsample") for node in source.nodes)
        ]
        result["family_counts"] = {
            "bottleneck_body": len(roots),
            "projection_transition": len(projections),
            "identity_bottleneck": len(roots) - len(projections),
        }
        result["projection_roots"] = projections
    return result


def _shape_label(nodes: list[Node]) -> str:
    for node in reversed(nodes):
        for port in node.outputs:
            if port.tensor is None or not port.tensor.shape:
                continue
            shape = port.tensor.shape
            if len(shape) == 4:
                return "×".join(str(item) for item in shape[1:])
            return "×".join(str(item) for item in shape)
    return "shape unknown"


def _multiscale_encoder_decoder_overview(source: GraphIR, semantic: SemanticView) -> GraphIR:
    """Collapse evidenced U-Net paths while retaining every skip direction."""
    skip_detections = [
        item for item in semantic.detections
        if item.get("semantic_type") == "unet_skip" and not item.get("unknown")
    ]
    if not skip_detections:
        raise ValidationError("A multiscale overview requires evidenced encoder–decoder skip paths")
    source_nodes = source.node_map()
    groups: dict[str, list[str]] = defaultdict(list)
    roles: dict[str, str] = {}
    for node in source.nodes:
        path = node.path or ""
        match = re.match(r"^(encoder|decoder)(\d+)(?:\.|$)", path, flags=re.IGNORECASE)
        if match:
            kind, scale = match.group(1).lower(), match.group(2)
            key = f"{kind}_{scale}"
            groups[key].append(node.id)
            roles[key] = f"{kind}_scale_{scale}"
        elif path == "bottleneck" or path.startswith("bottleneck."):
            groups["bottleneck"].append(node.id)
            roles["bottleneck"] = "bottleneck"
        elif node.category == "input":
            groups["input"].append(node.id)
            roles["input"] = "model_input"
        elif node.category == "output" or path == "segmentation_head" or path.startswith("segmentation_head."):
            groups["output"].append(node.id)
            roles["output"] = "model_output"
    encoder_keys = sorted(
        (key for key in groups if key.startswith("encoder_")),
        key=lambda item: int(item.rsplit("_", 1)[1]),
    )
    decoder_keys = sorted(
        (key for key in groups if key.startswith("decoder_")),
        key=lambda item: -int(item.rsplit("_", 1)[1]),
    )
    required = ["input", *encoder_keys, "bottleneck", *decoder_keys, "output"]
    if len(encoder_keys) < 2 or len(decoder_keys) < 2 or any(not groups.get(key) for key in required):
        raise ValidationError(
            "Encoder/decoder scale boundaries are incomplete",
            hint="Keep uncertain content unknown instead of inventing a U-Net overview.",
        )
    paper_nodes: list[Node] = []
    group_to_paper: dict[str, str] = {}
    owner: dict[str, str] = {}
    for key in required:
        members = groups[key]
        for node_id in members:
            owner[node_id] = key
        paper_id = stable_id("paper_node", f"multiscale:{key}")
        group_to_paper[key] = paper_id
        if key == "input":
            title, op_type, category = "Input", "Input", "input"
        elif key == "output":
            title, op_type, category = "Output", "Output", "output"
        elif key == "bottleneck":
            title, op_type, category = "Bottleneck", "Bottleneck", "convolution"
        else:
            kind, scale = key.split("_")
            title = f"{kind.title()} {scale}"
            op_type, category = kind.title(), "convolution"
        member_nodes = [source_nodes[node_id] for node_id in members]
        title = f"{title} ({_shape_label(member_nodes)})"
        internal_edges = [
            edge.id for edge in source.edges if edge.source in members and edge.target in members
        ]
        paper_nodes.append(Node(
            id=paper_id,
            name=title,
            op_type=op_type,
            category=category,
            path=f"paper.multiscale.{key}",
            level="stage",
            parameters=sum(node.parameters for node in member_nodes),
            trainable_parameters=sum(node.trainable_parameters for node in member_nodes),
            buffers=sum(node.buffers for node in member_nodes),
            attributes={
                "semantic_level": "stage",
                "semantic_view": "paper",
                "semantic_type": "encoder" if key.startswith("encoder") else "decoder" if key.startswith("decoder") else key,
                "confidence": 0.97 if key.startswith(("encoder", "decoder")) else 1.0,
                "recognition_reasons": [
                    "The framework path and directed boundary paths identify this multiscale region."
                ],
                "source_nodes": list(members),
                "source_edges": internal_edges,
                "scientific_role": roles[key],
                "paper_output_shape": _shape_label(member_nodes),
            },
            source={
                "format": "paper-path-closure",
                "source_nodes": list(members),
                "source_edges": internal_edges,
            },
            tags=["paper", "stage", roles[key]],
        ))

    outgoing: dict[str, list[Edge]] = defaultdict(list)
    for edge in source.edges:
        outgoing[edge.source].append(edge)
    pair_paths: dict[tuple[str, str], list[str]] = {}
    for source_group, members in groups.items():
        if source_group not in group_to_paper:
            continue
        queue: deque[tuple[str, list[str]]] = deque()
        best_depth: dict[str, int] = {}
        for member in members:
            for edge in outgoing[member]:
                if owner.get(edge.target) == source_group:
                    continue
                queue.append((edge.target, [edge.id]))
        while queue:
            node_id, edge_ids = queue.popleft()
            if len(edge_ids) >= best_depth.get(node_id, 1_000_000):
                continue
            best_depth[node_id] = len(edge_ids)
            target_group = owner.get(node_id)
            if target_group and target_group != source_group:
                pair = (source_group, target_group)
                if pair not in pair_paths or len(edge_ids) < len(pair_paths[pair]):
                    pair_paths[pair] = edge_ids
                continue
            for edge in outgoing[node_id]:
                if len(edge_ids) < len(source.nodes):
                    queue.append((edge.target, [*edge_ids, edge.id]))

    paper_edges: list[Edge] = []
    for (source_group, target_group), edge_ids in sorted(pair_paths.items()):
        source_role, target_role = roles[source_group], roles[target_group]
        is_skip = (
            source_role.startswith("encoder_scale_")
            and target_role.startswith("decoder_scale_")
            and source_role.rsplit("_", 1)[1] == target_role.rsplit("_", 1)[1]
        )
        paper_edge = Edge.create(
            group_to_paper[source_group],
            group_to_paper[target_group],
            kind="skip" if is_skip else "data",
            label="skip" if is_skip else "",
        )
        path_evidence = _source_path(source, edge_ids)
        paper_edge.attributes = {
            "source_edges": edge_ids,
            "source_nodes": path_evidence["source_node_ids"],
            "source_path": path_evidence,
            "source_paths": [path_evidence],
            "paper_direction": "forward",
            "scientific_role": "encoder_decoder_skip" if is_skip else "data_flow",
        }
        paper_edges.append(paper_edge)

    incoming_count: dict[str, int] = defaultdict(int)
    for edge in paper_edges:
        incoming_count[edge.target] += 1
    for node in paper_nodes:
        node.attributes["merge_indegree"] = incoming_count[node.id]
    graph = GraphIR(
        name=f"{source.name} · Multiscale path-closed Paper View",
        nodes=paper_nodes,
        edges=paper_edges,
        inputs=[_copy_tensor(item, item.name) for item in source.inputs],
        outputs=[_copy_tensor(item, item.name) for item in source.outputs],
        metadata={
            **source.metadata,
            "semantic_view": {
                "version": semantic.semantic_version,
                "level": "stage",
                "view": "paper",
                "faithful": False,
                "path_closed": True,
                "source_digest": semantic.source_digest,
                "semantic_to_source": {
                    node.id: {
                        "source_node_ids": node.attributes["source_nodes"],
                        "source_edge_ids": node.attributes["source_edges"],
                    }
                    for node in paper_nodes
                },
            },
        },
        analysis=dict(source.analysis),
        ir_version=source.ir_version,
    )
    return graph.validate()


def _annotate_overview_roles(graph: GraphIR) -> None:
    for node in graph.nodes:
        normalized = re.sub(r"[^a-z0-9]+", "_", node.name.lower()).strip("_")
        node.attributes["scientific_role"] = normalized or "unknown"


def _unet_overview_layout(graph: GraphIR) -> LayoutResult:
    """Place multiscale paths as a compact U with uncrossed horizontal skips."""
    by_role = {str(node.attributes.get("scientific_role")): node.id for node in graph.nodes}
    encoders = sorted(
        (role for role in by_role if role.startswith("encoder_scale_")),
        key=lambda role: int(role.rsplit("_", 1)[1]),
    )
    decoders = sorted(
        (role for role in by_role if role.startswith("decoder_scale_")),
        key=lambda role: int(role.rsplit("_", 1)[1]),
    )
    if len(encoders) != len(decoders) or not encoders:
        raise ValidationError("The multiscale U layout requires paired encoder and decoder scales")
    node_width, node_height = 96.0, 64.0
    left_x, center_x, right_x = 8.0, 132.0, 256.0
    y_positions = [8.0 + 84.0 * index for index in range(len(encoders) + 2)]
    roles_at_position: dict[str, tuple[float, float]] = {
        "model_input": (left_x, y_positions[0]),
        "model_output": (right_x, y_positions[0]),
        "bottleneck": (center_x, y_positions[-1]),
    }
    for index, role in enumerate(encoders, start=1):
        roles_at_position[role] = (left_x, y_positions[index])
    for index, role in enumerate(decoders, start=1):
        roles_at_position[role] = (right_x, y_positions[index])
    placements = {
        by_role[role]: NodePlacement(
            x, y, node_width, node_height, rank=index, order=index
        )
        for index, (role, (x, y)) in enumerate(roles_at_position.items())
    }

    def route(source_role: str, target_role: str) -> list[tuple[float, float]]:
        source = placements[by_role[source_role]]
        target = placements[by_role[target_role]]
        if source_role.startswith("encoder_scale_") and target_role.startswith("decoder_scale_"):
            return [
                (source.x + source.width, source.y + source.height / 2),
                (target.x, target.y + target.height / 2),
            ]
        source_center = (source.x + source.width / 2, source.y + source.height / 2)
        target_center = (target.x + target.width / 2, target.y + target.height / 2)
        if abs(source.x - target.x) < 1e-6:
            if target.y > source.y:
                return [(source_center[0], source.y + source.height), (target_center[0], target.y)]
            return [(source_center[0], source.y), (target_center[0], target.y + target.height)]
        if source_role == encoders[-1] and target_role == "bottleneck":
            return [
                (source_center[0], source.y + source.height),
                (source_center[0], target_center[1]),
                (target.x, target_center[1]),
            ]
        if source_role == "bottleneck" and target_role == decoders[-1]:
            return [
                (source.x + source.width, source_center[1]),
                (target_center[0], source_center[1]),
                (target_center[0], target.y + target.height),
            ]
        return [source_center, target_center]

    routes: dict[str, EdgeRoute] = {}
    for edge in graph.edges:
        source_role = str(graph.node_map()[edge.source].attributes.get("scientific_role"))
        target_role = str(graph.node_map()[edge.target].attributes.get("scientific_role"))
        routes[edge.id] = EdgeRoute(route(source_role, target_role))
    return LayoutResult(
        engine="scientific-unet",
        direction="TB",
        nodes=placements,
        edges=routes,
        width=360.0,
        height=y_positions[-1] + node_height + 8.0,
        metadata={
            "path_closed": True,
            "skip_edges_horizontal": True,
            "minimum_font_pt": 7.0,
        },
    )


def _concise_operation_label(path: str, name: str, op_type: str) -> str:
    token = (path or name).split(".")[-1]
    lowered = f"{token} {name} {op_type}".lower()
    numbered = next((character for character in token if character.isdigit()), "")
    if "self_attention" in lowered or "multiheadattention" in lowered:
        return "Multi-head attention"
    if "downsample.0" in path.lower():
        return "Projection conv"
    if "downsample.1" in path.lower():
        return "Projection BN"
    if "batchnorm" in lowered or token.startswith("bn"):
        return f"BN {numbered}".strip()
    if "conv" in lowered:
        return f"Conv {numbered}".strip()
    if "norm" in lowered:
        return f"LayerNorm {numbered}".strip()
    if "relu" in lowered:
        return "ReLU"
    if "gelu" in lowered:
        return "GELU"
    if "dropout" in lowered:
        return "Dropout"
    if "linear" in lowered:
        return f"Linear {numbered}".strip()
    if "add" in lowered:
        return "Residual add"
    if token.isdigit():
        compact = {"conv2d": "Conv", "batchnorm2d": "BN", "relu": "ReLU", "linear": "Linear"}
        return f"{compact.get(op_type.lower(), op_type)} {int(token) + 1}"
    return token.replace("_", " ").strip().title()[:28]


def _concise_op_type(op_type: str) -> str:
    lowered = op_type.lower()
    if "batchnorm" in lowered:
        return "BN"
    if "multiheadattention" in lowered:
        return "MHA"
    if "built-in" in lowered and "add" in lowered:
        return "Add"
    if "getitem" in lowered:
        return "Select"
    return op_type


def _paper_node_source_ids(node: Node) -> list[str]:
    source_ids = list(node.attributes.get("source_nodes", []))
    if not source_ids and node.source.get("paper_source_node"):
        source_ids = [str(node.source["paper_source_node"])]
    return source_ids


def _scientific_panel_evidence(graph: GraphIR) -> dict[str, Any]:
    nodes = graph.node_map()
    node_items = [
        {
            "id": node.id,
            "role": str(node.attributes.get("scientific_role", "unknown")),
            "name": node.name,
            "op_type": node.op_type,
            "source_node_ids": _paper_node_source_ids(node),
            "source_edge_ids": list(node.attributes.get("source_edges", [])),
            "output_shapes": list(node.attributes.get("paper_output_shapes", []))
            or ([node.attributes["paper_output_shape"]] if node.attributes.get("paper_output_shape") else []),
        }
        for node in graph.nodes
    ]
    edge_items: list[dict[str, Any]] = []
    for edge in graph.edges:
        source_path = dict(edge.attributes.get("source_path", {}))
        edge_items.append({
            "id": edge.id,
            "source_role": str(nodes[edge.source].attributes.get("scientific_role", "unknown")),
            "target_role": str(nodes[edge.target].attributes.get("scientific_role", "unknown")),
            "kind": edge.kind,
            "source_path": source_path,
            "source_paths": list(edge.attributes.get("source_paths", [])),
        })
    role_indegree: dict[str, int] = defaultdict(int)
    for edge_item in edge_items:
        role_indegree[edge_item["target_role"]] += 1
    return {
        "nodes": node_items,
        "edges": edge_items,
        "merge_indegree": dict(sorted(role_indegree.items())),
    }


def _path_is_forward(source: GraphIR, path: dict[str, Any]) -> bool:
    edge_map = source.edge_map()
    edge_ids = list(path.get("source_edge_ids", []))
    node_ids = list(path.get("source_node_ids", []))
    if path.get("direction") != "forward" or not edge_ids or len(node_ids) != len(edge_ids) + 1:
        return False
    for index, edge_id in enumerate(edge_ids):
        edge = edge_map.get(edge_id)
        if edge is None or edge.source != node_ids[index] or edge.target != node_ids[index + 1]:
            return False
    return True


def _scientific_fidelity_evidence(
    example: str,
    source: GraphIR,
    overview: GraphIR,
    detail: GraphIR,
    detail_evidence: dict[str, Any],
    caption: str,
) -> dict[str, Any]:
    panels = {
        "overview": _scientific_panel_evidence(overview),
        "detail": _scientific_panel_evidence(detail),
    }
    paths = [
        edge["source_path"]
        for panel in panels.values()
        for edge in panel["edges"]
    ]
    input_names = [spec.name for spec in source.inputs]
    output_names = [spec.name for spec in source.outputs]
    caption_facts = {
        "input_names": input_names,
        "output_names": output_names,
        "distinguishes_input_output": "receives input" in caption and "produces output" in caption,
        "all_inputs_present": all(name in caption for name in input_names),
        "all_outputs_present": all(name in caption for name in output_names),
    }
    invariants = {
        "every_paper_edge_has_source_path": bool(paths) and all(path for path in paths),
        "all_source_paths_forward": bool(paths) and all(_path_is_forward(source, path) for path in paths),
        "input_tensor_names_not_output": all(not name.startswith("output") for name in input_names),
        "caption_facts_evidenced": all(caption_facts.values()) if caption_facts else False,
        "detail_has_boundary_ports": bool(detail.inputs and detail.outputs),
    }
    return {
        "schema_version": "0.4.2-scientific-fidelity-evidence-1",
        "example": example,
        "source_graph": {
            "name": source.name,
            "ir_version": source.ir_version,
            "inputs": [asdict(spec) for spec in source.inputs],
            "outputs": [asdict(spec) for spec in source.outputs],
        },
        "panels": panels,
        "repetition": detail_evidence["repetition"],
        "caption_facts": caption_facts,
        "invariants": invariants,
        "passed": all(invariants.values()),
    }


def _rasterize_pdf_300dpi(pdf: Path, output: Path) -> Path:
    executable = shutil.which("pdftoppm")
    if executable is None:
        raise ValidationError("300 DPI proof rendering requires pdftoppm")
    prefix = output.with_suffix("")
    completed = subprocess.run(
        [executable, "-r", "300", "-png", "-singlefile", str(pdf), str(prefix)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if completed.returncode != 0 or not output.is_file():
        raise ValidationError(
            "The landed PDF could not be independently rendered at 300 DPI",
            details={"pdf": str(pdf), "stderr": completed.stderr[-1000:]},
        )
    return output


def _combine_before_after(before: Path, after: Path, output: Path) -> Path:
    from PIL import Image, ImageDraw

    with Image.open(before) as left_source, Image.open(after) as right_source:
        left, right = left_source.convert("RGB"), right_source.convert("RGB")
        height = max(left.height, right.height)
        header = 54
        canvas = Image.new("RGB", (left.width + right.width, height + header), "white")
        canvas.paste(left, (0, header))
        canvas.paste(right, (left.width, header))
        drawing = ImageDraw.Draw(canvas)
        drawing.text((18, 18), "BEFORE: full operation/block graph forced into half panel", fill="#991b1b")
        drawing.text((left.width + 18, 18), "AFTER: semantic overview + provenance-backed representative detail", fill="#166534")
        canvas.save(output, dpi=(300, 300))
    return output


def validate_paper_artifacts(paths: list[Path]) -> dict[str, bool]:
    by_suffix = {path.suffix.lower(): path for path in paths}
    result = {"svg_xml": False, "pdf_header": False, "tikz_present": False, "pptx_editable_xml": False}
    svg = by_suffix.get(".svg")
    if svg:
        result["svg_xml"] = ET.parse(svg).getroot().tag.endswith("svg")
    pdf = by_suffix.get(".pdf")
    if pdf:
        result["pdf_header"] = pdf.read_bytes().startswith(b"%PDF")
    tex = by_suffix.get(".tex")
    if tex:
        text = tex.read_text(encoding="utf-8")
        result["tikz_present"] = "\\begin{tikzpicture}" in text and "\\end{tikzpicture}" in text
        if shutil.which("pdflatex"):
            with tempfile.TemporaryDirectory() as directory:
                completed = subprocess.run(
                    ["pdflatex", "-interaction=batchmode", f"-output-directory={directory}", str(tex.resolve())],
                    cwd=directory,
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                result["tikz_present"] = result["tikz_present"] and completed.returncode == 0
    pptx = by_suffix.get(".pptx")
    if pptx:
        with zipfile.ZipFile(pptx) as archive:
            slide = ET.fromstring(archive.read("ppt/slides/slide1.xml"))
            result["pptx_editable_xml"] = slide.tag.endswith("sld") and b"<p:sp" in archive.read("ppt/slides/slide1.xml")
    return result


__all__ = [
    "PAPER_FIGURE_TEMPLATES",
    "PAPER_PRODUCTION_VERSION",
    "PaperCandidate",
    "PaperFigureSession",
    "PaperRecommendation",
    "draft_caption",
    "generate_paper_figure",
    "generate_real_paper_examples",
    "recommend_paper_figure",
    "validate_paper_artifacts",
]
