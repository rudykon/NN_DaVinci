from __future__ import annotations

from typing import Any

from ..errors import OptionalDependencyError, ValidationError
from ..ir import Edge, GraphIR, Node, Port, Subgraph, TensorSpec, stable_id
from ..adapters.onnx import _category


class TorchLensAnalyzer:
    """Translate a TorchLens runtime trace into NN_DaVinci Graph IR."""

    def capture(
        self,
        model: Any,
        sample_input: Any,
        *,
        save_activations: bool | str | list[Any] = False,
        capture_gradients: bool = False,
        backward_target: Any = None,
        profile: bool = True,
        keep_orphans: bool = True,
    ) -> dict[str, Any]:
        try:
            import torchlens as tl
        except ImportError as exc:
            raise OptionalDependencyError(
                "Operation-level runtime capture requires TorchLens",
                hint="Install torch and torchlens, or use RuntimeAnalyzer.capture() for module-level hooks.",
            ) from exc
        layers_to_save = "all" if save_activations is True else None if save_activations is False else save_activations
        capture = tl.options.CaptureOptions(
            layers_to_save=layers_to_save,
            save_grads=True if capture_gradients else False,
            backward_ready=capture_gradients,
            inference_only=not capture_gradients,
            keep_orphans=keep_orphans,
            verbose=False,
        )
        trace = tl.trace(
            model,
            sample_input,
            capture=capture,
            profile=profile,
        )
        if capture_gradients:
            output_ops = list(getattr(trace, "output_ops", []))
            if not output_ops:
                raise ValidationError("TorchLens trace has no output operation for backward analysis")
            output = getattr(output_ops[0], "out", None)
            if output is None:
                raise ValidationError("Backward analysis needs the output activation", hint="Use save_activations=True.")
            objective = backward_target(output) if callable(backward_target) else output.flatten()[int(backward_target or 0)]
            if hasattr(trace, "log_backward"):
                trace.log_backward(objective)
            else:
                objective.backward()
        graph = self.from_trace(trace)
        return {
            "graph": graph,
            "trace": trace,
            "summary": {
                "operations": len(graph.nodes),
                "edges": len(graph.edges),
                "forward_duration_ms": _duration_ms(getattr(trace, "forward_duration", None)),
                "functional_ops": sum(node.source.get("module_path") in {None, ""} for node in graph.nodes),
                "recurrent_operations": sum(int(node.attributes.get("num_passes", 1)) > 1 for node in graph.nodes),
                "gradient_operations": sum(bool(node.analysis.get("has_gradient")) for node in graph.nodes),
            },
        }

    def from_trace(self, trace: Any) -> GraphIR:
        layers = list(getattr(trace, "layer_list", []))
        nodes: list[Node] = []
        by_label: dict[str, Node] = {}
        groups: dict[str, list[str]] = {}
        for index, layer in enumerate(layers):
            label = str(_read(layer, "layer_label", _read(layer, "label", f"op_{index}")))
            op_type = str(_read(layer, "func_name", _read(layer, "layer_type", "Operation")))
            node_id = stable_id("node", f"torchlens:{label}")
            shape = _shape(_read(layer, "shape", []))
            dtype = str(_read(layer, "dtype", "unknown")).replace("torch.", "")
            spec = TensorSpec(label, shape, dtype, size_bytes=_quantity_int(_read(layer, "activation_memory", None)))
            module_path = _module_path(layer)
            attributes = {
                "num_passes": int(_read(layer, "num_passes", 1) or 1),
                "equivalence_class": _safe(_read(layer, "equivalence_class", None)),
                "is_inplace": bool(_read(layer, "is_inplace", False)),
                "is_orphan": bool(_read(layer, "is_orphan", False)),
                "conditional_branch_depth": int(_read(layer, "conditional_branch_depth", 0) or 0),
            }
            analysis = {
                "duration_ms": _duration_ms(_read(layer, "total_func_duration", _read(layer, "func_duration", None))),
                "flops": _quantity_int(_read(layer, "flops_forward", None)),
                "activation_bytes": _quantity_int(_read(layer, "activation_memory", None)),
                "gradient_bytes": _quantity_int(_read(layer, "gradient_memory", None)),
                "has_gradient": bool(_read(layer, "has_grad", False)),
                "gradient_shape": _shape(_read(layer, "grad_shape", [])),
            }
            category = "input" if bool(_read(layer, "is_input", False)) else "output" if bool(_read(layer, "is_output", False)) else _category(op_type)
            node = Node(
                id=node_id, name=str(_read(layer, "layer_label_short", label)), op_type=op_type,
                category=category, path=module_path or label, namespace=".".join(module_path.split(".")[:-1]),
                outputs=[Port(f"{node_id}:output:0", label, "output", spec)],
                parameters=int(_read(layer, "num_params", 0) or 0),
                trainable_parameters=int(_read(layer, "num_params_trainable", 0) or 0),
                attributes=attributes,
                source={"format": "torchlens", "trace_id": label, "operation_index": index, "module_path": module_path},
                analysis={key: value for key, value in analysis.items() if value is not None},
                tags=["dynamic"] + (["recurrent"] if attributes["num_passes"] > 1 else []),
            )
            nodes.append(node)
            by_label[label] = node
            if module_path:
                groups.setdefault(module_path, []).append(node_id)
        edges: list[Edge] = []
        seen_edges: set[tuple[str, str]] = set()
        for layer in layers:
            label = str(_read(layer, "layer_label", _read(layer, "label", "")))
            target = by_label.get(label)
            if target is None:
                continue
            for port_index, parent_label in enumerate(_read(layer, "parents", []) or []):
                parent = by_label.get(str(parent_label).split(":", 1)[0]) or by_label.get(str(parent_label))
                if parent is None or (parent.id, target.id) in seen_edges:
                    continue
                port = Port(f"{target.id}:input:{port_index}", str(parent_label), "input", parent.outputs[0].tensor)
                target.inputs.append(port)
                edges.append(Edge.create(parent.id, target.id, source_port=parent.outputs[0].id, target_port=port.id, tensor=parent.outputs[0].tensor))
                seen_edges.add((parent.id, target.id))
        subgraphs = [
            Subgraph(stable_id("group", path), path.split(".")[-1], members, level="module", attributes={"path": path})
            for path, members in sorted(groups.items())
        ]
        metadata = {
            "source_format": "torchlens",
            "model_class": _read(trace, "model_class_qualname", None),
            "torchlens_version": _read(trace, "torchlens_version", None),
            "forward_duration_ms": _duration_ms(_read(trace, "forward_duration", None)),
            "actual_dynamic_path": True,
            "trace_label": _read(trace, "trace_label", None),
        }
        return GraphIR(name=str(_read(trace, "model_name", metadata["model_class"] or "TorchLens trace")), nodes=nodes, edges=edges, subgraphs=subgraphs, metadata=metadata).validate()


def _read(value: Any, name: str, default: Any) -> Any:
    try:
        result = getattr(value, name)
        return default if result is None else result
    except Exception:
        return default


def _module_path(layer: Any) -> str:
    direct = _read(layer, "module_address", "") or _read(layer, "address", "")
    if direct:
        return str(direct)
    modules = _read(layer, "modules", []) or []
    if isinstance(modules, dict):
        modules = list(modules)
    if modules:
        item = modules[-1]
        return str(_read(item, "address", item if isinstance(item, str) else ""))
    return ""


def _shape(value: Any) -> list[int | str | None]:
    try:
        return [int(item) if isinstance(item, int) else None if item is None else str(item) for item in value]
    except TypeError:
        return []


def _quantity_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raw = _read(value, "value", None)
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None


def _duration_ms(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value) * 1000
    except (TypeError, ValueError):
        raw = _read(value, "seconds", _read(value, "value", None))
        try:
            return float(raw) * 1000 if raw is not None else None
        except (TypeError, ValueError):
            return None


def _safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if isinstance(value, (tuple, list)):
        return [_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    return str(value)
