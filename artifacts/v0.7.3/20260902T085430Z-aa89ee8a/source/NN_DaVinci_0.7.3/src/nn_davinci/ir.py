from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha1
from typing import Any, Iterable

from .errors import ValidationError

GRAPH_IR_VERSION = "1.0"


def stable_id(kind: str, value: str) -> str:
    slug = "".join(c.lower() if c.isalnum() else "_" for c in value).strip("_")[:42]
    digest = sha1(f"{kind}:{value}".encode("utf-8")).hexdigest()[:8]
    return f"{kind}_{slug or 'item'}_{digest}"


@dataclass(slots=True)
class TensorSpec:
    name: str = ""
    shape: list[int | str | None] = field(default_factory=list)
    dtype: str = "unknown"
    semantic: str | None = None
    size_bytes: int | None = None
    dynamic_axes: dict[int, str] = field(default_factory=dict)

    def infer_size_bytes(self) -> int | None:
        if self.size_bytes is not None:
            return self.size_bytes
        widths = {
            "bool": 1, "uint8": 1, "int8": 1, "float16": 2, "bfloat16": 2,
            "int16": 2, "float32": 4, "int32": 4, "float64": 8, "int64": 8,
            "complex64": 8, "complex128": 16,
        }
        width = widths.get(self.dtype.lower().replace("torch.", ""))
        if not width:
            return None
        total = width
        for dim in self.shape:
            if not isinstance(dim, int) or dim < 0:
                return None
            total *= dim
        return total


@dataclass(slots=True)
class Port:
    id: str
    name: str
    direction: str
    tensor: TensorSpec | None = None
    variadic: bool = False


@dataclass(slots=True)
class Node:
    id: str
    name: str
    op_type: str
    category: str = "operation"
    path: str = ""
    namespace: str = ""
    inputs: list[Port] = field(default_factory=list)
    outputs: list[Port] = field(default_factory=list)
    parent: str | None = None
    level: str = "operation"
    parameters: int = 0
    trainable_parameters: int = 0
    buffers: int = 0
    shared_weights: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    source: dict[str, Any] = field(default_factory=dict)
    analysis: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    visible: bool = True

    @classmethod
    def create(cls, name: str, op_type: str, **kwargs: Any) -> "Node":
        path = kwargs.get("path") or name
        return cls(id=stable_id("node", path), name=name, op_type=op_type, **kwargs)


@dataclass(slots=True)
class Edge:
    id: str
    source: str
    target: str
    source_port: str | None = None
    target_port: str | None = None
    tensor: TensorSpec | None = None
    kind: str = "data"
    label: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    visible: bool = True

    @classmethod
    def create(cls, source: str, target: str, **kwargs: Any) -> "Edge":
        salt = f"{source}:{kwargs.get('source_port', '')}->{target}:{kwargs.get('target_port', '')}:{kwargs.get('kind', 'data')}"
        return cls(id=stable_id("edge", salt), source=source, target=target, **kwargs)


@dataclass(slots=True)
class Subgraph:
    id: str
    name: str
    node_ids: list[str] = field(default_factory=list)
    parent: str | None = None
    level: str = "module"
    collapsed: bool = False
    locked: bool = False
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Annotation:
    id: str
    kind: str
    text: str = ""
    target_ids: list[str] = field(default_factory=list)
    geometry: dict[str, float] = field(default_factory=dict)
    style: dict[str, Any] = field(default_factory=dict)
    panel: str | None = None


@dataclass(slots=True)
class LayoutConstraint:
    target_ids: list[str]
    kind: str
    value: Any = None
    locked: bool = False


def _tensor_from_dict(data: dict | None) -> TensorSpec | None:
    if not data:
        return None
    payload = dict(data)
    payload["dynamic_axes"] = {int(key): value for key, value in payload.get("dynamic_axes", {}).items()}
    return TensorSpec(**payload)


def _port_from_dict(data: dict) -> Port:
    data = dict(data)
    data["tensor"] = _tensor_from_dict(data.get("tensor"))
    return Port(**data)


def _node_from_dict(data: dict) -> Node:
    data = dict(data)
    data["inputs"] = [_port_from_dict(item) for item in data.get("inputs", [])]
    data["outputs"] = [_port_from_dict(item) for item in data.get("outputs", [])]
    return Node(**data)


def _edge_from_dict(data: dict) -> Edge:
    data = dict(data)
    data["tensor"] = _tensor_from_dict(data.get("tensor"))
    return Edge(**data)


@dataclass(slots=True)
class GraphIR:
    name: str
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    subgraphs: list[Subgraph] = field(default_factory=list)
    annotations: list[Annotation] = field(default_factory=list)
    constraints: list[LayoutConstraint] = field(default_factory=list)
    inputs: list[TensorSpec] = field(default_factory=list)
    outputs: list[TensorSpec] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    analysis: dict[str, Any] = field(default_factory=dict)
    ir_version: str = GRAPH_IR_VERSION

    def node_map(self) -> dict[str, Node]:
        return {node.id: node for node in self.nodes}

    def edge_map(self) -> dict[str, Edge]:
        return {edge.id: edge for edge in self.edges}

    def children(self, parent_id: str | None) -> list[Node]:
        return [node for node in self.nodes if node.parent == parent_id]

    def validate(self) -> "GraphIR":
        errors: list[str] = []
        if str(self.ir_version).split(".", 1)[0] != GRAPH_IR_VERSION.split(".", 1)[0]:
            errors.append(
                f"Graph IR major version {self.ir_version!r} is incompatible with supported version {GRAPH_IR_VERSION!r}"
            )
        node_ids = [node.id for node in self.nodes]
        edge_ids = [edge.id for edge in self.edges]
        group_ids = [group.id for group in self.subgraphs]
        if len(node_ids) != len(set(node_ids)):
            errors.append("node IDs must be unique")
        if len(edge_ids) != len(set(edge_ids)):
            errors.append("edge IDs must be unique")
        if len(group_ids) != len(set(group_ids)):
            errors.append("subgraph IDs must be unique")
        known_nodes = set(node_ids)
        known_groups = set(group_ids)
        output_ports: dict[str, set[str]] = {}
        input_ports: dict[str, set[str]] = {}
        for node in self.nodes:
            if node.parent and node.parent not in known_groups and node.parent not in known_nodes:
                errors.append(f"node {node.id!r} references missing parent {node.parent!r}")
            port_ids = [port.id for port in node.inputs + node.outputs]
            if len(port_ids) != len(set(port_ids)):
                errors.append(f"node {node.id!r} has duplicate port IDs")
            output_ports[node.id] = {port.id for port in node.outputs}
            input_ports[node.id] = {port.id for port in node.inputs}
        for edge in self.edges:
            if edge.source not in known_nodes:
                errors.append(f"edge {edge.id!r} has missing source {edge.source!r}")
            if edge.target not in known_nodes:
                errors.append(f"edge {edge.id!r} has missing target {edge.target!r}")
            if edge.source_port and edge.source in known_nodes and edge.source_port not in output_ports[edge.source]:
                errors.append(f"edge {edge.id!r} references missing source port {edge.source_port!r}")
            if edge.target_port and edge.target in known_nodes and edge.target_port not in input_ports[edge.target]:
                errors.append(f"edge {edge.id!r} references missing target port {edge.target_port!r}")
        for group in self.subgraphs:
            missing = set(group.node_ids) - known_nodes
            if missing:
                errors.append(f"subgraph {group.id!r} references missing nodes {sorted(missing)!r}")
            if group.parent and group.parent not in known_groups:
                errors.append(f"subgraph {group.id!r} references missing parent subgraph {group.parent!r}")
        known_targets = known_nodes | known_groups | set(edge_ids)
        for annotation in self.annotations:
            missing = set(annotation.target_ids) - known_targets
            if missing:
                errors.append(f"annotation {annotation.id!r} references missing targets {sorted(missing)!r}")
        for index, constraint in enumerate(self.constraints):
            missing = set(constraint.target_ids) - known_targets
            if missing:
                errors.append(f"constraint {index} references missing targets {sorted(missing)!r}")
        if errors:
            raise ValidationError(
                f"Graph IR contains {len(errors)} validation error(s)",
                hint="Inspect the reported IDs and adapter output.",
                details={"errors": errors},
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GraphIR":
        payload = dict(data)
        source_version = str(payload.get("ir_version", "1.0"))
        source_major = source_version.split(".", 1)[0]
        current_major = GRAPH_IR_VERSION.split(".", 1)[0]
        if source_version != GRAPH_IR_VERSION and source_major == current_major:
            metadata = dict(payload.get("metadata", {}))
            migrations = list(metadata.get("schema_migrations", []))
            marker = {"from": source_version, "to": GRAPH_IR_VERSION, "reason": "0.3 semantic-canvas compatibility"}
            if marker not in migrations:
                migrations.append(marker)
            metadata["schema_migrations"] = migrations
            payload["metadata"] = metadata
            payload["ir_version"] = GRAPH_IR_VERSION
        elif source_major != current_major:
            raise ValidationError(
                f"Graph IR major version {source_version!r} is incompatible with supported version {GRAPH_IR_VERSION!r}",
                hint="Open the graph with a compatible release or migrate its Graph IR schema.",
            )
        payload["nodes"] = [_node_from_dict(item) for item in payload.get("nodes", [])]
        payload["edges"] = [_edge_from_dict(item) for item in payload.get("edges", [])]
        payload["subgraphs"] = [Subgraph(**item) for item in payload.get("subgraphs", [])]
        payload["annotations"] = [Annotation(**item) for item in payload.get("annotations", [])]
        payload["constraints"] = [LayoutConstraint(**item) for item in payload.get("constraints", [])]
        payload["inputs"] = [_tensor_from_dict(item) for item in payload.get("inputs", [])]
        payload["outputs"] = [_tensor_from_dict(item) for item in payload.get("outputs", [])]
        return cls(**payload).validate()

    def copy(self) -> "GraphIR":
        return GraphIR.from_dict(self.to_dict())

    def induced(self, node_ids: Iterable[str], *, name: str | None = None) -> "GraphIR":
        selected = set(node_ids)
        retained_groups = [group for group in self.subgraphs if selected.intersection(group.node_ids)]
        retained_group_ids = {group.id for group in retained_groups}
        retained_edge_ids = {edge.id for edge in self.edges if edge.source in selected and edge.target in selected}
        retained_targets = selected | retained_group_ids | retained_edge_ids
        graph = GraphIR(
            name=name or self.name,
            nodes=[_node_from_dict(asdict(node)) for node in self.nodes if node.id in selected],
            edges=[_edge_from_dict(asdict(edge)) for edge in self.edges if edge.source in selected and edge.target in selected],
            subgraphs=[Subgraph(**asdict(group)) for group in retained_groups],
            annotations=[Annotation(**{**asdict(item), "target_ids": [target for target in item.target_ids if target in retained_targets]}) for item in self.annotations if not item.target_ids or retained_targets.intersection(item.target_ids)],
            constraints=[LayoutConstraint(**{**asdict(item), "target_ids": [target for target in item.target_ids if target in retained_targets]}) for item in self.constraints if retained_targets.intersection(item.target_ids)],
            inputs=[TensorSpec(**asdict(item)) for item in self.inputs],
            outputs=[TensorSpec(**asdict(item)) for item in self.outputs],
            metadata=dict(self.metadata),
            analysis=dict(self.analysis),
            ir_version=self.ir_version,
        )
        for group in graph.subgraphs:
            group.node_ids = [item for item in group.node_ids if item in selected]
            if group.parent not in retained_group_ids:
                group.parent = None
        return graph
