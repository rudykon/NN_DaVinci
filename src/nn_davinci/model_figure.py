"""Evidence-preserving Graph IR → Semantic View → Figure IR pipeline."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict
import heapq
from typing import Any, Iterable

from .architecture_evidence import ArchitectureEvidence, ArchitectureRole, CriticalRoute
from .architecture_role_graph import RoleGraphEdge, build_architecture_role_graph
from .errors import ValidationError
from .figure_ir import FigureIR, FigureObject, FigureProvenance, FigureStyle, new_figure
from .ir import Edge, GraphIR, Node, Port, TensorSpec, stable_id
from .layout import LayoutEngine, LayoutResult, focus_graph
from .semantic import SemanticView, derive_semantic_view, normalize_semantic_level
from .viewport import Viewport, viewport_slice


MODEL_FIGURE_PIPELINE_VERSION = "1.0"
MAXIMUM_UNFOCUSED_OPERATION_NODES = 80


# The real-model corpus is intentionally drawn from its faithful module Graph
# rather than from a canned illustration.  These specifications name only the
# publication lanes; membership and every evidence ID are recovered from the
# imported Graph IR below.  Keeping the lane vocabulary here makes the
# projection deterministic while allowing the model implementation to remain
# the source of truth.
_LEGACY_CORPUS_PUBLICATION_SPECS: dict[str, dict[str, Any]] = {
    "resnet50": {
        "groups": (
            ("stem", "Input & stem", 1),
            ("stage1", "Residual stage 1", 3),
            ("stage2", "Residual stage 2", 4),
            ("stage3", "Residual stage 3", 6),
            ("stage4", "Residual stage 4", 3),
            ("head", "Pooling & classifier", 1),
        ),
        "links": (("stem", "stage1"), ("stage1", "stage2"), ("stage2", "stage3"), ("stage3", "stage4"), ("stage4", "head")),
        "layout": "sequence",
    },
    "vision_transformer": {
        "groups": (("input", "Patches & tokens", 1), ("encoder", "Transformer encoder", 3), ("head", "Norm & classifier", 1)),
        "links": (("input", "encoder"), ("encoder", "head")),
        "layout": "sequence",
    },
    "bert_encoder": {
        "groups": (("input", "Token + position", 1), ("encoder", "Transformer encoder", 3), ("head", "Pooler & output", 1)),
        "links": (("input", "encoder"), ("encoder", "head")),
        "layout": "sequence",
    },
    "multiscale_unet": {
        "groups": (("input", "Image input", 1), ("encoder", "Encoder", 3), ("bottleneck", "Bottleneck", 1), ("decoder", "Decoder + skip fusion", 3), ("head", "Segmentation head", 1)),
        "links": (("input", "encoder"), ("encoder", "bottleneck"), ("bottleneck", "decoder"), ("decoder", "head")),
        "layout": "sequence",
    },
    "diffusion_unet": {
        "groups": (("input", "Latent + timestep", 1), ("encoder", "Conditioned encoder", 1), ("bottleneck", "Bottleneck", 1), ("decoder", "Conditioned decoder", 1), ("head", "Denoised output", 1)),
        "links": (("input", "encoder"), ("encoder", "bottleneck"), ("bottleneck", "decoder"), ("decoder", "head")),
        "layout": "sequence",
    },
    "topk_moe": {
        "groups": (("input", "Token embedding", 1), ("router", "Top-k router", 1), ("experts", "Expert MLPs", 4), ("combine", "Weighted combine", 1)),
        "links": (("input", "router"), ("input", "experts"), ("router", "combine"), ("experts", "combine")),
        "layout": "fork-join",
    },
    "image_text": {
        "groups": (("image", "Image encoder", 1), ("text", "Text encoder", 1), ("fusion", "Gated fusion", 1), ("head", "Output head", 1)),
        "links": (("image", "fusion"), ("text", "fusion"), ("fusion", "head")),
        "layout": "dual-input",
    },
}


def _topological_nodes(graph: GraphIR) -> list[Node]:
    """Return a stable topological order, retaining source order on ties."""

    by_id = graph.node_map()
    source_order = {node.id: index for index, node in enumerate(graph.nodes)}
    indegree = {node.id: 0 for node in graph.nodes}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        if edge.source == edge.target:
            continue
        outgoing[edge.source].append(edge.target)
        indegree[edge.target] += 1
    ready = [(source_order[node_id], node_id) for node_id, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    ordered: list[Node] = []
    while ready:
        _, node_id = heapq.heappop(ready)
        ordered.append(by_id[node_id])
        for target in sorted(outgoing[node_id], key=source_order.__getitem__):
            indegree[target] -= 1
            if indegree[target] == 0:
                heapq.heappush(ready, (source_order[target], target))
    return ordered if len(ordered) == len(graph.nodes) else list(graph.nodes)


def _legacy_explicit_corpus_group(corpus_key: str, node: Node) -> str | None:
    """Compatibility-only 0.7.2 corpus grouping; never used in production."""

    path = str(node.path or node.name).lower()
    name = str(node.name).lower()
    category = str(node.category).lower()
    if corpus_key == "resnet50":
        if path.startswith("layer1."):
            return "stage1"
        if path.startswith("layer2."):
            return "stage2"
        if path.startswith("layer3."):
            return "stage3"
        if path.startswith("layer4."):
            return "stage4"
        if category == "input" or path in {"conv1", "bn1", "relu", "maxpool"}:
            return "stem"
        if category == "output" or path in {"avgpool", "fc", "flatten"}:
            return "head"
    elif corpus_key == "vision_transformer":
        if path.startswith("encoder."):
            return "encoder"
        if category == "input" or any(token in path for token in ("patch_embedding", "class_token", "position_embedding")):
            return "input"
        if category == "output" or path in {"norm", "head"}:
            return "head"
    elif corpus_key == "bert_encoder":
        if path.startswith("encoder."):
            return "encoder"
        if category == "input" or any(token in path for token in ("token_embedding", "position_embedding", "arange", "unsqueeze")):
            return "input"
        if category == "output" or path in {"pooler", "tanh"}:
            return "head"
    elif corpus_key == "multiscale_unet":
        if category == "input":
            return "input"
        if path.startswith("encoder") or path == "pool":
            return "encoder"
        if path.startswith("bottleneck"):
            return "bottleneck"
        if path.startswith("decoder") or name.startswith(("interpolate", "cat")):
            return "decoder"
        if category == "output" or path.startswith("segmentation_head"):
            return "head"
    elif corpus_key == "diffusion_unet":
        if category == "input" or path in {"reshape", "float"}:
            return "input"
        if path.startswith("encoder") or path.startswith("downsample") or path.startswith("timestep_embedding"):
            return "encoder"
        if path.startswith("bottleneck"):
            return "bottleneck"
        if path.startswith("decoder") or path.startswith("upsample"):
            return "decoder"
        if category == "output" or path.startswith("denoised_output"):
            return "head"
    elif corpus_key == "topk_moe":
        if category == "input" or path.startswith("token_embedding"):
            return "input"
        if path.startswith("router") or name.startswith(("softmax", "topk", "one_hot", "getitem")):
            return "router"
        if path.startswith("experts."):
            return "experts"
        if category == "output" or path.startswith("output_norm") or name.startswith(("stack", "mul", "sum", "add")):
            return "combine"
    elif corpus_key == "image_text":
        if name == "image" or path.startswith("image_encoder") or name == "flatten":
            return "image"
        if name == "token_ids" or path.startswith("text_encoder") or name.startswith(("getitem", "mean")):
            return "text"
        if path.startswith("modality_fusion") or name.startswith(("cat", "sigmoid", "mul", "sub", "add")):
            return "fusion"
        if category == "output" or path.startswith("output_head"):
            return "head"
    return None


def _legacy_corpus_assignments(graph: GraphIR, corpus_key: str, group_keys: list[str]) -> tuple[list[Node], dict[str, str]]:
    """Compatibility-only assignment retained for historical fixtures."""

    ordered = _topological_nodes(graph)
    positions = {node.id: index for index, node in enumerate(ordered)}
    group_order = {key: index for index, key in enumerate(group_keys)}
    assignments = {node.id: _legacy_explicit_corpus_group(corpus_key, node) for node in ordered}
    explicit = [(positions[node_id], group) for node_id, group in assignments.items() if group is not None]
    for node in ordered:
        if assignments[node.id] is not None:
            continue
        index = positions[node.id]
        prior = [(position, group) for position, group in explicit if position < index]
        following = [(position, group) for position, group in explicit if position > index]
        if prior:
            group = max(prior, key=lambda item: item[0])[1]
        elif following:
            group = min(following, key=lambda item: item[0])[1]
        else:
            group = group_keys[min(len(group_keys) - 1, round(index / max(1, len(ordered) - 1) * (len(group_keys) - 1)))]
        assignments[node.id] = group
    # A nearest-anchor assignment can only return declared group keys; the
    # assertion converts a programming error into an actionable validation.
    invalid = sorted({str(group) for group in assignments.values()} - set(group_order))
    if invalid:
        raise ValidationError(f"Publication projection produced undeclared groups {invalid!r}")
    return ordered, {node_id: str(group) for node_id, group in assignments.items()}


def _tensor_inventory(nodes: Iterable[Node]) -> list[dict[str, Any]]:
    return [
        {
            "node_id": node.id,
            "port_id": port.id,
            "name": port.name,
            "tensor": asdict(port.tensor) if port.tensor else None,
        }
        for node in nodes
        for port in node.outputs
    ]


def _architecture_role_pairs(evidence: ArchitectureEvidence) -> list[tuple[str, str]]:
    """Return evidence-role flow pairs without consulting a case or layout key."""

    roles = sorted(evidence.detected_roles, key=lambda item: (item.order, item.id))
    by_kind: dict[str, list[ArchitectureRole]] = defaultdict(list)
    for role in roles:
        by_kind[role.role].append(role)
    if evidence.family == "multimodal-fusion":
        fusion = by_kind["fusion"][0]
        output = by_kind["output-head"][0]
        return [
            (by_kind["image-lane"][0].id, fusion.id),
            (by_kind["text-lane"][0].id, fusion.id),
            (fusion.id, output.id),
        ]
    if evidence.family == "moe":
        input_role = by_kind["input"][0]
        router = by_kind["router"][0]
        experts = by_kind["experts"][0]
        combine = by_kind["weighted-combine"][0]
        output = by_kind["output-head"][0]
        return [
            (input_role.id, router.id),
            (input_role.id, experts.id),
            (router.id, combine.id),
            (experts.id, combine.id),
            (combine.id, output.id),
        ]
    if evidence.family == "diffusion-unet":
        structural = [role for role in roles if role.role != "conditioning"]
        return [(source.id, target.id) for source, target in zip(structural, structural[1:])]
    return [(source.id, target.id) for source, target in zip(roles, roles[1:])]


def _source_path_edges(graph: GraphIR, source_ids: Iterable[str], target_ids: Iterable[str]) -> list[Edge]:
    """Find one shortest directed Graph IR path between two role regions."""

    sources = set(source_ids)
    targets = set(target_ids)
    direct = [edge for edge in graph.edges if edge.source in sources and edge.target in targets]
    if direct:
        return direct
    outgoing: dict[str, list[Edge]] = defaultdict(list)
    for edge in graph.edges:
        outgoing[edge.source].append(edge)
    queue: list[tuple[str, list[Edge]]] = [(node_id, []) for node_id in sources]
    visited = set(sources)
    cursor = 0
    while cursor < len(queue):
        node_id, path = queue[cursor]
        cursor += 1
        for edge in outgoing[node_id]:
            candidate = [*path, edge]
            if edge.target in targets:
                return candidate
            if edge.target not in visited:
                visited.add(edge.target)
                queue.append((edge.target, candidate))
    return []


def _architecture_projection_edge(
    graph: GraphIR,
    semantic: SemanticView,
    source: Node,
    target: Node,
    evidence_edges: Iterable[Edge],
    *,
    identity: str,
    label: str,
    critical_route: CriticalRoute | None = None,
    role_graph_edge: RoleGraphEdge | None = None,
) -> Edge:
    source_edges = list(dict.fromkeys(item.id for item in evidence_edges))
    if not source_edges:
        raise ValidationError(f"Architecture connector {label!r} has no Graph IR edge evidence")
    edge_map = graph.edge_map()
    traced = [edge_map[edge_id] for edge_id in source_edges]
    evidence_nodes = list(dict.fromkeys(
        node_id for edge in traced for node_id in (edge.source, edge.target)
    ))
    candidate_semantic_ids = list(dict.fromkeys([
        *source.attributes.get("semantic_entity_ids", []),
        *target.attributes.get("semantic_entity_ids", []),
    ]))
    entities = {entity.id: entity for entity in semantic.entities_at("stage")}
    semantic_ids = [
        semantic_id
        for semantic_id in candidate_semantic_ids
        if semantic_id in entities
        and set(entities[semantic_id].provenance.source_node_ids).intersection(evidence_nodes)
    ]
    if not semantic_ids:
        raise ValidationError(f"Architecture connector {label!r} has no stage Semantic View endpoint evidence")
    semantic_connections = [
        connection.id
        for connection in semantic.connections.get("stage", [])
        if connection.source in semantic_ids
        and connection.target in semantic_ids
        if set(connection.provenance.source_edge_ids).intersection(source_edges)
    ]
    representative = next((edge for edge in traced if edge.tensor is not None), traced[0])
    bindings = [
        {
            "edge_id": edge.id,
            "source_node": edge.source,
            "source_port": edge.source_port,
            "target_node": edge.target,
            "target_port": edge.target_port,
            "tensor": asdict(edge.tensor) if edge.tensor else None,
        }
        for edge in traced
    ]
    return Edge(
        id=stable_id("architecture_projection_edge", identity),
        source=source.id,
        target=target.id,
        source_port=source.outputs[0].id,
        target_port=target.inputs[0].id,
        tensor=deepcopy(representative.tensor),
        kind="skip" if critical_route and critical_route.role in {"residual-skip", "unet-skip"} else "data",
        label=label,
        attributes={
            "semantic_level": "stage",
            "semantic_entity_ids": semantic_ids,
            "primary_semantic_id": semantic_ids[0],
            "semantic_connection_ids": semantic_connections,
            "source_edges": source_edges,
            "source_nodes": evidence_nodes,
            "boundary_count": len(source_edges),
            "source_port_binding": {
                "source_port_id": representative.source_port,
                "source_node_id": representative.source,
            },
            "target_port_binding": {
                "source_port_id": representative.target_port,
                "source_node_id": representative.target,
            },
            "bundled_bindings": bindings,
            "publication_bundle": True,
            "architecture_critical": critical_route is not None,
            "architecture_route_id": critical_route.id if critical_route else None,
            "architecture_route_role": critical_route.role if critical_route else "main-flow",
            "architecture_role_graph_edge_id": role_graph_edge.id if role_graph_edge else None,
            "architecture_source_role_id": role_graph_edge.source_role_id if role_graph_edge else None,
            "architecture_target_role_id": role_graph_edge.target_role_id if role_graph_edge else None,
            "architecture_direction": role_graph_edge.direction if role_graph_edge else "source-to-target",
            "protected_semantic_structure": bool(critical_route and critical_route.protected),
        },
    )


def _architecture_publication_projection(
    graph: GraphIR,
    semantic: SemanticView,
    *,
    requested_level: str,
    view: str,
) -> GraphIR | None:
    """Project source-bound Architecture Evidence into a compact Figure graph."""

    evidence = semantic.architecture_evidence
    if (
        evidence is None
        or evidence.family == "unknown"
        or requested_level != "stage"
        or view != "paper"
    ):
        return None
    evidence.validate(graph, source_digest=semantic.source_digest)
    role_graph = build_architecture_role_graph(graph, evidence)
    node_map = graph.node_map()
    roles = sorted(evidence.detected_roles, key=lambda item: (item.order, item.id))
    projected: dict[str, Node] = {}
    selected_stage_ids = {entity.id for entity in semantic.entities_at("stage")}
    all_ports = {
        port.id: port
        for node in graph.nodes
        for port in (*node.inputs, *node.outputs)
    }
    port_owners = {
        port.id: node.id
        for node in graph.nodes
        for port in (*node.inputs, *node.outputs)
    }
    for index, role in enumerate(roles):
        members = [node_map[node_id] for node_id in role.supporting_node_ids]
        incident = [
            edge for edge in graph.edges
            if edge.source in role.supporting_node_ids or edge.target in role.supporting_node_ids
        ]
        semantic_ids = list(dict.fromkeys(
            semantic_id
            for node_id in role.supporting_node_ids
            for semantic_id in semantic.trace_semantic(node_id, level="stage")
            if semantic_id in selected_stage_ids
        ))
        if not semantic_ids:
            raise ValidationError(f"Architecture role {role.role!r} has no persisted stage Semantic View identity")
        source_port_id = next(
            (
                port_id
                for port_id in role.supporting_port_ids
                if port_id in all_ports and all_ports[port_id].tensor is not None
            ),
            next((port_id for port_id in role.supporting_port_ids if port_id in all_ports), ""),
        )
        tensor = (
            deepcopy(all_ports[source_port_id].tensor)
            if source_port_id and all_ports[source_port_id].tensor is not None
            else next((deepcopy(edge.tensor) for edge in incident if edge.tensor is not None), None)
        )
        projection_id = stable_id("architecture_projection_role", role.id)
        input_port = Port(f"{projection_id}:input", "input bundle", "input", deepcopy(tensor))
        output_port = Port(f"{projection_id}:output", "tensor bundle", "output", deepcopy(tensor))
        inventory = _tensor_inventory(members)
        projected[role.id] = Node(
            id=projection_id,
            name=role.label,
            op_type="ArchitectureRole",
            category="model",
            path=f"architecture/{role.role}",
            inputs=[input_port],
            outputs=[output_port],
            level="stage",
            parameters=sum(node.parameters for node in members),
            trainable_parameters=sum(node.trainable_parameters for node in members),
            buffers=sum(node.buffers for node in members),
            attributes={
                "semantic_level": "stage",
                "semantic_type": role.role,
                "semantic_entity_ids": semantic_ids,
                "primary_semantic_id": semantic_ids[0],
                "confidence": role.confidence,
                "recognition_reasons": list(role.reasons),
                "source_nodes": list(role.supporting_node_ids),
                "source_edges": list(role.supporting_edge_ids),
                "source_ports": list(role.supporting_port_ids),
                "repeat_count": role.repeat_count,
                "output_tensor_inventory": inventory,
                "output_tensor_inventory_by_port": {output_port.id: inventory},
                "all_output_tensor_count": len(inventory),
                "boundary_port_bindings": {
                    output_port.id: {
                        "source_port_id": source_port_id,
                        "source_node_id": port_owners.get(source_port_id),
                        "bundled_port_ids": list(role.supporting_port_ids),
                    }
                },
                "publication_group": role.role,
                "publication_group_order": index,
                "publication_layout": evidence.family,
                "architecture_role_id": role.id,
                "architecture_role": role.role,
                "architecture_family": evidence.family,
                "architecture_attributes": deepcopy(role.attributes),
                "protected_semantic_structure": role.protected,
                "expansion_trace_available": True,
            },
            source={
                "format": "architecture-evidence",
                "evidence_version": evidence.evidence_version,
                "architecture_role_id": role.id,
                "semantic_entity_ids": semantic_ids,
            },
        )

    edges: list[Edge] = []
    route_by_id = {route.id: route for route in evidence.critical_routes}
    edge_map = graph.edge_map()
    for role_edge in role_graph.edges:
        critical_route = route_by_id.get(role_edge.id) if role_edge.critical else None
        edges.append(_architecture_projection_edge(
            graph,
            semantic,
            projected[role_edge.source_role_id],
            projected[role_edge.target_role_id],
            (edge_map[edge_id] for edge_id in role_edge.supporting_edge_ids),
            identity=f"role-graph:{role_edge.id}",
            label=role_edge.label,
            critical_route=critical_route,
            role_graph_edge=role_edge,
        ))

    mapped_nodes = {node_id for role in roles for node_id in role.supporting_node_ids}
    mapped_edges = {edge_id for role in roles for edge_id in role.supporting_edge_ids}
    mapped_edges.update(
        edge_id
        for edge in edges
        for edge_id in edge.attributes.get("source_edges", [])
    )
    mapped_ports = {port_id for role in roles for port_id in role.supporting_port_ids}
    layout = {
        "unet": "unet",
        "diffusion-unet": "diffusion-unet",
        "moe": "moe",
        "multimodal-fusion": "dual-input",
    }.get(evidence.family, "sequence")
    return GraphIR(
        name=f"{graph.name} · Architecture Evidence projection",
        nodes=[projected[role.id] for role in roles],
        edges=edges,
        inputs=deepcopy(graph.inputs),
        outputs=deepcopy(graph.outputs),
        metadata={
            **graph.metadata,
            "graph_view": "architecture-evidence-stage",
            "architecture_evidence": evidence.to_dict(),
            "publication_projection": {
                "schema_version": "nndv-architecture-projection-1",
                "source_view": str(graph.metadata.get("graph_view", "")),
                "requested_semantic_level": requested_level,
                "semantic_level": "stage",
                "layout": layout,
                "architecture_family": evidence.family,
                "source_node_count": len(graph.nodes),
                "source_edge_count": len(graph.edges),
                "visible_node_count": len(projected),
                "visible_edge_count": len(edges),
                "all_source_nodes_mapped": (
                    mapped_nodes == set(node_map)
                    and mapped_edges == set(graph.edge_map())
                    and mapped_ports == all_ports.keys()
                ),
                "omitted_noncritical_node_ids": sorted(set(node_map) - mapped_nodes),
                "omitted_noncritical_edge_ids": sorted(set(graph.edge_map()) - mapped_edges),
                "omitted_critical_edge_ids": [],
                "omitted_critical_edges": 0,
                "protected_semantic_summary": True,
                "semantic_entity_ids": sorted({
                    semantic_id
                    for node in projected.values()
                    for semantic_id in node.attributes["semantic_entity_ids"]
                }),
                "architecture_role_ids": [role.id for role in roles],
                "critical_route_ids": [route.id for route in evidence.critical_routes],
                "architecture_role_graph": role_graph.to_dict(),
                "architecture_role_graph_digest": role_graph.digest,
                "output_tensor_inventory_count": sum(
                    len(node.attributes["output_tensor_inventory"])
                    for node in projected.values()
                ),
            },
        },
        analysis=deepcopy(graph.analysis),
        ir_version=graph.ir_version,
    ).validate()


def _legacy_corpus_publication_projection(
    graph: GraphIR,
    semantic: SemanticView,
    *,
    requested_level: str,
    view: str,
) -> GraphIR | None:
    """Historical 0.7.2 corpus projection retained for fixture compatibility.

    This is selected only for inherited faithful/module and operation/block
    entry points.  The stage/paper production projection is exclusively
    derived from Architecture Evidence through the generic role graph above.
    """

    corpus_key = str(graph.metadata.get("corpus_key", ""))
    spec = _LEGACY_CORPUS_PUBLICATION_SPECS.get(corpus_key)
    source_view = str(graph.metadata.get("graph_view", ""))
    if spec is None:
        return None
    if source_view == "module":
        semantic_level = "stage"
    elif source_view == "operation" and view == "paper" and requested_level == "block":
        # The Start Center intentionally opens the faithful operation Graph.
        # A Block/Paper Figure must still be bounded and publication-readable,
        # while every operation/edge/port remains in the provenance index.
        semantic_level = "block"
    else:
        return None
    declared = list(spec["groups"])
    group_keys = [key for key, _label, _repeat in declared]
    ordered, assignments = _legacy_corpus_assignments(graph, corpus_key, group_keys)
    members = {key: [node for node in ordered if assignments[node.id] == key] for key in group_keys}
    active = [item for item in declared if members[item[0]]]
    if not active:
        return None
    selected_entities = semantic.entities_at(semantic_level)
    selected_entity_ids = {entity.id for entity in selected_entities}
    selected_entity_order = {
        entity.id: index for index, entity in enumerate(selected_entities)
    }
    selected_entity_nodes = {
        entity.id: set(entity.provenance.source_node_ids)
        for entity in selected_entities
    }
    semantic_ids_by_group: dict[str, list[str]] = {}
    primary_semantic_id_by_group: dict[str, str] = {}
    for key, _label, _repeat_count in active:
        member_ids = {node.id for node in members[key]}
        semantic_ids = {
            semantic_id
            for node_id in member_ids
            for semantic_id in semantic.trace_semantic(node_id, level=semantic_level)
            if semantic_id in selected_entity_ids
        }
        if not semantic_ids:
            raise ValidationError(
                f"Publication group {key!r} has no entity in the persisted {semantic_level} Semantic View",
                hint="Regenerate the Semantic View from the same Graph IR before creating the Figure.",
            )
        ordered_semantic_ids = sorted(
            semantic_ids,
            key=selected_entity_order.__getitem__,
        )
        semantic_ids_by_group[key] = ordered_semantic_ids
        primary_semantic_id_by_group[key] = max(
            ordered_semantic_ids,
            key=lambda semantic_id: (
                len(member_ids.intersection(selected_entity_nodes[semantic_id])),
                -selected_entity_order[semantic_id],
            ),
        )
    active_keys = {key for key, _label, _repeat in active}
    projected_ids = {key: stable_id("semantic_publication", f"{corpus_key}:{key}") for key in active_keys}
    boundary_edges: dict[tuple[str, str], list[Edge]] = defaultdict(list)
    for edge in graph.edges:
        source_group = assignments[edge.source]
        target_group = assignments[edge.target]
        if source_group != target_group:
            boundary_edges[(source_group, target_group)].append(edge)

    nodes: list[Node] = []
    node_by_key: dict[str, Node] = {}
    for group_index, (key, label, repeat_count) in enumerate(active):
        group_members = members[key]
        group_member_ids = {item.id for item in group_members}
        inventory = _tensor_inventory(group_members)
        incident_edges = [
            edge
            for edge in graph.edges
            if edge.source in group_member_ids or edge.target in group_member_ids
        ]
        outgoing_pairs = [(source, target) for source, target in spec["links"] if source == key and target in active_keys]
        representative_edge = next(
            (
                edge
                for pair in outgoing_pairs
                for edge in boundary_edges.get(pair, [])
                if edge.tensor is not None
            ),
            next((edge for pair in outgoing_pairs for edge in boundary_edges.get(pair, [])), None),
        )
        representative_port = None
        if representative_edge is not None and representative_edge.source_port:
            source_node = graph.node_map()[representative_edge.source]
            representative_port = next(
                (port for port in source_node.outputs if port.id == representative_edge.source_port),
                None,
            )
        if representative_port is None and not outgoing_pairs:
            output_edges = [
                edge
                for edge in graph.edges
                if edge.target in group_member_ids and graph.node_map()[edge.target].category == "output"
            ]
            representative_edge = next((edge for edge in output_edges if edge.tensor is not None), next(iter(output_edges), None))
            if representative_edge is not None and representative_edge.source_port:
                source_node = graph.node_map()[representative_edge.source]
                representative_port = next(
                    (port for port in source_node.outputs if port.id == representative_edge.source_port),
                    None,
                )
        if representative_port is None:
            representative_port = next(
                (port for node in reversed(group_members) for port in node.outputs if port.tensor is not None),
                next((port for node in reversed(group_members) for port in node.outputs), None),
            )
        representative_tensor = deepcopy(
            representative_edge.tensor
            if representative_edge is not None and representative_edge.tensor is not None
            else representative_port.tensor
            if representative_port is not None
            else graph.outputs[0]
            if not outgoing_pairs and graph.outputs
            else None
        )
        projection_id = projected_ids[key]
        output_port = Port(f"{projection_id}:output", "tensor bundle", "output", representative_tensor)
        input_tensor = next((deepcopy(edge.tensor) for edge in incident_edges if edge.target in {node.id for node in group_members} and edge.tensor is not None), representative_tensor)
        input_port = Port(f"{projection_id}:input", "input bundle", "input", input_tensor)
        original_port_id = representative_port.id if representative_port else representative_edge.source_port if representative_edge else ""
        original_node_id = (
            next((source_node.id for source_node in group_members if representative_port in source_node.outputs), "")
            if representative_port is not None
            else representative_edge.source
            if representative_edge is not None
            else ""
        )
        node = Node(
            id=projection_id,
            name=label,
            op_type="PublicationStage" if semantic_level == "stage" else "PublicationBlock",
            category="model",
            path=f"{graph.name}/{key}",
            inputs=[input_port],
            outputs=[output_port],
            level=semantic_level,
            parameters=sum(item.parameters for item in group_members),
            trainable_parameters=sum(item.trainable_parameters for item in group_members),
            buffers=sum(item.buffers for item in group_members),
            attributes={
                "semantic_level": semantic_level,
                "semantic_type": f"publication_{semantic_level}",
                "semantic_entity_ids": semantic_ids_by_group[key],
                "primary_semantic_id": primary_semantic_id_by_group[key],
                "confidence": "evidence-backed",
                "recognition_reasons": [
                    f"deterministic corpus {source_view}-path projection"
                ],
                "source_nodes": [item.id for item in group_members],
                "source_edges": [item.id for item in incident_edges],
                "source_ports": [port.id for item in group_members for port in [*item.inputs, *item.outputs]],
                "repeat_count": repeat_count,
                "output_tensor_inventory": inventory,
                "output_tensor_inventory_by_port": {output_port.id: inventory},
                "all_output_tensor_count": len(inventory),
                "boundary_port_bindings": {
                    output_port.id: {
                        "source_port_id": original_port_id,
                        "source_node_id": original_node_id,
                        "bundled_port_ids": [item["port_id"] for item in inventory],
                    }
                },
                "publication_group": key,
                "publication_group_order": group_index,
                "publication_layout": spec["layout"],
            },
            source={
                "format": "publication-projection",
                "projection": f"publication-{semantic_level}-v1",
                "corpus_key": corpus_key,
                "semantic_entity_ids": semantic_ids_by_group[key],
            },
        )
        nodes.append(node)
        node_by_key[key] = node

    links = [(source, target) for source, target in spec["links"] if source in active_keys and target in active_keys]
    edges: list[Edge] = []
    for source_key, target_key in links:
        source_node = node_by_key[source_key]
        target_node = node_by_key[target_key]
        evidence_edges = list(boundary_edges.get((source_key, target_key), []))
        if not evidence_edges:
            # The import may place an auxiliary FX operation in an adjacent
            # lane.  A real path still supports the visual bundle, but we do
            # not fabricate a direct source edge: gather only edges crossing
            # the ordered cut between the two declared lanes.
            source_index = group_keys.index(source_key)
            target_index = group_keys.index(target_key)
            lower, upper = sorted((source_index, target_index))
            evidence_edges = [
                edge
                for edge in graph.edges
                if group_keys.index(assignments[edge.source]) <= lower
                and group_keys.index(assignments[edge.target]) >= upper
            ]
        if not evidence_edges:
            continue
        representative = evidence_edges[0]
        source_semantic_ids = semantic_ids_by_group[source_key]
        target_semantic_ids = semantic_ids_by_group[target_key]
        evidence_edge_ids = {item.id for item in evidence_edges}
        evidence_node_ids = {
            node_id
            for item in evidence_edges
            for node_id in (item.source, item.target)
        }
        edge_semantic_ids = [
            semantic_id
            for semantic_id in dict.fromkeys([*source_semantic_ids, *target_semantic_ids])
            if evidence_node_ids.intersection(selected_entity_nodes[semantic_id])
        ]
        if not edge_semantic_ids:
            raise ValidationError(
                f"Publication connector {source_key!r} → {target_key!r} has no Semantic View endpoint evidence"
            )
        primary_edge_semantic_id = next(
            (semantic_id for semantic_id in source_semantic_ids if semantic_id in edge_semantic_ids),
            edge_semantic_ids[0],
        )
        semantic_connection_ids = [
            connection.id
            for connection in semantic.connections.get(semantic_level, [])
            if connection.source in edge_semantic_ids
            and connection.target in edge_semantic_ids
            and evidence_edge_ids.intersection(connection.provenance.source_edge_ids)
        ]
        edge = Edge(
            id=stable_id("semantic_publication_edge", f"{corpus_key}:{source_key}:{target_key}"),
            source=source_node.id,
            target=target_node.id,
            source_port=source_node.outputs[0].id,
            target_port=target_node.inputs[0].id,
            tensor=deepcopy(representative.tensor or source_node.outputs[0].tensor),
            kind="data",
            label=f"{len(evidence_edges)} traced flow{'s' if len(evidence_edges) != 1 else ''}",
            attributes={
                "semantic_level": semantic_level,
                "semantic_entity_ids": edge_semantic_ids,
                "primary_semantic_id": primary_edge_semantic_id,
                "semantic_connection_ids": semantic_connection_ids,
                "source_edges": [item.id for item in evidence_edges],
                "source_nodes": list(dict.fromkeys([item.source for item in evidence_edges] + [item.target for item in evidence_edges])),
                "boundary_count": len(evidence_edges),
                "source_port_binding": {"source_port_id": representative.source_port, "source_node_id": representative.source},
                "target_port_binding": {"source_port_id": representative.target_port, "source_node_id": representative.target},
                "bundled_bindings": [
                    {
                        "edge_id": item.id,
                        "source_node": item.source,
                        "source_port": item.source_port,
                        "target_node": item.target,
                        "target_port": item.target_port,
                        "tensor": asdict(item.tensor) if item.tensor else None,
                    }
                    for item in evidence_edges
                ],
                "publication_bundle": True,
            },
        )
        edges.append(edge)

    return GraphIR(
        name=f"{graph.name} · Publication projection",
        nodes=nodes,
        edges=edges,
        inputs=deepcopy(graph.inputs),
        outputs=deepcopy(graph.outputs),
        metadata={
            **graph.metadata,
            "graph_view": f"publication-{semantic_level}",
            "publication_projection": {
                "schema_version": "nndv-publication-projection-1",
                "source_view": source_view,
                "semantic_level": semantic_level,
                "layout": spec["layout"],
                "source_node_count": len(graph.nodes),
                "source_edge_count": len(graph.edges),
                "visible_node_count": len(nodes),
                "visible_edge_count": len(edges),
                "all_source_nodes_mapped": set(assignments) == {node.id for node in graph.nodes},
                "semantic_entity_ids": sorted({
                    semantic_id
                    for ids in semantic_ids_by_group.values()
                    for semantic_id in ids
                }),
                "all_selected_semantic_entities_mapped": (
                    {semantic_id for ids in semantic_ids_by_group.values() for semantic_id in ids}
                    == selected_entity_ids
                ),
                "all_stage_semantic_entities_mapped": (
                    semantic_level == "stage"
                    and {
                        semantic_id
                        for ids in semantic_ids_by_group.values()
                        for semantic_id in ids
                    }
                    == selected_entity_ids
                ),
                "output_tensor_inventory_count": sum(len(node.attributes["output_tensor_inventory"]) for node in nodes),
            },
        },
        analysis=deepcopy(graph.analysis),
        ir_version=graph.ir_version,
    ).validate()


def _shape(tensor: TensorSpec | None) -> tuple[list[int | str | None], str]:
    dimensions = list(tensor.shape) if tensor else []
    return dimensions, "[" + ", ".join("?" if value is None else str(value) for value in dimensions) + "]"


def _semantic_entity_ids(attributes: dict[str, Any], *fallback_ids: str) -> list[str]:
    ids = list(dict.fromkeys(
        str(item)
        for item in attributes.get("semantic_entity_ids", [])
        if item
    ))
    primary = str(attributes.get("primary_semantic_id", ""))
    if primary and primary not in ids:
        ids.insert(0, primary)
    if not ids:
        ids = list(dict.fromkeys(str(item) for item in fallback_ids if item))
    return ids


def _provenance_semantic_entity_ids(provenance: FigureProvenance) -> list[str]:
    if provenance.kind != "semantic_view":
        return []
    ids = list(dict.fromkeys(
        str(item)
        for item in provenance.evidence.get("semantic_entity_ids", [])
        if item
    ))
    if provenance.source_id and provenance.source_id not in ids:
        ids.insert(0, provenance.source_id)
    return ids


def _annotate_semantic_materialization(
    materialized: GraphIR,
    semantic: SemanticView,
    *,
    level: str,
) -> None:
    """Attach only persisted SemanticView entity/connection identities."""

    selected_entities = {entity.id: entity for entity in semantic.entities_at(level)}
    known_entities = set(selected_entities)
    materialized_to_persisted: dict[str, list[str]] = {}
    for node in materialized.nodes:
        if node.id in known_entities:
            semantic_ids = [node.id]
        else:
            # Paper View may group several persisted entities behind a
            # transient materialization ID.  The grouped ID is a layout
            # identity, never semantic evidence; retain the exact persisted
            # identities recorded by ``_paper_entities`` instead.
            raw_ids = node.attributes.get("source_semantic_ids", [])
            semantic_ids = list(dict.fromkeys(map(str, raw_ids))) if isinstance(raw_ids, list) else []
        orphan_ids = sorted(set(semantic_ids) - known_entities)
        if not semantic_ids or orphan_ids:
            raise ValidationError(
                f"Materialized semantic node {node.id!r} has no exact persisted Semantic View identity"
            )
        materialized_to_persisted[node.id] = semantic_ids
        node.attributes["semantic_entity_ids"] = semantic_ids
        node.attributes["primary_semantic_id"] = semantic_ids[0]
    connections = semantic.connections.get(level, [])
    for edge in materialized.edges:
        materialized_source_ids = materialized_to_persisted.get(edge.source, [])
        materialized_target_ids = materialized_to_persisted.get(edge.target, [])
        source_binding = dict(edge.attributes.get("source_port_binding", {}))
        target_binding = dict(edge.attributes.get("target_port_binding", {}))
        source_node_id = source_binding.get("source_node_id")
        target_node_id = target_binding.get("source_node_id")
        source_semantic_ids = [
            semantic_id
            for semantic_id in materialized_source_ids
            if source_node_id is None
            or str(source_node_id) in selected_entities[semantic_id].provenance.source_node_ids
        ]
        target_semantic_ids = [
            semantic_id
            for semantic_id in materialized_target_ids
            if target_node_id is None
            or str(target_node_id) in selected_entities[semantic_id].provenance.source_node_ids
        ]
        semantic_ids = list(dict.fromkeys([*source_semantic_ids, *target_semantic_ids]))
        if not source_semantic_ids or not target_semantic_ids:
            raise ValidationError(
                f"Materialized semantic edge {edge.id!r} has no persisted Semantic View endpoint"
            )
        source_edge_ids = set(map(str, edge.attributes.get("source_edges", [])))
        edge.attributes["semantic_entity_ids"] = list(dict.fromkeys(semantic_ids))
        edge.attributes["primary_semantic_id"] = semantic_ids[0]
        edge.attributes["semantic_connection_ids"] = [
            connection.id
            for connection in connections
            if connection.source in source_semantic_ids
            and connection.target in target_semantic_ids
            and source_edge_ids.intersection(connection.provenance.source_edge_ids)
        ]


def _restore_slice_provenance(sliced: GraphIR, source: GraphIR) -> GraphIR:
    """Replace synthetic slice identities with exact source evidence.

    ``focus_graph`` and ``viewport_slice`` intentionally create boundary node
    and edge identities for layout.  Those identities belong only to the
    transient slice and must never be recorded as Graph IR provenance.  Keep
    the transient IDs as Figure layout identities while copying the complete
    Semantic View evidence and original edge/port bindings from ``source``.
    """

    source_nodes = source.node_map()
    source_edges = source.edge_map()
    boundary_sources: dict[str, str] = {}
    for node in sliced.nodes:
        boundary_source = node.attributes.get("boundary_for")
        if boundary_source is None and node.attributes.get("boundary_proxy"):
            boundary_source = node.attributes.get("source_node")
        source_id = str(boundary_source or node.id)
        original_node = source_nodes.get(source_id)
        if original_node is None:
            raise ValidationError(
                f"Slice node {node.id!r} has no exact Semantic View source evidence"
            )
        if source_id != node.id:
            boundary_sources[node.id] = source_id
        transient_attributes = {
            key: deepcopy(value)
            for key, value in node.attributes.items()
            if key not in original_node.attributes
            and not (source_id != node.id and key == "source_node")
        }
        node.attributes = deepcopy(original_node.attributes)
        node.attributes.update(transient_attributes)
        if source_id != node.id:
            node.attributes["boundary_for"] = source_id
        node.source = deepcopy(original_node.source)
        # Boundary proxies are visual stubs, not duplicate tensor endpoints.
        # Exact source-port evidence remains in the Semantic View attributes
        # and on the repaired crossing edge below.
        if source_id == node.id:
            node.inputs = deepcopy(original_node.inputs)
            node.outputs = deepcopy(original_node.outputs)

    for edge in sliced.edges:
        original_edge = source_edges.get(edge.id)
        if original_edge is None:
            referenced_slice_edges = [
                str(item)
                for item in edge.attributes.get("source_edges", [])
                if str(item) in source_edges
            ]
            candidates = [source_edges[item] for item in referenced_slice_edges]
            if not candidates:
                logical_source = boundary_sources.get(edge.source, edge.source)
                logical_target = boundary_sources.get(edge.target, edge.target)
                candidates = [
                    item
                    for item in source.edges
                    if item.source == logical_source
                    and item.target == logical_target
                    and item.kind == edge.kind
                    and item.label == edge.label
                ]
            if len(candidates) != 1:
                raise ValidationError(
                    f"Slice edge {edge.id!r} does not map to exactly one Semantic View connection"
                )
            original_edge = candidates[0]
        transient_attributes = {
            key: deepcopy(value)
            for key, value in edge.attributes.items()
            if key not in original_edge.attributes
        }
        edge.attributes = deepcopy(original_edge.attributes)
        edge.attributes.update(transient_attributes)
        edge.source_port = None if edge.source in boundary_sources else original_edge.source_port
        edge.target_port = None if edge.target in boundary_sources else original_edge.target_port
        edge.tensor = deepcopy(original_edge.tensor)
    return sliced.validate()


def _source_ids(node: Node) -> tuple[list[str], list[str]]:
    node_ids = list(dict.fromkeys(map(str, [
        *node.attributes.get("source_nodes", []),
        *node.source.get("source_nodes", []),
        *([node.attributes["source_node"]] if node.attributes.get("source_node") else []),
    ])))
    edge_ids = list(dict.fromkeys(map(str, [
        *node.attributes.get("source_edges", []),
        *node.source.get("source_edges", []),
        *node.attributes.get("source_ports", []),
    ])))
    if not node_ids and node.source.get("format") != "semantic-view":
        node_ids = [node.id]
    return node_ids, edge_ids


def _node_provenance(node: Node) -> FigureProvenance:
    node_ids, edge_ids = _source_ids(node)
    semantic = node.source.get("format") == "semantic-view" or bool(node.attributes.get("semantic_level"))
    semantic_ids = _semantic_entity_ids(node.attributes, node.id) if semantic else []
    primary_semantic_id = str(node.attributes.get("primary_semantic_id") or semantic_ids[0]) if semantic_ids else node.id
    return FigureProvenance(
        "semantic_view" if semantic else "graph_ir",
        source_id=primary_semantic_id,
        graph_ir_ids=list(dict.fromkeys([*node_ids, *edge_ids])),
        source_locator=dict(node.source),
        evidence={
            "op_type": node.op_type,
            "semantic_level": node.attributes.get("semantic_level", node.level),
            "semantic_type": node.attributes.get("semantic_type"),
            "confidence": node.attributes.get("confidence"),
            "unknown_semantics": bool(node.attributes.get("unknown_semantics", False)),
            "semantic_entity_ids": semantic_ids,
        },
    )


def _edge_provenance(edge: Edge) -> FigureProvenance:
    graph_edge_ids = list(dict.fromkeys(map(str, edge.attributes.get("source_edges", [])))) or [edge.id]
    graph_node_ids = list(dict.fromkeys(map(str, edge.attributes.get("source_nodes", []))))
    source_binding = dict(edge.attributes.get("source_port_binding", {}))
    target_binding = dict(edge.attributes.get("target_port_binding", {}))
    bundled_bindings = list(edge.attributes.get("bundled_bindings", []))
    graph_port_ids = [
        str(port_id)
        for port_id in (
            source_binding.get("source_port_id"),
            target_binding.get("source_port_id"),
            *(binding.get(direction) for binding in bundled_bindings for direction in ("source_port", "target_port")),
        )
        if port_id
    ]
    semantic = bool(edge.attributes.get("semantic_level"))
    semantic_ids = _semantic_entity_ids(edge.attributes, edge.source, edge.target) if semantic else []
    primary_semantic_id = str(edge.attributes.get("primary_semantic_id") or semantic_ids[0]) if semantic_ids else edge.id
    return FigureProvenance(
        "semantic_view" if semantic else "graph_ir",
        source_id=primary_semantic_id,
        graph_ir_ids=list(dict.fromkeys([*graph_edge_ids, *graph_node_ids, *graph_port_ids])),
        evidence={
            "kind": edge.kind,
            "source_port": edge.source_port,
            "target_port": edge.target_port,
            "tensor": asdict(edge.tensor) if edge.tensor else None,
            "boundary_count": edge.attributes.get("boundary_count", 1),
            "semantic_entity_ids": semantic_ids,
            "semantic_connection_ids": list(edge.attributes.get("semantic_connection_ids", [])),
        },
    )


def _mapped_layout(
    graph: GraphIR,
    panel: Any,
    *,
    supplied: LayoutResult | None = None,
) -> tuple[LayoutResult, dict[str, dict[str, float]]]:
    result = supplied or LayoutEngine().layout(
        graph,
        algorithm="auto",
        direction="LR",
        node_width=118,
        node_height=62,
        rank_gap=78,
        node_gap=38,
        label_density="compact",
    )
    if set(result.nodes) != {node.id for node in graph.nodes}:
        raise ValidationError("Model-to-Figure layout does not cover exactly the materialized graph nodes")
    inner_x = float(panel.geometry["x"]) + 6.0
    inner_y = float(panel.geometry["y"]) + 11.0
    inner_width = max(10.0, float(panel.geometry["width"]) - 12.0)
    inner_height = max(10.0, float(panel.geometry["height"]) - 21.0)
    publication = graph.metadata.get("publication_projection")
    if isinstance(publication, dict):
        layout_kind = str(publication.get("layout", "sequence"))
        ordered = sorted(graph.nodes, key=lambda item: int(item.attributes.get("publication_group_order", 0)))
        positions: tuple[tuple[float, float], ...]
        if layout_kind == "dual-input":
            positions = ((0.13, 0.27), (0.13, 0.72), (0.56, 0.495), (0.86, 0.495))
        elif layout_kind == "fork-join":
            positions = ((0.10, 0.495), (0.43, 0.27), (0.43, 0.72), (0.82, 0.495))
        elif layout_kind == "unet":
            encoder = [node for node in ordered if node.attributes.get("architecture_role") == "encoder-level"]
            decoder = [node for node in ordered if node.attributes.get("architecture_role") == "decoder-level"]
            encoder_position = {
                node.id: (0.16 + index * 0.12, 0.24 + index * 0.17)
                for index, node in enumerate(encoder)
            }
            decoder_position = {
                node.id: (0.62 + index * 0.12, 0.58 - index * 0.17)
                for index, node in enumerate(decoder)
            }
            positions = tuple(
                encoder_position.get(node.id)
                or decoder_position.get(node.id)
                or {
                    "input": (0.05, 0.18),
                    "bottleneck": (0.50, 0.78),
                    "output-head": (0.95, 0.18),
                }.get(str(node.attributes.get("architecture_role")), (0.50, 0.50))
                for node in ordered
            )
        elif layout_kind == "diffusion-unet":
            role_positions = {
                "input": (0.07, 0.60),
                "conditioning": (0.46, 0.12),
                "down-path": (0.27, 0.56),
                "bottleneck": (0.49, 0.72),
                "up-path": (0.71, 0.56),
                "output-head": (0.93, 0.60),
            }
            positions = tuple(role_positions[str(node.attributes["architecture_role"])] for node in ordered)
        elif layout_kind == "moe":
            role_positions = {
                "input": (0.07, 0.50),
                "router": (0.28, 0.26),
                "experts": (0.48, 0.67),
                "weighted-combine": (0.73, 0.50),
                "output-head": (0.93, 0.50),
            }
            positions = tuple(role_positions[str(node.attributes["architecture_role"])] for node in ordered)
        else:
            positions = tuple(
                ((index + 0.5) / max(1, len(ordered)), 0.42)
                for index in range(len(ordered))
            )
        if len(positions) != len(ordered):
            raise ValidationError("Publication layout position count does not match its projected nodes")
        if layout_kind == "sequence":
            gap = 5.0
            object_width = min(28.0, max(18.5, (inner_width - max(0, len(ordered) - 1) * gap) / max(1, len(ordered))))
        else:
            object_width = 24.0 if layout_kind in {"unet", "diffusion-unet", "moe"} else 27.0
        object_height = 15.0
        publication_mapped: dict[str, dict[str, float]] = {}
        for node, (relative_x, relative_y) in zip(ordered, positions, strict=True):
            center_x = inner_x + relative_x * inner_width
            center_y = inner_y + relative_y * inner_height
            publication_mapped[node.id] = {
                "x": max(inner_x, min(inner_x + inner_width - object_width, center_x - object_width / 2.0)),
                "y": max(inner_y, min(inner_y + inner_height - object_height - 17.0, center_y - object_height / 2.0)),
                "width": object_width,
                "height": object_height,
            }
        return result, publication_mapped
    minimum_x = min((placement.x for placement in result.nodes.values()), default=0.0)
    minimum_y = min((placement.y for placement in result.nodes.values()), default=0.0)
    maximum_x = max((placement.x + placement.width for placement in result.nodes.values()), default=1.0)
    maximum_y = max((placement.y + placement.height for placement in result.nodes.values()), default=1.0)
    source_width = max(1.0, maximum_x - minimum_x)
    source_height = max(1.0, maximum_y - minimum_y)
    scale = min(inner_width / source_width, inner_height / source_height, 0.18)
    object_width = max(11.0, min(21.0, 118.0 * scale))
    # The default 9 pt Figure type uses a 1.2 line-height.  Keep enough
    # physical height for a legitimate two-line node label plus the renderer's
    # 0.8 mm inset; otherwise ordinary short names can wrap and fail strict
    # text layout after the graph is scaled onto a paper-sized panel.
    object_height = max(9.5, min(10.5, 62.0 * scale))
    centers = {
        node_id: (
            inner_x + (placement.x + placement.width / 2.0 - minimum_x) / source_width * inner_width,
            inner_y + (placement.y + placement.height / 2.0 - minimum_y) / source_height * inner_height,
        )
        for node_id, placement in result.nodes.items()
    }
    mapped: dict[str, dict[str, float]] = {}
    for node_id, (center_x, center_y) in centers.items():
        mapped[node_id] = {
            "x": max(inner_x, min(inner_x + inner_width - object_width, center_x - object_width / 2.0)),
            "y": max(inner_y, min(inner_y + inner_height - object_height, center_y - object_height / 2.0)),
            "width": object_width,
            "height": object_height,
        }
    return result, mapped


def _route_between(
    edge: Edge,
    geometries: dict[str, dict[str, float]],
    layout: LayoutResult,
) -> list[list[float]]:
    source, target = geometries[edge.source], geometries[edge.target]
    start = [source["x"] + source["width"], source["y"] + source["height"] / 2.0]
    end = [target["x"], target["y"] + target["height"] / 2.0]
    if edge.attributes.get("publication_bundle"):
        return [[round(x, 5), round(y, 5)] for x, y in (start, end)]
    layout_route = layout.edges.get(edge.id)
    if not layout_route or len(layout_route.points) < 2:
        middle = (start[0] + end[0]) / 2.0
        return [start, [middle, start[1]], [middle, end[1]], end]
    # Retain the layout engine's bend topology while mapping its normalized
    # intermediate points into the exact endpoint rectangle.
    raw = list(layout_route.points)
    first_x, first_y = raw[0]
    last_x, last_y = raw[-1]
    span_x = last_x - first_x
    span_y = last_y - first_y
    mapped = [start]
    for x, y in raw[1:-1]:
        tx = (x - first_x) / span_x if abs(span_x) > 1e-9 else 0.5
        ty = (y - first_y) / span_y if abs(span_y) > 1e-9 else 0.5
        mapped.append([
            start[0] + tx * (end[0] - start[0]),
            start[1] + ty * (end[1] - start[1]),
        ])
    mapped.append(end)
    return [[round(x, 5), round(y, 5)] for x, y in mapped]


def _reconcile(figure: FigureIR, existing: FigureIR | None) -> None:
    if existing is None:
        return
    previous = {item.id: item for item in existing.iter_objects()}
    for current in figure.iter_objects():
        prior = previous.get(current.id)
        if prior is None:
            continue
        if prior.locked:
            current.geometry = deepcopy(prior.geometry)
            current.locked = True
        if current.kind == "edge" and prior.manual_route:
            prior_auto = prior.metadata.get("auto_route")
            author_route = bool(prior.metadata.get("author_manual_route")) or prior.locked
            author_route = author_route or (prior_auto is not None and prior.manual_route != prior_auto)
            if author_route:
                current.manual_route = deepcopy(prior.manual_route)
                current.metadata["author_manual_route"] = True
                current.metadata["route_origin"] = "author"
        current.visible = prior.visible
        current.style = deepcopy(prior.style)
        for key in (
            "author_shape_override",
            "author_shape_override_label",
            "shape_label_origin",
        ):
            if key in prior.metadata:
                current.metadata[key] = deepcopy(prior.metadata[key])


def _resolve_source_graph(
    graph: GraphIR,
    semantic: SemanticView,
    *,
    level: str,
    view: str,
    focus_ids: Iterable[str],
    focus_hops: int,
    viewport: Viewport | dict[str, Any] | None,
) -> tuple[GraphIR, LayoutResult | None, dict[str, Any]]:
    requested_level = level
    selected_level = level
    focus = list(dict.fromkeys(map(str, focus_ids)))
    publication_projection = (
        _architecture_publication_projection(
            graph,
            semantic,
            requested_level=requested_level,
            view=view,
        )
        or _legacy_corpus_publication_projection(
            graph,
            semantic,
            requested_level=requested_level,
            view=view,
        )
        if not focus and viewport is None
        else None
    )
    if publication_projection is not None:
        selected_level = str(
            publication_projection.metadata["publication_projection"]["semantic_level"]
        )
    elif level == "operation" and len(graph.nodes) > MAXIMUM_UNFOCUSED_OPERATION_NODES and not focus and viewport is None:
        selected_level = "stage"
    semantic_materialized = semantic.materialize(graph, level=selected_level, view=view)
    _annotate_semantic_materialization(semantic_materialized, semantic, level=selected_level)
    materialized = publication_projection or semantic_materialized
    # Operation-level Semantic Views in older compatible project files did not
    # serialize ports.  Recover only exact one-to-one source evidence here;
    # aggregated boundaries remain unknown unless Semantic materialization
    # supplies their explicit boundary ports.
    source_nodes = graph.node_map()
    source_edges = graph.edge_map()
    for node in materialized.nodes:
        source_node_ids = list(node.attributes.get("source_nodes", []))
        if not node.inputs and not node.outputs and len(source_node_ids) == 1 and source_node_ids[0] in source_nodes:
            source_node = source_nodes[source_node_ids[0]]
            node.inputs = deepcopy(source_node.inputs)
            node.outputs = deepcopy(source_node.outputs)
    for edge in materialized.edges:
        source_edge_ids = list(edge.attributes.get("source_edges", []))
        if len(source_edge_ids) == 1 and source_edge_ids[0] in source_edges:
            source_edge = source_edges[source_edge_ids[0]]
            edge.source_port = edge.source_port or source_edge.source_port
            edge.target_port = edge.target_port or source_edge.target_port
            edge.tensor = edge.tensor or deepcopy(source_edge.tensor)
    metadata: dict[str, Any] = {
        "requested_level": requested_level,
        "selected_level": selected_level,
        "view": view,
        "summary_first": (
            publication_projection is not None
            or selected_level != requested_level
        ),
    }
    if publication_projection is not None:
        metadata["publication_projection"] = {
            **dict(publication_projection.metadata["publication_projection"]),
            "semantic_materialized_node_count": len(semantic_materialized.nodes),
            "semantic_materialized_edge_count": len(semantic_materialized.edges),
            "semantic_view_was_executed": True,
        }
    if focus:
        materialized_ids = {node.id for node in materialized.nodes}
        mapped_focus: set[str] = set()
        for source_id in focus:
            if source_id in materialized_ids:
                mapped_focus.add(source_id)
            mapped_focus.update(semantic.trace_semantic(source_id, level=selected_level))
        if not mapped_focus:
            raise ValidationError("None of the requested focus IDs map to the selected Semantic View level")
        focused = focus_graph(materialized, mapped_focus, hops=focus_hops)
        materialized = _restore_slice_provenance(focused, materialized)
        metadata.update({"focus_ids": focus, "materialized_focus_ids": sorted(mapped_focus), "focus_hops": focus_hops})
    if viewport is not None:
        request = viewport if isinstance(viewport, Viewport) else Viewport(**viewport)
        sliced = viewport_slice(materialized, request)
        _restore_slice_provenance(sliced.graph, materialized)
        metadata["viewport"] = {
            "rendered_nodes": sliced.rendered_node_count,
            "rendered_edges": sliced.rendered_edge_count,
            "boundary_proxies": sliced.boundary_proxy_count,
            "truncated": sliced.truncated,
        }
        return sliced.graph, sliced.layout, metadata
    return materialized, None, metadata


def model_figure_from_graph(
    graph: GraphIR,
    *,
    semantic_view: SemanticView | None = None,
    level: str = "operation",
    view: str = "faithful",
    mode: str = "schematic",
    page_preset: str = "double-column",
    focus_ids: Iterable[str] = (),
    focus_hops: int = 1,
    viewport: Viewport | dict[str, Any] | None = None,
    existing_figure: FigureIR | None = None,
) -> FigureIR:
    """Build a deterministic editable Figure while retaining every evidence ID."""

    graph.validate()
    level = normalize_semantic_level(level)
    if mode not in {"schematic", "tensor-geometry", "mixed"}:
        raise ValidationError(f"Unknown Figure mode {mode!r}")
    semantic = semantic_view or derive_semantic_view(graph)
    semantic.validate(graph)
    materialized, supplied_layout, pipeline = _resolve_source_graph(
        graph,
        semantic,
        level=level,
        view=view,
        focus_ids=focus_ids,
        focus_hops=focus_hops,
        viewport=viewport,
    )
    if len(materialized.nodes) > MAXIMUM_UNFOCUSED_OPERATION_NODES:
        raise ValidationError(
            f"Figure draft contains {len(materialized.nodes)} visible nodes, above the bounded authoring limit of {MAXIMUM_UNFOCUSED_OPERATION_NODES}",
            hint="Use a coarser semantic level, focus IDs, or a viewport slice.",
        )
    figure = new_figure(graph.name, page_preset=page_preset, panel_modes=(mode,))
    panel = next(figure.iter_panels())
    layer = next(item for item in panel.layers if item.role == "model-data")
    layout, geometries = _mapped_layout(materialized, panel, supplied=supplied_layout)
    node_objects: dict[str, FigureObject] = {}
    graph_to_figure: dict[str, list[str]] = defaultdict(list)
    semantic_to_figure: dict[str, list[str]] = defaultdict(list)
    figure_to_source: dict[str, dict[str, Any]] = {}
    publication_projection = isinstance(materialized.metadata.get("publication_projection"), dict)
    architecture_role_graph_digest = (
        materialized.metadata.get("publication_projection", {}).get("architecture_role_graph_digest")
        if publication_projection
        else None
    )
    architecture_evidence_digest = (
        semantic.architecture_evidence.provenance_digest
        if semantic.architecture_evidence is not None
        else None
    )
    source_graph_port_ids = {
        port.id
        for node in graph.nodes
        for port in [*node.inputs, *node.outputs]
    }

    def record_provenance(item: FigureObject, **extra: Any) -> None:
        graph_ids = list(dict.fromkeys(map(str, item.provenance.graph_ir_ids)))
        semantic_ids = _provenance_semantic_entity_ids(item.provenance)
        for graph_id in graph_ids:
            graph_to_figure[graph_id].append(item.id)
        for semantic_id in semantic_ids:
            semantic_to_figure[semantic_id].append(item.id)
        reverse: dict[str, Any] = {"graph_ir_ids": graph_ids}
        graph_port_ids = [graph_id for graph_id in graph_ids if graph_id in source_graph_port_ids]
        if graph_port_ids:
            reverse["graph_port_ids"] = graph_port_ids
        if item.provenance.kind == "semantic_view":
            reverse.update({
                "semantic_id": item.provenance.source_id,
                "semantic_ids": semantic_ids,
            })
        reverse.update(extra)
        figure_to_source[item.id] = reverse

    for order, node in enumerate(materialized.nodes):
        provenance = _node_provenance(node)
        provenance_semantic_ids = _provenance_semantic_entity_ids(provenance)
        semantic_type = str(node.attributes.get("semantic_type", node.op_type))
        representative_tensor = next(
            (port.tensor for port in (*node.inputs, *node.outputs) if port.tensor is not None),
            None,
        )
        glyph = FigureObject.create(
            "node-glyph" if publication_projection or node.category in {"input", "output", "model"} else "operator-glyph",
            node.name,
            dict(geometries[node.id]),
            provenance,
            identity=f"model-figure:node:{node.id}",
            metadata={
                "graph_ir_node_id": node.id if provenance.kind == "graph_ir" else None,
                "semantic_view_id": provenance.source_id if provenance.kind == "semantic_view" else None,
                "op_type": node.op_type,
                "operator_family": semantic_type,
                "label": node.name,
                "semantic_level": node.attributes.get("semantic_level", node.level),
                "semantic_type": semantic_type,
                "confidence": node.attributes.get("confidence"),
                "recognition_reasons": list(node.attributes.get("recognition_reasons", [])),
                "unknown_semantics": bool(node.attributes.get("unknown_semantics", False)),
                "repeat_count": int(node.attributes.get("repeat_count", 1)),
                "source_semantic_ids": provenance_semantic_ids,
                "architecture_family": node.attributes.get("architecture_family"),
                "architecture_role_id": node.attributes.get("architecture_role_id"),
                "architecture_role": node.attributes.get("architecture_role"),
                "architecture_evidence_digest": architecture_evidence_digest,
                "architecture_role_graph_digest": architecture_role_graph_digest,
                "architecture_attributes": deepcopy(node.attributes.get("architecture_attributes", {})),
                "protected_semantic_structure": bool(node.attributes.get("protected_semantic_structure", False)),
                "expansion_trace_available": bool(node.attributes.get("expansion_trace_available", False)),
                "architecture_tensor_shape": list(representative_tensor.shape) if representative_tensor else [None],
                "architecture_tensor_dtype": representative_tensor.dtype if representative_tensor else "unknown",
            },
            order=order * 20,
        )
        layer.objects.append(glyph)
        node_objects[node.id] = glyph
        record_provenance(glyph)

        if int(node.attributes.get("repeat_count", 1)) > 1:
            count = int(node.attributes["repeat_count"])
            repeat = FigureObject.create(
                "annotation", f"×{count}",
                {
                    "x": glyph.geometry["x"] + glyph.geometry["width"] / 2.0 - 5.0,
                    "y": glyph.geometry["y"] - 6.0,
                    "width": 10.0,
                    "height": 4.0,
                },
                deepcopy(provenance),
                identity=f"model-figure:repeat:{node.id}",
                style=FigureStyle(overrides={"font_size": 7.0}),
                metadata={
                    "text": f"×{count}",
                    "repeat_count": count,
                    "source_semantic_ids": provenance_semantic_ids,
                    "expansion_trace_available": True,
                },
                order=order * 20 + 1,
            )
            layer.objects.append(repeat)
            record_provenance(repeat)

        if mode not in {"tensor-geometry", "mixed"}:
            continue
        for port_index, port in enumerate(node.outputs):
            if port.tensor is None:
                continue
            dimensions, label = _shape(port.tensor)
            boundary_binding = dict(node.attributes.get("boundary_port_bindings", {}).get(port.id, {}))
            source_port_id = str(boundary_binding.get("source_port_id") or port.id)
            inventory = list(node.attributes.get("output_tensor_inventory_by_port", {}).get(port.id, []))
            inventory_port_ids = [str(item.get("port_id")) for item in inventory if item.get("port_id")]
            tensor_graph_ids = list(dict.fromkeys([*provenance.graph_ir_ids, source_port_id, *inventory_port_ids]))
            tensor = FigureObject.create(
                "tensor-glyph", f"{node.name} · {port.name or f'output {port_index}'}",
                {
                    "x": glyph.geometry["x"] + glyph.geometry["width"] / 2.0 - 3.6,
                    "y": glyph.geometry["y"] + glyph.geometry["height"] + 3.0 + port_index * 10.5,
                    "width": 7.2,
                    "height": 5.2,
                    "depth": 2.0,
                },
                FigureProvenance(
                    provenance.kind,
                    source_id=provenance.source_id if provenance.kind == "semantic_view" else source_port_id,
                    graph_ir_ids=tensor_graph_ids,
                    source_locator=dict(provenance.source_locator),
                    evidence={
                        "source_port_id": source_port_id,
                        "semantic_port_id": port.id,
                        "direction": "output",
                        "tensor": asdict(port.tensor),
                        "boundary_binding": boundary_binding,
                        "semantic_entity_ids": provenance_semantic_ids,
                    },
                ),
                identity=f"model-figure:tensor:{node.id}:{port.id}",
                style=FigureStyle(overrides={"font_size": 7.0}),
                metadata={
                    "tensor_shape": dimensions,
                    "shape_label": label,
                    "dtype": port.tensor.dtype,
                    "port_id": source_port_id,
                    "semantic_port_id": port.id,
                    "boundary_binding": boundary_binding,
                    "port_direction": "output",
                    "layout": "auto",
                    "geometry_scale": "manual",
                    "label_lane_width_mm": max(18.0, glyph.geometry["width"] + 4.0),
                    "unknown_dimensions_preserved": any(value is None or isinstance(value, str) for value in dimensions),
                    "tensor_inventory": inventory,
                    "bundled_output_tensor_count": len(inventory) or 1,
                    "all_source_output_tensors_preserved": bool(inventory) if publication_projection else True,
                },
                order=order * 20 + 2 + port_index,
            )
            layer.objects.append(tensor)
            record_provenance(
                tensor,
                port_id=source_port_id,
                semantic_port_id=port.id,
            )

    for order, edge in enumerate(materialized.edges):
        if edge.source not in node_objects or edge.target not in node_objects:
            continue
        route = _route_between(edge, geometries, layout)
        provenance = _edge_provenance(edge)
        provenance_semantic_ids = _provenance_semantic_entity_ids(provenance)
        semantic_connection_ids = list(provenance.evidence.get("semantic_connection_ids", []))
        source_binding = dict(edge.attributes.get("source_port_binding", {}))
        target_binding = dict(edge.attributes.get("target_port_binding", {}))
        connector_source_port_id = source_binding.get("source_port_id") or edge.source_port
        connector_target_port_id = target_binding.get("source_port_id") or edge.target_port
        connector = FigureObject.create(
            "edge", edge.label or f"{materialized.node_map()[edge.source].name} → {materialized.node_map()[edge.target].name}",
            {"x": route[0][0], "y": route[0][1], "x2": route[-1][0], "y2": route[-1][1]},
            provenance,
            identity=f"model-figure:edge:{edge.id}",
            manual_route=deepcopy(route),
            metadata={
                "graph_ir_edge_id": edge.id if provenance.kind == "graph_ir" else None,
                "semantic_connection_id": semantic_connection_ids[0] if semantic_connection_ids else None,
                "semantic_connection_ids": semantic_connection_ids,
                "source_semantic_ids": provenance_semantic_ids,
                "source_port": connector_source_port_id,
                "target_port": connector_target_port_id,
                "semantic_source_port": edge.source_port,
                "semantic_target_port": edge.target_port,
                "source_port_binding": source_binding,
                "target_port_binding": target_binding,
                "tensor": asdict(edge.tensor) if edge.tensor else None,
                "source_graph_edge_ids": list(edge.attributes.get("source_edges", [])),
                "endpoint_object_ids": [node_objects[edge.source].id, node_objects[edge.target].id],
                "edge_semantics": "model-data",
                "kind": edge.kind,
                "architecture_critical": bool(edge.attributes.get("architecture_critical", False)),
                "architecture_route_id": edge.attributes.get("architecture_route_id"),
                "architecture_route_role": edge.attributes.get("architecture_route_role"),
                "architecture_role_graph_edge_id": edge.attributes.get("architecture_role_graph_edge_id"),
                "endpoint_role_ids": [
                    edge.attributes.get("architecture_source_role_id"),
                    edge.attributes.get("architecture_target_role_id"),
                ],
                "architecture_direction": edge.attributes.get("architecture_direction"),
                "architecture_evidence_digest": architecture_evidence_digest,
                "architecture_role_graph_digest": architecture_role_graph_digest,
                "protected_semantic_structure": bool(edge.attributes.get("protected_semantic_structure", False)),
                "route_origin": "layout-engine",
                "author_manual_route": False,
                "auto_route": deepcopy(route),
            },
            order=100_000 + order,
        )
        layer.objects.append(connector)
        record_provenance(connector, semantic_connection_ids=semantic_connection_ids)

    _reconcile(figure, existing_figure)
    figure.metadata.update({
        "graph_ir": {
            "name": graph.name,
            "ir_version": graph.ir_version,
            "node_count": len(graph.nodes),
            "edge_count": len(graph.edges),
        },
        "semantic_view": {
            "version": semantic.semantic_version,
            "source_digest": semantic.source_digest,
            **pipeline,
        },
        "architecture_evidence": (
            semantic.architecture_evidence.to_dict()
            if semantic.architecture_evidence is not None
            else None
        ),
        "model_figure_pipeline": {
            "version": MODEL_FIGURE_PIPELINE_VERSION,
            "graph_to_semantic_to_figure": True,
            "layout_engine": layout.engine,
            "layout_direction": layout.direction,
            "bounded_visible_nodes": len(materialized.nodes),
            "all_output_tensors": True,
            "unknown_dimensions_are_not_inferred": True,
        },
        "provenance_index": {
            "graph_to_figure": {key: sorted(set(value)) for key, value in sorted(graph_to_figure.items())},
            "semantic_to_figure": {key: sorted(set(value)) for key, value in sorted(semantic_to_figure.items())},
            "figure_to_source": dict(sorted(figure_to_source.items())),
        },
    })
    return figure.validate()


def validate_model_figure_provenance(
    figure: FigureIR,
    graph: GraphIR,
    semantic_view: SemanticView | None = None,
) -> dict[str, Any]:
    """Validate Graph/Semantic/Figure identities and every reverse index."""

    graph.validate()
    failures: list[dict[str, Any]] = []
    semantic = semantic_view
    try:
        semantic = semantic or derive_semantic_view(graph)
        semantic.validate(graph)
    except ValidationError as exc:
        failures.append({"semantic_view_invalid": str(exc)})

    known_node_ids = {node.id for node in graph.nodes}
    known_edges = graph.edge_map()
    known_edge_ids = set(known_edges)
    known_ports = {
        port.id: port
        for node in graph.nodes
        for port in [*node.inputs, *node.outputs]
    }
    known_port_owners = {
        port.id: node.id
        for node in graph.nodes
        for port in [*node.inputs, *node.outputs]
    }
    known_port_ids = set(known_ports)
    known_graph_ids = known_node_ids | known_edge_ids | known_port_ids
    semantic_entities = {
        entity.id: entity
        for entity in semantic.entities
    } if semantic is not None else {}
    known_semantic_ids = set(semantic_entities)
    semantic_entity_levels = {
        entity.id: entity.level
        for entity in semantic.entities
    } if semantic is not None else {}
    semantic_connections = {
        connection.id: connection
        for connections in semantic.connections.values()
        for connection in connections
    } if semantic is not None else {}
    semantic_metadata = figure.metadata.get("semantic_view", {})
    if not isinstance(semantic_metadata, dict):
        failures.append({"malformed_figure_semantic_view_metadata": type(semantic_metadata).__name__})
        semantic_metadata = {}
    selected_level = str(semantic_metadata.get("selected_level", ""))
    selected_semantic_ids = {
        semantic_id
        for semantic_id, entity_level in semantic_entity_levels.items()
        if not selected_level or entity_level == selected_level
    }
    has_semantic_claims = any(
        item.provenance.kind == "semantic_view"
        for item in figure.iter_objects()
    )

    if semantic is not None and (
        has_semantic_claims
        or "source_digest" in semantic_metadata
        or "version" in semantic_metadata
    ):
        if semantic_metadata.get("source_digest") != semantic.source_digest:
            failures.append({
                "semantic_source_digest_mismatch": {
                    "figure": semantic_metadata.get("source_digest"),
                    "semantic_view": semantic.source_digest,
                }
            })
        if semantic_metadata.get("version") != semantic.semantic_version:
            failures.append({
                "semantic_version_mismatch": {
                    "figure": semantic_metadata.get("version"),
                    "semantic_view": semantic.semantic_version,
                }
            })

    claimed_items = {
        item.id: item
        for item in figure.iter_objects()
        if item.provenance.kind in {"graph_ir", "semantic_view"}
    }
    expected_graph_to_figure: dict[str, set[str]] = defaultdict(set)
    expected_semantic_to_figure: dict[str, set[str]] = defaultdict(set)
    for item in claimed_items.values():
        graph_ids = list(map(str, item.provenance.graph_ir_ids))
        if len(graph_ids) != len(set(graph_ids)):
            failures.append({"object_id": item.id, "duplicate_graph_ir_ids": graph_ids})
        missing_graph_ids = sorted(set(graph_ids) - known_graph_ids)
        if missing_graph_ids:
            failures.append({"object_id": item.id, "missing_graph_ir_ids": missing_graph_ids})
        for graph_id in graph_ids:
            expected_graph_to_figure[graph_id].add(item.id)

        if item.provenance.kind == "graph_ir" and (
            not item.provenance.source_id
            or item.provenance.source_id not in graph_ids
            or item.provenance.source_id not in known_graph_ids
        ):
            failures.append({
                "object_id": item.id,
                "graph_ir_primary_source_is_not_claimed_evidence": item.provenance.source_id,
            })
        lens_graph_ids = item.metadata.get("structure_lens_graph_ir_ids")
        if lens_graph_ids is not None and (
            not isinstance(lens_graph_ids, list)
            or set(map(str, lens_graph_ids)) != set(graph_ids)
        ):
            failures.append({
                "object_id": item.id,
                "structure_lens_graph_evidence_mismatch": lens_graph_ids,
            })

        if item.kind == "tensor-glyph":
            evidence_tensor = item.provenance.evidence.get("tensor")
            source_shape = item.metadata.get("tensor_shape")
            source_dtype = item.metadata.get("dtype")
            source_port_id = str(item.metadata.get("port_id", ""))
            source_port = known_ports.get(source_port_id)
            if source_port is None or source_port_id not in graph_ids:
                failures.append({
                    "object_id": item.id,
                    "tensor_source_port_is_not_exact_graph_evidence": source_port_id,
                })
            if not isinstance(evidence_tensor, dict):
                failures.append({"object_id": item.id, "missing_tensor_evidence": True})
            else:
                evidence_shape = evidence_tensor.get("shape")
                if not isinstance(source_shape, list) or evidence_shape != source_shape:
                    failures.append({
                        "object_id": item.id,
                        "tensor_shape_disagrees_with_provenance": {
                            "metadata": source_shape,
                            "evidence": evidence_shape,
                        },
                    })
                evidence_dtype = evidence_tensor.get("dtype")
                if evidence_dtype != source_dtype:
                    failures.append({
                        "object_id": item.id,
                        "tensor_dtype_disagrees_with_provenance": {
                            "metadata": source_dtype,
                            "evidence": evidence_dtype,
                        },
                    })
                if isinstance(source_shape, list):
                    source_label = "[" + ", ".join(
                        "?" if dimension is None else str(dimension)
                        for dimension in source_shape
                    ) + "]"
                    if item.metadata.get("shape_label") != source_label:
                        failures.append({
                            "object_id": item.id,
                            "tensor_source_label_disagrees_with_provenance": {
                                "metadata": item.metadata.get("shape_label"),
                                "expected": source_label,
                            },
                        })
                if source_port is not None:
                    graph_tensor = asdict(source_port.tensor) if source_port.tensor else None
                    if evidence_tensor != graph_tensor:
                        failures.append({
                            "object_id": item.id,
                            "tensor_evidence_disagrees_with_graph_port": {
                                "port_id": source_port_id,
                                "evidence": evidence_tensor,
                                "graph": graph_tensor,
                            },
                        })
            if item.provenance.evidence.get("source_port_id") != source_port_id:
                failures.append({
                    "object_id": item.id,
                    "tensor_evidence_source_port_mismatch": {
                        "metadata": source_port_id,
                        "evidence": item.provenance.evidence.get("source_port_id"),
                    },
                })
            if item.provenance.evidence.get("semantic_port_id") != item.metadata.get("semantic_port_id"):
                failures.append({
                    "object_id": item.id,
                    "tensor_semantic_port_mismatch": True,
                })
            evidence_boundary = item.provenance.evidence.get("boundary_binding", {})
            metadata_boundary = item.metadata.get("boundary_binding", {})
            if evidence_boundary != metadata_boundary:
                failures.append({
                    "object_id": item.id,
                    "tensor_boundary_binding_mismatch": True,
                })
            if isinstance(metadata_boundary, dict) and metadata_boundary:
                if (
                    metadata_boundary.get("source_port_id") != source_port_id
                    or metadata_boundary.get("source_node_id") != known_port_owners.get(source_port_id)
                ):
                    failures.append({
                        "object_id": item.id,
                        "tensor_boundary_binding_disagrees_with_graph": metadata_boundary,
                    })

        if item.kind == "edge":
            claimed_edge_ids = sorted(set(graph_ids).intersection(known_edge_ids))
            declared_edge_ids = list(map(str, item.metadata.get("source_graph_edge_ids", [])))
            graph_ir_edge_id = item.metadata.get("graph_ir_edge_id")
            if not declared_edge_ids and graph_ir_edge_id:
                declared_edge_ids = [str(graph_ir_edge_id)]
            if not claimed_edge_ids or set(declared_edge_ids) != set(claimed_edge_ids):
                failures.append({
                    "object_id": item.id,
                    "figure_edge_graph_ids_disagree_with_metadata": {
                        "claimed": claimed_edge_ids,
                        "declared": sorted(set(declared_edge_ids)),
                    },
                })
            edge_source_port_id = item.metadata.get("source_port")
            edge_target_port_id = item.metadata.get("target_port")
            binding_matches = [
                known_edges[edge_id]
                for edge_id in claimed_edge_ids
                if known_edges[edge_id].source_port == edge_source_port_id
                and known_edges[edge_id].target_port == edge_target_port_id
            ]
            if not binding_matches:
                failures.append({
                    "object_id": item.id,
                    "figure_edge_port_binding_disagrees_with_graph": {
                        "source_port": edge_source_port_id,
                        "target_port": edge_target_port_id,
                        "claimed_graph_edges": claimed_edge_ids,
                    },
                })
            else:
                graph_tensors = [
                    asdict(edge.tensor) if edge.tensor else None
                    for edge in binding_matches
                ]
                if item.metadata.get("tensor") not in graph_tensors:
                    failures.append({
                        "object_id": item.id,
                        "figure_edge_tensor_disagrees_with_graph": True,
                    })
                if item.provenance.evidence.get("tensor") not in graph_tensors:
                    failures.append({
                        "object_id": item.id,
                        "figure_edge_provenance_tensor_disagrees_with_graph": True,
                    })
                source_binding = item.metadata.get("source_port_binding", {})
                target_binding = item.metadata.get("target_port_binding", {})
                if source_binding and not any(
                    source_binding.get("source_port_id") == edge.source_port
                    and source_binding.get("source_node_id") == edge.source
                    for edge in binding_matches
                ):
                    failures.append({
                        "object_id": item.id,
                        "figure_edge_source_binding_disagrees_with_graph": source_binding,
                    })
                if target_binding and not any(
                    target_binding.get("source_port_id") == edge.target_port
                    and target_binding.get("source_node_id") == edge.target
                    for edge in binding_matches
                ):
                    failures.append({
                        "object_id": item.id,
                        "figure_edge_target_binding_disagrees_with_graph": target_binding,
                    })
            if item.provenance.kind == "semantic_view":
                if item.metadata.get("semantic_source_port") != item.provenance.evidence.get("source_port"):
                    failures.append({
                        "object_id": item.id,
                        "figure_edge_semantic_source_port_mismatch": True,
                    })
                if item.metadata.get("semantic_target_port") != item.provenance.evidence.get("target_port"):
                    failures.append({
                        "object_id": item.id,
                        "figure_edge_semantic_target_port_mismatch": True,
                    })
            elif item.metadata.get("semantic_source_port") is not None or item.metadata.get("semantic_target_port") is not None:
                failures.append({
                    "object_id": item.id,
                    "graph_ir_edge_retains_semantic_port_metadata": True,
                })

        if item.provenance.kind != "semantic_view":
            continue
        semantic_ids = _provenance_semantic_entity_ids(item.provenance)
        if len(semantic_ids) != len(set(semantic_ids)):
            failures.append({"object_id": item.id, "duplicate_semantic_entity_ids": semantic_ids})
        if not item.provenance.source_id:
            failures.append({"object_id": item.id, "missing_semantic_source_id": True})
        elif item.provenance.source_id not in semantic_ids:
            failures.append({
                "object_id": item.id,
                "semantic_source_id_missing_from_object_entities": item.provenance.source_id,
            })
        orphan_ids = sorted(set(semantic_ids) - known_semantic_ids)
        if orphan_ids:
            failures.append({"object_id": item.id, "orphan_semantic_entity_ids": orphan_ids})
        for semantic_id in set(semantic_ids).intersection(semantic_entities):
            entity_source_nodes = set(semantic_entities[semantic_id].provenance.source_node_ids)
            if entity_source_nodes.isdisjoint(set(graph_ids)):
                failures.append({
                    "object_id": item.id,
                    "semantic_entity_has_no_claimed_graph_node_evidence": semantic_id,
                })
        wrong_level_ids = sorted(set(semantic_ids) - selected_semantic_ids) if selected_level else []
        if wrong_level_ids:
            failures.append({
                "object_id": item.id,
                "semantic_entity_ids_at_wrong_level": wrong_level_ids,
                "selected_level": selected_level,
            })
        for semantic_id in semantic_ids:
            expected_semantic_to_figure[semantic_id].add(item.id)
        connection_ids = list(map(str, item.provenance.evidence.get("semantic_connection_ids", [])))
        metadata_semantic_ids = item.metadata.get("source_semantic_ids")
        if metadata_semantic_ids is not None and (
            not isinstance(metadata_semantic_ids, list)
            or set(map(str, metadata_semantic_ids)) != set(semantic_ids)
        ):
            failures.append({
                "object_id": item.id,
                "figure_metadata_semantic_ids_mismatch": metadata_semantic_ids,
            })
        metadata_connection_ids = item.metadata.get("semantic_connection_ids")
        if metadata_connection_ids is not None and (
            not isinstance(metadata_connection_ids, list)
            or set(map(str, metadata_connection_ids)) != set(connection_ids)
        ):
            failures.append({
                "object_id": item.id,
                "figure_metadata_semantic_connection_ids_mismatch": metadata_connection_ids,
            })
        if connection_ids and item.metadata.get("semantic_connection_id") != connection_ids[0]:
            failures.append({
                "object_id": item.id,
                "figure_primary_semantic_connection_mismatch": item.metadata.get("semantic_connection_id"),
            })
        orphan_connection_ids = sorted(set(connection_ids) - set(semantic_connections))
        if orphan_connection_ids:
            failures.append({"object_id": item.id, "orphan_semantic_connection_ids": orphan_connection_ids})
        for connection_id in set(connection_ids).intersection(semantic_connections):
            connection = semantic_connections[connection_id]
            missing_endpoints = sorted({connection.source, connection.target} - set(semantic_ids))
            if missing_endpoints:
                failures.append({
                    "object_id": item.id,
                    "semantic_connection_endpoints_missing_from_object": missing_endpoints,
                    "semantic_connection_id": connection_id,
                })
            if set(connection.provenance.source_edge_ids).isdisjoint(set(graph_ids)):
                failures.append({
                    "object_id": item.id,
                    "semantic_connection_has_no_claimed_graph_edge_evidence": connection_id,
                })

    index = figure.metadata.get("provenance_index", {})
    if not isinstance(index, dict):
        failures.append({"malformed_provenance_index": type(index).__name__})
        index = {}
    graph_index = index.get("graph_to_figure", {})
    semantic_index = index.get("semantic_to_figure", {})
    reverse_index = index.get("figure_to_source", {})

    def normalize_forward_index(
        name: str,
        value: Any,
        *,
        known_source_ids: set[str],
    ) -> dict[str, set[str]]:
        if not isinstance(value, dict):
            failures.append({f"malformed_{name}": type(value).__name__})
            return {}
        normalized: dict[str, set[str]] = {}
        for raw_source_id, raw_object_ids in value.items():
            source_id = str(raw_source_id)
            if not isinstance(raw_object_ids, list):
                failures.append({name: source_id, "object_ids_must_be_a_list": type(raw_object_ids).__name__})
                continue
            object_ids = list(map(str, raw_object_ids))
            if len(object_ids) != len(set(object_ids)):
                failures.append({name: source_id, "duplicate_object_ids": object_ids})
            if source_id not in known_source_ids:
                failures.append({name: source_id, "orphan_source_id": True})
            orphan_objects = sorted(set(object_ids) - set(claimed_items))
            if orphan_objects:
                failures.append({name: source_id, "orphan_figure_object_ids": orphan_objects})
            normalized[source_id] = set(object_ids)
        return normalized

    normalized_graph_index = normalize_forward_index(
        "graph_to_figure",
        graph_index,
        known_source_ids=known_graph_ids,
    )
    normalized_semantic_index = normalize_forward_index(
        "semantic_to_figure",
        semantic_index,
        known_source_ids=known_semantic_ids,
    )

    def compare_forward_index(
        name: str,
        actual: dict[str, set[str]],
        expected: dict[str, set[str]],
    ) -> None:
        actual_links = {(source_id, object_id) for source_id, object_ids in actual.items() for object_id in object_ids}
        expected_links = {(source_id, object_id) for source_id, object_ids in expected.items() for object_id in object_ids}
        if actual_links != expected_links:
            failures.append({
                f"{name}_bidirectional_mismatch": {
                    "missing_links": sorted(expected_links - actual_links),
                    "extra_links": sorted(actual_links - expected_links),
                }
            })

    compare_forward_index("graph_to_figure", normalized_graph_index, expected_graph_to_figure)
    compare_forward_index("semantic_to_figure", normalized_semantic_index, expected_semantic_to_figure)

    if not isinstance(reverse_index, dict):
        failures.append({"malformed_figure_to_source": type(reverse_index).__name__})
        reverse_index = {}
    indexed_object_ids = set(map(str, reverse_index))
    claimed_object_ids = set(claimed_items)
    if indexed_object_ids != claimed_object_ids:
        failures.append({
            "figure_to_source_object_mismatch": {
                "missing_objects": sorted(claimed_object_ids - indexed_object_ids),
                "extra_objects": sorted(indexed_object_ids - claimed_object_ids),
            }
        })
    for object_id in sorted(claimed_object_ids.intersection(indexed_object_ids)):
        item = claimed_items[object_id]
        entry = reverse_index[object_id]
        if not isinstance(entry, dict):
            failures.append({"object_id": object_id, "malformed_figure_to_source_entry": type(entry).__name__})
            continue
        expected_graph_ids = set(map(str, item.provenance.graph_ir_ids))
        entry_graph_ids = entry.get("graph_ir_ids", [])
        if not isinstance(entry_graph_ids, list) or set(map(str, entry_graph_ids)) != expected_graph_ids:
            failures.append({
                "object_id": object_id,
                "figure_to_source_graph_ids_mismatch": {
                    "expected": sorted(expected_graph_ids),
                    "actual": sorted(map(str, entry_graph_ids)) if isinstance(entry_graph_ids, list) else entry_graph_ids,
                },
            })
        expected_port_ids = expected_graph_ids.intersection(known_port_ids)
        entry_port_ids = entry.get("graph_port_ids", [])
        if not isinstance(entry_port_ids, list) or set(map(str, entry_port_ids)) != expected_port_ids:
            failures.append({
                "object_id": object_id,
                "figure_to_source_port_ids_mismatch": {
                    "expected": sorted(expected_port_ids),
                    "actual": sorted(map(str, entry_port_ids)) if isinstance(entry_port_ids, list) else entry_port_ids,
                },
            })
        explicit_port_id = entry.get("port_id")
        if explicit_port_id is not None and (
            str(explicit_port_id) not in known_port_ids
            or str(explicit_port_id) not in expected_graph_ids
        ):
            failures.append({"object_id": object_id, "invalid_figure_to_source_port_id": explicit_port_id})

        if item.provenance.kind == "semantic_view":
            expected_semantic_ids = set(_provenance_semantic_entity_ids(item.provenance))
            entry_semantic_ids = entry.get("semantic_ids", [])
            if not isinstance(entry_semantic_ids, list) or set(map(str, entry_semantic_ids)) != expected_semantic_ids:
                failures.append({
                    "object_id": object_id,
                    "figure_to_source_semantic_ids_mismatch": {
                        "expected": sorted(expected_semantic_ids),
                        "actual": sorted(map(str, entry_semantic_ids)) if isinstance(entry_semantic_ids, list) else entry_semantic_ids,
                    },
                })
            if entry.get("semantic_id") != item.provenance.source_id:
                failures.append({
                    "object_id": object_id,
                    "figure_to_source_primary_semantic_id_mismatch": {
                        "expected": item.provenance.source_id,
                        "actual": entry.get("semantic_id"),
                    },
                })
            expected_connection_ids = set(map(str, item.provenance.evidence.get("semantic_connection_ids", [])))
            entry_connection_ids = entry.get("semantic_connection_ids", [])
            if not isinstance(entry_connection_ids, list) or set(map(str, entry_connection_ids)) != expected_connection_ids:
                failures.append({
                    "object_id": object_id,
                    "figure_to_source_semantic_connection_ids_mismatch": {
                        "expected": sorted(expected_connection_ids),
                        "actual": sorted(map(str, entry_connection_ids)) if isinstance(entry_connection_ids, list) else entry_connection_ids,
                    },
                })
        elif entry.get("semantic_id") or entry.get("semantic_ids"):
            failures.append({"object_id": object_id, "graph_ir_object_claims_semantic_identity": True})

    projection = semantic_metadata.get("publication_projection", {})
    if isinstance(projection, dict) and projection.get("all_source_nodes_mapped"):
        missing_source_ids = sorted(known_graph_ids - set(expected_graph_to_figure))
        if missing_source_ids:
            failures.append({"publication_projection_unmapped_graph_ir_ids": missing_source_ids})
        projection_level = str(projection.get("semantic_level", "stage"))
        expected_projection_ids = {
            semantic_id
            for semantic_id, level in semantic_entity_levels.items()
            if level == projection_level
        }
        complete_semantic_coverage = bool(
            projection.get("all_selected_semantic_entities_mapped")
            or (
                projection_level == "stage"
                and projection.get("all_stage_semantic_entities_mapped")
            )
        )
        if complete_semantic_coverage and set(expected_semantic_to_figure) != expected_projection_ids:
            failures.append({
                "publication_projection_semantic_coverage_mismatch": {
                    "semantic_level": projection_level,
                    "missing": sorted(expected_projection_ids - set(expected_semantic_to_figure)),
                    "extra": sorted(set(expected_semantic_to_figure) - expected_projection_ids),
                }
            })
        declared_semantic_ids = set(map(str, projection.get("semantic_entity_ids", [])))
        if declared_semantic_ids != set(expected_semantic_to_figure):
            failures.append({
                "publication_projection_declared_semantic_ids_mismatch": {
                    "missing": sorted(set(expected_semantic_to_figure) - declared_semantic_ids),
                    "extra": sorted(declared_semantic_ids - set(expected_semantic_to_figure)),
                }
            })

    return {
        "schema_version": "nndv-model-figure-provenance-2",
        "linked_object_count": len(claimed_items),
        "known_graph_ir_id_count": len(known_graph_ids),
        "known_semantic_entity_count": len(known_semantic_ids),
        "failures": failures,
        "passed": not failures,
    }


def structure_lens_panel_preview(
    graph: GraphIR,
    result: Any,
    *,
    page_preset: str = "double-column",
    maximum_nodes: int = 40,
) -> dict[str, Any]:
    """Return a side-effect-free Figure Panel preview for an explicit Add step."""

    payload = result.to_dict() if hasattr(result, "to_dict") else dict(result)
    requested_ids = list(dict.fromkeys(map(str, payload.get("node_ids", []))))
    if not requested_ids:
        return {
            "available": False,
            "preview_only": True,
            "requires_explicit_add": True,
            "reason": "The Structure Lens result contains no Graph IR nodes to preview.",
        }
    selected_ids = requested_ids[:maximum_nodes]
    selected = set(selected_ids)
    source_nodes = graph.node_map()
    unknown = sorted(selected - set(source_nodes))
    if unknown:
        raise ValidationError(f"Structure Lens preview references missing Graph IR nodes {unknown!r}")
    selected_edge_ids = set(map(str, payload.get("edge_ids", [])))
    edges = [
        deepcopy(edge)
        for edge in graph.edges
        if edge.source in selected and edge.target in selected
        and (not selected_edge_ids or edge.id in selected_edge_ids)
    ]
    subset = GraphIR(
        f"{graph.name} · Structure Lens preview",
        [deepcopy(source_nodes[node_id]) for node_id in selected_ids],
        edges,
        metadata={
            **graph.metadata,
            "structure_lens_preview": {
                "operation": payload.get("operation"),
                "status": payload.get("status"),
                "source_node_count": len(requested_ids),
                "truncated": len(requested_ids) > maximum_nodes,
                "positive_claim": payload.get("metadata", {}).get("positive_claim"),
            },
        },
        ir_version=graph.ir_version,
    ).validate()
    preview_figure = model_figure_from_graph(
        subset,
        level="operation",
        view="faithful",
        mode="schematic",
        page_preset=page_preset,
    )
    panel = deepcopy(next(preview_figure.iter_panels()))
    panel.title = f"Structure Lens · {payload.get('operation', 'result')}"
    semantic_metadata_keys = {
        "semantic_view_id",
        "semantic_level",
        "semantic_type",
        "confidence",
        "recognition_reasons",
        "unknown_semantics",
        "source_semantic_ids",
        "semantic_connection_id",
        "semantic_connection_ids",
        "semantic_source_port",
        "semantic_target_port",
        "semantic_port_id",
    }
    for item in (object_ for layer in panel.layers for object_ in layer.objects):
        graph_ids = list(dict.fromkeys(map(str, item.provenance.graph_ir_ids)))
        semantic_evidence_keys = {
            "semantic_entity_ids",
            "semantic_connection_ids",
            "semantic_level",
            "semantic_type",
            "confidence",
            "unknown_semantics",
        }
        graph_evidence = {
            key: deepcopy(value)
            for key, value in item.provenance.evidence.items()
            if key not in semantic_evidence_keys
        }
        graph_evidence["structure_lens_graph_evidence"] = True
        graph_node_ids = [graph_id for graph_id in graph_ids if graph_id in source_nodes]
        if len(graph_node_ids) == 1:
            graph_node = source_nodes[graph_node_ids[0]]
            source_locator = deepcopy(graph_node.source)
            item.metadata["graph_ir_node_id"] = graph_node.id
            item.metadata["op_type"] = graph_node.op_type
            item.metadata["operator_family"] = graph_node.op_type
            graph_evidence["op_type"] = graph_node.op_type
        else:
            source_locator = {}
        if item.kind == "edge":
            graph_evidence["source_port"] = item.metadata.get("source_port")
            graph_evidence["target_port"] = item.metadata.get("target_port")
        for key in semantic_metadata_keys:
            item.metadata.pop(key, None)
        item.provenance = FigureProvenance(
            "graph_ir",
            source_id=graph_ids[0] if graph_ids else "",
            graph_ir_ids=graph_ids,
            source_locator=source_locator,
            evidence=graph_evidence,
            reason=(
                "Structure Lens panel object linked to exact Graph IR evidence; "
                "the bounded query's Semantic View evidence remains in the Lens result."
            ),
        )
        item.metadata["structure_lens_preview"] = True
        item.metadata["structure_lens_graph_ir_ids"] = graph_ids
        item.metadata["structure_lens_operation"] = payload.get("operation")
        item.metadata["structure_lens_status"] = payload.get("status")
    page = preview_figure.pages[0]
    return {
        "available": True,
        "preview_only": True,
        "requires_explicit_add": True,
        "mutated_figure": False,
        "panel": asdict(panel),
        "page": {
            "width_mm": page.width_mm,
            "height_mm": page.height_mm,
            "margin_mm": page.margin_mm,
            "columns": 1,
            "column_gap_mm": page.column_gap_mm,
            "baseline_grid_pt": page.baseline_grid_pt,
        },
        "source_result": {
            "operation": payload.get("operation"),
            "status": payload.get("status"),
            "node_ids": selected_ids,
            "edge_ids": [edge.id for edge in edges],
            "truncated": len(requested_ids) > maximum_nodes,
            "warnings": list(payload.get("warnings", [])),
        },
    }


__all__ = [
    "MAXIMUM_UNFOCUSED_OPERATION_NODES",
    "MODEL_FIGURE_PIPELINE_VERSION",
    "model_figure_from_graph",
    "structure_lens_panel_preview",
    "validate_model_figure_provenance",
]
