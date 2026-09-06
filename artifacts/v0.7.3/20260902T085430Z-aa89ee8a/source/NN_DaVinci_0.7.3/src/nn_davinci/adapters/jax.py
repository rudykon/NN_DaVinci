from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..errors import AdapterError, OptionalDependencyError
from ..ir import Edge, GraphIR, Node, Port, TensorSpec, stable_id
from .base import Adapter, Capability
from .onnx import _category


class JaxAdapter(Adapter):
    name = "jax"
    extensions: tuple[str, ...] = ()
    capabilities = (Capability("jaxpr"), Capability("shapes"), Capability("dynamic-execution"))

    def accepts(self, source: Any) -> bool:
        return callable(source) and source.__module__.startswith(("jax", "flax", "haiku"))

    def load(self, source: Any, **options: Any) -> GraphIR:
        try:
            import jax
        except ImportError as exc:
            raise OptionalDependencyError("JAX import requires jax", hint="Install nn-davinci[jax].") from exc
        sample = options.get("sample_input")
        if sample is None:
            raise AdapterError("JAX import requires sample_input", hint="Pass an array or tuple of arrays.")
        args = sample if isinstance(sample, tuple) and not options.get("sample_as_single", False) else (sample,)
        closed = jax.make_jaxpr(source)(*args)
        jaxpr = closed.jaxpr
        nodes: list[Node] = []
        producers: dict[str, tuple[Node, Port]] = {}
        edges: list[Edge] = []
        for variable in jaxpr.invars:
            name = str(variable)
            node_id = stable_id("node", f"jax:input:{name}")
            spec = _aval_spec(getattr(variable, "aval", None), name)
            node = Node(node_id, name, "Input", "input", path=name, outputs=[Port(f"{node_id}:output:0", name, "output", spec)])
            nodes.append(node)
            producers[name] = (node, node.outputs[0])
        for index, equation in enumerate(jaxpr.eqns):
            op_type = equation.primitive.name
            node_id = stable_id("node", f"jax:{op_type}:{index}")
            node = Node(
                node_id, f"{op_type}_{index}", op_type, _category(op_type), path=f"eqn.{index}",
                attributes={key: _safe(value) for key, value in equation.params.items()},
                source={"format": "jaxpr", "index": index},
            )
            for port_index, variable in enumerate(equation.invars):
                name = str(variable)
                spec = _aval_spec(getattr(variable, "aval", None), name)
                port = Port(f"{node_id}:input:{port_index}", name, "input", spec)
                node.inputs.append(port)
                if name in producers:
                    source_node, source_port = producers[name]
                    edges.append(Edge.create(source_node.id, node_id, source_port=source_port.id, target_port=port.id, tensor=spec))
            for port_index, variable in enumerate(equation.outvars):
                name = str(variable)
                spec = _aval_spec(getattr(variable, "aval", None), name)
                port = Port(f"{node_id}:output:{port_index}", name, "output", spec)
                node.outputs.append(port)
                producers[name] = (node, port)
            nodes.append(node)
        output_specs: list[TensorSpec] = []
        for index, variable in enumerate(jaxpr.outvars):
            name = str(variable)
            spec = _aval_spec(getattr(variable, "aval", None), name) or TensorSpec(name=name)
            output_specs.append(spec)
            node_id = stable_id("node", f"jax:output:{index}:{name}")
            port = Port(f"{node_id}:input:0", name, "input", spec)
            output = Node(node_id, f"output_{index}", "Output", "output", path=f"output.{index}", inputs=[port])
            nodes.append(output)
            if name in producers:
                producer, source_port = producers[name]
                edges.append(Edge.create(producer.id, output.id, source_port=source_port.id, target_port=port.id, tensor=spec))
        input_specs = [
            node.outputs[0].tensor
            for node in nodes
            if node.category == "input" and node.outputs and node.outputs[0].tensor is not None
        ]
        return GraphIR(
            name=getattr(source, "__name__", "JAX function"),
            nodes=nodes,
            edges=edges,
            inputs=input_specs,
            outputs=output_specs,
            metadata={
                "source_format": "jaxpr",
                "interface": "callable + sample_input -> JAXPR",
                "sample_pytree": str(jax.tree_util.tree_structure(sample)),
                "sample_pytree_type": type(sample).__name__,
                "output_count": len(output_specs),
                "limitations": ["Only the traced sample path and shapes represented by JAXPR are shown."],
            },
        )


class MlirAdapter(Adapter):
    name = "mlir"
    extensions = (".mlir",)
    priority = 6
    capabilities = (Capability("textual-mlir"), Capability("ssa-dataflow"))
    operation = re.compile(r"^\s*(?P<outs>%[\w., ]+)\s*=\s*(?:\"(?P<quoted>[^\"]+)\"|(?P<bare>[\w.]+))\s*(?P<rest>.*)$")

    def load(self, source: Any, **options: Any) -> GraphIR:
        text = Path(source).read_text(encoding="utf-8") if isinstance(source, (str, Path)) and Path(source).exists() else str(source)
        nodes: list[Node] = []
        producers: dict[str, Node] = {}
        edges: list[Edge] = []
        for line_number, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("//") or stripped in {"{", "}"}:
                continue
            if stripped.startswith(("module ", "func.func ", "return", "func.return")):
                continue
            match = self.operation.match(line)
            if not match:
                raise AdapterError(
                    f"Unsupported MLIR syntax at line {line_number}: {stripped[:80]}",
                    hint="The lightweight parser accepts one-line SSA assignments such as %0 = \"stablehlo.add\"(%a, %b) : ...; regions, block arguments, aliases and custom assembly require an official MLIR parser.",
                )
            op_type = match.group("quoted") or match.group("bare")
            outputs = [item.strip() for item in match.group("outs").split(",")]
            inputs = re.findall(r"%[\w.]+", match.group("rest").split(":", 1)[0])
            node_id = stable_id("node", f"mlir:{line_number}:{op_type}")
            node = Node(
                node_id, outputs[0].lstrip("%"), op_type, _category(op_type), path=outputs[0],
                source={"format": "mlir", "line": line_number}, attributes={"text": line.strip()},
            )
            for index, value in enumerate(inputs):
                port = Port(f"{node_id}:input:{index}", value, "input")
                node.inputs.append(port)
                if value in producers:
                    edges.append(Edge.create(producers[value].id, node.id, target_port=port.id, label=value))
            for index, value in enumerate(outputs):
                tensor = _mlir_result_spec(match.group("rest"), value)
                node.outputs.append(Port(f"{node_id}:output:{index}", value, "output", tensor))
                producers[value] = node
            nodes.append(node)
        if not nodes:
            raise AdapterError("No SSA operations were found in the MLIR input")
        return GraphIR(name=options.get("name", "MLIR module"), nodes=nodes, edges=edges, metadata={
            "source_format": "mlir",
            "support_level": "lightweight-ssa-subset",
            "supported_syntax": "one-line SSA assignments with quoted or bare operation names and tensor result types",
            "unsupported_syntax": ["regions", "block arguments", "type aliases", "custom assembly", "symbol resolution"],
        })


def _aval_spec(aval: Any, name: str) -> TensorSpec | None:
    if aval is None:
        return None
    return TensorSpec(name=name, shape=[int(item) if isinstance(item, int) else str(item) for item in getattr(aval, "shape", [])], dtype=str(getattr(aval, "dtype", "unknown")))


def _safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    return str(value)


def _mlir_result_spec(rest: str, name: str) -> TensorSpec | None:
    matches = re.findall(r"tensor<([^>]+)>", rest)
    if not matches:
        return None
    value = matches[-1]
    parts = value.split("x")
    if len(parts) < 2:
        return TensorSpec(name=name, shape=[], dtype=parts[-1])
    dtype = parts[-1]
    shape: list[int | str | None] = []
    for item in parts[:-1]:
        if item == "?":
            shape.append(None)
        elif item.isdigit():
            shape.append(int(item))
        else:
            shape.append(item)
    return TensorSpec(name=name, shape=shape, dtype=dtype)
