from __future__ import annotations

from pathlib import Path
from typing import Any

from ..errors import AdapterError, OptionalDependencyError
from ..ir import Edge, GraphIR, Node, Port, Subgraph, TensorSpec, stable_id
from .base import Adapter, Capability
from .onnx import _category


class TensorFlowAdapter(Adapter):
    name = "tensorflow"
    extensions = (".pb", ".pbtxt", ".savedmodel")
    priority = 7
    capabilities = (
        Capability("graphdef"), Capability("saved-model"), Capability("shapes"),
        Capability("constants"), Capability("control-edges"),
    )

    def accepts(self, source: Any) -> bool:
        if source.__class__.__module__.startswith("tensorflow"):
            return True
        if isinstance(source, (str, Path)):
            path = Path(source)
            if path.is_dir() and (path / "saved_model.pb").exists():
                return True
            return path.suffix.lower() in self.extensions
        return False

    def load(self, source: Any, **options: Any) -> GraphIR:
        try:
            import tensorflow as tf
        except ImportError as exc:
            raise OptionalDependencyError(
                "TensorFlow GraphDef/SavedModel import requires tensorflow",
                hint="Install TensorFlow in an optional NN_DaVinci environment, or convert the model to ONNX.",
            ) from exc
        source_name = "TensorFlow graph"
        available_signatures: list[str] = []
        selected_signature: str | None = None
        if hasattr(source, "node") and source.__class__.__name__ == "GraphDef":
            graph_def = source
        elif hasattr(source, "graph") and hasattr(source.graph, "as_graph_def"):
            graph_def = source.graph.as_graph_def(add_shapes=True)
            source_name = getattr(source, "name", source_name)
        else:
            path = Path(source)
            source_name = path.name
            if path.is_dir():
                loaded = tf.saved_model.load(str(path))
                signature_name = options.get("signature", "serving_default")
                signatures = getattr(loaded, "signatures", {})
                available_signatures = sorted(signatures)
                if signature_name not in signatures:
                    raise AdapterError(
                        f"SavedModel has no signature {signature_name!r}",
                        hint=f"Available signatures: {', '.join(signatures)}",
                    )
                graph_def = signatures[signature_name].graph.as_graph_def(add_shapes=True)
                selected_signature = signature_name
            else:
                graph_def = tf.compat.v1.GraphDef()
                data = path.read_bytes()
                if path.suffix.lower() == ".pbtxt":
                    from google.protobuf import text_format
                    text_format.Parse(data.decode("utf-8"), graph_def)
                else:
                    graph_def.ParseFromString(data)
        nodes: list[Node] = []
        by_name: dict[str, Node] = {}
        for index, item in enumerate(graph_def.node):
            node_id = stable_id("node", f"tensorflow:{item.name}")
            shape = _output_shape(item)
            dtype = _dtype(item, tf)
            spec = TensorSpec(item.name, shape, dtype)
            parameters = _const_elements(item)
            attributes = {key: _tf_attr(value, tf) for key, value in item.attr.items() if key not in {"value"}}
            namespace = "/".join(item.name.split("/")[:-1])
            category = "input" if item.op in {"Placeholder", "PlaceholderWithDefault"} else _category(item.op)
            node = Node(
                node_id, item.name.split("/")[-1], item.op, category, path=item.name,
                namespace=namespace, outputs=[Port(f"{node_id}:output:0", f"{item.name}:0", "output", spec)],
                parameters=parameters, trainable_parameters=0, attributes=attributes,
                source={"format": "tensorflow_graphdef", "index": index},
            )
            nodes.append(node)
            by_name[item.name] = node
        edges: list[Edge] = []
        for item in graph_def.node:
            target = by_name[item.name]
            for index, input_name in enumerate(item.input):
                control = input_name.startswith("^")
                clean = input_name.lstrip("^").split(":", 1)[0]
                source_node = by_name.get(clean)
                if source_node is None:
                    continue
                port = Port(f"{target.id}:input:{index}", input_name, "input", source_node.outputs[0].tensor)
                target.inputs.append(port)
                edges.append(Edge.create(source_node.id, target.id, source_port=source_node.outputs[0].id, target_port=port.id, tensor=port.tensor, kind="control" if control else "data"))
        consumers = {edge.source for edge in edges}
        for node in nodes:
            if node.id not in consumers and node.category != "input":
                node.category = "output"
        namespaces: dict[str, list[str]] = {}
        for node in nodes:
            if node.namespace:
                namespaces.setdefault(node.namespace, []).append(node.id)
        groups = [Subgraph(stable_id("group", key), key.split("/")[-1], value, level="module", attributes={"path": key}) for key, value in sorted(namespaces.items())]
        return GraphIR(name=source_name, nodes=nodes, edges=edges, subgraphs=groups, metadata={
            "source_format": "tensorflow_graphdef",
            "available_signatures": available_signatures,
            "selected_signature": selected_signature,
            "limitations": [
                "SavedModel signatures are selected one at a time; pass signature=<name> to inspect another graph."
            ] if available_signatures else [],
        })


def _output_shape(node: Any) -> list[int | None]:
    value = node.attr.get("_output_shapes")
    if value and value.list.shape:
        return [int(dim.size) if dim.size >= 0 else None for dim in value.list.shape[0].dim]
    value = node.attr.get("shape")
    if value and value.shape:
        return [int(dim.size) if dim.size >= 0 else None for dim in value.shape.dim]
    return []


def _dtype(node: Any, tf: Any) -> str:
    for key in ("dtype", "T", "DstT", "Tout"):
        value = node.attr.get(key)
        if value and value.type:
            try:
                return tf.dtypes.as_dtype(value.type).name
            except Exception:
                return str(value.type)
    return "unknown"


def _const_elements(node: Any) -> int:
    if node.op != "Const" or "value" not in node.attr:
        return 0
    tensor = node.attr["value"].tensor
    result = 1
    for dim in tensor.tensor_shape.dim:
        result *= max(0, int(dim.size))
    return result


def _tf_attr(value: Any, tf: Any) -> Any:
    if value.HasField("s"):
        return value.s.decode("utf-8", errors="replace")
    if value.HasField("i"):
        return int(value.i)
    if value.HasField("f"):
        return float(value.f)
    if value.HasField("b"):
        return bool(value.b)
    if value.HasField("type"):
        try:
            return tf.dtypes.as_dtype(value.type).name
        except Exception:
            return int(value.type)
    if value.HasField("shape"):
        return [int(dim.size) if dim.size >= 0 else None for dim in value.shape.dim]
    if value.list.i:
        return [int(item) for item in value.list.i]
    if value.list.f:
        return [float(item) for item in value.list.f]
    if value.list.s:
        return [item.decode("utf-8", errors="replace") for item in value.list.s]
    return str(value)
