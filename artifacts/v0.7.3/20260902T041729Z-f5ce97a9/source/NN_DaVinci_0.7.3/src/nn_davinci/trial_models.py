"""External-style, network-free model corpus for researcher workflow trials."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import gc
from pathlib import Path
import statistics
import time
from typing import Any, Callable

from .adapters.onnx import OnnxAdapter
from .adapters.pytorch import PyTorchAdapter
from .composer import FigureComposer, FigurePanel
from .errors import ValidationError
from .paper_production import generate_paper_figure
from .project import Project
from .semantic import derive_semantic_view
from .trial_cases import (
    make_custom_unknown,
    make_dynamic_branch,
    make_multi_io_onnx,
    make_shared_siamese,
    make_transformer_residual,
    make_unet_skip,
)

EXTERNAL_MODEL_CORPUS_VERSION = "0.5.0-external-models-1"
EXTERNAL_MODEL_CASE_KEYS = (
    "dynamic_pytorch",
    "onnx_multi_io",
    "shared_siamese",
    "transformer_residual",
    "unet_skip",
    "custom_unknown",
)


@dataclass(frozen=True, slots=True)
class ExternalModelSpec:
    key: str
    display_name: str
    framework: str
    coverage: tuple[str, ...]
    seed: int
    input_description: str
    factory: Callable[[], tuple[Any, Any]]
    expected_semantics: tuple[str, ...] = ()
    minimum_unknown: int = 0

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("factory")
        value["weights"] = "none downloaded"
        value["model_code_boundary"] = "standalone framework-only; no NN_DaVinci imports or recognizer tags"
        return value


def external_model_registry() -> dict[str, ExternalModelSpec]:
    return {
        "dynamic_pytorch": ExternalModelSpec(
            "dynamic_pytorch",
            "Dynamic PyTorch branch",
            "pytorch-runtime",
            ("dynamic-control-flow", "sampled-path-boundary"),
            5101,
            "image: float32[1,3,24,24]",
            make_dynamic_branch,
            minimum_unknown=1,
        ),
        "onnx_multi_io": ExternalModelSpec(
            "onnx_multi_io",
            "ONNX dynamic multi-input/output",
            "onnx",
            ("onnx", "dynamic-dimensions", "multiple-inputs", "multiple-outputs", "shared-initializer"),
            5106,
            "tokens: float32[batch,sequence,8]; mask: float32[batch,sequence,1]",
            make_multi_io_onnx,
            minimum_unknown=1,
        ),
        "shared_siamese": ExternalModelSpec(
            "shared_siamese",
            "Shared-weight Siamese network",
            "pytorch-fx",
            ("multiple-inputs", "multiple-outputs", "shared-module", "shared-parameters"),
            5102,
            "left/right: float32[2,16]",
            make_shared_siamese,
            minimum_unknown=1,
        ),
        "transformer_residual": ExternalModelSpec(
            "transformer_residual",
            "Transformer block with two residuals",
            "pytorch-fx",
            ("transformer", "attention-residual", "ffn-residual"),
            5103,
            "tokens: float32[1,12,48]",
            make_transformer_residual,
            expected_semantics=("attention", "residual_block"),
        ),
        "unet_skip": ExternalModelSpec(
            "unet_skip",
            "Two-scale U-Net with skips",
            "pytorch-fx",
            ("encoder", "decoder", "unet-skip", "merge"),
            5104,
            "image: float32[1,1,32,32]",
            make_unet_skip,
            expected_semantics=("encoder", "decoder", "unet_skip"),
        ),
        "custom_unknown": ExternalModelSpec(
            "custom_unknown",
            "Custom spectral gate",
            "pytorch-fx",
            ("custom-operator", "explicit-unknown"),
            5105,
            "signal: float32[3,20]",
            make_custom_unknown,
            minimum_unknown=1,
        ),
    }


def import_external_model(key: str) -> tuple[Any, ExternalModelSpec]:
    """Construct and import one independent case without paths or downloads."""
    try:
        spec = external_model_registry()[key]
    except KeyError as exc:
        raise ValidationError(
            f"Unknown researcher-trial model case {key!r}",
            hint=f"Choose one of: {', '.join(EXTERNAL_MODEL_CASE_KEYS)}.",
        ) from exc
    source, sample = spec.factory()
    if spec.framework == "onnx":
        graph = OnnxAdapter().load(source)
    else:
        graph = PyTorchAdapter().load(source, sample_input=sample, runtime_fallback=True)
    graph.metadata.update({
        "external_model_corpus_version": EXTERNAL_MODEL_CORPUS_VERSION,
        "external_trial_case": spec.key,
        "external_framework": spec.framework,
        "random_seed": spec.seed,
        "sample_input": spec.input_description,
        "weights": "random-local or initializer-only; none downloaded",
        "model_code_boundary": "standalone framework-only; no NN_DaVinci imports or recognizer tags",
    })
    return graph.validate(), spec


def external_model_case_manifest() -> dict[str, Any]:
    return {
        "schema_version": EXTERNAL_MODEL_CORPUS_VERSION,
        "case_count": len(EXTERNAL_MODEL_CASE_KEYS),
        "cases": [external_model_registry()[key].public_dict() for key in EXTERNAL_MODEL_CASE_KEYS],
        "network_required": False,
        "pretrained_weights": False,
    }


def _median(values: list[float]) -> dict[str, Any]:
    return {
        "runs_ms": [round(value, 3) for value in values],
        "median_ms": round(statistics.median(values), 3),
        "maximum_ms": round(max(values), 3),
    }


def _semantic_types(semantic: Any) -> set[str]:
    return {
        str(item["semantic_type"])
        for item in semantic.detections
        if not item.get("unknown")
    }


def _unknown_count(semantic: Any) -> int:
    return sum(bool(item.get("unknown")) for item in semantic.detections)


def _case_checks(key: str, graph: Any, semantic: Any, spec: ExternalModelSpec) -> dict[str, bool]:
    detected = _semantic_types(semantic)
    input_names = [item.name for item in graph.inputs]
    output_names = [item.name for item in graph.outputs]
    checks = {
        "graph_nonempty": bool(graph.nodes),
        "input_names_are_not_outputs": bool(input_names) and all(not name.startswith("output_") for name in input_names),
        "outputs_named": bool(output_names) and all(name.startswith("output_") or name in {"scores", "features"} for name in output_names),
        "expected_semantics": set(spec.expected_semantics).issubset(detected),
        "unknown_is_explicit": _unknown_count(semantic) >= spec.minimum_unknown,
        "provenance_present": all(
            bool(item.get("reasons"))
            and "source_node_ids" in item.get("provenance", {})
            and "source_edge_ids" in item.get("provenance", {})
            for item in semantic.detections
        ),
    }
    if key == "dynamic_pytorch":
        checks["dynamic_sample_boundary"] = bool(graph.metadata.get("dynamic_sampling_boundary"))
    elif key == "onnx_multi_io":
        checks.update({
            "multiple_inputs": len(graph.inputs) == 2,
            "multiple_outputs": len(graph.outputs) == 2,
            "dynamic_dimensions": any(isinstance(value, str) for item in graph.inputs for value in item.shape),
            "shared_initializer": bool(graph.metadata.get("shared_initializers")),
        })
    elif key == "shared_siamese":
        checks.update({
            "multiple_inputs": len(graph.inputs) == 2,
            "multiple_outputs": len(graph.outputs) == 2,
            "shared_parameters": bool(graph.metadata.get("shared_parameters"))
            or any(node.shared_weights for node in graph.nodes),
        })
    elif key == "transformer_residual":
        merge_nodes = [node for node in graph.nodes if node.category == "merge" or "add" in node.op_type.lower()]
        indegree = {node.id: sum(edge.target == node.id for edge in graph.edges) for node in merge_nodes}
        checks["two_residual_merges"] = sum(value >= 2 for value in indegree.values()) >= 2
    elif key == "unet_skip":
        skip_detections = [item for item in semantic.detections if item.get("semantic_type") == "unet_skip" and not item.get("unknown")]
        checks["skip_edges_have_provenance"] = bool(skip_detections) and all(
            item.get("provenance", {}).get("source_edge_ids") for item in skip_detections
        )
    elif key == "custom_unknown":
        checks["no_guessed_named_architecture"] = not detected.intersection({
            "attention", "encoder", "decoder", "unet_skip", "moe_router_experts", "timestep_conditioning"
        })
    return checks


def build_external_model_compatibility_report(
    output_root: str | Path,
    *,
    repeats: int = 1,
) -> dict[str, Any]:
    """Run all six model-to-paper workflows and write editable evidence."""
    if repeats < 1:
        raise ValidationError("External-model report requires at least one measured run")
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "schema_version": "0.5.0-external-model-compatibility-1",
        "corpus_version": EXTERNAL_MODEL_CORPUS_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_count": len(EXTERNAL_MODEL_CASE_KEYS),
        "repeats": repeats,
        "models": {},
        "failures": [],
    }
    for key in EXTERNAL_MODEL_CASE_KEYS:
        timings: dict[str, list[float]] = {name: [] for name in ("import", "semantic", "paper", "composer")}
        final_graph = final_semantic = final_session = final_composer = final_proof = None
        for _ in range(repeats):
            started = time.perf_counter()
            graph, spec = import_external_model(key)
            timings["import"].append((time.perf_counter() - started) * 1000.0)
            started = time.perf_counter()
            semantic = derive_semantic_view(graph)
            timings["semantic"].append((time.perf_counter() - started) * 1000.0)
            started = time.perf_counter()
            session = generate_paper_figure(graph, maximum_candidates=3)
            timings["paper"].append((time.perf_counter() - started) * 1000.0)
            composer = FigureComposer(
                title=f"{spec.display_name} trial figure",
                panels=[
                    FigurePanel("A", "Semantic blocks", graph, semantic_level="block", semantic_view="paper"),
                    FigurePanel("B", "Operation evidence", graph, semantic_level="operation", semantic_view="paper"),
                ],
                arrangement="horizontal",
                page_preset="double-column",
                paper_ready_required=True,
            )
            started = time.perf_counter()
            _, _, proof = composer.compose()
            timings["composer"].append((time.perf_counter() - started) * 1000.0)
            final_graph, final_semantic, final_session = graph, semantic, session
            final_composer, final_proof = composer, proof
            gc.collect()
        assert final_graph is not None and final_semantic is not None and final_session is not None
        assert final_composer is not None and final_proof is not None
        case_root = root / key
        case_root.mkdir(parents=True, exist_ok=True)
        outputs = final_composer.export(
            case_root / f"{key}.svg",
            formats=("svg", "pdf", "tikz", "pptx"),
            tikz_panels=False,
        )
        project = Project(
            f"{final_graph.name} researcher trial",
            final_graph,
            model_source={"trial_case": key, "contains_path": False},
            sample_inputs=[{"description": external_model_registry()[key].input_description}],
            semantic_view={"version": "1.0", "level": "stage", "view": "paper"},
            export={"formats": ["svg", "pdf", "tikz", "pptx"], "page": "double-column"},
            figure_composer=final_composer.to_dict(),
        )
        project_path = project.save(case_root / f"{key}.nndv.json")
        restored = Project.load(project_path)
        checks = _case_checks(key, final_graph, final_semantic, external_model_registry()[key])
        checks.update({
            "paper_candidates_reviewable": 1 <= len(final_session.candidates) <= 3,
            "composer_paper_ready": bool(final_proof.get("paper_ready")),
            "project_roundtrip": restored.graph.to_dict() == final_graph.to_dict()
            and bool(restored.figure_composer),
            "four_required_exports": {path.suffix for path in outputs} == {".svg", ".pdf", ".tex", ".pptx"}
            and all(path.stat().st_size > 0 for path in outputs),
        })
        passed = all(checks.values())
        if not passed:
            report["failures"].append({"case": key, "checks": [name for name, value in checks.items() if not value]})
        report["models"][key] = {
            "spec": external_model_registry()[key].public_dict(),
            "graph": {
                "nodes": len(final_graph.nodes),
                "edges": len(final_graph.edges),
                "inputs": [asdict(item) for item in final_graph.inputs],
                "outputs": [asdict(item) for item in final_graph.outputs],
                "source_format": final_graph.metadata.get("source_format"),
            },
            "semantics": {
                "detected": sorted(_semantic_types(final_semantic)),
                "unknown_count": _unknown_count(final_semantic),
                "detections": final_semantic.detections,
            },
            "paper": {
                "template": final_session.recommendation.template,
                "level": final_session.recommendation.semantic_level,
                "candidates": len(final_session.candidates),
                "paper_ready": final_proof.get("paper_ready"),
                "minimum_font_pt": final_proof.get("minimum_font_pt"),
            },
            "artifacts": [str(path.relative_to(root)) for path in [*outputs, project_path]],
            "timings": {name: _median(values) for name, values in timings.items()},
            "checks": checks,
            "passed": passed,
        }
    report["compatible"] = not report["failures"] and len(report["models"]) == 6
    report["passed"] = report["compatible"]
    return report


__all__ = [
    "EXTERNAL_MODEL_CASE_KEYS",
    "EXTERNAL_MODEL_CORPUS_VERSION",
    "ExternalModelSpec",
    "build_external_model_compatibility_report",
    "external_model_case_manifest",
    "external_model_registry",
    "import_external_model",
]
