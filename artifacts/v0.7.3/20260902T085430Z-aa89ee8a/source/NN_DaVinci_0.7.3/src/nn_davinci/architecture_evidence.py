"""Versioned, source-bound architecture evidence for scientific figures.

The detector deliberately separates *recognition* from layout.  A requested
Scene layout, project/corpus key, graph display name, Python class name, and
file name never participate in family selection.  Evidence comes from Graph
IR topology, importer-declared operation/module identity, ports and tensor
shapes, plus source-ID-backed Semantic View detections.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
import math
import re
from typing import Any, Iterable, Mapping, Sequence

from .errors import ValidationError
from .ir import GraphIR, Node, stable_id


ARCHITECTURE_EVIDENCE_VERSION = "1.0"
ARCHITECTURE_EVIDENCE_FAMILIES = (
    "unknown",
    "cnn",
    "resnet",
    "unet",
    "transformer",
    "moe",
    "multimodal-fusion",
    "diffusion-unet",
)


def _json_semantic_value(value: Any) -> Any:
    """Canonicalize values whose JSON number spelling changes in JavaScript.

    JSON has one number type, so ``0`` and ``0.0`` are the same document
    value.  Browsers stringify both as ``0``.  Evidence digests therefore
    normalize integral finite floats before hashing while preserving every
    non-integral value and all container structure.
    """

    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        return int(value) if math.isfinite(value) and value.is_integer() else value
    if isinstance(value, Mapping):
        return {str(key): _json_semantic_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_semantic_value(item) for item in value]
    return value


@dataclass(slots=True)
class ArchitectureRole:
    id: str
    role: str
    label: str
    confidence: float
    reasons: list[str]
    supporting_node_ids: list[str] = field(default_factory=list)
    supporting_edge_ids: list[str] = field(default_factory=list)
    supporting_port_ids: list[str] = field(default_factory=list)
    repeat_count: int = 1
    order: int = 0
    protected: bool = True
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RepeatedStructure:
    role_id: str
    count: int
    member_node_ids: list[str]
    member_edge_ids: list[str]
    reasons: list[str]


@dataclass(slots=True)
class CriticalRoute:
    id: str
    role: str
    source_role_id: str
    target_role_id: str
    label: str
    confidence: float
    reasons: list[str]
    supporting_node_ids: list[str]
    supporting_edge_ids: list[str]
    supporting_port_ids: list[str]
    protected: bool = True
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ArchitectureEvidence:
    family: str
    confidence: float
    reasons: list[str]
    supporting_node_ids: list[str]
    supporting_edge_ids: list[str]
    supporting_port_ids: list[str]
    detected_roles: list[ArchitectureRole]
    repeated_structure: list[RepeatedStructure]
    critical_routes: list[CriticalRoute]
    alternative_candidates: list[dict[str, Any]]
    unknown_reason: str | None
    source_digest: str
    provenance_digest: str = ""
    evidence_version: str = ARCHITECTURE_EVIDENCE_VERSION
    uncertain_claims: list[dict[str, Any]] = field(default_factory=list)

    def _digest_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("provenance_digest", None)
        return _json_semantic_value(payload)

    def seal(self) -> "ArchitectureEvidence":
        self.provenance_digest = sha256(json.dumps(self._digest_payload(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        return self

    def validate(self, graph: GraphIR | None = None, *, source_digest: str | None = None) -> "ArchitectureEvidence":
        failures: list[str] = []
        if self.evidence_version.split(".", 1)[0] != ARCHITECTURE_EVIDENCE_VERSION.split(".", 1)[0]:
            failures.append(f"unsupported Architecture Evidence version {self.evidence_version!r}")
        if self.family not in ARCHITECTURE_EVIDENCE_FAMILIES:
            failures.append(f"unsupported architecture family {self.family!r}")
        if isinstance(self.confidence, bool) or not 0.0 <= float(self.confidence) <= 1.0:
            failures.append("architecture confidence must be between zero and one")
        if not self.reasons:
            failures.append("architecture evidence needs at least one reason")
        if self.family == "unknown" and not self.unknown_reason:
            failures.append("unknown architecture evidence needs an explicit unknown_reason")
        if self.family != "unknown" and (self.unknown_reason or not self.detected_roles):
            failures.append("known architecture evidence needs roles and cannot carry unknown_reason")
        role_ids = [role.id for role in self.detected_roles]
        if len(role_ids) != len(set(role_ids)):
            failures.append("architecture role IDs must be unique")
        route_ids = [route.id for route in self.critical_routes]
        if len(route_ids) != len(set(route_ids)):
            failures.append("critical route IDs must be unique")
        known_roles = set(role_ids)
        for role in self.detected_roles:
            if not role.role or not role.label or not role.reasons:
                failures.append(f"architecture role {role.id!r} is incomplete")
            if role.repeat_count < 1:
                failures.append(f"architecture role {role.id!r} has invalid repeat_count")
        for route in self.critical_routes:
            if route.source_role_id not in known_roles or route.target_role_id not in known_roles:
                failures.append(f"critical route {route.id!r} has a missing role endpoint")
            if not route.supporting_edge_ids or not route.reasons:
                failures.append(f"critical route {route.id!r} lacks source-edge evidence")
            if not route.protected:
                failures.append(f"critical route {route.id!r} is not protected")
        if source_digest is not None and self.source_digest != source_digest:
            failures.append("Architecture Evidence source digest does not match the Semantic View source digest")
        expected_digest = sha256(json.dumps(self._digest_payload(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        if self.provenance_digest != expected_digest:
            failures.append("Architecture Evidence provenance digest is stale or tampered")
        if graph is not None:
            graph.validate()
            known_nodes = set(graph.node_map())
            known_edges = set(graph.edge_map())
            known_ports = {port.id for node in graph.nodes for port in (*node.inputs, *node.outputs)}
            node_sets = [self.supporting_node_ids]
            edge_sets = [self.supporting_edge_ids]
            port_sets = [self.supporting_port_ids]
            for role in self.detected_roles:
                node_sets.append(role.supporting_node_ids)
                edge_sets.append(role.supporting_edge_ids)
                port_sets.append(role.supporting_port_ids)
            for route in self.critical_routes:
                node_sets.append(route.supporting_node_ids)
                edge_sets.append(route.supporting_edge_ids)
                port_sets.append(route.supporting_port_ids)
            for repeated in self.repeated_structure:
                node_sets.append(repeated.member_node_ids)
                edge_sets.append(repeated.member_edge_ids)
            missing_nodes = set().union(*(set(values) for values in node_sets)) - known_nodes
            missing_edges = set().union(*(set(values) for values in edge_sets)) - known_edges
            missing_ports = set().union(*(set(values) for values in port_sets)) - known_ports
            if missing_nodes:
                failures.append(f"Architecture Evidence references unknown Graph nodes {sorted(missing_nodes)!r}")
            if missing_edges:
                failures.append(f"Architecture Evidence references unknown Graph edges {sorted(missing_edges)!r}")
            if missing_ports:
                failures.append(f"Architecture Evidence references unknown Graph ports {sorted(missing_ports)!r}")
        if failures:
            raise ValidationError(
                f"Architecture Evidence contains {len(failures)} validation error(s)",
                hint="Regenerate Architecture Evidence from the current Graph IR and Semantic View.",
                details={"errors": failures},
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ArchitectureEvidence":
        payload = dict(data)
        payload["detected_roles"] = [ArchitectureRole(**item) for item in payload.get("detected_roles", [])]
        payload["repeated_structure"] = [RepeatedStructure(**item) for item in payload.get("repeated_structure", [])]
        payload["critical_routes"] = [CriticalRoute(**item) for item in payload.get("critical_routes", [])]
        return cls(**payload).validate()


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value))


def _detection_provenance(detection: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    provenance = detection.get("provenance", {})
    if not isinstance(provenance, Mapping):
        return [], []
    nodes = _unique(provenance.get("source_node_ids", []))
    edges = _unique(provenance.get("source_edge_ids", []))
    return nodes, edges


def _valid_detections(graph: GraphIR, detections: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    known_nodes = set(graph.node_map())
    known_edges = set(graph.edge_map())
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for original in detections:
        detection = dict(original)
        semantic_type = str(detection.get("semantic_type", ""))
        nodes, edges = _detection_provenance(detection)
        reasons = [str(reason) for reason in detection.get("reasons", []) if str(reason).strip()]
        confidence = detection.get("confidence")
        if (
            not semantic_type
            or not reasons
            or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0.0 <= float(confidence) <= 1.0
            or not set(nodes).issubset(known_nodes)
            or not set(edges).issubset(known_edges)
        ):
            continue
        detection["provenance"] = {"source_node_ids": nodes, "source_edge_ids": edges}
        result[semantic_type].append(detection)
    return result


def _ports_for(graph: GraphIR, node_ids: Iterable[str], edge_ids: Iterable[str]) -> list[str]:
    selected = set(node_ids)
    ports: list[str] = []
    for node in graph.nodes:
        if node.id in selected:
            ports.extend(port.id for port in (*node.inputs, *node.outputs))
    edge_map = graph.edge_map()
    for edge_id in edge_ids:
        edge = edge_map.get(edge_id)
        if edge is not None:
            ports.extend(port for port in (edge.source_port, edge.target_port) if port)
    return _unique(ports)


def _edges_for(graph: GraphIR, node_ids: Iterable[str], *, incident: bool = False) -> list[str]:
    selected = set(node_ids)
    if incident:
        return [edge.id for edge in graph.edges if edge.source in selected or edge.target in selected]
    return [edge.id for edge in graph.edges if edge.source in selected and edge.target in selected]


def _role(
    graph: GraphIR,
    role: str,
    label: str,
    node_ids: Iterable[str],
    *,
    edge_ids: Iterable[str] = (),
    confidence: float,
    reasons: Sequence[str],
    repeat_count: int = 1,
    order: int,
    attributes: Mapping[str, Any] | None = None,
) -> ArchitectureRole:
    nodes = _unique(node_ids)
    edges = _unique([*edge_ids, *_edges_for(graph, nodes)])
    identity = f"{role}:{order}:{'|'.join(nodes)}"
    return ArchitectureRole(
        id=stable_id("architecture_role", identity),
        role=role,
        label=label,
        confidence=confidence,
        reasons=list(reasons),
        supporting_node_ids=nodes,
        supporting_edge_ids=edges,
        supporting_port_ids=_ports_for(graph, nodes, edges),
        repeat_count=repeat_count,
        order=order,
        attributes=dict(attributes or {}),
    )


def _route(
    graph: GraphIR,
    role: str,
    source: ArchitectureRole,
    target: ArchitectureRole,
    detections: Iterable[Mapping[str, Any]],
    *,
    label: str,
    attributes: Mapping[str, Any] | None = None,
) -> CriticalRoute:
    detection_list = list(detections)
    nodes = _unique(source_id for detection in detection_list for source_id in _detection_provenance(detection)[0])
    edges = _unique(source_id for detection in detection_list for source_id in _detection_provenance(detection)[1])
    reasons = _unique(str(reason) for detection in detection_list for reason in detection.get("reasons", []))
    confidence = min((float(detection["confidence"]) for detection in detection_list), default=1.0)
    identity = f"{role}:{source.id}:{target.id}:{'|'.join(edges)}"
    return CriticalRoute(
        id=stable_id("architecture_route", identity),
        role=role,
        source_role_id=source.id,
        target_role_id=target.id,
        label=label,
        confidence=confidence,
        reasons=reasons or ["Protected source-graph route."],
        supporting_node_ids=nodes,
        supporting_edge_ids=edges,
        supporting_port_ids=_ports_for(graph, nodes, edges),
        attributes=dict(attributes or {}),
    )


def _topological_order(graph: GraphIR) -> tuple[list[str], dict[str, int]]:
    incoming = {node.id: 0 for node in graph.nodes}
    outgoing: dict[str, list[str]] = defaultdict(list)
    original = {node.id: index for index, node in enumerate(graph.nodes)}
    for edge in graph.edges:
        incoming[edge.target] += 1
        outgoing[edge.source].append(edge.target)
    ready = deque(sorted((node_id for node_id, count in incoming.items() if count == 0), key=original.__getitem__))
    ordered: list[str] = []
    while ready:
        node_id = ready.popleft()
        ordered.append(node_id)
        for target in sorted(outgoing[node_id], key=original.__getitem__):
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
    if len(ordered) != len(graph.nodes):
        ordered = [node.id for node in graph.nodes]
    return ordered, {node_id: index for index, node_id in enumerate(ordered)}


def _ancestors(graph: GraphIR, targets: Iterable[str]) -> set[str]:
    incoming: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        incoming[edge.target].append(edge.source)
    result = set(targets)
    queue = deque(result)
    while queue:
        current = queue.popleft()
        for source in incoming[current]:
            if source not in result:
                result.add(source)
                queue.append(source)
    return result


def _descendants(graph: GraphIR, sources: Iterable[str]) -> set[str]:
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        outgoing[edge.source].append(edge.target)
    result = set(sources)
    queue = deque(result)
    while queue:
        current = queue.popleft()
        for target in outgoing[current]:
            if target not in result:
                result.add(target)
                queue.append(target)
    return result


def _module_prefix(node: Node) -> str:
    return (node.path or "").strip(".").split(".", 1)[0].casefold()


def _module_groups(graph: GraphIR, pattern: str) -> list[list[str]]:
    expression = re.compile(pattern, flags=re.IGNORECASE)
    groups: dict[str, list[str]] = defaultdict(list)
    for node in graph.nodes:
        path = (node.path or "").strip(".")
        match = expression.match(path)
        if match:
            groups[match.group(1).casefold()].append(node.id)
    _, order = _topological_order(graph)
    return [nodes for _key, nodes in sorted(groups.items(), key=lambda item: min(order[node_id] for node_id in item[1]))]


def _entity_value(entity: Any, name: str, default: Any = None) -> Any:
    if isinstance(entity, Mapping):
        return entity.get(name, default)
    return getattr(entity, name, default)


def _entity_provenance(entity: Any) -> tuple[list[str], list[str]]:
    provenance = _entity_value(entity, "provenance", {})
    if isinstance(provenance, Mapping):
        return _unique(provenance.get("source_node_ids", [])), _unique(provenance.get("source_edge_ids", []))
    return _unique(getattr(provenance, "source_node_ids", [])), _unique(getattr(provenance, "source_edge_ids", []))


def _operation_text(node: Node) -> str:
    """Return importer-declared operation identity only.

    Display names, source targets, module paths and namespaces are deliberately
    absent: all four are user-controlled lexical material in metamorphic tests.
    """

    return f"{node.op_type} {node.category}".casefold()


def _operation_is(node: Node, *tokens: str) -> bool:
    declared = _operation_text(node)
    return any(token.casefold() in declared for token in tokens)


def _node_shape(node: Node) -> tuple[int | str | None, ...]:
    for port in node.outputs:
        if port.tensor is not None and port.tensor.shape:
            return tuple(port.tensor.shape)
    for port in node.inputs:
        if port.tensor is not None and port.tensor.shape:
            return tuple(port.tensor.shape)
    return ()


def _spatial_signature(node: Node) -> tuple[int | str | None, ...] | None:
    shape = _node_shape(node)
    return shape[-3:] if len(shape) >= 4 else None


def _graph_maps(graph: GraphIR) -> tuple[dict[str, list[Any]], dict[str, list[Any]]]:
    incoming: dict[str, list[Any]] = defaultdict(list)
    outgoing: dict[str, list[Any]] = defaultdict(list)
    for edge in graph.edges:
        incoming[edge.target].append(edge)
        outgoing[edge.source].append(edge)
    return incoming, outgoing


def _depths(graph: GraphIR) -> dict[str, int]:
    """Compute array-order-independent longest-path depths for a DAG."""

    incoming, outgoing = _graph_maps(graph)
    remaining = {node.id: len(incoming[node.id]) for node in graph.nodes}
    depth = {node.id: 0 for node in graph.nodes}
    ready = sorted(node_id for node_id, count in remaining.items() if count == 0)
    visited = 0
    while ready:
        node_id = ready.pop(0)
        visited += 1
        for edge in sorted(outgoing[node_id], key=lambda item: item.id):
            depth[edge.target] = max(depth[edge.target], depth[node_id] + 1)
            remaining[edge.target] -= 1
            if remaining[edge.target] == 0:
                ready.append(edge.target)
                ready.sort()
    if visited != len(graph.nodes):
        # Cyclic graphs can still be preserved, but acyclic architecture claims
        # below will not be manufactured from their fallback depths.
        return {node.id: 0 for node in graph.nodes}
    return depth


def _input_nodes(graph: GraphIR) -> list[Node]:
    return [node for node in graph.nodes if node.category.casefold() == "input" or node.op_type.casefold() == "input"]


def _output_nodes(graph: GraphIR) -> list[Node]:
    return [node for node in graph.nodes if node.category.casefold() == "output" or node.op_type.casefold() == "output"]


def _source_detection_record(
    semantic_type: str,
    node_ids: Iterable[str],
    edge_ids: Iterable[str],
    confidence: float,
    reason: str,
    *,
    attributes: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "semantic_type": semantic_type,
        "confidence": confidence,
        "reasons": [reason],
        "provenance": {
            "source_node_ids": _unique(node_ids),
            "source_edge_ids": _unique(edge_ids),
        },
        "attributes": dict(attributes or {}),
        "unknown": False,
        "evidence_kind": "typed-operation-topology-shape",
    }


def _structural_detection_map(
    graph: GraphIR,
    inherited: Mapping[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Recognize supported families without corpus or lexical identifiers."""

    nodes = graph.node_map()
    incoming, outgoing = _graph_maps(graph)
    depth = _depths(graph)
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)

    # A declared attention op must participate in the dataflow.  Its display
    # name and module path are never consulted.
    for node in graph.nodes:
        if _operation_is(node, "attention") and incoming[node.id] and outgoing[node.id]:
            incident = [edge.id for edge in (*incoming[node.id], *outgoing[node.id])]
            neighbors = [node.id, *(edge.source for edge in incoming[node.id]), *(edge.target for edge in outgoing[node.id])]
            result["attention"].append(_source_detection_record(
                "attention", neighbors, incident, 0.96,
                "An importer-declared attention operation has observable fan-in and fan-out.",
                attributes={"attention_node_id": node.id},
            ))

    # An elementwise add with two source edges is merge evidence.  Family
    # selection later requires repeated spatial groups or repeated attention,
    # so an isolated arithmetic add cannot create a family claim.
    for node in graph.nodes:
        if len(incoming[node.id]) < 2 or not _operation_is(node, "add"):
            continue
        merge_edges = incoming[node.id]
        members = [node.id, *(edge.source for edge in merge_edges)]
        result["residual_block"].append(_source_detection_record(
            "residual_block", members, (edge.id for edge in merge_edges), 0.86,
            "A typed elementwise add has two converging source branches.",
            attributes={"merge_node_id": node.id, "spatial_signature": list(_spatial_signature(node) or ())},
        ))

    # Cross-scale U-Net skips terminate at typed concatenation operations.  Of
    # the two inputs, the shallower branch is the skip and the deeper branch is
    # required to contain an upsampling operation or a substantial depth gap.
    input_node_ids = {node.id for node in _input_nodes(graph)}
    for target in graph.nodes:
        target_edges = incoming[target.id]
        if len(target_edges) < 2 or not _operation_is(target, "cat", "concat"):
            continue
        explicit_up_edges = [
            edge for edge in target_edges
            if _operation_is(nodes[edge.source], "interpolate", "upsample", "convtranspose")
        ]
        if explicit_up_edges and len(explicit_up_edges) < len(target_edges):
            deep_edges = explicit_up_edges
            skip_edge = min(
                (edge for edge in target_edges if edge not in explicit_up_edges),
                key=lambda edge: (depth[edge.source], _operation_text(nodes[edge.source])),
            )
        else:
            ranked = sorted(target_edges, key=lambda edge: (depth[edge.source], _operation_text(nodes[edge.source])))
            skip_edge = ranked[0]
            deep_edges = ranked[1:]
        deep_ancestors = _ancestors(graph, [edge.source for edge in deep_edges])
        has_upsample = any(
            _operation_is(nodes[node_id], "interpolate", "upsample", "convtranspose")
            for node_id in deep_ancestors
        )
        substantial_gap = max(depth[edge.source] for edge in deep_edges) - depth[skip_edge.source] >= 2
        source_shape = _spatial_signature(nodes[skip_edge.source])
        target_shape = _spatial_signature(target)
        if (
            source_shape is None
            or target_shape is None
            or source_shape[-2:] != target_shape[-2:]
            or not (has_upsample or substantial_gap)
            or skip_edge.source in input_node_ids
        ):
            continue
        result["unet_skip"].append(_source_detection_record(
            "unet_skip", [skip_edge.source, target.id], [skip_edge.id], 0.97,
            "A shallower same-resolution branch bypasses a deeper path and enters a typed concatenation merge.",
            attributes={
                "source_node_id": skip_edge.source,
                "target_node_id": target.id,
                "spatial_signature": list(source_shape),
                "target_depth": depth[target.id],
            },
        ))

    inputs = _input_nodes(graph)
    spatial_inputs = [node for node in inputs if len(_node_shape(node)) >= 4]
    scalar_inputs = [
        node for node in inputs
        if len(_node_shape(node)) <= 2 and "float" in next((port.tensor.dtype.casefold() for port in node.outputs if port.tensor), "")
    ]
    down_nodes: set[str] = set()
    up_nodes: set[str] = set()
    for node in graph.nodes:
        if not _operation_is(node, "conv", "pool", "interpolate", "upsample"):
            continue
        input_areas = [
            int(edge.tensor.shape[-2]) * int(edge.tensor.shape[-1])
            for edge in incoming[node.id]
            if edge.tensor is not None and len(edge.tensor.shape) >= 4
            and isinstance(edge.tensor.shape[-2], int) and isinstance(edge.tensor.shape[-1], int)
        ]
        output_areas = [
            int(edge.tensor.shape[-2]) * int(edge.tensor.shape[-1])
            for edge in outgoing[node.id]
            if edge.tensor is not None and len(edge.tensor.shape) >= 4
            and isinstance(edge.tensor.shape[-2], int) and isinstance(edge.tensor.shape[-1], int)
        ]
        if input_areas and output_areas and min(output_areas) < max(input_areas):
            down_nodes.add(node.id)
        if input_areas and output_areas and max(output_areas) > max(input_areas):
            up_nodes.add(node.id)
        if _operation_is(node, "convtranspose", "upsample", "interpolate"):
            up_nodes.add(node.id)

    # Scalar floating input -> pure conditioning branch -> multiple spatial
    # joins is the denoiser conditioning proof.  Exactly the joining source
    # edges are retained so deleting one changes the evidence.
    if spatial_inputs and scalar_inputs:
        spatial_desc = _descendants(graph, [node.id for node in spatial_inputs])
        scalar_desc = _descendants(graph, [node.id for node in scalar_inputs])
        scalar_only = scalar_desc - spatial_desc
        joins: list[Any] = []
        for target in graph.nodes:
            target_edges = incoming[target.id]
            condition_edges = [edge for edge in target_edges if edge.source in scalar_only]
            spatial_edges = [edge for edge in target_edges if edge.source in spatial_desc]
            if condition_edges and spatial_edges and _operation_is(target, "add", "mul"):
                joins.extend(condition_edges)
        if len(joins) >= 2 and down_nodes and up_nodes:
            condition_nodes = set(scalar_only)
            condition_nodes.update(edge.target for edge in joins)
            condition_edges = [edge.id for edge in joins]
            conditioning = _source_detection_record(
                "timestep_conditioning", condition_nodes, condition_edges, 0.97,
                "A scalar floating input follows a pure branch into multiple spatial merge operations.",
                attributes={"join_count": len(joins), "join_target_ids": [edge.target for edge in joins]},
            )
            result["timestep_conditioning"].append(conditioning)
            component_nodes = spatial_desc | scalar_desc
            result["diffusion_component"].append(_source_detection_record(
                "diffusion_component", component_nodes, _edges_for(graph, component_nodes), 0.95,
                "The acyclic graph contains spatial down/up transitions conditioned by a scalar branch at multiple joins.",
                attributes={"down_node_ids": sorted(down_nodes), "up_node_ids": sorted(up_nodes)},
            ))

    # Top-k routing and a typed stack of independent repeated branches are the
    # minimum MoE proof.  Branch membership is set-theoretic ancestry, not a
    # path prefix such as ``experts.3``.
    topk_nodes = [node for node in graph.nodes if _operation_is(node, "topk")]
    stack_nodes = [node for node in graph.nodes if _operation_is(node, "stack") and len(incoming[node.id]) >= 2]
    embedding_ids = {node.id for node in graph.nodes if _operation_is(node, "embedding")}
    for topk in topk_nodes:
        topk_ancestors = _ancestors(graph, [topk.id])
        if not embedding_ids.intersection(topk_ancestors):
            continue
        for stack in stack_nodes:
            branch_sources = [edge.source for edge in incoming[stack.id]]
            ancestor_sets = [_ancestors(graph, [source]) for source in branch_sources]
            common = set.intersection(*ancestor_sets) if ancestor_sets else set()
            branch_groups = [sorted((ancestors - common) | {source}) for source, ancestors in zip(branch_sources, ancestor_sets, strict=True)]
            if len(branch_groups) < 2 or any(not group for group in branch_groups):
                continue
            router_nodes = (_ancestors(graph, [topk.id]) & _descendants(graph, embedding_ids)) - embedding_ids
            common_downstream = _descendants(graph, [topk.id]) & _descendants(graph, [stack.id])
            combine_nodes = {
                node_id for node_id in common_downstream
                if _operation_is(nodes[node_id], "mul", "sum", "add", "stack")
            }
            topk_shape = _node_shape(topk)
            top_k = topk_shape[-1] if topk_shape and isinstance(topk_shape[-1], int) else None
            evidence_nodes = set().union(*map(set, branch_groups), router_nodes, combine_nodes, {topk.id, stack.id})
            evidence_edges = _edges_for(graph, evidence_nodes)
            result["moe_router_experts"].append(_source_detection_record(
                "moe_router_experts", evidence_nodes, evidence_edges, 0.98,
                "A typed top-k routing path controls independent repeated branches that reconverge at a typed stack/weighted reduction.",
                attributes={
                    "router_node_ids": sorted(router_nodes | {topk.id}),
                    "expert_groups": branch_groups,
                    "stack_node_id": stack.id,
                    "combine_node_ids": sorted(combine_nodes | {stack.id}),
                    "expert_count": len(branch_groups),
                    "top_k": top_k,
                },
            ))
            break

    # A multimodal claim requires two structurally distinct declared inputs and
    # their first common typed concatenation.  Reordering the input list cannot
    # change this proof.
    if len(inputs) >= 2:
        distinct = {(tuple(_node_shape(node)), next((port.tensor.dtype.casefold() for port in node.outputs if port.tensor), "unknown")) for node in inputs}
        if len(distinct) >= 2:
            descendants_by_input = {node.id: _descendants(graph, [node.id]) for node in inputs}
            fusion_candidates: list[tuple[int, Node, list[Any], list[str]]] = []
            for target in graph.nodes:
                if not _operation_is(target, "cat", "concat") or len(incoming[target.id]) < 2:
                    continue
                origins = [
                    input_node.id for input_node in inputs
                    if any(edge.source in descendants_by_input[input_node.id] for edge in incoming[target.id])
                ]
                if len(set(origins)) >= 2:
                    fusion_candidates.append((depth[target.id], target, incoming[target.id], origins))
            if fusion_candidates:
                _rank, target, target_edges, origins = min(fusion_candidates, key=lambda item: (item[0], item[1].id))
                members = [target.id, *(edge.source for edge in target_edges)]
                result["modality_fusion"].append(_source_detection_record(
                    "modality_fusion", members, (edge.id for edge in target_edges), 0.98,
                    "Two shape/dtype-distinct declared input branches first converge at a typed concatenation operation.",
                    attributes={"fusion_node_id": target.id, "input_node_ids": sorted(set(origins))},
                ))

    # The only inherited claim used by Architecture Evidence is an SCC-backed
    # loop.  It is topology evidence and cannot be created by renamed labels.
    result["diffusion_loop"].extend(inherited.get("diffusion_loop", []))
    return result


def _candidate_families(
    graph: GraphIR,
    detections: Mapping[str, list[dict[str, Any]]],
    entities: Sequence[Any],
) -> list[dict[str, Any]]:
    del entities
    candidates: list[dict[str, Any]] = []
    residual = [item for item in detections.get("residual_block", []) if float(item["confidence"]) >= 0.8]
    attention = [item for item in detections.get("attention", []) if float(item["confidence"]) >= 0.9]
    residual_shapes: dict[tuple[Any, ...], int] = defaultdict(int)
    for item in residual:
        signature = tuple((item.get("attributes", {}) or {}).get("spatial_signature", []))
        if len(signature) == 3:
            residual_shapes[signature] += 1
    attention_nodes = {node_id for item in attention for node_id in _detection_provenance(item)[0]}
    attention_descendants = _descendants(graph, attention_nodes) if attention_nodes else set()
    encoder_residuals = [item for item in residual if set(_detection_provenance(item)[0]).intersection(attention_descendants)]

    if detections.get("diffusion_component") and detections.get("timestep_conditioning"):
        candidates.append(
            {
                "family": "diffusion-unet",
                "confidence": 0.98,
                "reasons": [
                    "A scalar floating branch conditions multiple joins in an acyclic spatial down/up graph.",
                    "Family selection uses typed operations, topology and tensor shapes only.",
                ],
            }
        )
    if detections.get("moe_router_experts"):
        candidates.append(
            {
                "family": "moe",
                "confidence": min(float(item["confidence"]) for item in detections["moe_router_experts"]),
                "reasons": ["A typed top-k router and independent repeated branches reconverge at a weighted reduction."],
            }
        )
    distinct_inputs = {(tuple(spec.shape), spec.dtype.casefold()) for spec in graph.inputs}
    if detections.get("modality_fusion") and len(distinct_inputs) >= 2:
        candidates.append(
            {
                "family": "multimodal-fusion",
                "confidence": min(float(item["confidence"]) for item in detections["modality_fusion"]),
                "reasons": ["Two shape/dtype-distinct inputs follow independent branches to a typed fusion point."],
            }
        )
    if len(detections.get("unet_skip", [])) >= 2:
        candidates.append(
            {
                "family": "unet",
                "confidence": 0.97,
                "reasons": [f"{len(detections['unet_skip'])} same-resolution bypasses enter typed cross-scale concatenation merges."],
            }
        )
    if len(attention) >= 2 and len(encoder_residuals) >= 2:
        candidates.append(
            {
                "family": "transformer",
                "confidence": min(0.98, 0.92 + 0.01 * len(attention)),
                "reasons": [f"{len(attention)} typed attention operations repeat with {len(encoder_residuals)} downstream add merges."],
            }
        )
    if not attention and len(residual_shapes) >= 3 and sum(residual_shapes.values()) >= 6:
        counts = [count for _signature, count in sorted(residual_shapes.items(), key=lambda item: (-int(item[0][-1]), -int(item[0][-2]), int(item[0][0])))]
        candidates.append(
            {
                "family": "resnet",
                "confidence": min(0.99, 0.92 + 0.005 * sum(counts)),
                "reasons": [
                    f"{sum(counts)} typed residual merges form {len(counts)} repeated spatial/channel stages with counts {counts}.",
                    "No display name, module token or requested layout participates in the claim.",
                ],
            }
        )
    return sorted(candidates, key=lambda item: (-float(item["confidence"]), str(item["family"])))


def _resnet_roles(
    graph: GraphIR,
    detections: Mapping[str, list[dict[str, Any]]],
    entities: Sequence[Any],
) -> tuple[list[ArchitectureRole], list[RepeatedStructure], list[CriticalRoute], list[dict[str, Any]]]:
    del entities
    residuals = detections.get("residual_block", [])
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for detection in residuals:
        signature = tuple((detection.get("attributes", {}) or {}).get("spatial_signature", []))
        if len(signature) == 3:
            grouped[signature].append(detection)
    ordered_groups = sorted(
        grouped.items(),
        key=lambda item: (
            -int(item[0][-1]) if isinstance(item[0][-1], int) else 0,
            -int(item[0][-2]) if isinstance(item[0][-2], int) else 0,
            int(item[0][0]) if isinstance(item[0][0], int) else 0,
        ),
    )
    stage_nodes = [
        set(node_id for detection in stage for node_id in _detection_provenance(detection)[0])
        for _signature, stage in ordered_groups
    ]
    first_nodes, last_nodes = stage_nodes[0], stage_nodes[-1]
    all_stage_nodes = set().union(*stage_nodes)
    input_nodes = _ancestors(graph, first_nodes) - all_stage_nodes
    output_nodes = _descendants(graph, last_nodes) - all_stage_nodes
    roles: list[ArchitectureRole] = [
        _role(
            graph,
            "input-stem",
            "Input / stem",
            input_nodes,
            confidence=0.94,
            reasons=["This source subgraph is the complete ancestor prefix of the first repeated residual stage."],
            order=0,
        )
    ]
    repeated: list[RepeatedStructure] = []
    for index, ((_signature, stage_residuals), members) in enumerate(zip(ordered_groups, stage_nodes, strict=True), start=1):
        count = len(stage_residuals)
        role = _role(
            graph,
            "residual-stage",
            f"Stage {index} ×{count} Bottleneck",
            members,
            edge_ids=(edge_id for item in stage_residuals for edge_id in _detection_provenance(item)[1]),
            confidence=min(float(item["confidence"]) for item in stage_residuals),
            reasons=[
                f"The stage contains {count} same-shape topology-backed residual merges.",
                "Its boundary is the output tensor shape transition between adjacent residual groups.",
            ],
            repeat_count=count,
            order=index,
            attributes={
                "stage_index": index,
                "semantic_type": "residual_block",
                "spatial_signature": list(_signature),
                "merge_node_ids": [
                    str((item.get("attributes", {}) or {}).get("merge_node_id", ""))
                    for item in stage_residuals
                ],
                "bottleneck": True,
            },
        )
        roles.append(role)
        repeated.append(RepeatedStructure(role.id, count, role.supporting_node_ids, role.supporting_edge_ids, list(role.reasons)))
    roles.append(
        _role(
            graph,
            "output-head",
            "Pooling / classifier",
            output_nodes,
            confidence=0.94,
            reasons=["This source subgraph is the complete descendant suffix of the final repeated residual stage."],
            order=len(roles),
        )
    )
    routes: list[CriticalRoute] = []
    for index, (role, (_signature, relevant)) in enumerate(zip(roles[1:-1], ordered_groups, strict=True), start=1):
        routes.append(_route(graph, "residual-skip", roles[index - 1], role, relevant, label=f"Stage {index} shortcuts"))
    return roles, repeated, routes, []


def _transformer_roles(
    graph: GraphIR,
    detections: Mapping[str, list[dict[str, Any]]],
) -> tuple[list[ArchitectureRole], list[RepeatedStructure], list[CriticalRoute], list[dict[str, Any]]]:
    attention = detections["attention"]
    node_map = graph.node_map()
    depth = _depths(graph)
    attention_ops = {
        str((item.get("attributes", {}) or {}).get("attention_node_id"))
        for item in attention
        if (item.get("attributes", {}) or {}).get("attention_node_id") in node_map
    }
    ordered_attention = sorted(attention_ops, key=lambda node_id: (depth[node_id], node_id))
    first_attention = {ordered_attention[0]}
    last_attention = {ordered_attention[-1]}
    attention_descendants = _descendants(graph, attention_ops)
    residual = [
        item for item in detections["residual_block"]
        if set(_detection_provenance(item)[0]).intersection(attention_descendants)
        and int((item.get("attributes", {}) or {}).get("merge_node_id") in attention_descendants) == 1
    ]
    residual_nodes = set(node_id for item in residual for node_id in _detection_provenance(item)[0])
    merge_nodes = {
        str((item.get("attributes", {}) or {}).get("merge_node_id"))
        for item in residual
    }
    # Everything upstream of the first attention call is the embedding path.
    # The token/position addition is itself an ``add`` merge, but it is not an
    # encoder residual and must remain visible as embedding evidence.
    embedding_nodes = _ancestors(graph, first_attention) - attention_ops
    ffn_nodes = {
        node.id for node in graph.nodes
        if _operation_is(node, "linear")
        and node.id in attention_descendants
        and bool(_descendants(graph, [node.id]).intersection(merge_nodes))
    }
    norm_nodes = {
        node.id for node in graph.nodes
        if _operation_is(node, "layernorm", "rmsnorm") and node.id in attention_descendants
    }
    repeated_nodes = attention_ops | residual_nodes | ffn_nodes | norm_nodes
    output_nodes = _descendants(graph, last_attention) - repeated_nodes
    input_shape = graph.inputs[0].shape if graph.inputs else []
    input_dtype = graph.inputs[0].dtype.casefold() if graph.inputs else "unknown"
    image_tokens = len(input_shape) == 4 and "float" in input_dtype
    embedding_label = "Patch + class token embed." if image_tokens else "Token + position embed."
    repeat_count = len(attention)
    roles = [
        _role(
            graph,
            "embedding",
            embedding_label,
            embedding_nodes,
            confidence=0.93,
            reasons=["Input tensor rank/dtype and importer module operations establish the embedding path before the first attention block."],
            order=0,
            attributes={"input_kind": "image" if image_tokens else "token"},
        ),
        _role(
            graph,
            "attention",
            f"Self-attention ×{repeat_count}",
            attention_ops,
            edge_ids=(edge_id for item in attention for edge_id in _detection_provenance(item)[1]),
            confidence=0.96,
            reasons=["Repeated importer-declared multi-input attention operations with exact source topology."],
            repeat_count=repeat_count,
            order=1,
        ),
        _role(
            graph,
            "feed-forward",
            f"FFN ×{repeat_count}",
            ffn_nodes,
            confidence=0.94,
            reasons=["Linear operations downstream of attention and upstream of residual merges form the repeated feed-forward paths."],
            repeat_count=repeat_count,
            order=2,
        ),
        _role(
            graph,
            "residual-norm",
            f"Residual + norm ×{repeat_count}",
            residual_nodes | norm_nodes,
            edge_ids=(edge_id for item in residual for edge_id in _detection_provenance(item)[1]),
            confidence=0.92,
            reasons=["Topology-backed add merges and typed normalization operations repeat downstream of attention."],
            repeat_count=repeat_count,
            order=3,
        ),
        _role(
            graph,
            "output-head",
            "Classifier / output",
            output_nodes,
            confidence=0.9,
            reasons=["This source subgraph is downstream of the repeated encoder and reaches every Graph IR output."],
            order=4,
        ),
    ]
    repeated = [RepeatedStructure(role.id, repeat_count, role.supporting_node_ids, role.supporting_edge_ids, list(role.reasons)) for role in roles[1:4]]
    routes = [
        _route(graph, "residual-skip", roles[1], roles[3], residual, label="Encoder residual paths"),
    ]
    uncertain = [
        {
            "claim": "class_token",
            "status": "evidenced" if image_tokens else "not-applicable",
            "reason": "Image-token role requires a rank-4 floating input and the importer embedding/concatenation path.",
        }
    ]
    return roles, repeated, routes, uncertain


def _unet_roles(
    graph: GraphIR,
    detections: Mapping[str, list[dict[str, Any]]],
    *,
    diffusion: bool,
) -> tuple[list[ArchitectureRole], list[RepeatedStructure], list[CriticalRoute], list[dict[str, Any]]]:
    incoming, _outgoing = _graph_maps(graph)
    depth = _depths(graph)
    input_objects = _input_nodes(graph)
    input_nodes = [node.id for node in input_objects]
    output_objects = _output_nodes(graph)
    output_nodes = [node.id for node in output_objects]
    head_nodes = _unique([edge.source for node in output_objects for edge in incoming[node.id]])
    roles: list[ArchitectureRole] = []
    if diffusion:
        noisy = [node.id for node in input_objects if len(_node_shape(node)) >= 4]
        timestep_detection = detections["timestep_conditioning"]
        timestep_nodes = set(node_id for item in timestep_detection for node_id in _detection_provenance(item)[0])
        roles.append(
            _role(
                graph,
                "input",
                "Noisy latent / input",
                noisy or input_nodes[:1],
                confidence=0.96,
                reasons=["A floating spatial Graph IR input supplies the denoising path."],
                order=0,
            )
        )
        roles.append(
            _role(
                graph,
                "conditioning",
                "Timestep conditioning",
                timestep_nodes,
                confidence=0.96,
                reasons=[reason for item in timestep_detection for reason in item["reasons"]],
                order=1,
            )
        )
        component = detections["diffusion_component"][0]
        attributes = component.get("attributes", {}) or {}
        down_anchors = set(attributes.get("down_node_ids", []))
        up_anchors = set(attributes.get("up_node_ids", []))
        spatial_descendants = _descendants(graph, noisy)
        down_depth = max((depth[node_id] for node_id in down_anchors), default=0)
        up_depth = min((depth[node_id] for node_id in up_anchors), default=down_depth + 1)
        down_members = {
            node_id for node_id in spatial_descendants
            if node_id not in set(input_nodes) | timestep_nodes and depth[node_id] <= down_depth
        } | down_anchors
        bottleneck_nodes = {
            node_id for node_id in spatial_descendants
            if down_depth < depth[node_id] < up_depth and node_id not in timestep_nodes
        }
        up_members = {
            node_id for node_id in spatial_descendants
            if depth[node_id] >= up_depth and node_id not in set(output_nodes) | set(head_nodes) | timestep_nodes
        } | up_anchors
        structural_groups = [("down-path", "Conditioned down path", down_members), ("bottleneck", "Mid / bottleneck", bottleneck_nodes), ("up-path", "Conditioned up path", up_members)]
        for role_name, label, members in structural_groups:
            roles.append(_role(
                graph,
                role_name,
                label,
                members,
                confidence=0.95,
                reasons=["Longest-path depth and typed spatial resolution transitions locate this denoiser region."],
                order=len(roles),
            ))
    else:
        roles.append(
            _role(
                graph, "input", "Image input", input_nodes, confidence=0.96, reasons=["Graph IR declares a spatial input tensor feeding the encoder."], order=0
            )
        )
        skip_detections = sorted(
            detections.get("unet_skip", []),
            key=lambda item: (
                -int(((item.get("attributes", {}) or {}).get("spatial_signature", [0, 0, 0]))[-1]),
                str((item.get("attributes", {}) or {}).get("source_node_id", "")),
            ),
        )
        encoder_roles: dict[str, ArchitectureRole] = {}
        for index, detection in enumerate(skip_detections, start=1):
            attributes = detection.get("attributes", {}) or {}
            source_id = str(attributes["source_node_id"])
            role = _role(
                graph,
                "encoder-level",
                f"Encoder level {index}",
                [source_id],
                confidence=0.95,
                reasons=["This feature source is the shallower endpoint of a proven cross-scale concatenation bypass."],
                order=len(roles),
                attributes={"level_index": index, "spatial_signature": attributes.get("spatial_signature", [])},
            )
            roles.append(role)
            encoder_roles[source_id] = role

        deepest = skip_detections[-1]
        deepest_attributes = deepest.get("attributes", {}) or {}
        deepest_source = str(deepest_attributes["source_node_id"])
        deepest_target = str(deepest_attributes["target_node_id"])
        deep_inputs = [edge.source for edge in incoming[deepest_target] if edge.source != deepest_source]
        encoder_ancestry = _ancestors(graph, encoder_roles)
        bottleneck_nodes = _ancestors(graph, deep_inputs) - encoder_ancestry
        bottleneck_nodes.update(deep_inputs)
        roles.append(_role(
            graph,
            "bottleneck",
            "Bottleneck",
            bottleneck_nodes,
            confidence=0.95,
            reasons=["The non-skip branch feeding the deepest concatenation lies beyond every encoder skip source."],
            order=len(roles),
        ))

        decoder_roles: dict[str, ArchitectureRole] = {}
        for index, detection in enumerate(reversed(skip_detections), start=1):
            attributes = detection.get("attributes", {}) or {}
            target_id = str(attributes["target_node_id"])
            role = _role(
                graph,
                "decoder-level",
                f"Decoder level {index}",
                [target_id],
                confidence=0.95,
                reasons=["This typed concatenation is the decoder endpoint of a proven cross-scale bypass."],
                order=len(roles),
                attributes={"level_index": index, "spatial_signature": attributes.get("spatial_signature", [])},
            )
            roles.append(role)
            decoder_roles[target_id] = role
    roles.append(
        _role(
            graph,
            "output-head",
            "Segmentation head" if not diffusion else "Denoised output",
            _unique([*head_nodes, *output_nodes]),
            confidence=0.94,
            reasons=["This terminal source path produces every declared Graph IR output."],
            order=len(roles),
        )
    )
    routes: list[CriticalRoute] = []
    skip_detections = detections.get("unet_skip", [])
    if not diffusion:
        for detection in skip_detections:
            attributes = detection.get("attributes", {}) or {}
            source = encoder_roles.get(str(attributes.get("source_node_id", "")))
            target = decoder_roles.get(str(attributes.get("target_node_id", "")))
            if source is not None and target is not None:
                routes.append(_route(graph, "unet-skip", source, target, [detection], label="Cross-scale skip"))
    if diffusion:
        conditioning = next(role for role in roles if role.role == "conditioning")
        conditioning_detections = detections["timestep_conditioning"]
        for target in [role for role in roles if role.role in {"down-path", "bottleneck", "up-path"}]:
            routes.append(_route(graph, "conditioning", conditioning, target, conditioning_detections, label="Timestep conditioning"))
    repeated: list[RepeatedStructure] = []
    uncertain = []
    if diffusion:
        has_loop = bool(detections.get("diffusion_loop"))
        uncertain.append(
            {
                "claim": "external_sampling_loop",
                "status": "evidenced" if has_loop else "unknown",
                "reason": "No diffusion loop is asserted unless Graph IR contains a source-backed cyclic component.",
            }
        )
    return roles, repeated, routes, uncertain


def _moe_roles(
    graph: GraphIR,
    detections: Mapping[str, list[dict[str, Any]]],
) -> tuple[list[ArchitectureRole], list[RepeatedStructure], list[CriticalRoute], list[dict[str, Any]]]:
    router_detection = detections["moe_router_experts"]
    structural = router_detection[0].get("attributes", {}) or {}
    expert_groups = [list(group) for group in structural.get("expert_groups", [])]
    expert_nodes = set(node_id for group in expert_groups for node_id in group)
    router_nodes = set(structural.get("router_node_ids", []))
    topk_nodes = {
        node.id
        for node in graph.nodes
        if _operation_is(node, "topk", "softmax", "one_hot") and node.id in _ancestors(graph, router_nodes)
    }
    input_nodes = {node.id for node in _input_nodes(graph)}
    embedding_nodes = {node.id for node in graph.nodes if _operation_is(node, "embedding") and node.id in _ancestors(graph, router_nodes | expert_nodes)}
    combine_nodes = set(structural.get("combine_node_ids", []))
    output_nodes = {node.id for node in _output_nodes(graph)}
    output_nodes.update(node.id for node in graph.nodes if _operation_is(node, "layernorm", "rmsnorm") and node.id in _descendants(graph, combine_nodes))
    top_k = structural.get("top_k")
    roles = [
        _role(
            graph,
            "input",
            "Tokens / embedding",
            input_nodes | embedding_nodes,
            confidence=0.95,
            reasons=["Integer token input reaches an importer-declared embedding and both router/expert paths."],
            order=0,
        ),
        _role(
            graph,
            "router",
            f"Router + top-{top_k}" if isinstance(top_k, int) else "Router + top-k",
            router_nodes | topk_nodes,
            edge_ids=(edge_id for item in router_detection for edge_id in _detection_provenance(item)[1]),
            confidence=0.97,
            reasons=["A source-backed router probability/top-k path controls downstream expert weighting."],
            order=1,
        ),
        _role(
            graph,
            "experts",
            f"Experts ×{len(expert_groups)}",
            expert_nodes,
            confidence=0.97,
            reasons=["Repeated importer expert module branches share an operation signature and reconverge."],
            repeat_count=len(expert_groups),
            order=2,
            attributes={"expert_count": len(expert_groups), "expanded_members": [list(group) for group in expert_groups]},
        ),
        _role(
            graph,
            "weighted-combine",
            "Weighted combine",
            combine_nodes,
            confidence=0.96,
            reasons=["Expert outputs and router-derived weights meet at multiply/stack/sum source operations."],
            order=3,
        ),
        _role(
            graph,
            "output-head",
            "Normalization / output",
            output_nodes,
            confidence=0.93,
            reasons=["The terminal normalization path reaches every Graph IR output."],
            order=4,
        ),
    ]
    repeated = [RepeatedStructure(roles[2].id, len(expert_groups), roles[2].supporting_node_ids, roles[2].supporting_edge_ids, list(roles[2].reasons))]
    routes: list[CriticalRoute] = []
    for index, group in enumerate(expert_groups, start=1):
        member_edges = [edge.id for edge in graph.edges if edge.source in group or edge.target in group]
        synthetic = [
            {
                "confidence": 0.97,
                "reasons": [f"Expert branch {index} is a distinct repeated source module that contributes to the weighted merge."],
                "provenance": {"source_node_ids": group, "source_edge_ids": member_edges},
            }
        ]
        routes.append(_route(graph, "expert-branch", roles[1], roles[2], synthetic, label=f"Top-k expert branch {index}", attributes={"expert_index": index}))
    routes.append(_route(graph, "weighted-combine", roles[2], roles[3], router_detection, label="Weighted expert combine"))
    return roles, repeated, routes, []


def node_map_text(node: Node, tokens: Sequence[str]) -> bool:
    """Match importer operation identity, never graph/case/display identity."""
    declared = f"{node.op_type} {node.category} {node.source.get('target', '')}".casefold()
    return any(token in declared for token in tokens)


def _multimodal_roles(
    graph: GraphIR,
    detections: Mapping[str, list[dict[str, Any]]],
) -> tuple[list[ArchitectureRole], list[RepeatedStructure], list[CriticalRoute], list[dict[str, Any]]]:
    fusion_detections = detections["modality_fusion"]
    fusion_nodes = set(node_id for item in fusion_detections for node_id in _detection_provenance(item)[0])
    input_nodes = [node for node in graph.nodes if node.category == "input" or node.op_type.casefold() == "input"]
    output_nodes = {node.id for node in graph.nodes if node.category == "output" or node.op_type.casefold() == "output"}
    fusion_ancestors = _ancestors(graph, fusion_nodes)
    lane_nodes: list[set[str]] = []
    for input_node in input_nodes:
        lane_nodes.append((_descendants(graph, [input_node.id]) & fusion_ancestors) - fusion_nodes)
    while len(lane_nodes) < 2:
        lane_nodes.append(set())
    image_index = 0
    for index, node in enumerate(input_nodes):
        tensor = next((port.tensor for port in node.outputs if port.tensor is not None), None)
        if tensor is not None and len(tensor.shape) >= 4:
            image_index = index
            break
    text_index = 1 - image_index if len(input_nodes) == 2 else next((i for i in range(len(lane_nodes)) if i != image_index), 1)
    image_nodes = lane_nodes[image_index]
    text_nodes = lane_nodes[text_index]
    attention_nodes = set(node_id for item in detections.get("attention", []) for node_id in _detection_provenance(item)[0])
    downstream = _descendants(graph, fusion_nodes) - fusion_nodes
    roles = [
        _role(
            graph,
            "image-lane",
            "Image encoder / representation",
            image_nodes,
            confidence=0.96,
            reasons=["A rank-4 floating input follows an independent convolution/pooling path to fusion."],
            order=0,
            attributes={"modality": "image"},
        ),
        _role(
            graph,
            "text-lane",
            "Text encoder / attention",
            text_nodes | attention_nodes,
            confidence=0.96,
            reasons=["An integer token input follows an embedding/attention path independent of the image path."],
            order=1,
            attributes={"modality": "text"},
        ),
        _role(
            graph,
            "fusion",
            "Gated fusion",
            fusion_nodes,
            edge_ids=(edge_id for item in fusion_detections for edge_id in _detection_provenance(item)[1]),
            confidence=0.96,
            reasons=[reason for item in fusion_detections for reason in item["reasons"]],
            order=2,
        ),
        _role(
            graph,
            "output-head",
            "Output head",
            downstream | output_nodes,
            confidence=0.93,
            reasons=["The fused representation reaches the terminal Graph IR output path."],
            order=3,
        ),
    ]
    routes = [
        _route(graph, "multimodal-stream", roles[0], roles[2], fusion_detections, label="Image stream", attributes={"modality": "image"}),
        _route(graph, "multimodal-stream", roles[1], roles[2], fusion_detections, label="Text stream", attributes={"modality": "text"}),
    ]
    return roles, [], routes, []


def derive_architecture_evidence(
    graph: GraphIR,
    *,
    source_digest: str,
    detections: Iterable[Mapping[str, Any]],
    entities: Sequence[Any],
) -> ArchitectureEvidence:
    """Derive one source-bound architecture claim without layout/name hints."""

    graph.validate()
    inherited_detections = _valid_detections(graph, detections)
    detection_map = _structural_detection_map(graph, inherited_detections)
    candidates = _candidate_families(graph, detection_map, entities)
    if not candidates:
        unknown = ArchitectureEvidence(
            family="unknown",
            confidence=0.0,
            reasons=["Available topology, operation, module, port, and shape evidence does not prove a supported architecture family."],
            supporting_node_ids=[],
            supporting_edge_ids=[],
            supporting_port_ids=[],
            detected_roles=[],
            repeated_structure=[],
            critical_routes=[],
            alternative_candidates=[],
            unknown_reason="No supported family reached the evidence threshold; requested layout and display names were ignored.",
            source_digest=source_digest,
        ).seal()
        return unknown.validate(graph, source_digest=source_digest)

    selected = candidates[0]
    family = str(selected["family"])
    if family == "resnet":
        roles, repeated, routes, uncertain = _resnet_roles(graph, detection_map, entities)
    elif family == "transformer":
        roles, repeated, routes, uncertain = _transformer_roles(graph, detection_map)
    elif family == "unet":
        roles, repeated, routes, uncertain = _unet_roles(graph, detection_map, diffusion=False)
    elif family == "diffusion-unet":
        roles, repeated, routes, uncertain = _unet_roles(graph, detection_map, diffusion=True)
    elif family == "moe":
        roles, repeated, routes, uncertain = _moe_roles(graph, detection_map)
    elif family == "multimodal-fusion":
        roles, repeated, routes, uncertain = _multimodal_roles(graph, detection_map)
    else:  # Defensive: known detector branches above are deliberately explicit.
        raise ValidationError(f"Architecture Evidence role materialization is unavailable for {family!r}")
    supporting_nodes = _unique(node_id for role in roles for node_id in role.supporting_node_ids)
    supporting_edges = _unique(
        [
            *(edge_id for role in roles for edge_id in role.supporting_edge_ids),
            *(edge_id for route in routes for edge_id in route.supporting_edge_ids),
        ]
    )
    evidence = ArchitectureEvidence(
        family=family,
        confidence=float(selected["confidence"]),
        reasons=list(selected["reasons"]),
        supporting_node_ids=supporting_nodes,
        supporting_edge_ids=supporting_edges,
        supporting_port_ids=_ports_for(graph, supporting_nodes, supporting_edges),
        detected_roles=sorted(roles, key=lambda role: (role.order, role.id)),
        repeated_structure=repeated,
        critical_routes=routes,
        alternative_candidates=[candidate for candidate in candidates[1:]],
        unknown_reason=None,
        source_digest=source_digest,
        uncertain_claims=uncertain,
    ).seal()
    return evidence.validate(graph, source_digest=source_digest)


__all__ = [
    "ARCHITECTURE_EVIDENCE_FAMILIES",
    "ARCHITECTURE_EVIDENCE_VERSION",
    "ArchitectureEvidence",
    "ArchitectureRole",
    "CriticalRoute",
    "RepeatedStructure",
    "derive_architecture_evidence",
]
