"""Versioned semantic views derived from, but independent of, Graph IR.

The semantic layer deliberately stores only stable source provenance.  It never
rewrites the imported graph and it never claims a detector result when the
available evidence is weak: uncovered nodes are represented by ``unknown``
entities with an explicit reason.
"""

from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
import re
from typing import Any, Iterable

from .architecture_evidence import ArchitectureEvidence, derive_architecture_evidence
from .errors import ValidationError
from .ir import Edge, GraphIR, Node, Port, stable_id

SEMANTIC_VIEW_VERSION = "1.0"
SEMANTIC_LEVELS = ("model", "stage", "block", "layer", "operation")
# ``model``/``layer`` remain the persisted 1.x identities.  Figure Studio's
# author-facing hierarchy uses the clearer framework/module vocabulary from
# the 0.6.1 model-to-Figure contract, so public entry points accept both
# spellings without rewriting existing projects.
SEMANTIC_LEVEL_ALIASES = {"framework": "model", "module": "layer"}
SEMANTIC_SELECTION_LEVELS = ("framework", "stage", "block", "module", "operation")
VIEW_MODES = ("faithful", "paper")
SEMANTIC_RECOGNIZERS: dict[str, Any] = {}


def register_semantic_recognizer(name: str, recognizer: Any, *, replace: bool = False) -> None:
    if name in SEMANTIC_RECOGNIZERS and not replace:
        raise ValueError(f"Semantic recognizer {name!r} is already registered")
    if not callable(recognizer):
        raise TypeError("Semantic recognizer must be callable")
    SEMANTIC_RECOGNIZERS[name] = recognizer


@dataclass(slots=True)
class SemanticProvenance:
    source_node_ids: list[str] = field(default_factory=list)
    source_edge_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SemanticEntity:
    id: str
    name: str
    level: str
    semantic_type: str
    confidence: float
    reasons: list[str]
    provenance: SemanticProvenance
    parent_id: str | None = None
    child_ids: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    unknown: bool = False


@dataclass(slots=True)
class SemanticConnection:
    id: str
    source: str
    target: str
    kind: str
    provenance: SemanticProvenance
    confidence: float = 1.0
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SemanticView:
    name: str
    source_ir_version: str
    source_digest: str
    entities: list[SemanticEntity]
    connections: dict[str, list[SemanticConnection]]
    source_to_semantic: dict[str, dict[str, list[str]]]
    semantic_to_source: dict[str, SemanticProvenance]
    detections: list[dict[str, Any]] = field(default_factory=list)
    architecture_evidence: ArchitectureEvidence | None = None
    semantic_version: str = SEMANTIC_VIEW_VERSION

    def validate(self, source: GraphIR | None = None) -> "SemanticView":
        """Validate the view, its bidirectional index, and optional source.

        A serialized Semantic View can validate its own evidence index because
        the model-level entity is the authoritative inventory of source node
        and edge IDs.  Supplying ``source`` additionally proves that inventory
        and the digest against the actual Graph IR rather than trusting the
        serialized view alone.
        """
        errors: list[str] = []
        if self.semantic_version.split(".", 1)[0] != SEMANTIC_VIEW_VERSION.split(".", 1)[0]:
            errors.append(f"unsupported Semantic View version {self.semantic_version!r}")
        ids = [entity.id for entity in self.entities]
        if len(ids) != len(set(ids)):
            errors.append("semantic entity IDs must be unique")
        known = set(ids)
        entity_by_id = {entity.id: entity for entity in self.entities}
        model_entities = [entity for entity in self.entities if entity.level == "model"]
        if len(model_entities) != 1:
            errors.append("Semantic View must contain exactly one model entity as its source-ID inventory")
        has_source_inventory = len(model_entities) == 1
        known_source_nodes = set(model_entities[0].provenance.source_node_ids) if len(model_entities) == 1 else set()
        known_source_edges = set(model_entities[0].provenance.source_edge_ids) if len(model_entities) == 1 else set()
        for entity in self.entities:
            if entity.level not in SEMANTIC_LEVELS:
                errors.append(f"entity {entity.id!r} has invalid level {entity.level!r}")
            if not 0.0 <= entity.confidence <= 1.0:
                errors.append(f"entity {entity.id!r} has invalid confidence")
            if not entity.reasons:
                errors.append(f"entity {entity.id!r} has no recognition reason")
            if entity.parent_id and entity.parent_id not in known:
                errors.append(f"entity {entity.id!r} has missing parent {entity.parent_id!r}")
            missing_children = set(entity.child_ids) - known
            if missing_children:
                errors.append(f"entity {entity.id!r} has missing children {sorted(missing_children)!r}")
            if len(entity.provenance.source_node_ids) != len(set(entity.provenance.source_node_ids)):
                errors.append(f"entity {entity.id!r} repeats source node provenance")
            if len(entity.provenance.source_edge_ids) != len(set(entity.provenance.source_edge_ids)):
                errors.append(f"entity {entity.id!r} repeats source edge provenance")
            if has_source_inventory:
                missing_nodes = set(entity.provenance.source_node_ids) - known_source_nodes
                if missing_nodes:
                    errors.append(f"entity {entity.id!r} references unknown source nodes {sorted(missing_nodes)!r}")
                missing_edges = set(entity.provenance.source_edge_ids) - known_source_edges
                if missing_edges:
                    errors.append(f"entity {entity.id!r} references unknown source edges {sorted(missing_edges)!r}")
            if entity.parent_id:
                parent = entity_by_id.get(entity.parent_id)
                if parent and entity.id not in parent.child_ids:
                    errors.append(f"entity {entity.id!r} parent/child mapping is not reciprocal")
            for child_id in entity.child_ids:
                child = entity_by_id.get(child_id)
                if child and child.parent_id != entity.id:
                    errors.append(f"entity {entity.id!r} child {child_id!r} does not point back to its parent")

        expected_source_to_semantic: dict[str, dict[str, list[str]]] = {
            level: defaultdict(list) for level in SEMANTIC_LEVELS
        }
        for entity in self.entities:
            if entity.level not in expected_source_to_semantic:
                continue
            for source_id in (*entity.provenance.source_node_ids, *entity.provenance.source_edge_ids):
                expected_source_to_semantic[entity.level][source_id].append(entity.id)
        for level in set(self.source_to_semantic) - set(SEMANTIC_LEVELS):
            errors.append(f"source-to-semantic mapping uses invalid level {level!r}")
        missing_mapping_levels = set(SEMANTIC_LEVELS) - set(self.source_to_semantic)
        if missing_mapping_levels:
            errors.append(f"source-to-semantic mapping omits levels {sorted(missing_mapping_levels)!r}")
        for level in SEMANTIC_LEVELS:
            actual = self.source_to_semantic.get(level, {})
            expected = expected_source_to_semantic[level]
            for source_id, semantic_ids in actual.items():
                if len(semantic_ids) != len(set(semantic_ids)):
                    errors.append(f"source-to-semantic mapping for {source_id!r} at {level!r} repeats IDs")
                missing_semantic = set(semantic_ids) - known
                if missing_semantic:
                    errors.append(
                        f"source-to-semantic mapping for {source_id!r} references unknown entities "
                        f"{sorted(missing_semantic)!r}"
                    )
                wrong_level = [
                    semantic_id for semantic_id in semantic_ids
                    if semantic_id in entity_by_id and entity_by_id[semantic_id].level != level
                ]
                if wrong_level:
                    errors.append(
                        f"source-to-semantic mapping for {source_id!r} places entities "
                        f"{sorted(wrong_level)!r} at the wrong level"
                    )
            if {key: sorted(value) for key, value in actual.items()} != {
                key: sorted(value) for key, value in expected.items()
            }:
                errors.append(f"source-to-semantic mapping at {level!r} is inconsistent with entity provenance")

        if set(self.semantic_to_source) != known:
            errors.append("semantic-to-source mapping keys must exactly match the semantic entity IDs")
        for semantic_id, provenance in self.semantic_to_source.items():
            mapped_entity = entity_by_id.get(semantic_id)
            if mapped_entity and (
                provenance.source_node_ids != mapped_entity.provenance.source_node_ids
                or provenance.source_edge_ids != mapped_entity.provenance.source_edge_ids
            ):
                errors.append(f"semantic-to-source mapping for {semantic_id!r} disagrees with entity provenance")

        connection_ids: list[str] = []
        missing_connection_levels = set(SEMANTIC_LEVELS) - set(self.connections)
        if missing_connection_levels:
            errors.append(f"semantic connections omit levels {sorted(missing_connection_levels)!r}")
        for level, connections in self.connections.items():
            if level not in SEMANTIC_LEVELS:
                errors.append(f"connections use invalid level {level!r}")
            for connection in connections:
                connection_ids.append(connection.id)
                if connection.source not in known or connection.target not in known:
                    errors.append(f"connection {connection.id!r} has missing endpoint")
                else:
                    if entity_by_id[connection.source].level != level or entity_by_id[connection.target].level != level:
                        errors.append(f"connection {connection.id!r} endpoints do not belong to level {level!r}")
                if not 0.0 <= connection.confidence <= 1.0:
                    errors.append(f"connection {connection.id!r} has invalid confidence")
                if not connection.reasons:
                    errors.append(f"connection {connection.id!r} has no evidence reason")
                if has_source_inventory:
                    missing_nodes = set(connection.provenance.source_node_ids) - known_source_nodes
                    if missing_nodes:
                        errors.append(
                            f"connection {connection.id!r} references unknown source nodes {sorted(missing_nodes)!r}"
                        )
                    missing_edges = set(connection.provenance.source_edge_ids) - known_source_edges
                    if missing_edges:
                        errors.append(
                            f"connection {connection.id!r} references unknown source edges {sorted(missing_edges)!r}"
                        )
        if len(connection_ids) != len(set(connection_ids)):
            errors.append("semantic connection IDs must be unique")

        for index, detection in enumerate(self.detections):
            if not isinstance(detection, dict):
                errors.append(f"detection {index} is not a mapping")
                continue
            provenance = detection.get("provenance", {})
            detection_nodes = {str(item) for item in provenance.get("source_node_ids", [])}
            detection_edges = {str(item) for item in provenance.get("source_edge_ids", [])}
            confidence = detection.get("confidence")
            if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
                errors.append(f"detection {index} has invalid confidence")
            if not detection.get("reasons"):
                errors.append(f"detection {index} has no evidence reason")
            detection_semantic_id = detection.get("semantic_id")
            if detection_semantic_id is not None and detection_semantic_id not in known:
                errors.append(f"detection {index} references unknown semantic entity {detection_semantic_id!r}")
            if detection_semantic_id in entity_by_id:
                entity_provenance = entity_by_id[detection_semantic_id].provenance
                if (
                    detection_nodes != set(entity_provenance.source_node_ids)
                    or detection_edges != set(entity_provenance.source_edge_ids)
                ):
                    errors.append(
                        f"detection {index} provenance disagrees with semantic entity {detection_semantic_id!r}"
                    )
            if has_source_inventory and not detection_nodes.issubset(known_source_nodes):
                errors.append(f"detection {index} references unknown source nodes {sorted(detection_nodes - known_source_nodes)!r}")
            if has_source_inventory and not detection_edges.issubset(known_source_edges):
                errors.append(f"detection {index} references unknown source edges {sorted(detection_edges - known_source_edges)!r}")

        if self.architecture_evidence is not None:
            try:
                self.architecture_evidence.validate(source, source_digest=self.source_digest)
            except ValidationError as exc:
                errors.extend(
                    f"architecture_evidence:{failure}"
                    for failure in exc.details.get("errors", [str(exc)])
                )

        if source is not None:
            source.validate()
            actual_nodes = set(source.node_map())
            actual_edges = set(source.edge_map())
            if self.source_ir_version != source.ir_version:
                errors.append(
                    f"source IR version {source.ir_version!r} does not match Semantic View "
                    f"source version {self.source_ir_version!r}"
                )
            if self.source_digest != _graph_digest(source):
                errors.append("source digest does not match the supplied Graph IR")
            if known_source_nodes != actual_nodes:
                errors.append("model entity source-node inventory does not exactly match the supplied Graph IR")
            if known_source_edges != actual_edges:
                errors.append("model entity source-edge inventory does not exactly match the supplied Graph IR")
        if errors:
            source_mismatch = "source digest does not match the supplied Graph IR" in errors
            raise ValidationError(
                (
                    "Semantic View source digest does not match this Graph IR"
                    if source_mismatch else
                    f"Semantic View contains {len(errors)} validation error(s)"
                ),
                hint=(
                    "Regenerate the Semantic View after changing nodes, ports, tensors, or edge bindings."
                    if source_mismatch else
                    "Regenerate the Semantic View from its source Graph IR."
                ),
                details={"errors": errors},
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SemanticView":
        payload = dict(data)
        payload["entities"] = [
            SemanticEntity(
                **{
                    **item,
                    "provenance": SemanticProvenance(**item.get("provenance", {})),
                }
            )
            for item in payload.get("entities", [])
        ]
        payload["connections"] = {
            level: [
                SemanticConnection(
                    **{
                        **item,
                        "provenance": SemanticProvenance(**item.get("provenance", {})),
                    }
                )
                for item in items
            ]
            for level, items in payload.get("connections", {}).items()
        }
        payload["semantic_to_source"] = {
            key: SemanticProvenance(**value)
            for key, value in payload.get("semantic_to_source", {}).items()
        }
        if isinstance(payload.get("architecture_evidence"), dict):
            payload["architecture_evidence"] = ArchitectureEvidence.from_dict(payload["architecture_evidence"])
        return cls(**payload).validate()

    def entities_at(self, level: str) -> list[SemanticEntity]:
        level = normalize_semantic_level(level)
        return [entity for entity in self.entities if entity.level == level]

    def trace_source(self, semantic_id: str) -> SemanticProvenance:
        return self.semantic_to_source.get(semantic_id, SemanticProvenance())

    def trace_semantic(self, source_id: str, *, level: str | None = None) -> list[str]:
        if level:
            level = normalize_semantic_level(level)
            return list(self.source_to_semantic.get(level, {}).get(source_id, []))
        result: list[str] = []
        for mapping in self.source_to_semantic.values():
            result.extend(mapping.get(source_id, []))
        return list(dict.fromkeys(result))

    def materialize(self, source: GraphIR, *, level: str = "block", view: str = "faithful") -> GraphIR:
        """Create a renderable graph for one level without changing ``source``."""
        level = normalize_semantic_level(level)
        _check_view(view)
        self.validate(source)
        selected = self.entities_at(level)
        if view == "paper":
            selected = _paper_entities(selected, source)
        source_nodes = source.node_map()
        nodes: list[Node] = []
        member_to_entity: dict[str, str] = {}
        members_by_entity: dict[str, list[Node]] = {}
        for entity in selected:
            members = [source_nodes[node_id] for node_id in entity.provenance.source_node_ids if node_id in source_nodes]
            members_by_entity[entity.id] = members
            for member in members:
                member_to_entity[member.id] = entity.id
            parameters = sum(node.parameters for node in members)
            trainable = sum(node.trainable_parameters for node in members)
            analysis = _aggregate_analysis(members)
            category = _semantic_category(entity.semantic_type, members)
            internal_source_edges = [
                edge.id for edge in source.edges
                if edge.source in entity.provenance.source_node_ids
                and edge.target in entity.provenance.source_node_ids
            ]
            nodes.append(Node(
                id=entity.id,
                name=entity.name,
                op_type=_semantic_label(entity.semantic_type, entity.unknown),
                category=category,
                path=f"semantic.{level}.{entity.id}",
                namespace="semantic",
                level=level,
                parameters=parameters,
                trainable_parameters=trainable,
                buffers=sum(node.buffers for node in members),
                attributes={
                    **entity.attributes,
                    "semantic_level": level,
                    "semantic_view": view,
                    "semantic_type": entity.semantic_type,
                    "confidence": entity.confidence,
                    "recognition_reasons": list(entity.reasons),
                    "source_nodes": list(entity.provenance.source_node_ids),
                    "source_edges": list(entity.provenance.source_edge_ids),
                    "internal_source_edges": internal_source_edges,
                    "child_semantic_ids": list(entity.child_ids),
                    "unknown_semantics": entity.unknown,
                    # Port evidence is populated below.  It is kept on the
                    # semantic node because Graph IR 1.x intentionally has no
                    # free-form attributes on Port.
                    "boundary_port_bindings": {},
                },
                source={
                    "format": "semantic-view",
                    "semantic_version": self.semantic_version,
                    "source_ir_version": self.source_ir_version,
                    "source_nodes": list(entity.provenance.source_node_ids),
                    "source_edges": list(entity.provenance.source_edge_ids),
                },
                analysis=analysis,
                tags=[entity.semantic_type, level, view],
            ))

        semantic_nodes = {node.id: node for node in nodes}
        internal_inputs: set[tuple[str, str]] = set()
        internal_outputs: set[tuple[str, str]] = set()
        crossing_inputs: set[tuple[str, str]] = set()
        crossing_outputs: set[tuple[str, str]] = set()
        for edge in source.edges:
            source_entity = member_to_entity.get(edge.source)
            target_entity = member_to_entity.get(edge.target)
            if not source_entity or not target_entity:
                continue
            internal = source_entity == target_entity
            if edge.source_port:
                (internal_outputs if internal else crossing_outputs).add((edge.source, edge.source_port))
            if edge.target_port:
                (internal_inputs if internal else crossing_inputs).add((edge.target, edge.target_port))

        port_ids: dict[tuple[str, str, str, str], str] = {}

        def ensure_port(
            entity_id: str,
            source_node_id: str,
            direction: str,
            source_port_id: str,
        ) -> str:
            source_node = source_nodes[source_node_id]
            candidates = source_node.outputs if direction == "output" else source_node.inputs
            exact_port = next((port for port in candidates if port.id == source_port_id), None)
            if exact_port is None:
                raise ValidationError(
                    f"Source port {source_port_id!r} disappeared while materializing Semantic View",
                    hint="Validate or re-import the source Graph IR, then regenerate its Semantic View.",
                )
            cache_key = (entity_id, source_node_id, direction, source_port_id)
            existing = port_ids.get(cache_key)
            if existing:
                return existing
            semantic_port_id = stable_id(
                "semantic_port",
                f"{level}:{entity_id}:{direction}:{source_node_id}:{source_port_id}",
            )
            port = Port(
                id=semantic_port_id,
                name=exact_port.name,
                direction=direction,
                tensor=deepcopy(exact_port.tensor),
                variadic=exact_port.variadic,
            )
            semantic_node = semantic_nodes[entity_id]
            (semantic_node.outputs if direction == "output" else semantic_node.inputs).append(port)
            semantic_node.attributes["boundary_port_bindings"][semantic_port_id] = {
                "source_node_id": source_node_id,
                "source_port_id": source_port_id,
                "source_edge_id": None,
                "direction": direction,
                "status": "exact",
                "tensor_source": "source-port" if exact_port.tensor is not None else "unknown",
            }
            port_ids[cache_key] = semantic_port_id
            return semantic_port_id

        # Retain declared ports exactly when they cross the selected semantic
        # boundary or are not consumed/produced wholly inside that boundary.
        for entity in selected:
            for member in members_by_entity[entity.id]:
                for port in member.inputs:
                    key = (member.id, port.id)
                    if key not in internal_inputs or key in crossing_inputs:
                        ensure_port(entity.id, member.id, "input", port.id)
                for port in member.outputs:
                    key = (member.id, port.id)
                    if key not in internal_outputs or key in crossing_outputs:
                        ensure_port(entity.id, member.id, "output", port.id)

        # GraphIR stores model-call boundaries independently from operation
        # ports.  Expose those source tensors on the model entity without
        # pretending that an importer supplied a node/port binding.
        if level == "model" and len(selected) == 1:
            model_node = semantic_nodes[selected[0].id]
            for direction, tensors in (("input", source.inputs), ("output", source.outputs)):
                for index, tensor in enumerate(tensors):
                    port_id = stable_id(
                        "semantic_port",
                        f"{level}:{selected[0].id}:graph-{direction}:{index}:{tensor.name}",
                    )
                    port = Port(
                        id=port_id,
                        name=tensor.name or f"model {direction} {index + 1}",
                        direction=direction,
                        tensor=deepcopy(tensor),
                    )
                    (model_node.inputs if direction == "input" else model_node.outputs).append(port)
                    model_node.attributes["boundary_port_bindings"][port_id] = {
                        "source_node_id": None,
                        "source_port_id": None,
                        "source_edge_id": None,
                        "direction": direction,
                        "status": "exact-graph-boundary",
                        "tensor_source": f"graph-{direction}",
                    }

        # A semantic edge represents exactly one source edge.  Parallel edges
        # cannot be combined without losing port/tensor binding evidence.
        edges: list[Edge] = []
        for source_edge in source.edges:
            source_id = member_to_entity.get(source_edge.source)
            target_id = member_to_entity.get(source_edge.target)
            if not source_id or not target_id or source_id == target_id:
                continue
            source_port = (
                ensure_port(
                    source_id, source_edge.source, "output", source_edge.source_port,
                )
                if source_edge.source_port is not None else None
            )
            target_port = (
                ensure_port(
                    target_id, source_edge.target, "input", source_edge.target_port,
                )
                if source_edge.target_port is not None else None
            )
            semantic_edge = Edge(
                id=stable_id("semantic_edge", f"{level}:{source_id}:{target_id}:{source_edge.id}"),
                source=source_id,
                target=target_id,
                source_port=source_port,
                target_port=target_port,
                tensor=deepcopy(source_edge.tensor),
                kind=source_edge.kind,
                label=source_edge.label,
                visible=source_edge.visible,
                attributes={
                    "source_edge_id": source_edge.id,
                    "source_edges": [source_edge.id],
                    "source_nodes": [source_edge.source, source_edge.target],
                    "source_port_binding": {
                        "source_node_id": source_edge.source,
                        "source_port_id": source_edge.source_port,
                        "status": "exact" if source_edge.source_port is not None else "unknown",
                    },
                    "target_port_binding": {
                        "source_node_id": source_edge.target,
                        "source_port_id": source_edge.target_port,
                        "status": "exact" if source_edge.target_port is not None else "unknown",
                    },
                    "source_edge_attributes": deepcopy(source_edge.attributes),
                    "semantic_level": level,
                    "semantic_view": view,
                    "boundary_count": 1,
                },
            )
            edges.append(semantic_edge)

        result = GraphIR(
            name=f"{source.name} · {level.title()} · {view.title()}",
            nodes=nodes,
            edges=edges,
            inputs=deepcopy(source.inputs),
            outputs=deepcopy(source.outputs),
            metadata={
                **deepcopy(source.metadata),
                "semantic_view": {
                    "version": self.semantic_version,
                    "level": level,
                    "view": view,
                    "source_digest": self.source_digest,
                    "faithful": view == "faithful",
                    "semantic_to_source": {
                        entity.id: {
                            "source_node_ids": list(entity.provenance.source_node_ids),
                            "source_edge_ids": list(entity.provenance.source_edge_ids),
                        }
                        for entity in selected
                    },
                    "source_to_semantic": {
                        source_id: sorted({
                            entity.id
                            for entity in selected
                            if source_id in entity.provenance.source_node_ids
                            or source_id in entity.provenance.source_edge_ids
                        })
                        for source_id in sorted({
                            source_id
                            for entity in selected
                            for source_id in (
                                *entity.provenance.source_node_ids,
                                *entity.provenance.source_edge_ids,
                            )
                        })
                    },
                    "edge_to_source": {edge.id: edge.attributes["source_edge_id"] for edge in edges},
                    "port_evidence": {
                        node.id: deepcopy(node.attributes["boundary_port_bindings"])
                        for node in nodes
                    },
                },
            },
            analysis=deepcopy(source.analysis),
            ir_version=source.ir_version,
        )
        return result.validate()


def derive_semantic_view(graph: GraphIR) -> SemanticView:
    """Recognize a conservative five-level hierarchy with provenance."""
    graph.validate()
    nodes = graph.node_map()
    incident: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        incident[edge.source].append(edge.id)
        incident[edge.target].append(edge.id)

    operation_entities = [
        _entity(
            "operation",
            node.name,
            node.op_type.lower() or "operation",
            [node.id],
            incident[node.id],
            1.0,
            [f"Direct Graph IR operation {node.op_type!r}."],
            unknown=False,
        )
        for node in graph.nodes
    ]

    layer_groups: dict[str, list[str]] = defaultdict(list)
    for node in graph.nodes:
        path = (node.path or node.name).strip(".")
        parent_path = path.rsplit(".", 1)[0] if "." in path else path
        key = parent_path if parent_path and parent_path != node.name else node.id
        layer_groups[key].append(node.id)
    layer_entities: list[SemanticEntity] = []
    for key, member_ids in layer_groups.items():
        members = [nodes[node_id] for node_id in member_ids]
        known_layer = len(member_ids) > 1 or any(node.level == "layer" for node in members)
        layer_entities.append(_entity(
            "layer",
            key if known_layer and key not in nodes else members[0].name,
            _dominant_type(members) if known_layer else "unknown",
            member_ids,
            _internal_edges(graph, member_ids),
            0.82 if known_layer else 0.35,
            ["Shared framework/module path identifies this layer."] if known_layer else ["No reliable layer boundary; preserved as an unknown singleton."],
            unknown=not known_layer,
        ))

    block_entities, detections = _detect_blocks(graph)
    stage_entities, stage_detections = _detect_stages(graph, block_entities)
    detections.extend(stage_detections)
    detections.extend(_plugin_detections(graph))
    model_entity = _entity(
        "model", graph.name, "model", [node.id for node in graph.nodes], [edge.id for edge in graph.edges],
        1.0, ["Top-level boundary is the imported Graph IR model."], unknown=False,
    )

    entities = [model_entity, *stage_entities, *block_entities, *layer_entities, *operation_entities]
    _link_hierarchy(entities)
    source_to_semantic: dict[str, dict[str, list[str]]] = {
        level: defaultdict(list) for level in SEMANTIC_LEVELS
    }
    semantic_to_source: dict[str, SemanticProvenance] = {}
    for entity in entities:
        semantic_to_source[entity.id] = deepcopy(entity.provenance)
        for source_id in entity.provenance.source_node_ids:
            source_to_semantic[entity.level][source_id].append(entity.id)
        for source_id in entity.provenance.source_edge_ids:
            source_to_semantic[entity.level][source_id].append(entity.id)

    connections = {
        level: _semantic_connections(graph, [entity for entity in entities if entity.level == level], level)
        for level in SEMANTIC_LEVELS
    }
    source_digest = _graph_digest(graph)
    architecture_evidence = derive_architecture_evidence(
        graph,
        source_digest=source_digest,
        detections=detections,
        entities=entities,
    )
    view = SemanticView(
        name=graph.name,
        source_ir_version=graph.ir_version,
        source_digest=source_digest,
        entities=entities,
        connections=connections,
        source_to_semantic={
            level: {
                source_id: sorted(set(semantic_ids))
                for source_id, semantic_ids in sorted(mapping.items())
            }
            for level, mapping in source_to_semantic.items()
        },
        semantic_to_source=semantic_to_source,
        detections=detections,
        architecture_evidence=architecture_evidence,
    )
    return view.validate(graph)


def semantic_graph(graph: GraphIR, *, level: str = "block", view: str = "faithful") -> tuple[GraphIR, SemanticView]:
    semantic = derive_semantic_view(graph)
    return semantic.materialize(graph, level=normalize_semantic_level(level), view=view), semantic


def _detect_blocks(graph: GraphIR) -> tuple[list[SemanticEntity], list[dict[str, Any]]]:
    nodes = graph.node_map()
    claimed: set[str] = set()
    entities: list[SemanticEntity] = []
    detections: list[dict[str, Any]] = []

    # Explicit block boundaries are strongest; their semantic label is still
    # inferred conservatively from the contained operations.
    for group in graph.subgraphs:
        if group.level.lower() not in {"block", "module"}:
            continue
        member_ids = [node_id for node_id in group.node_ids if node_id in nodes and node_id not in claimed]
        if not member_ids:
            continue
        semantic_type, confidence, reasons = _classify_members(group.name, [nodes[item] for item in member_ids], explicit=True)
        entity = _entity("block", group.name, semantic_type, member_ids, _internal_edges(graph, member_ids), confidence, reasons, unknown=semantic_type == "unknown")
        entity.attributes["source_subgraph"] = group.id
        entities.append(entity)
        claimed.update(member_ids)
        detections.append(_detection(entity))

    candidates: list[tuple[int, str, list[str], float, list[str]]] = []
    incoming: dict[str, list[Edge]] = defaultdict(list)
    outgoing: dict[str, list[Edge]] = defaultdict(list)
    for edge in graph.edges:
        incoming[edge.target].append(edge)
        outgoing[edge.source].append(edge)

    # Diffusion loops are identifiable only when graph topology and names agree.
    for component in _strong_components(graph):
        members = [nodes[item] for item in component]
        text = " ".join(f"{node.name} {node.op_type}" for node in members).lower()
        if len(component) > 1 and any(word in text for word in ("diffusion", "scheduler", "denois")):
            candidates.append((100, "diffusion_loop", component, 0.96, ["A cyclic component contains a denoiser/scheduler diffusion marker."]))

    attention_ids = [
        node.id for node in graph.nodes
        if "attention" in f"{node.name} {node.op_type} {node.category}".lower()
    ]
    for attention_id in attention_ids:
        # A label alone is not evidence of an attention structure.  Require
        # observable connectivity plus either multi-input fan-in or an
        # importer-declared attention operation/category.
        attention_node = nodes[attention_id]
        declared_attention = "attention" in f"{attention_node.op_type} {attention_node.category}".lower()
        if (
            not incoming[attention_id]
            or not outgoing[attention_id]
            or (len(incoming[attention_id]) < 2 and not declared_attention)
        ):
            continue
        neighborhood = {attention_id}
        for edge in incoming[attention_id] + outgoing[attention_id]:
            other = edge.source if edge.target == attention_id else edge.target
            other_text = f"{nodes[other].name} {nodes[other].op_type}".lower()
            if any(token in other_text for token in ("query", "key", "value", " q", " k", " v", "projection", "proj")) or nodes[other].category in {"linear", "normalization"}:
                neighborhood.add(other)
        candidates.append((90, "attention", sorted(neighborhood), 0.93, [
            "An importer-declared attention operation has source-graph fan-in/fan-out and adjacent projection operations."
        ]))

    routers = [node.id for node in graph.nodes if "router" in f"{node.name} {node.op_type} {node.path} {node.namespace}".lower()]
    experts = [node.id for node in graph.nodes if "expert" in f"{node.name} {node.op_type} {node.path} {node.namespace}".lower()]
    if routers and experts:
        expert_set = set(experts)
        for router in routers:
            routed_experts = {
                edge.target for edge in outgoing[router]
                if edge.target in expert_set
            }
            merge_to_experts: dict[str, set[str]] = defaultdict(set)
            for expert in routed_experts:
                for edge in outgoing[expert]:
                    if nodes[edge.target].category == "merge":
                        merge_to_experts[edge.target].add(expert)
            for merge, contributing_experts in merge_to_experts.items():
                if len(contributing_experts) < 2:
                    continue
                member_ids = [router, *sorted(contributing_experts), merge]
                candidates.append((95, "moe_router_experts", member_ids, 0.97, [
                    "One router fans out to multiple declared experts that reconverge at the same merge operation."
                ]))

    for node in graph.nodes:
        merge_edges = incoming[node.id]
        label = f"{node.name} {node.op_type} {' '.join(node.tags)}".lower()
        if len(merge_edges) >= 2 and (_is_add_merge(node) or "residual" in label):
            residual_members = {node.id, *(edge.source for edge in merge_edges)}
            for edge in merge_edges:
                residual_members.update(parent.source for parent in incoming[edge.source])
            bypass_evidence = any(len(incoming[edge.source]) == 0 for edge in merge_edges) or len(residual_members) >= 4
            confidence = 0.94 if "residual" in label else 0.84 if bypass_evidence else 0.72
            reasons = [
                "Add/merge receives a bypass and transformed branch; residual marker present."
                if "residual" in label
                else "Elementwise add has two converging branches with unequal upstream depth; this is structural residual evidence."
                if bypass_evidence
                else "Elementwise add has multiple converging inputs; residual classification remains lower-confidence."
            ]
            candidates.append((85, "residual_block", sorted(residual_members), confidence, reasons))
            # Keep the complete merge-edge claim independently of renderable
            # block ownership.  Explicit module blocks can otherwise claim
            # branch operations first and leave a later residual entity with
            # only two functional add nodes and no edge provenance.
            detections.append(_source_detection(
                "residual_block",
                sorted(residual_members),
                [edge.id for edge in merge_edges],
                confidence,
                reasons,
            ))

    timestep_ids = [
        node.id for node in graph.nodes
        if any(marker in f"{node.name} {node.op_type} {node.path} {node.namespace}".lower() for marker in ("timestep", "time_embedding", "condition_projection"))
    ]
    if timestep_ids:
        conditioned: set[str] = set()
        for node_id in timestep_ids:
            targets = {
                edge.target for edge in outgoing[node_id]
                if len(incoming[edge.target]) >= 2
            }
            if targets:
                conditioned.add(node_id)
                conditioned.update(targets)
        if len(conditioned) >= 2:
            candidates.append((92, "timestep_conditioning", sorted(conditioned), 0.96, [
                "A declared timestep embedding joins another input at a downstream operation; the fan-in edge supplies conditioning evidence."
            ]))

    fusion_ids = [
        node.id for node in graph.nodes
        if any(marker in f"{node.name} {node.op_type} {node.path} {node.namespace}".lower() for marker in ("modality_fusion", "fusion_gate", "cross_modal"))
    ]
    if fusion_ids:
        fusion_members: set[str] = set()
        for node_id in fusion_ids:
            sources = {edge.source for edge in incoming[node_id]}
            if len(sources) >= 2:
                fusion_members.add(node_id)
                fusion_members.update(sources)
        if len(fusion_members) >= 3:
            candidates.append((93, "modality_fusion", sorted(fusion_members), 0.96, [
                "Multiple independent source branches converge at a declared fusion/gating operation."
            ]))

    # Preserve topology-backed detections even when explicit source subgraphs
    # already own some of their operations.  Detection provenance may overlap
    # an explicit semantic entity; renderable entities remain non-overlapping.
    timestep_evidence: set[str] = set()
    for node_id in timestep_ids:
        direct_edges = outgoing[node_id]
        joined_targets = [edge.target for edge in direct_edges if len(incoming[edge.target]) >= 2]
        if len(direct_edges) >= 2 or joined_targets:
            timestep_evidence.add(node_id)
            timestep_evidence.update(edge.target for edge in direct_edges)
    if len(timestep_evidence) >= 2:
        evidence_edges = _internal_edges(graph, timestep_evidence)
        detections.append(_source_detection(
            "timestep_conditioning", timestep_evidence, evidence_edges, 0.96,
            ["A declared timestep path branches into multiple consumers or joins another source at a conditioned operation."],
        ))

    components = _strong_components(graph)
    cyclic_nodes = {node_id for component in components if len(component) > 1 for node_id in component}
    denoiser_ids = [
        node.id for node in graph.nodes
        if any(marker in f"{node.name} {node.op_type} {node.path} {node.namespace}".lower()
               for marker in ("denois", "conditionalunet", "diffusion"))
    ]
    acyclic_conditioning = timestep_evidence - cyclic_nodes
    if not cyclic_nodes and acyclic_conditioning and denoiser_ids:
        evidence_path: list[str] = []
        for start in sorted(acyclic_conditioning):
            evidence_path = _source_path(outgoing, start, set(denoiser_ids))
            if evidence_path:
                break
        if evidence_path:
            evidence_nodes = set(evidence_path) | set(timestep_evidence)
            detections.append(_source_detection(
                "diffusion_component", evidence_nodes, _internal_edges(graph, evidence_nodes), 0.91,
                ["An acyclic timestep-conditioning path reaches a declared denoising component; no recurrent sampling loop is asserted."],
            ))

    fusion_set = set(fusion_ids)
    fusion_evidence: set[str] = set()
    for target_id, target_edges in incoming.items():
        branch_sources = {edge.source for edge in target_edges if edge.source in fusion_set}
        if len(branch_sources) >= 2:
            fusion_evidence.update(branch_sources)
            fusion_evidence.add(target_id)
    if len(fusion_evidence) >= 3:
        detections.append(_source_detection(
            "modality_fusion", fusion_evidence, _internal_edges(graph, fusion_evidence), 0.96,
            ["Two or more declared modality-projection branches converge at the same source-graph operation."],
        ))

    expert_merges: dict[str, set[str]] = defaultdict(set)
    for expert_id in experts:
        for edge in outgoing[expert_id]:
            expert_merges[edge.target].add(expert_id)
    for expert_merge, contributors in expert_merges.items():
        if len(contributors) < 2:
            continue
        for router_id in routers:
            router_path = _source_path(outgoing, router_id, _descendants(outgoing, expert_merge))
            if not router_path:
                continue
            evidence_nodes = set(experts) | {expert_merge} | set(router_path)
            detections.append(_source_detection(
                "moe_router_experts", evidence_nodes, _internal_edges(graph, evidence_nodes), 0.97,
                ["Multiple declared expert branches reconverge and meet a downstream path derived from a declared router."],
            ))
            break
        else:
            continue
        break

    for priority, semantic_type, member_ids, confidence, reasons in sorted(candidates, reverse=True):
        del priority
        available = [node_id for node_id in member_ids if node_id in nodes and node_id not in claimed]
        minimum = 2 if semantic_type != "attention" else 1
        if len(available) < minimum:
            continue
        name = _semantic_label(semantic_type, False)
        entity = _entity("block", name, semantic_type, available, _internal_edges(graph, available), confidence, reasons, unknown=False)
        entities.append(entity)
        claimed.update(available)
        detections.append(_detection(entity))

    # Repetition is recorded even when a surrounding semantic group already
    # exists.  It is useful to Paper View but does not steal source ownership.
    signatures: dict[str, list[str]] = defaultdict(list)
    for node in graph.nodes:
        normalized = re.sub(r"\d+", "#", f"{node.name}:{node.op_type}:{node.category}".lower())
        signatures[normalized].append(node.id)
    for signature, member_ids in signatures.items():
        if len(member_ids) < 2:
            continue
        detections.append({
            "semantic_type": "repeated_block",
            "confidence": 0.84,
            "reasons": ["Multiple operations share the same digit-normalized name/type/category signature."],
            "provenance": {"source_node_ids": member_ids, "source_edge_ids": _internal_edges(graph, member_ids)},
            "attributes": {"signature": signature, "repeat_count": len(member_ids)},
        })
        for entity in entities:
            overlap = set(entity.provenance.source_node_ids).intersection(member_ids)
            if overlap:
                entity.attributes.setdefault("repeat_members", []).extend(sorted(overlap))

    for node in graph.nodes:
        if node.id in claimed:
            continue
        semantic_type, confidence, reasons = _classify_members(node.name, [node], explicit=False)
        unknown = semantic_type == "unknown"
        entity = _entity("block", node.name, semantic_type, [node.id], [], confidence, reasons, unknown=unknown)
        entities.append(entity)
        detections.append(_detection(entity))
    return entities, detections


def _detect_stages(graph: GraphIR, blocks: list[SemanticEntity]) -> tuple[list[SemanticEntity], list[dict[str, Any]]]:
    nodes = graph.node_map()
    claimed: set[str] = set()
    stages: list[SemanticEntity] = []
    detections: list[dict[str, Any]] = []
    for group in graph.subgraphs:
        if group.level.lower() != "stage":
            continue
        member_ids = [node_id for node_id in group.node_ids if node_id in nodes and node_id not in claimed]
        if not member_ids:
            continue
        semantic_type, confidence, reasons = _classify_members(group.name, [nodes[item] for item in member_ids], explicit=True)
        if semantic_type == "unknown":
            semantic_type = "stage"
            confidence = 0.96
            reasons = ["Explicit Graph IR stage subgraph boundary."]
        entity = _entity("stage", group.name, semantic_type, member_ids, _internal_edges(graph, member_ids), confidence, reasons, unknown=False)
        entity.attributes["source_subgraph"] = group.id
        stages.append(entity)
        claimed.update(member_ids)
        detections.append(_detection(entity))

    for semantic_type, marker in (("encoder", "encoder"), ("decoder", "decoder")):
        member_ids = [
            node.id for node in graph.nodes
            if node.id not in claimed and marker in f"{node.name} {node.path} {node.namespace}".lower()
        ]
        connecting_edges = _internal_edges(graph, member_ids)
        explicit_region = any(
            len(set(member_ids).intersection(group.node_ids)) >= 2
            for group in graph.subgraphs
        )
        if len(member_ids) >= 2 and (connecting_edges or explicit_region):
            reasons = [
                f"Multiple {marker!r}-declared operations form a connected or explicit source-graph region."
            ]
            entity = _entity("stage", marker.title(), semantic_type, member_ids, _internal_edges(graph, member_ids), 0.91, reasons, unknown=False)
            stages.append(entity)
            claimed.update(member_ids)
            detections.append(_detection(entity))

    # Framework traces such as torchvision ResNet expose repeated top-level
    # ``layer1`` ... ``layerN`` module paths even when the tracing backend did
    # not preserve an explicit stage subgraph.  This is structural evidence,
    # not a conclusion derived from the model's display name.
    numbered_layers: dict[str, list[str]] = defaultdict(list)
    operation_order = {node.id: index for index, node in enumerate(graph.nodes)}
    for node in graph.nodes:
        if node.id in claimed:
            continue
        path = (node.path or "").strip(".")
        match = re.match(r"^(layer\d+)(?:\.|$)", path, flags=re.IGNORECASE)
        if match:
            numbered_layers[match.group(1).lower()].append(node.id)
    ordered_numbered = sorted(
        numbered_layers.items(), key=lambda item: int(item[0][len("layer"):])
    )
    first_indices = [min(operation_order[node_id] for node_id in member_ids) for _, member_ids in ordered_numbered]
    numbered_last_index = -1
    for layer_index, (marker, original_member_ids) in enumerate(ordered_numbered):
        member_ids = list(original_member_ids)
        start_index = first_indices[layer_index]
        if layer_index + 1 < len(first_indices):
            end_index = first_indices[layer_index + 1]
        else:
            end_index = max(operation_order[node_id] for node_id in member_ids) + 1
            while end_index < len(graph.nodes):
                boundary = graph.nodes[end_index]
                boundary_text = f"{boundary.name} {boundary.op_type}".lower()
                if not any(token in boundary_text for token in ("add", "relu")):
                    break
                end_index += 1
        member_ids.extend(
            node.id for node in graph.nodes[start_index:end_index]
            if node.id not in claimed and node.id not in member_ids
        )
        numbered_last_index = max(numbered_last_index, end_index - 1)
        if not member_ids:
            continue
        repeat_roots = sorted({
            ".".join((nodes[node_id].path or "").split(".")[:2])
            for node_id in member_ids
            if len((nodes[node_id].path or "").split(".")) >= 2
        })
        entity = _entity(
            "stage",
            marker.replace("layer", "Layer ").title(),
            "stage",
            member_ids,
            _internal_edges(graph, member_ids),
            0.94,
            [f"A shared top-level framework module path {marker!r} defines this stage boundary."],
            unknown=False,
        )
        entity.attributes.update({
            "module_path": marker,
            "repeat_count": len(repeat_roots),
            "repeat_members": repeat_roots,
        })
        stages.append(entity)
        claimed.update(member_ids)
        detections.append(_detection(entity))

    if ordered_numbered:
        first_index = first_indices[0]
        stem_ids = [node.id for node in graph.nodes[:first_index] if node.id not in claimed]
        head_ids = [node.id for node in graph.nodes[numbered_last_index + 1:] if node.id not in claimed]
        for name, member_ids, reason in (
            (
                "Input stem",
                stem_ids,
                "A contiguous input/convolution/pooling prefix precedes the repeated numbered layer stages.",
            ),
            (
                "Output head",
                head_ids,
                "A contiguous pooling/flatten/linear/output suffix follows the repeated numbered layer stages.",
            ),
        ):
            if not member_ids:
                continue
            entity = _entity(
                "stage", name, "stage", member_ids, _internal_edges(graph, member_ids), 0.9,
                [reason], unknown=False,
            )
            stages.append(entity)
            claimed.update(member_ids)
            detections.append(_detection(entity))

    # A U-Net skip is an edge-level detection, retained separately because it
    # may connect already-recognized encoder and decoder stages.
    for edge in graph.edges:
        source_text = f"{nodes[edge.source].name} {nodes[edge.source].path}".lower()
        target_text = f"{nodes[edge.target].name} {nodes[edge.target].path}".lower()
        direct = "encoder" in source_text and "decoder" in target_text
        through_merge = "encoder" in source_text and any(
            "decoder" in f"{nodes[next_edge.target].name} {nodes[next_edge.target].path}".lower()
            for next_edge in graph.edges
            if next_edge.source == edge.target
        )
        if direct or through_merge:
            detections.append({
                "semantic_type": "unet_skip",
                "confidence": 0.97 if direct else 0.93,
                "reasons": [
                    "Direct encoder-to-decoder edge bypasses the bottleneck."
                    if direct else
                    "Encoder output reaches a decoder through a one-hop concatenation/merge boundary, bypassing the bottleneck."
                ],
                "provenance": {"source_node_ids": [edge.source, edge.target], "source_edge_ids": [edge.id]},
            })

    # FX/module views may place functional concatenate/add nodes between the
    # named encoder and decoder modules.  Detect the actual cross-bottleneck
    # edge from topology so the skip survives even when neither endpoint name
    # contains "encoder" or "decoder".
    encoder_nodes = {
        node.id for node in graph.nodes
        if "encoder" in f"{node.path} {node.namespace}".casefold()
    }
    decoder_nodes = {
        node.id for node in graph.nodes
        if "decoder" in f"{node.path} {node.namespace}".casefold()
    }
    bottleneck_nodes = {
        node.id for node in graph.nodes
        if any(marker in f"{node.path} {node.namespace}".casefold() for marker in ("bottleneck", "middle", "mid_block"))
    }
    if encoder_nodes and decoder_nodes and bottleneck_nodes:
        outgoing_map: dict[str, list[Edge]] = defaultdict(list)
        incoming_map: dict[str, list[Edge]] = defaultdict(list)
        for candidate_edge in graph.edges:
            outgoing_map[candidate_edge.source].append(candidate_edge)
            incoming_map[candidate_edge.target].append(candidate_edge)
        encoder_descendants = set().union(*(_descendants(outgoing_map, node_id) for node_id in encoder_nodes))
        decoder_ancestors = set().union(*(_ancestors(incoming_map, node_id) for node_id in decoder_nodes))
        bottleneck_ancestors = set().union(*(_ancestors(incoming_map, node_id) for node_id in bottleneck_nodes))
        bottleneck_descendants = set().union(*(_descendants(outgoing_map, node_id) for node_id in bottleneck_nodes))
        recorded_skip_edges = {
            edge_id
            for detection in detections
            if detection.get("semantic_type") == "unet_skip"
            for edge_id in detection.get("provenance", {}).get("source_edge_ids", [])
        }
        for edge in graph.edges:
            if edge.id in recorded_skip_edges:
                continue
            if (
                edge.source in encoder_descendants
                and edge.source in bottleneck_ancestors
                and edge.target in decoder_ancestors
                and edge.target in bottleneck_descendants
                and len(incoming_map[edge.target]) >= 2
            ):
                detections.append({
                    "semantic_type": "unet_skip",
                    "confidence": 0.96,
                    "reasons": [
                        "A source edge crosses from the encoder-side ancestry to a post-bottleneck decoder merge, bypassing the bottleneck path."
                    ],
                    "provenance": {
                        "source_node_ids": [edge.source, edge.target],
                        "source_edge_ids": [edge.id],
                    },
                    "unknown": False,
                    "evidence_kind": "source-topology",
                })

    remaining = [node.id for node in graph.nodes if node.id not in claimed]
    if remaining:
        # Preserve unknown content as one honest stage.  Block-level drilldown
        # still exposes all recognized and singleton blocks beneath it.
        entity = _entity(
            "stage", "Unclassified stage", "unknown", remaining, _internal_edges(graph, remaining), 0.2,
            ["No reliable stage boundary was present in names, hierarchy, or topology."], unknown=True,
        )
        stages.append(entity)
        detections.append(_detection(entity))
    return stages, detections


def _classify_members(name: str, members: list[Node], *, explicit: bool) -> tuple[str, float, list[str]]:
    del name
    # Display names and paths are user-controlled labels.  A subtype claim may
    # use declared operation/category/tag evidence, but never a keyword in a
    # name alone.  Topological recognizers above may combine labels with edges.
    declared_text = " ".join(
        f"{node.op_type} {node.category} {' '.join(node.tags)}"
        for node in members
    ).lower()
    patterns = [
        # Acyclic denoiser modules are diffusion components, not loops.  The
        # stronger ``diffusion_loop`` label is reserved for the SCC detector.
        ("diffusion_component", ("diffusion", "scheduler", "denois")),
        ("moe_router_experts", ("router", "expert", "moe")),
        ("timestep_conditioning", ("timestep", "time_embedding", "condition_projection")),
        ("modality_fusion", ("modality_fusion", "fusion_gate", "cross_modal")),
        ("attention", ("attention", "multihead", "self-attn", "cross-attn")),
        ("residual_block", ("residual", "resnet", "skip add")),
        ("encoder", ("encoder", "downsample")),
        ("decoder", ("decoder", "upsample", "upconv")),
    ]
    for semantic_type, markers in patterns:
        present = [marker for marker in markers if marker in declared_text]
        if present:
            confidence = min(0.98, (0.88 if explicit else 0.72) + 0.04 * len(present))
            return semantic_type, confidence, [f"{'Explicit boundary and ' if explicit else ''}semantic marker(s): {', '.join(present)}."]
    if explicit:
        return "block", 0.95, ["Explicit Graph IR block/module boundary; subtype is not asserted."]
    return "unknown", 0.25, ["No reliable block pattern; retained without invented semantics."]


def _entity(
    level: str,
    name: str,
    semantic_type: str,
    node_ids: Iterable[str],
    edge_ids: Iterable[str],
    confidence: float,
    reasons: list[str],
    *,
    unknown: bool,
) -> SemanticEntity:
    nodes = list(dict.fromkeys(node_ids))
    edges = list(dict.fromkeys(edge_ids))
    identity = f"{level}:{semantic_type}:{'|'.join(nodes)}"
    return SemanticEntity(
        id=stable_id("semantic", identity),
        name=name,
        level=level,
        semantic_type=semantic_type,
        confidence=max(0.0, min(1.0, confidence)),
        reasons=reasons,
        provenance=SemanticProvenance(nodes, edges),
        unknown=unknown,
    )


def _link_hierarchy(entities: list[SemanticEntity]) -> None:
    by_level = {level: [entity for entity in entities if entity.level == level] for level in SEMANTIC_LEVELS}
    for index in range(1, len(SEMANTIC_LEVELS)):
        level = SEMANTIC_LEVELS[index]
        parents = by_level[SEMANTIC_LEVELS[index - 1]]
        parent_by_id = {parent.id: parent for parent in parents}
        owners: dict[str, list[str]] = defaultdict(list)
        for parent in parents:
            for node_id in parent.provenance.source_node_ids:
                owners[node_id].append(parent.id)
        for child in by_level[level]:
            overlap_counts: dict[str, int] = defaultdict(int)
            for node_id in child.provenance.source_node_ids:
                for parent_id in owners.get(node_id, []):
                    overlap_counts[parent_id] += 1
            if not overlap_counts:
                continue
            parent_id = max(
                overlap_counts,
                key=lambda item: (overlap_counts[item], -len(parent_by_id[item].provenance.source_node_ids), item),
            )
            parent = parent_by_id[parent_id]
            child.parent_id = parent.id
            parent.child_ids.append(child.id)


def _semantic_connections(graph: GraphIR, entities: list[SemanticEntity], level: str) -> list[SemanticConnection]:
    owner: dict[str, str] = {}
    for entity in entities:
        for node_id in entity.provenance.source_node_ids:
            owner[node_id] = entity.id
    grouped: dict[tuple[str, str, str], list[Edge]] = defaultdict(list)
    for edge in graph.edges:
        source = owner.get(edge.source)
        target = owner.get(edge.target)
        if source and target and source != target:
            grouped[(source, target, edge.kind)].append(edge)
    result: list[SemanticConnection] = []
    for (source, target, kind), edges in sorted(grouped.items()):
        edge_ids = [edge.id for edge in edges]
        result.append(SemanticConnection(
            id=stable_id("semantic_connection", f"{level}:{source}:{target}:{kind}"),
            source=source,
            target=target,
            kind=kind,
            provenance=SemanticProvenance(
                sorted({edge.source for edge in edges} | {edge.target for edge in edges}), edge_ids,
            ),
            reasons=["Aggregated from explicit Graph IR edge provenance."],
        ))
    return result


def _paper_entities(entities: list[SemanticEntity], graph: GraphIR) -> list[SemanticEntity]:
    """Collapse structurally equivalent semantic regions for a paper view.

    Faithful View retains every entity.  This transformation is deliberately
    separate and groups only confident, already-recognized regions.  Unknown
    entities are never merged because structural similarity alone would not be
    sufficient evidence for a semantic claim.
    """
    nodes = graph.node_map()
    grouped: dict[tuple[Any, ...], list[SemanticEntity]] = defaultdict(list)
    for entity in entities:
        members = [nodes[node_id] for node_id in entity.provenance.source_node_ids if node_id in nodes]
        operation_signature = tuple(
            (re.sub(r"\d+", "#", node.op_type.lower()), node.category.lower())
            for node in members
        )
        if entity.level in {"model", "stage"} or entity.unknown or entity.confidence < 0.7 or not operation_signature:
            signature: tuple[Any, ...] = ("unique", entity.id)
        else:
            signature = (entity.level, entity.semantic_type, operation_signature)
        grouped[signature].append(entity)

    result: list[SemanticEntity] = []
    for group in grouped.values():
        if len(group) == 1:
            item = deepcopy(group[0])
            item.attributes["conceptualized"] = True
            repeat_count = int(item.attributes.get("repeat_count", 1))
            if repeat_count > 1 and "×" not in item.name:
                item.name = f"{item.name} ×{repeat_count}"
            result.append(item)
            continue
        source_nodes = list(dict.fromkeys(
            source_id for entity in group for source_id in entity.provenance.source_node_ids
        ))
        source_edges = list(dict.fromkeys(
            source_id for entity in group for source_id in entity.provenance.source_edge_ids
        ))
        semantic_type = group[0].semantic_type
        operation_types = [nodes[node_id].op_type.lower() for node_id in group[0].provenance.source_node_ids if node_id in nodes]
        if semantic_type == "attention":
            base_name = "Attention block"
        elif semantic_type == "encoder":
            base_name = "Encoder block"
        elif semantic_type == "decoder":
            base_name = "Decoder block"
        elif semantic_type == "residual_block":
            base_name = "Residual merge"
        elif operation_types.count("conv2d") >= 3 and sum("batchnorm" in item for item in operation_types) >= 3:
            base_name = "Bottleneck block"
        else:
            normalized = re.sub(r"\b\d+\b", "", group[0].name).strip(" ._-")
            base_name = normalized or _semantic_label(semantic_type, False)
        identity = f"paper:{group[0].level}:{semantic_type}:{'|'.join(entity.id for entity in group)}"
        result.append(SemanticEntity(
            id=stable_id("semantic", identity),
            name=f"{base_name} ×{len(group)}",
            level=group[0].level,
            semantic_type=semantic_type,
            confidence=min(entity.confidence for entity in group),
            reasons=[
                *list(dict.fromkeys(reason for entity in group for reason in entity.reasons)),
                f"Paper View groups {len(group)} structurally equivalent semantic regions; every source operation remains traceable.",
            ],
            provenance=SemanticProvenance(source_nodes, source_edges),
            child_ids=list(dict.fromkeys(child for entity in group for child in entity.child_ids)),
            attributes={
                "conceptualized": True,
                "repeat_count": len(group),
                "source_semantic_ids": [entity.id for entity in group],
            },
            unknown=False,
        ))
    return result


def _aggregate_analysis(nodes: list[Node]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    numeric_keys = {key for node in nodes for key, value in node.analysis.items() if isinstance(value, (int, float)) and not isinstance(value, bool)}
    for key in numeric_keys:
        values = [node.analysis[key] for node in nodes if isinstance(node.analysis.get(key), (int, float))]
        if values:
            result[key] = sum(values)
    result["semantic_source_count"] = len(nodes)
    return result


def _semantic_category(semantic_type: str, members: list[Node]) -> str:
    if semantic_type == "attention":
        return "attention"
    if semantic_type == "moe_router_experts":
        return "routing"
    if semantic_type in {"residual_block", "encoder", "decoder", "diffusion_loop", "diffusion_component", "timestep_conditioning"}:
        return "convolution"
    counts: dict[str, int] = defaultdict(int)
    for node in members:
        counts[node.category] += 1
    return max(counts, key=lambda key: (counts[key], key)) if counts else "operation"


def _semantic_label(semantic_type: str, unknown: bool) -> str:
    labels = {
        "model": "Model",
        "stage": "Stage",
        "block": "Block",
        "residual_block": "ResidualBlock",
        "attention": "Attention",
        "encoder": "Encoder",
        "decoder": "Decoder",
        "moe_router_experts": "MoE",
        "diffusion_loop": "DiffusionLoop",
        "diffusion_component": "DiffusionComponent",
        "repeated_block": "RepeatedBlock",
        "timestep_conditioning": "TimestepConditioning",
        "modality_fusion": "ModalityFusion",
    }
    return "Unknown" if unknown else labels.get(semantic_type, semantic_type.replace("_", " ").title())


def _dominant_type(nodes: list[Node]) -> str:
    counts: dict[str, int] = defaultdict(int)
    for node in nodes:
        counts[node.op_type.lower()] += 1
    return max(counts, key=lambda key: (counts[key], key)) if counts else "unknown"


def _is_add_merge(node: Node) -> bool:
    text = f"{node.name} {node.op_type} {node.attributes.get('target', '')}".lower()
    return any(token in text for token in (" add", "add_", "operator.add", "function add", "aten::add", "sum"))


def _internal_edges(graph: GraphIR, node_ids: Iterable[str]) -> list[str]:
    selected = set(node_ids)
    if len(selected) < 2:
        return []
    return [edge.id for edge in graph.edges if edge.source in selected and edge.target in selected]


def _detection(entity: SemanticEntity) -> dict[str, Any]:
    return {
        "semantic_id": entity.id,
        "semantic_type": entity.semantic_type,
        "confidence": entity.confidence,
        "reasons": list(entity.reasons),
        "provenance": asdict(entity.provenance),
        "unknown": entity.unknown,
    }


def _plugin_detections(graph: GraphIR) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    known_nodes = set(graph.node_map())
    known_edges = set(graph.edge_map())
    for name, recognizer in sorted(SEMANTIC_RECOGNIZERS.items()):
        try:
            detections = recognizer(graph.copy())
            if not isinstance(detections, list):
                raise TypeError("recognizer must return a list of detection dictionaries")
            for item in detections:
                if not isinstance(item, dict):
                    raise TypeError("each detection must be a dictionary")
                provenance = item.get("provenance", {})
                nodes = [str(value) for value in provenance.get("source_node_ids", [])]
                edges = [str(value) for value in provenance.get("source_edge_ids", [])]
                confidence = float(item.get("confidence", -1))
                reasons = [str(value) for value in item.get("reasons", [])]
                if not 0 <= confidence <= 1 or not reasons or not set(nodes).issubset(known_nodes) or not set(edges).issubset(known_edges):
                    raise ValueError("detection needs confidence, reasons, and valid source node/edge provenance")
                result.append({**item, "plugin": name, "provenance": {"source_node_ids": nodes, "source_edge_ids": edges}})
        except Exception as exc:
            # A third-party recognizer is local executable code, but its
            # failure remains an explicit unknown instead of crashing import.
            result.append({
                "semantic_type": "unknown",
                "confidence": 0.0,
                "reasons": [f"Semantic recognizer plugin {name!r} failed: {type(exc).__name__}: {exc}"],
                "provenance": {"source_node_ids": [], "source_edge_ids": []},
                "unknown": True,
                "plugin": name,
                "plugin_error": True,
            })
    return result


def _source_detection(
    semantic_type: str,
    node_ids: Iterable[str],
    edge_ids: Iterable[str],
    confidence: float,
    reasons: list[str],
) -> dict[str, Any]:
    """Build a topology detection that need not own a renderable entity."""
    return {
        "semantic_type": semantic_type,
        "confidence": max(0.0, min(1.0, confidence)),
        "reasons": list(reasons),
        "provenance": {
            "source_node_ids": list(dict.fromkeys(sorted(node_ids))),
            "source_edge_ids": list(dict.fromkeys(sorted(edge_ids))),
        },
        "unknown": False,
        "evidence_kind": "source-topology",
    }


def _descendants(outgoing: dict[str, list[Edge]], start: str) -> set[str]:
    result = {start}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for edge in outgoing.get(current, []):
            if edge.target not in result:
                result.add(edge.target)
                queue.append(edge.target)
    return result


def _ancestors(incoming: dict[str, list[Edge]], start: str) -> set[str]:
    result = {start}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for edge in incoming.get(current, []):
            if edge.source not in result:
                result.add(edge.source)
                queue.append(edge.source)
    return result


def _source_path(outgoing: dict[str, list[Edge]], start: str, targets: set[str]) -> list[str]:
    """Return one deterministic source-node path to any target."""
    if start in targets:
        return [start]
    parent: dict[str, str | None] = {start: None}
    queue = deque([start])
    reached: str | None = None
    while queue and reached is None:
        current = queue.popleft()
        for edge in sorted(outgoing.get(current, []), key=lambda item: (item.target, item.id)):
            if edge.target in parent:
                continue
            parent[edge.target] = current
            if edge.target in targets:
                reached = edge.target
                break
            queue.append(edge.target)
    if reached is None:
        return []
    path: list[str] = []
    cursor: str | None = reached
    while cursor is not None:
        path.append(cursor)
        cursor = parent[cursor]
    return list(reversed(path))


def _strong_components(graph: GraphIR) -> list[list[str]]:
    adjacency: dict[str, list[str]] = {node.id: [] for node in graph.nodes}
    reverse: dict[str, list[str]] = {node.id: [] for node in graph.nodes}
    for edge in graph.edges:
        adjacency[edge.source].append(edge.target)
        reverse[edge.target].append(edge.source)
    visited: set[str] = set()
    order: list[str] = []
    for start in adjacency:
        if start in visited:
            continue
        stack: list[tuple[str, bool]] = [(start, False)]
        while stack:
            current, expanded = stack.pop()
            if expanded:
                order.append(current)
                continue
            if current in visited:
                continue
            visited.add(current)
            stack.append((current, True))
            stack.extend((target, False) for target in adjacency[current] if target not in visited)
    components: list[list[str]] = []
    visited.clear()
    for start in reversed(order):
        if start in visited:
            continue
        component: list[str] = []
        queue = deque([start])
        visited.add(start)
        while queue:
            current = queue.popleft()
            component.append(current)
            for target in reverse[current]:
                if target not in visited:
                    visited.add(target)
                    queue.append(target)
        components.append(sorted(component))
    return components


def _graph_digest(graph: GraphIR) -> str:
    """Hash the complete semantic source and every tensor/port binding.

    Graph-level presentation metadata, annotations, and layout constraints are
    intentionally outside this digest, as is derived per-node ``analysis``.
    Every imported/source field on nodes and edges, including nested Port and
    TensorSpec records, is inside it; changing a shape, dtype, dynamic axis,
    port ID, or edge binding invalidates a stale Semantic View.
    """
    structural = {
        "ir_version": graph.ir_version,
        "name": graph.name,
        "nodes": [
            {key: value for key, value in asdict(node).items() if key != "analysis"}
            for node in graph.nodes
        ],
        "edges": [asdict(edge) for edge in graph.edges],
        "subgraphs": [asdict(group) for group in graph.subgraphs],
        "inputs": [asdict(tensor) for tensor in graph.inputs],
        "outputs": [asdict(tensor) for tensor in graph.outputs],
    }
    return sha256(json.dumps(structural, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def normalize_semantic_level(level: str) -> str:
    """Return the persisted semantic level for a public hierarchy spelling."""

    requested = str(level).strip().lower()
    normalized = SEMANTIC_LEVEL_ALIASES.get(requested, requested)
    if normalized not in SEMANTIC_LEVELS:
        choices = (*SEMANTIC_SELECTION_LEVELS, *SEMANTIC_LEVELS)
        raise ValidationError(
            f"Unknown semantic level {level!r}",
            hint=f"Choose one of: {', '.join(dict.fromkeys(choices))}.",
        )
    return normalized


def _check_level(level: str) -> None:
    normalize_semantic_level(level)


def _check_view(view: str) -> None:
    if view not in VIEW_MODES:
        raise ValidationError(f"Unknown semantic view {view!r}", hint=f"Choose one of: {', '.join(VIEW_MODES)}.")


__all__ = [
    "SEMANTIC_LEVELS",
    "SEMANTIC_LEVEL_ALIASES",
    "SEMANTIC_SELECTION_LEVELS",
    "SEMANTIC_VIEW_VERSION",
    "SEMANTIC_RECOGNIZERS",
    "VIEW_MODES",
    "SemanticConnection",
    "ArchitectureEvidence",
    "SemanticEntity",
    "SemanticProvenance",
    "SemanticView",
    "derive_semantic_view",
    "normalize_semantic_level",
    "semantic_graph",
    "register_semantic_recognizer",
]
