from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..errors import AdapterError, OptionalDependencyError
from ..ir import Edge, GraphIR, Node, Port, Subgraph, TensorSpec, stable_id
from .base import Adapter, Capability


def _load_mapping(source: Any) -> dict:
    if isinstance(source, dict):
        return source
    path = Path(source)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as exc:
            raise OptionalDependencyError(
                "YAML model descriptions require PyYAML",
                hint="Install nn-davinci[yaml] or use JSON.",
            ) from exc
        return yaml.safe_load(text)
    return json.loads(text)


def _tensor(value: Any, *, name: str = "") -> TensorSpec | None:
    if value is None:
        return None
    if isinstance(value, TensorSpec):
        return value
    if isinstance(value, (list, tuple)):
        return TensorSpec(name=name, shape=list(value))
    return TensorSpec(**value)


class ManualAdapter(Adapter):
    name = "manual"
    extensions = (".json", ".yaml", ".yml", ".nndv", ".nndv.json")
    priority = 2
    capabilities = (
        Capability("hierarchy"), Capability("manual-graph"), Capability("tensor-metadata"),
    )

    def accepts(self, source: Any) -> bool:
        return isinstance(source, dict) or super().accepts(source)

    def load(self, source: Any, **options: Any) -> GraphIR:
        data = _load_mapping(source)
        if "project_version" in data and "graph" in data:
            return GraphIR.from_dict(data["graph"])
        if "ir_version" in data and "nodes" in data:
            return GraphIR.from_dict(data)
        return self._from_description(data)

    def _from_description(self, data: dict) -> GraphIR:
        name = data.get("name", "Untitled network")
        raw_nodes = data.get("nodes") or data.get("layers")
        if not isinstance(raw_nodes, list):
            raise AdapterError(
                "Manual model description needs a 'nodes' or 'layers' list",
                hint="See examples/resnet.json for the accepted schema.",
            )
        nodes: list[Node] = []
        aliases: dict[str, str] = {}
        for index, item in enumerate(raw_nodes):
            if isinstance(item, str):
                item = {"name": item, "op_type": item}
            item = dict(item)
            node_name = item.pop("name", f"layer_{index}")
            path = item.pop("path", node_name)
            node_id = item.pop("id", stable_id("node", path))
            op_type = item.pop("op_type", item.pop("type", "Operation"))
            raw_inputs = item.pop("inputs", [])
            raw_outputs = item.pop("outputs", [])
            input_ports = [self._port(node_id, value, "input", i) for i, value in enumerate(raw_inputs)]
            output_ports = [self._port(node_id, value, "output", i) for i, value in enumerate(raw_outputs)]
            allowed = {
                "category", "namespace", "parent", "level", "parameters", "trainable_parameters",
                "buffers", "shared_weights", "attributes", "source", "analysis", "tags", "visible",
            }
            attributes = dict(item.pop("attributes", {}))
            attributes.update({key: value for key, value in item.items() if key not in allowed})
            kwargs = {key: value for key, value in item.items() if key in allowed and key != "attributes"}
            nodes.append(Node(
                id=node_id, name=node_name, op_type=op_type, path=path,
                inputs=input_ports, outputs=output_ports, attributes=attributes, **kwargs,
            ))
            aliases[node_name] = node_id
            aliases[path] = node_id
            aliases[node_id] = node_id

        raw_edges = data.get("edges", [])
        if not raw_edges and len(nodes) > 1:
            raw_edges = [{"source": nodes[i].id, "target": nodes[i + 1].id} for i in range(len(nodes) - 1)]
        edges: list[Edge] = []
        for item in raw_edges:
            if isinstance(item, (list, tuple)):
                item = {"source": item[0], "target": item[1]}
            item = dict(item)
            source_name = item.pop("source")
            target_name = item.pop("target")
            source_id = aliases.get(source_name, source_name)
            target_id = aliases.get(target_name, target_name)
            tensor = _tensor(item.pop("tensor", None))
            edge_id = item.pop("id", None)
            edge = Edge.create(source_id, target_id, tensor=tensor, **item)
            if edge_id:
                edge.id = edge_id
            edges.append(edge)

        groups = []
        for index, item in enumerate(data.get("subgraphs", data.get("groups", []))):
            item = dict(item)
            group_name = item.pop("name", f"Group {index + 1}")
            members = [aliases.get(member, member) for member in item.pop("node_ids", item.pop("nodes", []))]
            groups.append(Subgraph(id=item.pop("id", stable_id("group", group_name)), name=group_name, node_ids=members, **item))

        graph = GraphIR(
            name=name, nodes=nodes, edges=edges, subgraphs=groups,
            inputs=[_tensor(item) for item in data.get("inputs", []) if item is not None],
            outputs=[_tensor(item) for item in data.get("outputs", []) if item is not None],
            metadata={**data.get("metadata", {}), "source_format": "manual"},
        )
        return graph.validate()

    @staticmethod
    def _port(node_id: str, value: Any, direction: str, index: int) -> Port:
        if isinstance(value, str):
            value = {"name": value}
        elif isinstance(value, (list, tuple)):
            value = {"name": f"{direction}_{index}", "shape": list(value)}
        value = dict(value)
        name = value.pop("name", f"{direction}_{index}")
        port_id = value.pop("id", f"{node_id}:{direction}:{index}")
        tensor_data = value.pop("tensor", None)
        if tensor_data is None and any(key in value for key in ("shape", "dtype", "semantic")):
            tensor_data = {key: value.pop(key) for key in list(value) if key in TensorSpec.__dataclass_fields__}
            tensor_data.setdefault("name", name)
        return Port(id=port_id, name=name, direction=direction, tensor=_tensor(tensor_data), **value)

