"""Safe, non-executing import inspection and reproducible recommendations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import io
import json
from pathlib import Path
import re
from typing import Any
import zipfile

from .errors import ValidationError

IMPORT_PLAN_VERSION = "1.0"


@dataclass(slots=True)
class ImportPlan:
    filename: str
    detected_format: str
    confidence: float
    reasons: list[str]
    safety: dict[str, Any]
    sample_input: dict[str, Any]
    estimate: dict[str, Any]
    recommendation: dict[str, Any]
    diagnostics: list[dict[str, str]] = field(default_factory=list)
    topology_available: bool = True
    dynamic_sampling_boundary: str | None = None
    plan_version: str = IMPORT_PLAN_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def inspect_import(
    filename: str,
    data: bytes | str | None = None,
    *,
    size_bytes: int | None = None,
) -> ImportPlan:
    """Inspect a path/name and optional bytes without executing model code."""
    name = Path(filename).name
    suffix = Path(name).suffix.lower()
    raw = data.encode("utf-8") if isinstance(data, str) else data
    size = size_bytes if size_bytes is not None else len(raw or b"")
    detected, confidence, reasons = _detect(name, suffix, raw)
    safety = _safety(detected)
    sample = _sample_requirements(detected)
    estimate = _estimate(detected, raw, size)
    recommendation = _recommend(estimate, detected)
    diagnostics: list[dict[str, str]] = []
    topology_available = detected != "pytorch-state-dict"
    boundary = None
    if detected == "pytorch-state-dict":
        diagnostics.append({
            "level": "warning",
            "code": "weights-only",
            "message": "state_dict can restore weight groups only; it cannot recover model topology.",
        })
    if detected in {"pytorch-factory", "jax", "tensorflow-savedmodel"}:
        boundary = "The imported graph represents one sampled execution/signature; data-dependent paths not exercised by the sample remain unknown."
        diagnostics.append({"level": "info", "code": "dynamic-sample", "message": boundary})
    if sample.get("required"):
        diagnostics.append({
            "level": "info",
            "code": "sample-input",
            "message": "Provide every input shape and dtype; mark symbolic/dynamic dimensions by name.",
        })
    return ImportPlan(
        filename=name,
        detected_format=detected,
        confidence=confidence,
        reasons=reasons,
        safety=safety,
        sample_input=sample,
        estimate=estimate,
        recommendation=recommendation,
        diagnostics=diagnostics,
        topology_available=topology_available,
        dynamic_sampling_boundary=boundary,
    )


def saved_import_config(plan: ImportPlan, options: dict[str, Any]) -> dict[str, Any]:
    """Create the stable project-file record used by one-click re-import."""
    allowed = {
        "adapter", "sample_inputs", "dynamic_dimensions", "input_names", "input_semantics",
        "allow_code", "allow_pickle", "framework_view", "semantic_level", "view", "summary",
        "focus", "page", "label_density",
    }
    return {
        "config_version": IMPORT_PLAN_VERSION,
        "source": {"filename": plan.filename, "detected_format": plan.detected_format},
        "safety_confirmation_required": bool(plan.safety.get("confirmation_required")),
        "options": {key: value for key, value in options.items() if key in allowed},
        "estimate": dict(plan.estimate),
        "recommendation": dict(plan.recommendation),
    }


def _detect(name: str, suffix: str, data: bytes | None) -> tuple[str, float, list[str]]:
    lower = name.lower()
    if lower.endswith((".nndv.json", ".nndv.yaml", ".nndv.yml")):
        return "project", 1.0, ["NN_DaVinci project filename suffix."]
    if suffix in {".json", ".nndv", ".yaml", ".yml"}:
        mapping = _parse_mapping(data, suffix)
        if isinstance(mapping, dict):
            if "project_version" in mapping and "graph" in mapping:
                return "project", 1.0, ["Versioned project envelope with embedded Graph IR."]
            if "ir_version" in mapping and "nodes" in mapping:
                return "graph-ir", 1.0, ["Versioned Graph IR fields are present."]
            if "layers" in mapping or "nodes" in mapping:
                return "manual-config", 0.96, ["Declarative JSON/YAML layer or node collection."]
        return "manual-config", 0.72, ["JSON/YAML is treated as declarative data; schema will be validated at import."]
    if suffix == ".onnx" or data and data[:4] == b"\x08\x00\x12\x00":
        return "onnx", 0.99 if suffix == ".onnx" else 0.75, ["ONNX extension or protobuf header."]
    if suffix == ".py":
        text = (data or b"").decode("utf-8", errors="ignore")
        if "jax" in text or "jax.numpy" in text:
            return "jax", 0.78, ["Python source references JAX; callable execution requires confirmation."]
        return "pytorch-factory", 0.86, ["Python factory/module source can construct a PyTorch model."]
    if suffix in {".pt", ".pth", ".ckpt", ".bin"}:
        kind = _torch_archive_kind(data)
        if kind == "torchscript":
            return "torchscript", 0.96, ["Torch archive contains TorchScript code/data entries."]
        if "state" in lower or "weight" in lower:
            return "pytorch-state-dict", 0.82, ["Checkpoint filename indicates weights/state_dict; pickle inspection is not executed."]
        return "pytorch-pickle", 0.68, ["PyTorch checkpoint is pickle-capable and cannot be safely classified without loading."]
    if suffix in {".keras", ".h5", ".hdf5"}:
        return "keras", 0.98, ["Keras archive/HDF5 extension."]
    if Path(name).name == "saved_model.pb":
        return "tensorflow-savedmodel", 1.0, ["TensorFlow SavedModel marker filename."]
    if suffix in {".pb", ".pbtxt"}:
        return "tensorflow", 0.95, ["TensorFlow GraphDef protobuf extension."]
    if suffix == ".mlir" or data and b"module" in data[:256] and b"func.func" in data[:2048]:
        return "mlir", 0.98, ["MLIR extension or module/function syntax."]
    raise ValidationError(
        f"Could not identify import format for {name!r}",
        hint="Choose a supported ONNX, PyTorch, TensorFlow/Keras, JAX, MLIR, JSON/YAML, or project file.",
    )


def _safety(detected: str) -> dict[str, Any]:
    if detected in {"pytorch-factory", "jax"}:
        return {
            "level": "restricted",
            "executes_code": True,
            "uses_pickle": False,
            "confirmation_required": True,
            "default_action": "blocked",
            "message": "Python factory execution is disabled until the user explicitly trusts this local source.",
        }
    if detected in {"pytorch-pickle", "pytorch-state-dict"}:
        return {
            "level": "restricted",
            "executes_code": False,
            "uses_pickle": True,
            "confirmation_required": True,
            "default_action": "blocked",
            "message": "Pickle deserialization is disabled until the user explicitly trusts this local checkpoint.",
        }
    if detected in {"keras", "tensorflow-savedmodel"}:
        return {
            "level": "caution",
            "executes_code": False,
            "uses_pickle": False,
            "confirmation_required": False,
            "default_action": "inspect",
            "message": "Load with framework safe mode where available; custom objects remain disabled.",
        }
    return {
        "level": "safe-data",
        "executes_code": False,
        "uses_pickle": False,
        "confirmation_required": False,
        "default_action": "inspect",
        "message": "Parsed as data without executing model code.",
    }


def _sample_requirements(detected: str) -> dict[str, Any]:
    required = detected in {"pytorch-factory", "jax", "pytorch-pickle"}
    helpful = detected in {"onnx", "torchscript", "tensorflow", "tensorflow-savedmodel", "keras"}
    return {
        "required": required,
        "recommended": required or helpful,
        "fields": ["name", "shape", "dtype", "dynamic_axes", "semantic"],
        "supports_multiple_inputs": True,
        "dynamic_dimension_syntax": "For a dynamic dimension, use a symbolic name such as batch, height, sequence, or tokens instead of inventing a fixed value.",
        "default_dtype": "float32",
        "reason": (
            "Tracing requires representative values for every positional/keyword input."
            if required else "Existing graph shapes are used when present; samples improve shape inference and diagnostics."
        ),
    }


def _estimate(detected: str, data: bytes | None, size: int) -> dict[str, Any]:
    nodes: int | None = None
    edges: int | None = None
    basis = "file-size heuristic"
    if detected in {"project", "graph-ir", "manual-config"}:
        mapping = _parse_mapping(data, ".json")
        if isinstance(mapping, dict):
            graph = mapping.get("graph", mapping)
            collection = graph.get("nodes", graph.get("layers", [])) if isinstance(graph, dict) else []
            raw_edges = graph.get("edges", []) if isinstance(graph, dict) else []
            nodes = len(collection) if isinstance(collection, list) else None
            edges = len(raw_edges) if isinstance(raw_edges, list) else None
            if nodes is not None and edges == 0 and nodes > 1 and "layers" in graph:
                edges = nodes - 1
            basis = "declarative node/edge count"
    elif detected == "mlir" and data:
        text = data.decode("utf-8", errors="ignore")
        nodes = len(re.findall(r"^\s*%[\w.-]+\s*=", text, flags=re.MULTILINE))
        edges = max(0, nodes - 1)
        basis = "MLIR SSA result count"
    elif detected == "onnx" and data:
        try:
            import onnx

            model = onnx.load_model_from_string(data)
            nodes = len(model.graph.node) + len(model.graph.input) + len(model.graph.output)
            edges = sum(len(node.input) for node in model.graph.node)
            basis = "ONNX protobuf inspection"
        except Exception:
            pass
    if nodes is None:
        ratio = {
            "pytorch-state-dict": 48_000,
            "pytorch-pickle": 64_000,
            "torchscript": 32_000,
            "keras": 40_000,
            "tensorflow": 24_000,
            "tensorflow-savedmodel": 24_000,
            "pytorch-factory": 800,
            "jax": 800,
        }.get(detected, 24_000)
        nodes = max(1, min(100_000, size // ratio if size else 100))
        edges = max(0, int(nodes * 1.25))
    confidence = 0.95 if basis != "file-size heuristic" else 0.35
    return {
        "nodes": int(nodes),
        "edges": int(edges or 0),
        "confidence": confidence,
        "basis": basis,
        "file_size_bytes": int(size),
        "operation_graph_upper_bound": max(int(nodes), int(nodes * (4 if detected in {"pytorch-factory", "torchscript", "jax"} else 2))),
    }


def _recommend(estimate: dict[str, Any], detected: str) -> dict[str, Any]:
    operation_upper = int(estimate["operation_graph_upper_bound"])
    if detected == "pytorch-state-dict":
        framework_view, semantic_level, summary = "framework", "stage", True
    elif operation_upper > 10_000:
        framework_view, semantic_level, summary = "module", "stage", True
    elif operation_upper > 2_000:
        framework_view, semantic_level, summary = "module", "block", True
    elif operation_upper > 500:
        framework_view, semantic_level, summary = "operation", "block", False
    else:
        framework_view, semantic_level, summary = "operation", "operation", False
    if operation_upper > 3_000:
        page, density = "wide-two-column", "compact"
    elif operation_upper > 500:
        page, density = "double-column", "paper"
    else:
        page, density = "single-column", "detailed" if operation_upper < 80 else "paper"
    return {
        "framework_view": framework_view,
        "semantic_level": semantic_level,
        "semantic_view": "faithful",
        "summary_first": summary,
        "focus_recommended": operation_upper > 2_000,
        "page": page,
        "label_density": density,
        "reason": f"Estimated operation upper bound is {operation_upper:,}; keep the initial canvas below 500 visible nodes.",
    }


def _parse_mapping(data: bytes | None, suffix: str) -> Any:
    if not data:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, RecursionError):
        if suffix not in {".yaml", ".yml"}:
            return None
        try:
            import yaml

            return yaml.safe_load(text)
        except Exception:
            return None


def _torch_archive_kind(data: bytes | None) -> str:
    if not data or not zipfile.is_zipfile(io.BytesIO(data)):
        return "pickle"
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
    except (OSError, zipfile.BadZipFile):
        return "pickle"
    return "torchscript" if any("/code/" in f"/{name}" or name.endswith("constants.pkl") for name in names) else "pickle"


__all__ = ["IMPORT_PLAN_VERSION", "ImportPlan", "inspect_import", "saved_import_config"]
