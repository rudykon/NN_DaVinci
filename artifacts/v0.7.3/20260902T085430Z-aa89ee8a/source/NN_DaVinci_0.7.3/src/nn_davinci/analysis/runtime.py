from __future__ import annotations

import time
from dataclasses import dataclass, field
from math import ceil
from statistics import mean, median
from typing import Any

from ..errors import OptionalDependencyError
from ..ir import GraphIR


@dataclass(slots=True)
class RuntimeRecord:
    path: str
    execution_index: int
    duration_ms: float
    input_summary: list[dict[str, Any]] = field(default_factory=list)
    output_summary: list[dict[str, Any]] = field(default_factory=list)
    gradient_summary: list[dict[str, Any]] = field(default_factory=list)
    nan_count: int = 0
    inf_count: int = 0
    device_memory_bytes: int | None = None


class RuntimeAnalyzer:
    """Capture leaf-module execution without modifying the model."""

    def capture(
        self,
        model: Any,
        sample_input: Any,
        *,
        backward_target: Any = None,
        graph: GraphIR | None = None,
        warmup: int = 2,
        iterations: int = 7,
    ) -> dict[str, Any]:
        try:
            import torch
        except ImportError as exc:
            raise OptionalDependencyError(
                "Runtime analysis requires PyTorch",
                hint="Install nn-davinci[pytorch] and retry on CPU or GPU.",
            ) from exc
        records: list[RuntimeRecord] = []
        handles = []
        starts: dict[int, float] = {}
        paths = {module: name for name, module in model.named_modules()}
        gradients: dict[str, list[dict[str, Any]]] = {}
        args = sample_input if isinstance(sample_input, tuple) else (sample_input,)
        warmup = max(1, int(warmup))
        iterations = max(3, int(iterations))
        with torch.no_grad():
            for _ in range(warmup):
                model(*args)
            timings: list[float] = []
            for _ in range(iterations):
                if torch.cuda.is_available():
                    torch.cuda.synchronize()
                started = time.perf_counter()
                model(*args)
                if torch.cuda.is_available():
                    torch.cuda.synchronize()
                timings.append((time.perf_counter() - started) * 1000)

        def pre_hook(module: Any, inputs: Any) -> None:
            if torch.cuda.is_available():
                torch.cuda.synchronize()
            starts[id(module)] = time.perf_counter()

        def post_hook(module: Any, inputs: Any, output: Any) -> None:
            if torch.cuda.is_available():
                torch.cuda.synchronize()
            duration = (time.perf_counter() - starts.pop(id(module), time.perf_counter())) * 1000
            tensors = _tensors(output, torch)
            records.append(RuntimeRecord(
                path=paths.get(module, module.__class__.__name__), execution_index=len(records), duration_ms=duration,
                input_summary=[_summary(item, torch) for item in _tensors(inputs, torch)],
                output_summary=[_summary(item, torch) for item in tensors],
                nan_count=sum(int(torch.isnan(item).sum()) for item in tensors if item.is_floating_point()),
                inf_count=sum(int(torch.isinf(item).sum()) for item in tensors if item.is_floating_point()),
                device_memory_bytes=int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else None,
            ))

        def backward_hook(module: Any, grad_input: Any, grad_output: Any) -> None:
            path = paths.get(module, module.__class__.__name__)
            values = _tensors(grad_output, torch)
            gradients.setdefault(path, []).append({
                "outputs": [_summary(item, torch) for item in values],
                "inputs": [_summary(item, torch) for item in _tensors(grad_input, torch)],
                "nan_count": sum(int(torch.isnan(item).sum()) for item in values if item.is_floating_point()),
                "inf_count": sum(int(torch.isinf(item).sum()) for item in values if item.is_floating_point()),
            })

        leaves = [(name, module) for name, module in model.named_modules() if name and not any(True for _ in module.children())]
        for _, module in leaves:
            handles.extend([module.register_forward_pre_hook(pre_hook), module.register_forward_hook(post_hook)])
            if backward_target is not None:
                handles.append(module.register_full_backward_hook(backward_hook))
        try:
            if torch.cuda.is_available():
                torch.cuda.reset_peak_memory_stats()
            output = model(*args)
            if backward_target is not None:
                loss = backward_target(output) if callable(backward_target) else output.flatten()[int(backward_target)]
                loss.backward()
        finally:
            for handle in handles:
                handle.remove()

        by_path: dict[str, list[RuntimeRecord]] = {}
        for record in records:
            by_path.setdefault(record.path, []).append(record)
        undeclared = []
        unexecuted = []
        if graph is not None:
            for node in graph.nodes:
                matches = by_path.get(node.path, [])
                if matches:
                    gradient_records = gradients.get(node.path, [])
                    node.analysis.update({
                        "duration_ms": sum(item.duration_ms for item in matches),
                        "execution_count": len(matches),
                        "nan_count": sum(item.nan_count for item in matches),
                        "inf_count": sum(item.inf_count for item in matches),
                        "runtime_outputs": [item.output_summary for item in matches],
                        "gradient_records": gradient_records,
                        "gradient_count": len(gradient_records),
                        "peak_memory_bytes": max((item.device_memory_bytes or 0 for item in matches), default=0) or None,
                    })
                elif node.category not in {"input", "output"}:
                    unexecuted.append(node.id)
            known_paths = {node.path for node in graph.nodes}
            undeclared = sorted(path for path in by_path if path not in known_paths)
        peak_record = max(records, key=lambda item: item.device_memory_bytes or 0, default=None)
        ordered_timings = sorted(timings)
        runtime_candidates = [node for node in graph.nodes if node.category not in {"input", "output"}] if graph else []
        covered_runtime = len(runtime_candidates) - len(unexecuted)
        summary = {
            "total_duration_ms": sum(item.duration_ms for item in records),
            "peak_memory_bytes": int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else None,
            "peak_memory_location": peak_record.path if peak_record and peak_record.device_memory_bytes else None,
            "executed_operations": len(records),
            "unexecuted_nodes": unexecuted,
            "runtime_only_paths": undeclared,
            "nan_count": sum(item.nan_count for item in records),
            "inf_count": sum(item.inf_count for item in records),
            "gradient_modules": len(gradients),
            "runtime_coverage": covered_runtime / len(runtime_candidates) if runtime_candidates else 1.0,
            "latency_ms": {
                "label": "measured end-to-end",
                "warmup_iterations": warmup,
                "measured_iterations": iterations,
                "mean": mean(timings),
                "median": median(timings),
                "p95": ordered_timings[max(0, ceil(0.95 * len(ordered_timings)) - 1)],
                "min": ordered_timings[0],
                "max": ordered_timings[-1],
            },
            "limitations": [
                "Latency is measured after warm-up on the current host and is not a hardware-independent model property.",
                "Module hooks attribute leaf-module time; functional operations may appear only in end-to-end latency unless TorchLens is used.",
                "GPU measurements synchronize around each iteration; CPU measurements include Python dispatch overhead.",
            ],
        }
        if graph is not None:
            graph.analysis["runtime"] = summary
        return {
            "records": [record.__dict__ if hasattr(record, "__dict__") else {field: getattr(record, field) for field in RuntimeRecord.__dataclass_fields__} for record in records],
            "summary": summary,
            "output": output,
        }

    def capture_operations(self, model: Any, sample_input: Any, **options: Any) -> dict[str, Any]:
        """Use TorchLens when available to capture functional ops and recurrent passes."""
        from .torchlens import TorchLensAnalyzer

        return TorchLensAnalyzer().capture(model, sample_input, **options)


def _tensors(value: Any, torch: Any) -> list[Any]:
    if isinstance(value, torch.Tensor):
        return [value]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _tensors(child, torch)]
    if isinstance(value, (list, tuple)):
        return [item for child in value for item in _tensors(child, torch)]
    return []


def _summary(tensor: Any, torch: Any) -> dict[str, Any]:
    result = {"shape": list(tensor.shape), "dtype": str(tensor.dtype), "device": str(tensor.device), "requires_grad": tensor.requires_grad}
    if tensor.numel() and tensor.is_floating_point():
        detached = tensor.detach()
        result.update({"min": float(detached.min()), "max": float(detached.max()), "mean": float(detached.mean()), "std": float(detached.std()) if detached.numel() > 1 else 0.0})
    return result
