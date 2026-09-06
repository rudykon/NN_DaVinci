from __future__ import annotations

from pathlib import Path
from typing import Any

from ..errors import OptionalDependencyError
from ..ir import Edge, GraphIR, Node, Port, Subgraph, TensorSpec, stable_id
from .base import Adapter, Capability


def _shape(value_info: Any) -> TensorSpec:
    tensor_type = value_info.type.tensor_type
    dims: list[int | str | None] = []
    if tensor_type.HasField("shape"):
        for dim in tensor_type.shape.dim:
            if dim.HasField("dim_value"):
                dims.append(int(dim.dim_value))
            elif dim.HasField("dim_param"):
                dims.append(dim.dim_param)
            else:
                dims.append(None)
    try:
        import onnx
        dtype = onnx.TensorProto.DataType.Name(tensor_type.elem_type).lower()
    except Exception:
        dtype = str(tensor_type.elem_type)
    return TensorSpec(name=value_info.name, shape=dims, dtype=dtype)


def _attribute(attr: Any) -> Any:
    try:
        import onnx
        return onnx.helper.get_attribute_value(attr)
    except Exception:
        return str(attr)


class OnnxAdapter(Adapter):
    name = "onnx"
    extensions = (".onnx", ".pb")
    priority = 10
    capabilities = (
        Capability("static-graph"), Capability("shapes"), Capability("parameters"),
        Capability("subgraphs"), Capability("dynamic-dimensions"),
    )

    def load(self, source: Any, **options: Any) -> GraphIR:
        try:
            import onnx
        except ImportError as exc:
            raise OptionalDependencyError(
                "ONNX import requires the onnx package",
                hint="Install nn-davinci[onnx].",
            ) from exc
        if hasattr(source, "graph"):
            model = source
        else:
            model = onnx.load(str(source), load_external_data=options.get("load_external_data", True))
        if options.get("infer_shapes", True):
            try:
                model = onnx.shape_inference.infer_shapes(model)
            except Exception:
                pass
        graph_proto = model.graph
        known_specs = {
            value.name: _shape(value)
            for value in list(graph_proto.input) + list(graph_proto.value_info) + list(graph_proto.output)
        }
        initializers = {item.name: item for item in graph_proto.initializer}
        nodes: list[Node] = []
        producers: dict[str, tuple[str, str]] = {}
        input_nodes: dict[str, str] = {}
        initializer_names = set(initializers)
        initializer_owners: dict[str, str] = {}

        for index, value in enumerate(graph_proto.input):
            if value.name in initializer_names:
                continue
            node_id = stable_id("node", f"input:{value.name}")
            port_id = f"{node_id}:output:0"
            spec = known_specs.get(value.name)
            nodes.append(Node(
                id=node_id, name=value.name or f"Input {index}", op_type="Input",
                category="input", path=value.name, level="operation",
                outputs=[Port(port_id, value.name, "output", spec)],
                source={"onnx_value": value.name},
            ))
            producers[value.name] = (node_id, port_id)
            input_nodes[value.name] = node_id

        operator_nodes: list[Node] = []
        nested_nodes: list[Node] = []
        nested_edges: list[Edge] = []
        nested_groups: list[Subgraph] = []
        for index, item in enumerate(graph_proto.node):
            original_name = item.name or f"{item.op_type}_{index}"
            node_id = stable_id("node", f"onnx:{original_name}:{index}")
            path = item.name or original_name
            in_ports = [
                Port(f"{node_id}:input:{i}", value or f"input_{i}", "input", known_specs.get(value))
                for i, value in enumerate(item.input)
            ]
            out_ports = [
                Port(f"{node_id}:output:{i}", value or f"output_{i}", "output", known_specs.get(value))
                for i, value in enumerate(item.output)
            ]
            params = 0
            trainable = 0
            parameter_tensors: list[dict] = []
            shared_weights: list[str] = []
            for value in item.input:
                if value in initializers:
                    init = initializers[value]
                    count = 1
                    for dim in init.dims:
                        count *= int(dim)
                    if value in initializer_owners:
                        shared_weights.append(value)
                    else:
                        initializer_owners[value] = node_id
                        params += count
                        trainable += count
                    parameter_tensors.append({"name": value, "shape": list(init.dims), "elements": count})
            attributes = {}
            for attr in item.attribute:
                value = _attribute(attr)
                if hasattr(value, "SerializeToString"):
                    value = f"<{type(value).__name__}>"
                elif isinstance(value, bytes):
                    value = value.decode("utf-8", errors="replace")
                elif isinstance(value, tuple):
                    value = list(value)
                attributes[attr.name] = value
            if parameter_tensors:
                attributes["parameter_tensors"] = parameter_tensors
            category = _category(item.op_type)
            namespace = "/".join(path.split("/")[:-1])
            operator_nodes.append(Node(
                id=node_id, name=original_name, op_type=item.op_type, category=category,
                path=path, namespace=namespace, inputs=in_ports, outputs=out_ports,
                parameters=params, trainable_parameters=trainable, attributes=attributes,
                shared_weights=shared_weights,
                source={"format": "onnx", "index": index, "domain": item.domain},
            ))
            child_nodes, child_edges, child_groups = _onnx_control_subgraphs(item, node_id, known_specs)
            nested_nodes.extend(child_nodes)
            nested_edges.extend(child_edges)
            nested_groups.extend(child_groups)
            for port, value in zip(out_ports, item.output):
                if value:
                    producers[value] = (node_id, port.id)
        nodes.extend(operator_nodes)
        nodes.extend(nested_nodes)

        edges: list[Edge] = list(nested_edges)
        for node in operator_nodes:
            for port in node.inputs:
                value_name = port.name
                if value_name in initializers or not value_name:
                    continue
                producer = producers.get(value_name)
                if producer:
                    edges.append(Edge.create(
                        producer[0], node.id, source_port=producer[1], target_port=port.id,
                        tensor=known_specs.get(value_name), label=value_name,
                    ))

        output_specs: list[TensorSpec] = []
        for index, value in enumerate(graph_proto.output):
            spec = known_specs.get(value.name, TensorSpec(name=value.name))
            output_specs.append(spec)
            node_id = stable_id("node", f"output:{value.name}")
            port_id = f"{node_id}:input:0"
            nodes.append(Node(
                id=node_id, name=value.name or f"Output {index}", op_type="Output",
                category="output", path=value.name, inputs=[Port(port_id, value.name, "input", spec)],
                source={"onnx_value": value.name},
            ))
            if value.name in producers:
                producer = producers[value.name]
                edges.append(Edge.create(
                    producer[0], node_id, source_port=producer[1], target_port=port_id,
                    tensor=spec, label=value.name,
                ))

        namespaces: dict[str, list[str]] = {}
        for node in operator_nodes:
            if node.namespace:
                namespaces.setdefault(node.namespace, []).append(node.id)
        groups = [
            Subgraph(id=stable_id("group", name), name=name.split("/")[-1], node_ids=member_ids, level="module")
            for name, member_ids in sorted(namespaces.items())
        ] + nested_groups
        metadata = {
            "source_format": "onnx",
            "producer": model.producer_name,
            "producer_version": model.producer_version,
            "opset": [{"domain": item.domain, "version": item.version} for item in model.opset_import],
            "model_version": int(model.model_version),
            "doc_string": model.doc_string,
            "shared_initializers": {name: owner for name, owner in initializer_owners.items() if sum(name in node.input for node in graph_proto.node) > 1},
            "control_subgraphs": [group.attributes for group in nested_groups],
        }
        return GraphIR(
            name=graph_proto.name or Path(str(source)).stem,
            nodes=nodes, edges=edges, subgraphs=groups,
            inputs=[known_specs[item.name] for item in graph_proto.input if item.name not in initializer_names],
            outputs=output_specs, metadata=metadata,
        )


def _category(op_type: str) -> str:
    from ..operators import operator_specification

    registered = operator_specification(op_type)
    if registered:
        return str(registered["category"])
    lowered = op_type.lower()
    rules = {
        "conv": "convolution", "pool": "pooling", "relu": "activation", "gelu": "activation",
        "sigmoid": "activation", "softmax": "activation", "norm": "normalization",
        "matmul": "linear", "gemm": "linear", "linear": "linear", "attention": "attention",
        "embed": "embedding", "concat": "merge", "add": "merge", "mul": "merge",
        "router": "routing", "expert": "routing",
    }
    return next((category for needle, category in rules.items() if needle in lowered), "operation")


def _onnx_control_subgraphs(
    parent: Any,
    parent_id: str,
    known_specs: dict[str, TensorSpec],
) -> tuple[list[Node], list[Edge], list[Subgraph]]:
    try:
        import onnx
    except ImportError:
        return [], [], []
    nodes: list[Node] = []
    edges: list[Edge] = []
    groups: list[Subgraph] = []
    for attribute in parent.attribute:
        protos = []
        if attribute.type == onnx.AttributeProto.GRAPH:
            protos = [attribute.g]
        elif attribute.type == onnx.AttributeProto.GRAPHS:
            protos = list(attribute.graphs)
        for graph_index, graph_proto in enumerate(protos):
            prefix = f"{parent.name or parent.op_type}/{attribute.name}/{graph_index}"
            producers: dict[str, str] = {}
            member_ids: list[str] = []
            initializer_names = {item.name for item in graph_proto.initializer}
            initializer_owners: set[str] = set()
            internal_incoming: dict[str, int] = {}
            for index, item in enumerate(graph_proto.node):
                node_id = stable_id("node", f"onnx-subgraph:{prefix}:{item.name or item.op_type}:{index}")
                member_ids.append(node_id)
                parameters = 0
                parameter_tensors = []
                for value in item.input:
                    initializer = next((tensor for tensor in graph_proto.initializer if tensor.name == value), None)
                    if initializer is None:
                        continue
                    count = 1
                    for dimension in initializer.dims:
                        count *= int(dimension)
                    if value not in initializer_owners:
                        parameters += count
                        initializer_owners.add(value)
                    parameter_tensors.append({"name": value, "shape": list(initializer.dims), "elements": count})
                node = Node(
                    id=node_id,
                    name=item.name or f"{item.op_type}_{index}",
                    op_type=item.op_type,
                    category=_category(item.op_type),
                    path=f"{prefix}/{item.name or item.op_type}",
                    namespace=prefix,
                    parameters=parameters,
                    trainable_parameters=parameters,
                    attributes={"parameter_tensors": parameter_tensors} if parameter_tensors else {},
                    source={"format": "onnx_subgraph", "parent_node": parent_id, "attribute": attribute.name, "index": index},
                    inputs=[Port(f"{node_id}:input:{port_index}", value, "input", known_specs.get(value)) for port_index, value in enumerate(item.input)],
                    outputs=[Port(f"{node_id}:output:{port_index}", value, "output", known_specs.get(value)) for port_index, value in enumerate(item.output)],
                )
                nodes.append(node)
                internal_incoming[node_id] = 0
                for value in item.output:
                    producers[value] = node_id
            node_map = {node.id: node for node in nodes if node.id in member_ids}
            for node in node_map.values():
                for port in node.inputs:
                    if port.name in initializer_names:
                        continue
                    source_id = producers.get(port.name)
                    if source_id and source_id != node.id:
                        source = node_map[source_id]
                        source_port = next((item.id for item in source.outputs if item.name == port.name), None)
                        edges.append(Edge.create(source_id, node.id, source_port=source_port, target_port=port.id, tensor=port.tensor))
                        internal_incoming[node.id] += 1
            for node_id, count in internal_incoming.items():
                if count == 0:
                    control = Edge.create(parent_id, node_id, kind="control", label=attribute.name)
                    control.attributes["semantic"] = "control-subgraph"
                    edges.append(control)
            groups.append(Subgraph(
                stable_id("group", f"onnx-subgraph:{prefix}"),
                f"{attribute.name} ({graph_proto.name or graph_index})",
                member_ids,
                level="subgraph",
                attributes={
                    "path": prefix,
                    "parent_node": parent_id,
                    "attribute": attribute.name,
                    "graph_name": graph_proto.name,
                    "node_count": len(member_ids),
                },
            ))
    return nodes, edges, groups
