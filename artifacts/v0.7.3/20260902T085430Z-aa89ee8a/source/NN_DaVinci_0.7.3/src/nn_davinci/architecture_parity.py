"""Independent Figure IR ↔ Scene IR architecture parity oracle.

The oracle reads only landed documents and their sealed Architecture Evidence;
it does not call either projection builder.  This makes removal, relabeling,
repeat-count drift, and provenance substitution observable after serialization.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

from .architecture_evidence import ArchitectureEvidence
from .figure_ir import FigureIR, FigureObject
from .ir import GraphIR
from .scene_ir import Object3D, Scene
from .semantic import SemanticView


ARCHITECTURE_PARITY_ORACLE_VERSION = "1.0"


def _evidence_from_documents(
    figure: FigureIR,
    scene: Scene,
    supplied: ArchitectureEvidence | Mapping[str, Any] | None,
    semantic_evidence: ArchitectureEvidence | Mapping[str, Any] | None = None,
) -> tuple[ArchitectureEvidence | None, list[dict[str, Any]]]:
    failures: list[dict[str, Any]] = []
    raw_figure = figure.metadata.get("architecture_evidence")
    raw_scene = scene.metadata.get("architecture_evidence")
    candidates: list[tuple[str, ArchitectureEvidence]] = []
    for origin, raw in (
        ("figure", raw_figure),
        ("scene", raw_scene),
        ("semantic", semantic_evidence),
        ("supplied", supplied),
    ):
        if raw is None:
            continue
        try:
            evidence = raw if isinstance(raw, ArchitectureEvidence) else ArchitectureEvidence.from_dict(raw)
        except Exception as exc:  # noqa: BLE001 - validation is reported as oracle data.
            failures.append({"invalid_architecture_evidence": origin, "error": str(exc)})
            continue
        candidates.append((origin, evidence))
    if not candidates:
        failures.append({"architecture_evidence_missing": ["figure", "scene"]})
        return None, failures
    digests = {item.provenance_digest for _origin, item in candidates}
    if len(digests) != 1:
        failures.append({
            "architecture_evidence_digest_mismatch": {
                origin: item.provenance_digest for origin, item in candidates
            }
        })
    return candidates[0][1], failures


def _by_role_id(objects: list[FigureObject] | list[Object3D]) -> dict[str, list[Any]]:
    result: dict[str, list[Any]] = defaultdict(list)
    for item in objects:
        role_id = item.metadata.get("architecture_role_id")
        if role_id:
            result[str(role_id)].append(item)
    return result


def _protected_routes(objects: list[FigureObject] | list[Object3D]) -> dict[str, list[Any]]:
    result: dict[str, list[Any]] = defaultdict(list)
    for item in objects:
        route_id = item.metadata.get("architecture_route_id")
        if route_id and item.metadata.get("protected_semantic_structure"):
            result[str(route_id)].append(item)
    return result


def _source_tensor_contracts(graph: GraphIR, source_ids: set[str]) -> set[tuple[str, str]]:
    """Return canonical shape/dtype contracts reachable from exact source IDs."""

    contracts: set[tuple[str, str]] = set()
    for node in graph.nodes:
        if node.id not in source_ids and not any(
            port.id in source_ids for port in (*node.inputs, *node.outputs)
        ):
            continue
        for port in (*node.inputs, *node.outputs):
            if port.tensor is None:
                continue
            shape = str(list(port.tensor.shape))
            contracts.add((shape, port.tensor.dtype))
    for edge in graph.edges:
        if edge.id in source_ids and edge.tensor is not None:
            contracts.add((str(list(edge.tensor.shape)), edge.tensor.dtype))
    return contracts


def validate_figure_scene_architecture_parity(
    figure: FigureIR,
    scene: Scene,
    evidence: ArchitectureEvidence | Mapping[str, Any] | None = None,
    *,
    graph: GraphIR | None = None,
    semantic: SemanticView | None = None,
) -> dict[str, Any]:
    """Compare independently landed source, semantic, 2D, and 3D claims.

    The oracle never calls either production builder.  When ``graph`` and
    ``semantic`` are supplied it additionally revalidates the landed source
    digest, exact source IDs, ports, and tensor contracts.
    """

    failures: list[dict[str, Any]] = []
    try:
        figure.validate()
    except Exception as exc:  # noqa: BLE001 - return all parity failures together.
        failures.append({"figure_invalid": str(exc)})
    try:
        scene.validate()
    except Exception as exc:  # noqa: BLE001 - return all parity failures together.
        failures.append({"scene_invalid": str(exc)})
    if graph is not None:
        try:
            graph.validate()
        except Exception as exc:  # noqa: BLE001 - return all parity failures together.
            failures.append({"graph_invalid": str(exc)})
    if semantic is not None:
        try:
            semantic.validate(graph)
        except Exception as exc:  # noqa: BLE001 - return all parity failures together.
            failures.append({"semantic_invalid": str(exc)})
    semantic_evidence = semantic.architecture_evidence if semantic is not None else None
    expected, evidence_failures = _evidence_from_documents(
        figure,
        scene,
        evidence,
        semantic_evidence,
    )
    failures.extend(evidence_failures)
    if expected is None:
        return {
            "schema_version": "nndv-architecture-parity-1",
            "oracle_version": ARCHITECTURE_PARITY_ORACLE_VERSION,
            "passed": False,
            "failures": failures,
        }
    if graph is not None:
        try:
            expected.validate(
                graph,
                source_digest=semantic.source_digest if semantic is not None else expected.source_digest,
            )
        except Exception as exc:  # noqa: BLE001 - report stale landed evidence.
            failures.append({"source_bound_architecture_evidence_invalid": str(exc)})
    if semantic is not None:
        figure_source_digest = figure.metadata.get("semantic_view", {}).get("source_digest")
        scene_source_digest = scene.metadata.get("semantic_view", {}).get("source_digest")
        if figure_source_digest != semantic.source_digest or scene_source_digest != semantic.source_digest:
            failures.append({
                "semantic_source_digest_mismatch": {
                    "expected": semantic.source_digest,
                    "figure": figure_source_digest,
                    "scene": scene_source_digest,
                }
            })

    figure_objects = list(figure.iter_objects())
    scene_objects = list(scene.iter_objects())
    figure_roles = _by_role_id(figure_objects)
    scene_roles = _by_role_id(scene_objects)
    figure_routes = _protected_routes(figure_objects)
    scene_routes = _protected_routes(scene_objects)
    expected_role_ids = {role.id for role in expected.detected_roles}
    expected_route_ids = {route.id for route in expected.critical_routes}

    for surface, actual in (("figure", figure_roles), ("scene", scene_roles)):
        actual_ids = set(actual)
        if actual_ids != expected_role_ids:
            failures.append({
                f"{surface}_architecture_roles_mismatch": {
                    "missing": sorted(expected_role_ids - actual_ids),
                    "extra": sorted(actual_ids - expected_role_ids),
                }
            })
        duplicates = sorted(role_id for role_id, objects in actual.items() if len(objects) != 1)
        if duplicates:
            failures.append({f"{surface}_architecture_role_cardinality": duplicates})
    for surface, actual in (("figure", figure_routes), ("scene", scene_routes)):
        actual_ids = set(actual)
        if actual_ids != expected_route_ids:
            failures.append({
                f"{surface}_critical_routes_mismatch": {
                    "missing": sorted(expected_route_ids - actual_ids),
                    "extra": sorted(actual_ids - expected_route_ids),
                }
            })
        duplicates = sorted(route_id for route_id, objects in actual.items() if len(objects) != 1)
        if duplicates:
            failures.append({f"{surface}_critical_route_cardinality": duplicates})

    for role in expected.detected_roles:
        required_graph_ids = set(role.supporting_node_ids) | set(role.supporting_edge_ids) | set(role.supporting_port_ids)
        landed: dict[str, Any] = {}
        for surface, actual in (("figure", figure_roles), ("scene", scene_roles)):
            for item in actual.get(role.id, []):
                landed[surface] = item
                if str(item.metadata.get("architecture_role")) != role.role:
                    failures.append({
                        "role_id": role.id,
                        "surface": surface,
                        "role_label_drift": {
                            "expected": role.role,
                            "actual": item.metadata.get("architecture_role"),
                        },
                    })
                if int(item.metadata.get("repeat_count", 1)) != role.repeat_count:
                    failures.append({
                        "role_id": role.id,
                        "surface": surface,
                        "repeat_count_drift": {
                            "expected": role.repeat_count,
                            "actual": item.metadata.get("repeat_count"),
                        },
                    })
                actual_graph_ids = set(item.provenance.graph_ir_ids)
                if actual_graph_ids != required_graph_ids:
                    failures.append({
                        "role_id": role.id,
                        "surface": surface,
                        "role_provenance_mismatch": {
                            "missing": sorted(required_graph_ids - actual_graph_ids),
                            "extra": sorted(actual_graph_ids - required_graph_ids),
                        },
                    })
                if not item.metadata.get("protected_semantic_structure"):
                    failures.append({
                        "role_id": role.id,
                        "surface": surface,
                        "role_not_protected": True,
                    })
                if str(item.metadata.get("semantic_level")) != "stage":
                    failures.append({
                        "role_id": role.id,
                        "surface": surface,
                        "semantic_level_drift": {
                            "expected": "stage",
                            "actual": item.metadata.get("semantic_level"),
                        },
                    })
        if set(landed) == {"figure", "scene"}:
            figure_shape = landed["figure"].metadata.get("architecture_tensor_shape")
            scene_shape = landed["scene"].metadata.get("architecture_tensor_shape")
            figure_dtype = landed["figure"].metadata.get("architecture_tensor_dtype")
            scene_dtype = landed["scene"].metadata.get("architecture_tensor_dtype")
            if figure_shape != scene_shape or figure_dtype != scene_dtype:
                failures.append({
                    "role_id": role.id,
                    "tensor_contract_mismatch": {
                        "figure": {"shape": figure_shape, "dtype": figure_dtype},
                        "scene": {"shape": scene_shape, "dtype": scene_dtype},
                    },
                })
            if graph is not None:
                source_contracts = _source_tensor_contracts(graph, required_graph_ids)
                landed_contract = (str(figure_shape), str(figure_dtype))
                if source_contracts and landed_contract not in source_contracts:
                    failures.append({
                        "role_id": role.id,
                        "tensor_contract_not_in_graph_source": {
                            "landed": {"shape": figure_shape, "dtype": figure_dtype},
                            "source_contracts": [
                                {"shape": shape, "dtype": dtype}
                                for shape, dtype in sorted(source_contracts)
                            ],
                        },
                    })

    for route in expected.critical_routes:
        required_edges = set(route.supporting_edge_ids)
        for surface, actual in (("figure", figure_routes), ("scene", scene_routes)):
            for item in actual.get(route.id, []):
                if str(item.metadata.get("architecture_route_role")) != route.role:
                    failures.append({
                        "route_id": route.id,
                        "surface": surface,
                        "route_role_drift": {
                            "expected": route.role,
                            "actual": item.metadata.get("architecture_route_role"),
                        },
                    })
                actual_ids = set(item.provenance.graph_ir_ids)
                if graph is None:
                    missing_edges = required_edges - actual_ids
                    extra_edges: set[str] = set()
                    missing_endpoints: set[str] = set()
                    unknown_ids: set[str] = set()
                else:
                    graph_edges = graph.edge_map()
                    graph_nodes = set(graph.node_map())
                    graph_ports = {
                        port.id
                        for node in graph.nodes
                        for port in (*node.inputs, *node.outputs)
                    }
                    actual_edges = actual_ids & set(graph_edges)
                    missing_edges = required_edges - actual_edges
                    extra_edges = actual_edges - required_edges
                    required_endpoints = {
                        source_id
                        for edge_id in required_edges
                        for source_id in (
                            graph_edges[edge_id].source,
                            graph_edges[edge_id].target,
                            graph_edges[edge_id].source_port,
                            graph_edges[edge_id].target_port,
                        )
                        if source_id
                    }
                    missing_endpoints = required_endpoints - actual_ids
                    unknown_ids = actual_ids - graph_nodes - set(graph_edges) - graph_ports
                if missing_edges or extra_edges or missing_endpoints or unknown_ids:
                    failures.append({
                        "route_id": route.id,
                        "surface": surface,
                        "route_provenance_mismatch": {
                            "missing_edges": sorted(missing_edges),
                            "extra_edges": sorted(extra_edges),
                            "missing_edge_endpoints": sorted(missing_endpoints),
                            "unknown_source_ids": sorted(unknown_ids),
                        },
                    })

    figure_family = (figure.metadata.get("architecture_evidence") or {}).get("family")
    scene_family = scene.metadata.get("evidenced_architecture_family")
    if figure_family != expected.family or scene_family != expected.family:
        failures.append({
            "family_mismatch": {
                "expected": expected.family,
                "figure": figure_family,
                "scene": scene_family,
            }
        })
    omitted_default = 0 if not expected.critical_routes else None
    omitted = scene.metadata.get("model_scene_pipeline", {}).get("omitted_critical_edges", omitted_default)
    projection = figure.metadata.get("semantic_view", {}).get("publication_projection", {})
    figure_omitted = projection.get("omitted_critical_edges", omitted_default)
    if omitted != 0 or figure_omitted != 0:
        failures.append({
            "critical_edges_omitted": {"figure": figure_omitted, "scene": omitted}
        })

    return {
        "schema_version": "nndv-architecture-parity-1",
        "oracle_version": ARCHITECTURE_PARITY_ORACLE_VERSION,
        "family": expected.family,
        "evidence_version": expected.evidence_version,
        "evidence_provenance_digest": expected.provenance_digest,
        "expected_role_count": len(expected.detected_roles),
        "expected_critical_route_count": len(expected.critical_routes),
        "figure_role_count": len(figure_roles),
        "scene_role_count": len(scene_roles),
        "figure_critical_route_count": len(figure_routes),
        "scene_critical_route_count": len(scene_routes),
        "input_role_ids": [
            role.id
            for role in expected.detected_roles
            if role.role in {"input", "input-stem", "embedding", "image-lane", "text-lane"}
        ],
        "output_role_ids": [
            role.id for role in expected.detected_roles if role.role == "output-head"
        ],
        "unknown_reason": expected.unknown_reason,
        "uncertain_claims": expected.uncertain_claims,
        "failures": failures,
        "passed": not failures,
    }


def validate_landed_architecture_parity(
    graph: GraphIR,
    semantic: SemanticView,
    figure: FigureIR,
    scene: Scene,
) -> dict[str, Any]:
    """Strict four-document entry point used by release artifact generation."""

    return validate_figure_scene_architecture_parity(
        figure,
        scene,
        semantic.architecture_evidence,
        graph=graph,
        semantic=semantic,
    )


__all__ = [
    "ARCHITECTURE_PARITY_ORACLE_VERSION",
    "validate_figure_scene_architecture_parity",
    "validate_landed_architecture_parity",
]
