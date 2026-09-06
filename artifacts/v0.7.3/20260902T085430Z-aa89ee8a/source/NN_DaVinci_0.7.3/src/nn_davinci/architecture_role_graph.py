"""Generic, source-bound role graph derived from Architecture Evidence.

The role graph is the only scientific structure consumed by publication
Figure and Scene builders.  It deliberately ignores corpus keys, display
names, requested layouts, and existing coordinates.  Non-critical flow edges
are recovered from directed Graph IR paths; protected critical routes retain
their exact Architecture Evidence IDs and provenance.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any, Iterable

from .architecture_evidence import ArchitectureEvidence
from .errors import ValidationError
from .ir import Edge, GraphIR, stable_id


ARCHITECTURE_ROLE_GRAPH_VERSION = "1.0"


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value))


@dataclass(frozen=True, slots=True)
class RoleGraphNode:
    role_id: str
    role: str
    label: str
    repeat_count: int
    order: int
    confidence: float
    supporting_node_ids: list[str]
    supporting_edge_ids: list[str]
    supporting_port_ids: list[str]
    attributes: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RoleGraphEdge:
    id: str
    source_role_id: str
    target_role_id: str
    role: str
    label: str
    direction: str
    critical: bool
    critical_route_id: str | None
    supporting_node_ids: list[str]
    supporting_edge_ids: list[str]
    supporting_port_ids: list[str]
    attributes: dict[str, Any]


@dataclass(slots=True)
class ArchitectureRoleGraph:
    family: str
    evidence_provenance_digest: str
    source_digest: str
    nodes: list[RoleGraphNode]
    edges: list[RoleGraphEdge]
    digest: str = ""
    version: str = ARCHITECTURE_ROLE_GRAPH_VERSION

    def _digest_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("digest", None)
        return payload

    def seal(self) -> "ArchitectureRoleGraph":
        encoded = json.dumps(
            self._digest_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.digest = sha256(encoded).hexdigest()
        return self

    def validate(
        self,
        graph: GraphIR | None = None,
        evidence: ArchitectureEvidence | None = None,
    ) -> "ArchitectureRoleGraph":
        failures: list[str] = []
        role_ids = [node.role_id for node in self.nodes]
        if len(role_ids) != len(set(role_ids)):
            failures.append("role graph node IDs must be unique")
        known_roles = set(role_ids)
        edge_ids = [edge.id for edge in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            failures.append("role graph edge IDs must be unique")
        for edge in self.edges:
            if edge.source_role_id not in known_roles or edge.target_role_id not in known_roles:
                failures.append(f"role graph edge {edge.id!r} has an unknown endpoint")
            if edge.direction != "source-to-target":
                failures.append(f"role graph edge {edge.id!r} has no forward direction evidence")
            if not edge.supporting_edge_ids:
                failures.append(f"role graph edge {edge.id!r} has no Graph IR edge evidence")
            if edge.critical and edge.critical_route_id != edge.id:
                failures.append(f"critical role graph edge {edge.id!r} lost its route ID")
        expected_digest = sha256(
            json.dumps(
                self._digest_payload(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if self.digest != expected_digest:
            failures.append("role graph digest is stale or tampered")
        if evidence is not None:
            if self.family != evidence.family:
                failures.append("role graph family disagrees with Architecture Evidence")
            if self.source_digest != evidence.source_digest:
                failures.append("role graph source digest disagrees with Architecture Evidence")
            if self.evidence_provenance_digest != evidence.provenance_digest:
                failures.append("role graph evidence digest is stale")
            if set(role_ids) != {role.id for role in evidence.detected_roles}:
                failures.append("role graph role set disagrees with Architecture Evidence")
            critical_ids = {edge.id for edge in self.edges if edge.critical}
            if critical_ids != {route.id for route in evidence.critical_routes}:
                failures.append("role graph critical-route set disagrees with Architecture Evidence")
        if graph is not None:
            known_nodes = set(graph.node_map())
            known_edges = set(graph.edge_map())
            known_ports = {
                port.id
                for node in graph.nodes
                for port in (*node.inputs, *node.outputs)
            }
            for node in self.nodes:
                if not set(node.supporting_node_ids).issubset(known_nodes):
                    failures.append(f"role graph node {node.role_id!r} references unknown Graph nodes")
                if not set(node.supporting_edge_ids).issubset(known_edges):
                    failures.append(f"role graph node {node.role_id!r} references unknown Graph edges")
                if not set(node.supporting_port_ids).issubset(known_ports):
                    failures.append(f"role graph node {node.role_id!r} references unknown Graph ports")
            for edge in self.edges:
                if not set(edge.supporting_node_ids).issubset(known_nodes):
                    failures.append(f"role graph edge {edge.id!r} references unknown Graph nodes")
                if not set(edge.supporting_edge_ids).issubset(known_edges):
                    failures.append(f"role graph edge {edge.id!r} references unknown Graph edges")
                if not set(edge.supporting_port_ids).issubset(known_ports):
                    failures.append(f"role graph edge {edge.id!r} references unknown Graph ports")
        if failures:
            raise ValidationError(
                f"Architecture role graph contains {len(failures)} validation error(s)",
                hint="Regenerate the role graph from the current Architecture Evidence and Graph IR.",
                details={"errors": failures},
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _path_ports(path: Iterable[Edge]) -> list[str]:
    return _unique(
        port_id
        for edge in path
        for port_id in (edge.source_port, edge.target_port)
        if port_id
    )


def _immediate_role_paths(
    graph: GraphIR,
    source_role_id: str,
    role_nodes: dict[str, set[str]],
    node_roles: dict[str, set[str]],
) -> dict[str, list[Edge]]:
    """Find the first directed role regions reachable from one role.

    Traversal stops when another role is reached.  This prevents a path from
    jumping over an intermediate scientific role merely because the endpoints
    are transitively connected.
    """

    outgoing: dict[str, list[Edge]] = defaultdict(list)
    for edge in graph.edges:
        outgoing[edge.source].append(edge)
    for edges in outgoing.values():
        edges.sort(key=lambda item: item.id)
    starts = sorted(role_nodes[source_role_id])
    queue: deque[tuple[str, list[Edge]]] = deque((node_id, []) for node_id in starts)
    best_depth = {node_id: 0 for node_id in starts}
    found: dict[str, list[Edge]] = {}
    while queue:
        node_id, path = queue.popleft()
        for edge in outgoing.get(node_id, []):
            candidate = [*path, edge]
            reached = sorted(node_roles.get(edge.target, set()) - {source_role_id})
            if reached:
                for target_role_id in reached:
                    prior = found.get(target_role_id)
                    candidate_key = (len(candidate), tuple(item.id for item in candidate))
                    prior_key = (
                        (len(prior), tuple(item.id for item in prior))
                        if prior is not None
                        else None
                    )
                    if prior_key is None or candidate_key < prior_key:
                        found[target_role_id] = candidate
                continue
            depth = len(candidate)
            if depth < best_depth.get(edge.target, depth + 1):
                best_depth[edge.target] = depth
                queue.append((edge.target, candidate))
    return found


def build_architecture_role_graph(
    graph: GraphIR,
    evidence: ArchitectureEvidence,
) -> ArchitectureRoleGraph:
    """Build a deterministic generic role graph from source-bound evidence."""

    graph.validate()
    evidence.validate(graph, source_digest=evidence.source_digest)
    roles = sorted(evidence.detected_roles, key=lambda item: (item.order, item.id))
    nodes = [
        RoleGraphNode(
            role_id=role.id,
            role=role.role,
            label=role.label,
            repeat_count=role.repeat_count,
            order=role.order,
            confidence=role.confidence,
            supporting_node_ids=list(role.supporting_node_ids),
            supporting_edge_ids=list(role.supporting_edge_ids),
            supporting_port_ids=list(role.supporting_port_ids),
            attributes=dict(role.attributes),
        )
        for role in roles
    ]
    role_nodes = {role.id: set(role.supporting_node_ids) for role in roles}
    node_roles: dict[str, set[str]] = defaultdict(set)
    for role_id, node_ids in role_nodes.items():
        for node_id in node_ids:
            node_roles[node_id].add(role_id)

    edges: list[RoleGraphEdge] = []
    for source in roles:
        for target_role_id, path in sorted(
            _immediate_role_paths(graph, source.id, role_nodes, node_roles).items(),
            key=lambda item: (next(role.order for role in roles if role.id == item[0]), item[0]),
        ):
            edge_ids = [edge.id for edge in path]
            supporting_nodes = _unique(
                node_id
                for edge in path
                for node_id in (edge.source, edge.target)
            )
            identity = stable_id(
                "architecture_role_flow",
                f"{source.id}:{target_role_id}:{'|'.join(edge_ids)}",
            )
            edges.append(
                RoleGraphEdge(
                    id=identity,
                    source_role_id=source.id,
                    target_role_id=target_role_id,
                    role="main-flow",
                    label="Traced main flow",
                    direction="source-to-target",
                    critical=False,
                    critical_route_id=None,
                    supporting_node_ids=supporting_nodes,
                    supporting_edge_ids=edge_ids,
                    supporting_port_ids=_path_ports(path),
                    attributes={},
                )
            )

    for route in evidence.critical_routes:
        edges.append(
            RoleGraphEdge(
                id=route.id,
                source_role_id=route.source_role_id,
                target_role_id=route.target_role_id,
                role=route.role,
                label=route.label,
                direction="source-to-target",
                critical=True,
                critical_route_id=route.id,
                supporting_node_ids=list(route.supporting_node_ids),
                supporting_edge_ids=list(route.supporting_edge_ids),
                supporting_port_ids=list(route.supporting_port_ids),
                attributes=dict(route.attributes),
            )
        )

    role_graph = ArchitectureRoleGraph(
        family=evidence.family,
        evidence_provenance_digest=evidence.provenance_digest,
        source_digest=evidence.source_digest,
        nodes=nodes,
        edges=sorted(
            edges,
            key=lambda item: (
                next(role.order for role in roles if role.id == item.source_role_id),
                next(role.order for role in roles if role.id == item.target_role_id),
                not item.critical,
                item.id,
            ),
        ),
    ).seal()
    return role_graph.validate(graph, evidence)


__all__ = [
    "ARCHITECTURE_ROLE_GRAPH_VERSION",
    "ArchitectureRoleGraph",
    "RoleGraphEdge",
    "RoleGraphNode",
    "build_architecture_role_graph",
]
