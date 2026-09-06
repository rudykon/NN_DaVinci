from __future__ import annotations

from collections import Counter
from typing import Any

from .analysis import analyze_graph
from .ir import GraphIR, Node


def summarize_graph(graph: GraphIR) -> dict[str, Any]:
    analyzed = analyze_graph(graph)
    summary = analyzed["summary"]
    categories = Counter(node.category for node in graph.nodes)
    operations = Counter(node.op_type for node in graph.nodes)
    inputs = [node for node in graph.nodes if node.category == "input"]
    outputs = [node for node in graph.nodes if node.category == "output"]
    return {
        **summary,
        "name": graph.name,
        "categories": dict(categories.most_common()),
        "top_operations": dict(operations.most_common(10)),
        "inputs": [_endpoint(node) for node in inputs],
        "outputs": [_endpoint(node) for node in outputs],
        "groups": [{"name": item.name, "level": item.level, "nodes": len(item.node_ids)} for item in graph.subgraphs],
        "dynamic_runtime_graph": bool(graph.metadata.get("actual_dynamic_path")),
    }


def generate_caption(graph: GraphIR, *, style: str = "paper") -> str:
    data = summarize_graph(graph)
    dominant = [name for name, count in data["categories"].items() if count and name not in {"input", "output", "operation"}]
    architecture = ", ".join(dominant[:3]) or "neural-network"
    shape_text = ""
    if data["inputs"] and data["outputs"]:
        shape_text = f" Data flow is shown from {data['inputs'][0]['shape']} to {data['outputs'][0]['shape']}."
    if style == "short":
        return f"Architecture of {graph.name} ({data['node_count']} operations, {data['total_parameters']:,} parameters)."
    if style == "presentation":
        return f"{graph.name}: {data['node_count']} operations across {max(1, len(graph.subgraphs))} modules, highlighting {architecture} stages and skip/data-flow connections."
    return (
        f"Architecture of {graph.name}. The diagram contains {data['node_count']} operations and "
        f"{data['edge_count']} data-flow connections, organized around {architecture} components; "
        f"the model has {data['total_parameters']:,} parameters and an analytical FLOPs subtotal of {data['flops']:,} "
        f"at {data['flops_coverage']:.1%} operator coverage."
        f"{shape_text} Dashed containers denote hierarchical modules and routed outer edges denote skip or recurrent connections."
    )


def generate_markdown_report(graph: GraphIR) -> str:
    data = summarize_graph(graph)
    lines = [
        f"# {graph.name}", "", generate_caption(graph), "", "## Summary", "",
        "| Metric | Value | Coverage / label |", "|---|---:|---|",
        f"| Nodes | {data['node_count']:,} | imported topology |", f"| Edges | {data['edge_count']:,} | imported topology |",
        f"| Parameters | {data['total_parameters']:,} | {data['parameter_coverage']:.1%}; {data['parameters_label']} |",
        f"| Trainable parameters | {data['trainable_parameters']:,} | imported/declared |",
        f"| FLOPs known subtotal | {data['flops']:,} | {data['flops_coverage']:.1%}; {data['flops_label']} |",
        f"| MACs known subtotal | {data['macs_estimate']:,} | {data['macs_coverage']:.1%}; {data['multiply_add_convention']} |",
        f"| Activation bytes known subtotal | {data['activation_bytes']:,} | {data['activation_memory_coverage']:.1%}; {data['activation_memory_label']} |",
        f"| Longest path | {data['longest_path']:,} | {data['depth_label']} |",
        f"| Receptive field | per-node | {data['receptive_field_coverage']:.1%}; {data['receptive_field_label']} |",
        "", "## Modules", "",
    ]
    if data["groups"]:
        lines.extend(["| Module | Level | Nodes |", "|---|---|---:|"])
        lines.extend(f"| {item['name']} | {item['level']} | {item['nodes']} |" for item in data["groups"])
    else:
        lines.append("No explicit hierarchical modules were imported.")
    lines.extend(["", "## Bottlenecks", ""])
    for item in data["bottlenecks"]["parameters"][:5]:
        lines.append(f"- `{item['name']}`: {item['value']:,} parameters")
    lines.extend(["", "## Analysis notes", ""])
    lines.extend(f"- {item}" for item in data["limitations"])
    return "\n".join(lines) + "\n"


def _endpoint(node: Node) -> dict[str, Any]:
    ports = node.outputs if node.category == "input" else node.inputs
    tensor = ports[0].tensor if ports and ports[0].tensor else None
    return {"name": node.name, "shape": "×".join(str(item) for item in tensor.shape) if tensor and tensor.shape else "unknown", "dtype": tensor.dtype if tensor else "unknown"}
