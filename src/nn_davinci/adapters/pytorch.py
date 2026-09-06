from __future__ import annotations

import importlib.util
import inspect
import operator
import copy
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..errors import AdapterError, OptionalDependencyError
from ..ir import Edge, GraphIR, Node, Port, Subgraph, TensorSpec, stable_id
from .base import Adapter, Capability
from .onnx import _category


def _require_torch():
    try:
        import torch
        return torch
    except ImportError as exc:
        raise OptionalDependencyError(
            "PyTorch import requires torch",
            hint="Install nn-davinci[pytorch] in a compatible environment.",
        ) from exc


def _shape_dtype(meta: Any, name: str = "") -> TensorSpec | None:
    if meta is None:
        return None
    shape = getattr(meta, "shape", None)
    dtype = getattr(meta, "dtype", None)
    if shape is None and isinstance(meta, dict):
        shape, dtype = meta.get("shape"), meta.get("dtype")
    if shape is None:
        return None
    return TensorSpec(name=name, shape=[int(x) if isinstance(x, int) else str(x) for x in shape], dtype=str(dtype).replace("torch.", ""))


class PyTorchAdapter(Adapter):
    name = "pytorch"
    extensions = (".pt", ".pth", ".torchscript", ".py")
    priority = 8
    capabilities = (
        Capability("fx-graph"), Capability("module-hierarchy"), Capability("shapes"),
        Capability("parameters"), Capability("shared-weights"), Capability("runtime-capture"),
    )

    def accepts(self, source: Any) -> bool:
        module = getattr(source.__class__, "__module__", "")
        return module.startswith("torch") or super().accepts(source)

    def load(self, source: Any, **options: Any) -> GraphIR:
        torch = _require_torch()
        model = self._resolve_model(source, options)
        if isinstance(model, GraphIR):
            return model
        sample = options.get("sample_input")
        if hasattr(model, "inlined_graph") and model.__class__.__module__.startswith("torch.jit"):
            return self._from_torchscript(model)
        try:
            traced = torch.fx.symbolic_trace(model)
        except Exception as exc:
            if sample is not None and options.get("runtime_fallback", True):
                return self._runtime_modules(model, sample, torch, trace_error=str(exc))
            raise AdapterError(
                f"torch.fx could not trace {model.__class__.__name__}: {exc}",
                hint="Provide sample_input for runtime fallback, or mark dynamic regions as leaf modules.",
            ) from exc
        if sample is not None:
            try:
                from torch.fx.passes.shape_prop import ShapeProp
                args = sample if isinstance(sample, tuple) else (sample,)
                ShapeProp(traced).propagate(*args)
            except Exception:
                pass
        return self._from_fx(model, traced)

    def resolve_model(self, source: Any, **options: Any) -> Any:
        """Resolve a trusted source into a model for runtime/explainability APIs."""
        return self._resolve_model(source, options)

    def _resolve_model(self, source: Any, options: dict) -> Any:
        torch = _require_torch()
        if not isinstance(source, (str, Path)):
            return source.eval() if hasattr(source, "eval") else source
        text = str(source)
        if ":" in text and text.split(":", 1)[0].endswith(".py"):
            if not options.get("allow_code", False):
                raise AdapterError(
                    "Importing model.py executes user code and is disabled by default",
                    hint="Use a trusted file with --allow-code.",
                )
            filename, symbol = text.split(":", 1)
            spec = importlib.util.spec_from_file_location("nn_davinci_user_model", filename)
            if spec is None or spec.loader is None:
                raise AdapterError(f"Cannot load Python model file {filename!r}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            factory = getattr(module, symbol)
            model = factory() if callable(factory) else factory
            return model.eval() if hasattr(model, "eval") else model
        if not options.get("allow_pickle", False):
            if Path(text).suffix.lower() in {".torchscript", ".jit"}:
                try:
                    return torch.jit.load(text, map_location=options.get("device", "cpu")).eval()
                except Exception as exc:
                    raise AdapterError(
                        f"Cannot load TorchScript archive {text!r}: {exc}",
                        hint="Re-save it with torch.jit.save and verify the archive in PyTorch.",
                    ) from exc
            raise AdapterError(
                "Loading .pt/.pth may execute pickle code and is disabled by default",
                hint="Use a trusted file with --allow-pickle, or pass model.py:factory.",
            )
        model = torch.load(text, map_location=options.get("device", "cpu"), weights_only=False)
        if isinstance(model, dict) and not hasattr(model, "forward"):
            return self._state_dict_graph(model, Path(text).stem)
        return model.eval() if hasattr(model, "eval") else model

    def _from_fx(self, model: Any, traced: Any) -> GraphIR:
        modules = dict(model.named_modules()) if hasattr(model, "named_modules") else {}
        nodes: list[Node] = []
        by_fx: dict[Any, Node] = {}
        groups: dict[str, list[str]] = {}
        parameter_owners: dict[int, str] = {}
        shared: dict[str, list[str]] = {}
        for index, fx_node in enumerate(traced.graph.nodes):
            target = str(fx_node.target)
            op_type = target
            module = None
            if fx_node.op == "call_module":
                module = modules.get(target)
                op_type = module.__class__.__name__ if module is not None else target
            elif fx_node.op == "placeholder":
                op_type = "Input"
            elif fx_node.op == "output":
                op_type = "Output"
            name = fx_node.name
            node_id = stable_id("node", f"fx:{name}:{index}")
            category = "input" if fx_node.op == "placeholder" else "output" if fx_node.op == "output" else _category(op_type)
            params = trainable = buffers = 0
            shared_weights: list[str] = []
            if module is not None:
                for parameter_name, parameter in module.named_parameters(recurse=False):
                    count = parameter.numel()
                    identity = id(parameter)
                    full_name = f"{target}.{parameter_name}" if target else parameter_name
                    if identity in parameter_owners:
                        shared_weights.append(parameter_owners[identity])
                        shared.setdefault(parameter_owners[identity], []).append(full_name)
                    else:
                        parameter_owners[identity] = full_name
                        params += count
                        trainable += count if parameter.requires_grad else 0
                buffers = sum(item.numel() for item in module.buffers(recurse=False))
            tensor_meta = fx_node.meta.get("tensor_meta") if hasattr(fx_node, "meta") else None
            # TensorMetadata is a namedtuple in current PyTorch releases; its own
            # fields must not be mistaken for a model returning multiple tensors.
            out_specs = [
                _shape_dtype(item, f"output_{i}")
                for i, item in enumerate(_flatten_metadata(tensor_meta))
            ]
            if fx_node.op == "placeholder":
                for port_index, spec in enumerate(out_specs):
                    if spec is not None:
                        spec.name = name if len(out_specs) == 1 else f"{name}_{port_index}"
            outputs = [
                Port(f"{node_id}:output:{i}", spec.name, "output", spec)
                for i, spec in enumerate(out_specs) if spec is not None
            ]
            if not outputs:
                outputs = [Port(f"{node_id}:output:0", "output", "output")]
            namespace = ".".join(target.split(".")[:-1]) if fx_node.op == "call_module" else ""
            node = Node(
                id=node_id, name=name, op_type=op_type, category=category, path=target,
                namespace=namespace, outputs=outputs, parameters=params,
                trainable_parameters=trainable, buffers=buffers, shared_weights=shared_weights,
                attributes={"fx_op": fx_node.op, "target": target},
                source={"format": "pytorch_fx", "index": index},
            )
            nodes.append(node)
            by_fx[fx_node] = node
            if namespace:
                groups.setdefault(namespace, []).append(node_id)

        edges: list[Edge] = []
        from torch.fx.node import map_arg

        for fx_node, target_node in by_fx.items():
            dependencies: list[Any] = []
            map_arg((fx_node.args, fx_node.kwargs), dependencies.append)
            bindings: list[tuple[Any, Port]] = []
            for dependency in dependencies:
                source_node = by_fx.get(dependency)
                if source_node is None:
                    continue
                source_ports = source_node.outputs
                # FX represents tuple/named-tuple extraction as operator.getitem.
                # Bind that consumer to the selected producer port instead of
                # silently routing every extracted value through output:0.
                if (
                    fx_node.op == "call_function"
                    and fx_node.target is operator.getitem
                    and fx_node.args
                    and fx_node.args[0] is dependency
                    and len(fx_node.args) > 1
                    and isinstance(fx_node.args[1], int)
                    and not isinstance(fx_node.args[1], bool)
                    and len(source_ports) > 1
                ):
                    selected = int(fx_node.args[1])
                    if selected < 0:
                        selected += len(source_ports)
                    source_ports = source_ports[selected : selected + 1]
                # A direct dependency on a tuple value represents all of its
                # tensor members. Preserve every source port as evidence.
                for source_port in source_ports:
                    bindings.append((dependency, source_port))
            for index, (dependency, source_port) in enumerate(bindings):
                tensor = copy.deepcopy(source_port.tensor)
                input_name = dependency.name
                if len(by_fx[dependency].outputs) > 1:
                    input_name = f"{dependency.name}.{source_port.name or source_port.id.rsplit(':', 1)[-1]}"
                port = Port(f"{target_node.id}:input:{index}", input_name, "input", tensor)
                target_node.inputs.append(port)
                edges.append(Edge.create(
                    by_fx[dependency].id,
                    target_node.id,
                    source_port=source_port.id,
                    target_port=port.id,
                    tensor=copy.deepcopy(source_port.tensor),
                ))
        graph_inputs = [
            replace(port.tensor)
            for node in nodes
            if node.attributes.get("fx_op") == "placeholder"
            for port in node.outputs
            if port.tensor is not None
        ]
        graph_outputs = [
            replace(port.tensor, name=f"output_{index}")
            for index, port in enumerate(
                port
                for node in nodes
                if node.attributes.get("fx_op") == "output"
                for port in node.inputs
                if port.tensor is not None
            )
        ]
        graph = GraphIR(
            name=model.__class__.__name__, nodes=nodes, edges=edges,
            subgraphs=[Subgraph(stable_id("group", key), key.split(".")[-1], value, attributes={"path": key}) for key, value in sorted(groups.items())],
            inputs=graph_inputs,
            outputs=graph_outputs,
            metadata={
                "source_format": "pytorch_fx",
                "model_class": model.__class__.__qualname__,
                "shared_parameters": shared,
                "parameter_total": sum(parameter.numel() for parameter in model.parameters()),
                "trainable_parameter_total": sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad),
            },
        )
        return graph

    def _runtime_modules(self, model: Any, sample: Any, torch: Any, *, trace_error: str) -> GraphIR:
        records: list[tuple[str, Any, Any, Any]] = []
        hooks = []
        for name, module in model.named_modules():
            if name and not any(True for _ in module.children()):
                hooks.append(module.register_forward_hook(lambda mod, inp, out, n=name: records.append((n, mod, inp, out))))
        try:
            args = sample if isinstance(sample, tuple) else (sample,)
            with torch.no_grad():
                model_output = model(*args)
        finally:
            for hook in hooks:
                hook.remove()
        nodes: list[Node] = []
        edges: list[Edge] = []
        tensor_producer: dict[int, Node] = {}
        graph_inputs: list[TensorSpec] = []
        try:
            argument_names = [
                name
                for name, parameter in inspect.signature(model.forward).parameters.items()
                if parameter.kind in {parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD}
            ]
        except (TypeError, ValueError):
            argument_names = []
        for index, tensor in enumerate(_flatten_tensors(args, torch)):
            name = argument_names[index] if index < len(argument_names) else f"input_{index}"
            spec = _shape_dtype(tensor, name)
            if spec is None:
                continue
            node_id = stable_id("node", f"runtime:input:{name}:{index}")
            port = Port(f"{node_id}:output:0", name, "output", spec)
            node = Node(
                id=node_id,
                name=name,
                op_type="Input",
                category="input",
                path=name,
                outputs=[port],
                source={"format": "pytorch_runtime", "input_index": index},
            )
            nodes.append(node)
            graph_inputs.append(spec)
            tensor_producer[id(tensor)] = node
        parameter_owners: dict[int, str] = {}
        shared: dict[str, list[str]] = {}
        for index, (name, module, inputs, output) in enumerate(records):
            node_id = stable_id("node", f"runtime:{name}:{index}")
            parameters = trainable = 0
            shared_weights: list[str] = []
            for parameter_name, parameter in module.named_parameters(recurse=False):
                identity = id(parameter)
                full_name = f"{name}.{parameter_name}"
                if identity in parameter_owners:
                    owner = parameter_owners[identity]
                    shared_weights.append(owner)
                    shared.setdefault(owner, []).append(full_name)
                else:
                    parameter_owners[identity] = full_name
                    parameters += parameter.numel()
                    trainable += parameter.numel() if parameter.requires_grad else 0
            node = Node(
                id=node_id, name=name, op_type=module.__class__.__name__, category=_category(module.__class__.__name__),
                path=name, parameters=parameters,
                trainable_parameters=trainable, shared_weights=shared_weights,
                source={"format": "pytorch_runtime", "execution_index": index},
            )
            flat_inputs = _flatten_tensors(inputs, torch)
            flat_outputs = _flatten_tensors(output, torch)
            for port_index, tensor in enumerate(flat_inputs):
                spec = _shape_dtype(tensor, f"input_{port_index}")
                if spec is None:  # tensor flattening guarantees shape metadata
                    continue
                port = Port(f"{node_id}:input:{port_index}", spec.name, "input", spec)
                node.inputs.append(port)
                producer = tensor_producer.get(id(tensor))
                if producer:
                    edges.append(Edge.create(producer.id, node_id, target_port=port.id, tensor=spec))
            for port_index, tensor in enumerate(flat_outputs):
                spec = _shape_dtype(tensor, f"output_{port_index}")
                if spec is None:  # tensor flattening guarantees shape metadata
                    continue
                node.outputs.append(Port(f"{node_id}:output:{port_index}", spec.name, "output", spec))
                tensor_producer[id(tensor)] = node
            nodes.append(node)
        graph_outputs: list[TensorSpec] = []
        for index, tensor in enumerate(_flatten_tensors(model_output, torch)):
            name = f"output_{index}"
            spec = _shape_dtype(tensor, name)
            if spec is None:
                continue
            graph_outputs.append(spec)
            node_id = stable_id("node", f"runtime:output:{index}")
            port = Port(f"{node_id}:input:0", name, "input", spec)
            node = Node(
                id=node_id,
                name=name,
                op_type="Output",
                category="output",
                path=name,
                inputs=[port],
                source={"format": "pytorch_runtime", "output_index": index},
            )
            producer = tensor_producer.get(id(tensor))
            if producer is not None:
                source_port = producer.outputs[0].id if producer.outputs else None
                edges.append(Edge.create(
                    producer.id,
                    node.id,
                    source_port=source_port,
                    target_port=port.id,
                    tensor=spec,
                ))
            nodes.append(node)
        return GraphIR(
            name=model.__class__.__name__, nodes=nodes, edges=edges,
            inputs=graph_inputs,
            outputs=graph_outputs,
            metadata={
                "source_format": "pytorch_runtime",
                "fx_trace_error": trace_error,
                "shared_parameters": shared,
                "dynamic_sampling_boundary": (
                    "Runtime fallback records only the branch executed by the provided sample input; "
                    "unexecuted dynamic branches remain unknown."
                ),
            },
        )

    def _from_torchscript(self, model: Any) -> GraphIR:
        jit_graph = model.inlined_graph
        nodes: list[Node] = []
        edges: list[Edge] = []
        producers: dict[str, tuple[Node, Port]] = {}
        input_specs: list[TensorSpec] = []
        for index, value in enumerate(jit_graph.inputs()):
            spec = _jit_tensor_spec(value)
            if spec is None:
                continue
            name = value.debugName()
            node_id = stable_id("node", f"torchscript:input:{name}:{index}")
            port = Port(f"{node_id}:output:0", name, "output", spec)
            node = Node(node_id, name, "Input", "input", path=name, outputs=[port], source={"format": "pytorch_torchscript", "index": index})
            nodes.append(node)
            producers[name] = (node, port)
            input_specs.append(spec)
        operator_nodes: list[Node] = []
        for index, item in enumerate(jit_graph.nodes()):
            op_type = str(item.kind())
            node_id = stable_id("node", f"torchscript:{op_type}:{index}")
            node = Node(
                node_id,
                f"{op_type.split('::')[-1]}_{index}",
                op_type,
                _category(op_type),
                path=f"torchscript.{index}",
                attributes={"scope": str(item.scopeName())},
                source={"format": "pytorch_torchscript", "index": index},
            )
            for port_index, value in enumerate(item.inputs()):
                name = value.debugName()
                port = Port(f"{node_id}:input:{port_index}", name, "input", _jit_tensor_spec(value))
                node.inputs.append(port)
                if name in producers:
                    source, source_port = producers[name]
                    edges.append(Edge.create(source.id, node.id, source_port=source_port.id, target_port=port.id, tensor=port.tensor))
            for port_index, value in enumerate(item.outputs()):
                name = value.debugName()
                port = Port(f"{node_id}:output:{port_index}", name, "output", _jit_tensor_spec(value))
                node.outputs.append(port)
                producers[name] = (node, port)
            operator_nodes.append(node)
            nodes.append(node)
        parameter_count = sum(parameter.numel() for parameter in model.parameters())
        trainable_count = sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad)
        if operator_nodes:
            operator_nodes[0].parameters = parameter_count
            operator_nodes[0].trainable_parameters = trainable_count
            operator_nodes[0].attributes["module_parameter_total"] = True
        output_specs: list[TensorSpec] = []
        for index, value in enumerate(jit_graph.outputs()):
            name = value.debugName()
            spec = _jit_tensor_spec(value) or TensorSpec(name=name)
            output_specs.append(spec)
            node_id = stable_id("node", f"torchscript:output:{name}:{index}")
            port = Port(f"{node_id}:input:0", name, "input", spec)
            output = Node(node_id, f"output_{index}", "Output", "output", path=f"output.{index}", inputs=[port], source={"format": "pytorch_torchscript"})
            nodes.append(output)
            if name in producers:
                source, source_port = producers[name]
                edges.append(Edge.create(source.id, output.id, source_port=source_port.id, target_port=port.id, tensor=spec))
        return GraphIR(
            name=model.__class__.__name__,
            nodes=nodes,
            edges=edges,
            inputs=input_specs,
            outputs=output_specs,
            metadata={
                "source_format": "pytorch_torchscript",
                "model_class": model.__class__.__qualname__,
                "module_paths": [name for name, _ in model.named_modules() if name],
                "limitations": ["TorchScript parameters are counted once at graph level and attached to the first operation."],
            },
        )

    def _state_dict_graph(self, state: dict, name: str) -> GraphIR:
        grouped: dict[str, list[tuple[str, Any]]] = {}
        for key, value in state.items():
            grouped.setdefault(key.rsplit(".", 1)[0] if "." in key else "parameters", []).append((key, value))
        nodes = []
        for index, (path, items) in enumerate(grouped.items()):
            params = sum(value.numel() for _, value in items if hasattr(value, "numel"))
            nodes.append(Node(
                id=stable_id("node", f"state:{path}"), name=path.split(".")[-1], op_type="ParameterGroup",
                category="operation", path=path, parameters=params, trainable_parameters=params,
                attributes={"tensors": [{"name": key, "shape": list(value.shape)} for key, value in items]},
                source={"format": "pytorch_state_dict", "index": index},
            ))
        return GraphIR(name=name, nodes=nodes, metadata={
            "source_format": "pytorch_state_dict",
            "structure_available": False,
            "representation": "weight-groups-only",
            "limitations": [
                "state_dict contains named tensors but no executable topology; nodes are weight groups, not recovered layers.",
                "Provide the model class plus sample_input, TorchScript, or ONNX to recover connectivity.",
            ],
        })


def _flatten_tensors(value: Any, torch: Any) -> list[Any]:
    if isinstance(value, torch.Tensor):
        return [value]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _flatten_tensors(child, torch)]
    if isinstance(value, (tuple, list)):
        return [item for child in value for item in _flatten_tensors(child, torch)]
    return []


def _flatten_metadata(value: Any) -> list[Any]:
    if value is None:
        return []
    if getattr(value, "shape", None) is not None:
        return [value]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _flatten_metadata(child)]
    if isinstance(value, (tuple, list)):
        return [item for child in value for item in _flatten_metadata(child)]
    return []


def _jit_tensor_spec(value: Any) -> TensorSpec | None:
    value_type = value.type()
    try:
        sizes = value_type.sizes()
    except (AttributeError, RuntimeError):
        return None
    if sizes is None:
        shape: list[int | str | None] = []
    else:
        shape = [int(item) if isinstance(item, int) else None for item in sizes]
    try:
        dtype = str(value_type.dtype()).replace("torch.", "")
    except (AttributeError, RuntimeError):
        dtype = str(value_type)
    return TensorSpec(name=value.debugName(), shape=shape, dtype=dtype)
