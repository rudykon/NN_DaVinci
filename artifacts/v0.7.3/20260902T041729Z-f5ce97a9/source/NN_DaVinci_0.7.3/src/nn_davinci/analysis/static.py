from __future__ import annotations

from collections import defaultdict, deque
from math import prod
from typing import Any

from ..ir import GraphIR, Node, TensorSpec


def _integer_shape(spec: TensorSpec | None) -> list[int] | None:
    if spec is None or not spec.shape or any(not isinstance(dim, int) or dim < 0 for dim in spec.shape):
        return None
    return [int(dim) for dim in spec.shape]


def _pair(value: Any, default: int = 1) -> tuple[int, int]:
    if isinstance(value, (list, tuple)):
        return (int(value[0]), int(value[-1]))
    if isinstance(value, int):
        return (value, value)
    return (default, default)


def estimate_flops(node: Node) -> int | None:
    op = node.op_type.lower()
    output = _integer_shape(node.outputs[0].tensor) if node.outputs else None
    input_shape = _integer_shape(node.inputs[0].tensor) if node.inputs else None
    attrs = node.attributes
    if output is None:
        return None
    output_elements = prod(output)
    if "conv" in op:
        kernel = attrs.get("kernel_shape") or attrs.get("kernel_size") or [1, 1]
        kernel_area = prod(kernel) if isinstance(kernel, (list, tuple)) else int(kernel) ** 2
        groups = int(attrs.get("group", attrs.get("groups", 1)) or 1)
        input_channels = input_shape[1] if input_shape and len(input_shape) > 1 else None
        if input_channels is None:
            weights = attrs.get("parameter_tensors", [])
            input_channels = weights[0]["shape"][1] * groups if weights and len(weights[0].get("shape", [])) > 1 else None
        return int(2 * output_elements * input_channels * kernel_area / groups) if input_channels else None
    if any(token in op for token in ("gemm", "linear", "matmul")):
        if input_shape and len(input_shape) >= 2:
            return int(2 * prod(output) * input_shape[-1])
        if node.parameters:
            return int(2 * node.parameters)
    if any(token in op for token in ("attention", "scaled_dot_product")):
        if len(output) >= 3:
            batch = prod(output[:-2]) or 1
            seq, width = output[-2:]
            return int(batch * (4 * seq * width * width + 2 * seq * seq * width))
    if any(token in op for token in ("add", "mul", "relu", "gelu", "sigmoid", "norm", "softmax", "pool")):
        return int(output_elements)
    return None


def estimate_macs(node: Node) -> int | None:
    op = node.op_type.lower()
    flops = estimate_flops(node)
    if flops is None:
        return None
    if any(token in op for token in ("conv", "gemm", "linear", "matmul", "attention", "scaled_dot_product")):
        return flops // 2
    return 0


def _longest_paths(graph: GraphIR) -> tuple[int, dict[str, int], set[str]]:
    visible = {node.id for node in graph.nodes if node.visible}
    incoming: dict[str, set[str]] = {node_id: set() for node_id in visible}
    outgoing: dict[str, set[str]] = {node_id: set() for node_id in visible}
    for edge in graph.edges:
        if edge.visible and edge.source in visible and edge.target in visible and edge.source != edge.target:
            incoming[edge.target].add(edge.source)
            outgoing[edge.source].add(edge.target)
    indegree = {key: len(value) for key, value in incoming.items()}
    queue = deque(sorted(key for key, value in indegree.items() if value == 0))
    depths = {key: 1 for key in visible}
    visited: set[str] = set()
    while queue:
        current = queue.popleft()
        visited.add(current)
        for target in sorted(outgoing[current]):
            depths[target] = max(depths[target], depths[current] + 1)
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    cyclic = visible - visited
    if cyclic:
        for node_id in sorted(cyclic):
            predecessors = incoming[node_id] - cyclic
            depths[node_id] = max((depths[item] + 1 for item in predecessors), default=depths[node_id])
    return max(depths.values(), default=0), depths, cyclic


def _receptive_fields(graph: GraphIR) -> dict[str, dict[str, int]]:
    _, depths, _ = _longest_paths(graph)
    incoming: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        incoming[edge.target].append(edge.source)
    result: dict[str, dict[str, int]] = {}
    for node in sorted(graph.nodes, key=lambda item: (depths.get(item.id, 1), item.id)):
        parents = [result[item] for item in incoming[node.id] if item in result]
        jump_x = max((item["jump_x"] for item in parents), default=1)
        jump_y = max((item["jump_y"] for item in parents), default=1)
        rf_x = max((item["width"] for item in parents), default=1)
        rf_y = max((item["height"] for item in parents), default=1)
        op = node.op_type.lower()
        if "conv" in op or "pool" in op:
            kernel_x, kernel_y = _pair(node.attributes.get("kernel_shape", node.attributes.get("kernel_size", 1)))
            stride_x, stride_y = _pair(node.attributes.get("strides", node.attributes.get("stride", 1)))
            rf_x += (kernel_x - 1) * jump_x
            rf_y += (kernel_y - 1) * jump_y
            jump_x *= stride_x
            jump_y *= stride_y
        result[node.id] = {"width": rf_x, "height": rf_y, "jump_x": jump_x, "jump_y": jump_y}
    return result


def analyze_graph(graph: GraphIR, *, inplace: bool = False) -> dict[str, Any]:
    target = graph if inplace else graph.copy()
    total_parameters = sum(node.parameters for node in target.nodes)
    trainable_parameters = sum(node.trainable_parameters for node in target.nodes)
    total_buffers = sum(node.buffers for node in target.nodes)
    total_flops = 0
    total_macs = 0
    known_flops = 0
    activation_bytes = 0
    unknown_activation_nodes = 0
    compute_nodes = [node for node in target.nodes if node.visible and node.category not in {"input", "output"}]
    unknown_flop_nodes: list[str] = []
    unknown_activation_node_ids: list[str] = []
    for node in target.nodes:
        flops = estimate_flops(node)
        if flops is not None:
            node.analysis["flops"] = flops
            total_flops += flops
            macs = estimate_macs(node)
            if macs is not None:
                node.analysis["macs"] = macs
                total_macs += macs
            if node in compute_nodes:
                known_flops += 1
        elif node in compute_nodes:
            unknown_flop_nodes.append(node.id)
        node_memory = 0
        memory_known = False
        for port in node.outputs:
            if port.tensor:
                size = port.tensor.infer_size_bytes()
                if size is not None:
                    node_memory += size
                    memory_known = True
        if memory_known:
            node.analysis["activation_bytes"] = node_memory
            activation_bytes += node_memory
        elif node.outputs:
            unknown_activation_nodes += 1
            unknown_activation_node_ids.append(node.id)
        if total_parameters:
            node.analysis["parameter_fraction"] = node.parameters / total_parameters
    depth, depths, cyclic = _longest_paths(target)
    receptive_fields = _receptive_fields(target)
    for node in target.nodes:
        node.analysis["depth"] = depths.get(node.id, 1)
        node.analysis["receptive_field"] = receptive_fields.get(node.id, {"width": 1, "height": 1})
    parameter_bottlenecks = sorted(target.nodes, key=lambda item: (-item.parameters, item.id))[:10]
    flop_bottlenecks = sorted(target.nodes, key=lambda item: (-int(item.analysis.get("flops", 0)), item.id))[:10]
    memory_bottlenecks = sorted(target.nodes, key=lambda item: (-int(item.analysis.get("activation_bytes", 0)), item.id))[:10]
    flop_coverage = known_flops / len(compute_nodes) if compute_nodes else 1.0
    activation_nodes = [node for node in target.nodes if node.visible and node.outputs]
    activation_coverage = 1 - unknown_activation_nodes / len(activation_nodes) if activation_nodes else 1.0
    receptive_supported = sum(
        node.category in {"input", "output", "convolution", "pooling", "merge", "activation", "normalization"}
        for node in target.nodes if node.visible
    )
    receptive_coverage = receptive_supported / sum(node.visible for node in target.nodes) if target.nodes else 1.0
    summary = {
        "total_parameters": total_parameters,
        "trainable_parameters": trainable_parameters,
        "non_trainable_parameters": max(0, total_parameters - trainable_parameters),
        "total_buffers": total_buffers,
        "parameter_coverage": 1.0,
        "parameters_label": "imported/declared count",
        "shared_parameter_groups": len(target.metadata.get("shared_parameters", target.metadata.get("shared_initializers", {}))),
        "flops": total_flops,
        "flops_known_subtotal": total_flops,
        "flops_complete": flop_coverage == 1.0,
        "flops_coverage": flop_coverage,
        "flops_label": "analytical estimate" if flop_coverage == 1.0 else "analytical estimate (covered operators only)",
        "unknown_flop_nodes": unknown_flop_nodes,
        "multiply_add_convention": "one multiply-add = 2 FLOPs and 1 MAC",
        "macs_estimate": total_macs,
        "macs_known_subtotal": total_macs,
        "macs_coverage": flop_coverage,
        "activation_bytes": activation_bytes,
        "activation_bytes_known_subtotal": activation_bytes,
        "activation_memory_complete": activation_coverage == 1.0,
        "activation_memory_coverage": activation_coverage,
        "activation_memory_label": "analytical tensor-size estimate",
        "unknown_activation_nodes": unknown_activation_node_ids,
        "depth": depth,
        "longest_path": depth,
        "cyclic_nodes": sorted(cyclic),
        "depth_label": "DAG longest path" if not cyclic else "bounded estimate; graph contains a cycle",
        "receptive_field_coverage": receptive_coverage,
        "receptive_field_label": "exact for supported convolution/pooling paths; conservative through merges/unknown operators",
        "node_count": len(target.nodes),
        "edge_count": len(target.edges),
        "bottlenecks": {
            "parameters": [_bottleneck(item, "parameters") for item in parameter_bottlenecks if item.parameters],
            "flops": [_bottleneck(item, "flops") for item in flop_bottlenecks if item.analysis.get("flops")],
            "activation_memory": [_bottleneck(item, "activation_bytes") for item in memory_bottlenecks if item.analysis.get("activation_bytes")],
        },
        "limitations": [
            "FLOPs are analytical estimates and count multiply-add as two operations.",
            f"FLOPs coverage is {flop_coverage:.1%}; uncovered operators are listed and are not added as zero-cost operations.",
            "Activation memory excludes allocator overhead and tensor lifetime reuse.",
            f"Activation-size coverage is {activation_coverage:.1%}; the value is a known subtotal when coverage is below 100%.",
            "Receptive field is exact for common convolution/pooling chains and conservative at merges.",
            "Static depth is a longest-path measure; cyclic/recurrent graphs require an unroll bound for an execution depth.",
        ],
    }
    target.analysis["static"] = summary
    if inplace:
        graph.analysis["static"] = summary
    return {"graph": target, "summary": summary}


def _bottleneck(node: Node, metric: str) -> dict[str, Any]:
    value = getattr(node, metric, None)
    if value is None:
        value = node.analysis.get(metric, 0)
    return {"node_id": node.id, "name": node.name, "value": value}
