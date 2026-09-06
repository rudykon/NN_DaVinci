"""Bounded, evidence-linked structural analysis for paper authors."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
import time
from typing import Any, Callable, Iterable

from .errors import ValidationError
from .ir import Edge, GraphIR, Node, TensorSpec
from .tensor_geometry import shape_label, shape_transition


STRUCTURE_LENS_VERSION = "1.0"


@dataclass(slots=True)
class AnalysisBudget:
    maximum_visits: int = 10_000
    maximum_depth: int = 64
    maximum_paths: int = 25
    maximum_queue_entries: int = 10_000
    maximum_generated_states: int = 50_000
    maximum_memory_bytes: int = 64 * 1024 * 1024
    timeout_seconds: float = 1.0

    def validate(self) -> "AnalysisBudget":
        if not 1 <= int(self.maximum_visits) <= 1_000_000:
            raise ValidationError("Structure Lens maximum_visits must be between 1 and 1,000,000")
        if not 1 <= int(self.maximum_depth) <= 1_000:
            raise ValidationError("Structure Lens maximum_depth must be between 1 and 1,000")
        if not 1 <= int(self.maximum_paths) <= 1_000:
            raise ValidationError("Structure Lens maximum_paths must be between 1 and 1,000")
        if not 1 <= int(self.maximum_queue_entries) <= 1_000_000:
            raise ValidationError("Structure Lens maximum_queue_entries must be between 1 and 1,000,000")
        if not 1 <= int(self.maximum_generated_states) <= 10_000_000:
            raise ValidationError("Structure Lens maximum_generated_states must be between 1 and 10,000,000")
        if not 1_024 <= int(self.maximum_memory_bytes) <= 8 * 1024 * 1024 * 1024:
            raise ValidationError("Structure Lens maximum_memory_bytes must be between 1 KiB and 8 GiB")
        if not 0.01 <= float(self.timeout_seconds) <= 60.0:
            raise ValidationError("Structure Lens timeout_seconds must be between 0.01 and 60")
        return self


@dataclass(slots=True)
class LensResult:
    operation: str
    status: str
    node_ids: list[str] = field(default_factory=list)
    edge_ids: list[str] = field(default_factory=list)
    paths: list[list[str]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    version: str = STRUCTURE_LENS_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class _BudgetGuard:
    def __init__(self, budget: AnalysisBudget, cancelled: Callable[[], bool] | None) -> None:
        self.budget = budget.validate()
        self.cancelled = cancelled
        self.started = time.perf_counter()
        self.visits = 0
        self.generated_states = 0
        self.queue_entries = 0
        self.peak_queue_entries = 0
        self.estimated_queue_bytes = 0
        self.peak_estimated_memory_bytes = 0
        self.reason: str | None = None

    def step(self) -> bool:
        self.visits += 1
        if self.cancelled and self.cancelled():
            self.reason = "cancelled"
            return False
        if self.visits > self.budget.maximum_visits:
            self.reason = "maximum_visits"
            return False
        if time.perf_counter() - self.started > self.budget.timeout_seconds:
            self.reason = "timeout"
            return False
        return True

    def enqueue(self, *, node_count: int = 1, edge_count: int = 0) -> int | None:
        """Reserve one bounded queue state and return its conservative byte cost."""

        if self.reason:
            return None
        self.generated_states += 1
        if self.generated_states > self.budget.maximum_generated_states:
            self.reason = "maximum_generated_states"
            return None
        if self.queue_entries + 1 > self.budget.maximum_queue_entries:
            self.reason = "maximum_queue_entries"
            return None
        # Python containers vary by build; this intentionally overestimates IDs,
        # list slots and tuple/deque bookkeeping without claiming exact RSS.
        state_bytes = 256 + max(0, int(node_count)) * 96 + max(0, int(edge_count)) * 96
        if self.estimated_queue_bytes + state_bytes > self.budget.maximum_memory_bytes:
            self.reason = "maximum_memory_bytes"
            return None
        self.queue_entries += 1
        self.peak_queue_entries = max(self.peak_queue_entries, self.queue_entries)
        self.estimated_queue_bytes += state_bytes
        self.peak_estimated_memory_bytes = max(self.peak_estimated_memory_bytes, self.estimated_queue_bytes)
        return state_bytes

    def dequeue(self, state_bytes: int) -> None:
        self.queue_entries = max(0, self.queue_entries - 1)
        self.estimated_queue_bytes = max(0, self.estimated_queue_bytes - int(state_bytes))

    def metadata(self) -> dict[str, Any]:
        return {
            "visits": self.visits,
            "maximum_visits": self.budget.maximum_visits,
            "maximum_depth": self.budget.maximum_depth,
            "maximum_paths": self.budget.maximum_paths,
            "maximum_queue_entries": self.budget.maximum_queue_entries,
            "maximum_generated_states": self.budget.maximum_generated_states,
            "maximum_memory_bytes": self.budget.maximum_memory_bytes,
            "timeout_seconds": self.budget.timeout_seconds,
            "generated_states": self.generated_states,
            "peak_queue_entries": self.peak_queue_entries,
            "peak_estimated_memory_bytes": self.peak_estimated_memory_bytes,
            "memory_measurement": "conservative queued-state estimate; not process RSS",
            "terminated_by": self.reason,
            "enumerated_all_simple_paths": False,
            "large_graph_recovery": "Return the bounded partial result; narrow the endpoints or use focus view.",
        }


class StructureLens:
    def __init__(self, graph: GraphIR, semantic_view: Any | None = None) -> None:
        self.graph = graph.validate()
        self.semantic_view = semantic_view
        if semantic_view is not None:
            semantic_view.validate(graph)
        self.nodes = graph.node_map()
        self.edges = graph.edge_map()
        self.outgoing: dict[str, list[Edge]] = defaultdict(list)
        self.incoming: dict[str, list[Edge]] = defaultdict(list)
        for edge in graph.edges:
            self.outgoing[edge.source].append(edge)
            self.incoming[edge.target].append(edge)
        for adjacency in (self.outgoing, self.incoming):
            for node_id in adjacency:
                adjacency[node_id].sort(key=lambda item: item.id)

    def _require_node(self, node_id: str) -> None:
        if node_id not in self.nodes:
            raise ValidationError(f"Structure Lens node {node_id!r} does not exist")

    def _evidence(self, node_ids: Iterable[str], edge_ids: Iterable[str] = ()) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []
        for node_id in sorted(set(node_ids)):
            node = self.nodes[node_id]
            evidence.append({
                "kind": "graph_ir_node", "id": node.id, "name": node.name,
                "op_type": node.op_type, "source": dict(node.source),
                "provenance_complete": bool(node.source or self.graph.metadata.get("source_format")),
            })
        for edge_id in sorted(set(edge_ids)):
            edge = self.edges[edge_id]
            evidence.append({
                "kind": "graph_ir_edge", "id": edge.id, "source": edge.source,
                "target": edge.target, "source_port": edge.source_port,
                "target_port": edge.target_port, "tensor": asdict(edge.tensor) if edge.tensor else None,
                "edge_kind": edge.kind,
            })
        return evidence

    @staticmethod
    def _bound_port_tensor(node: Node, port_id: str | None, direction: str) -> tuple[TensorSpec | None, str]:
        ports = node.outputs if direction == "output" else node.inputs
        if port_id:
            port = next((candidate for candidate in ports if candidate.id == port_id), None)
            if port is None:
                return None, "missing-port"
            if port.tensor is None:
                return None, "missing-tensor"
            return port.tensor, "explicit-port"
        candidates = [port for port in ports if port.tensor is not None]
        if len(candidates) == 1:
            return candidates[0].tensor, "single-port-inference"
        if not candidates:
            return None, "missing-tensor"
        return None, "ambiguous-port"

    def _edge_tensor_pair(self, edge: Edge) -> tuple[TensorSpec | None, TensorSpec | None, dict[str, Any]]:
        source = self.nodes[edge.source]
        target = self.nodes[edge.target]
        source_tensor, source_resolution = self._bound_port_tensor(source, edge.source_port, "output")
        target_tensor, target_resolution = self._bound_port_tensor(target, edge.target_port, "input")
        if edge.tensor is not None:
            source_tensor = edge.tensor
            source_resolution = "edge-tensor"
        return source_tensor, target_tensor, {
            "edge_id": edge.id,
            "source_port": edge.source_port,
            "target_port": edge.target_port,
            "source_resolution": source_resolution,
            "target_resolution": target_resolution,
        }

    def trace(
        self,
        node_id: str,
        *,
        direction: str,
        budget: AnalysisBudget | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> LensResult:
        self._require_node(node_id)
        if direction not in {"upstream", "downstream"}:
            raise ValidationError("Structure Lens direction must be upstream or downstream")
        guard = _BudgetGuard(budget or AnalysisBudget(), cancelled)
        initial_size = guard.enqueue()
        queue = deque([(node_id, 0, initial_size)]) if initial_size is not None else deque()
        visited = {node_id}
        edges: set[str] = set()
        while queue:
            current, depth, state_size = queue.popleft()
            guard.dequeue(state_size)
            if not guard.step():
                break
            if depth >= guard.budget.maximum_depth:
                guard.reason = guard.reason or "maximum_depth"
                continue
            candidates = self.incoming[current] if direction == "upstream" else self.outgoing[current]
            for edge in candidates:
                adjacent = edge.source if direction == "upstream" else edge.target
                edges.add(edge.id)
                if adjacent not in visited:
                    visited.add(adjacent)
                    next_state_size = guard.enqueue()
                    if next_state_size is None:
                        break
                    queue.append((adjacent, depth + 1, next_state_size))
            if guard.reason:
                break
        status = "partial" if guard.reason else "supported"
        return LensResult(
            f"{direction}-trace", status, sorted(visited), sorted(edges),
            evidence=self._evidence(visited, edges), metadata=guard.metadata(),
        )

    def bounded_paths(
        self,
        source_id: str,
        target_id: str,
        *,
        budget: AnalysisBudget | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> LensResult:
        self._require_node(source_id)
        self._require_node(target_id)
        guard = _BudgetGuard(budget or AnalysisBudget(), cancelled)
        initial_size = guard.enqueue(node_count=1)
        queue: deque[tuple[str, list[str], list[str], int]] = (
            deque([(source_id, [source_id], [], initial_size)]) if initial_size is not None else deque()
        )
        paths: list[list[str]] = []
        path_edges: list[list[str]] = []
        while queue and len(paths) < guard.budget.maximum_paths:
            current, path, edges, state_size = queue.popleft()
            guard.dequeue(state_size)
            if not guard.step():
                break
            if current == target_id:
                paths.append(path)
                path_edges.append(edges)
                continue
            if len(path) - 1 >= guard.budget.maximum_depth:
                guard.reason = guard.reason or "maximum_depth"
                continue
            for edge in self.outgoing[current]:
                if edge.target in path:
                    continue
                next_path = [*path, edge.target]
                next_edges = [*edges, edge.id]
                next_size = guard.enqueue(node_count=len(next_path), edge_count=len(next_edges))
                if next_size is None:
                    break
                queue.append((edge.target, next_path, next_edges, next_size))
            if guard.reason:
                break
        if queue and len(paths) >= guard.budget.maximum_paths:
            guard.reason = guard.reason or "maximum_paths"
        all_nodes = {item for path in paths for item in path}
        all_edges = {item for path in path_edges for item in path}
        if not paths and not guard.reason:
            status = "unsupported"
            warnings = [{"kind": "no-path", "message": "No directed Graph IR path connects the selected endpoints."}]
        else:
            status = "partial" if guard.reason else "supported"
            warnings = []
        metadata = guard.metadata()
        metadata["path_edge_ids"] = path_edges
        metadata["path_count"] = len(paths)
        return LensResult(
            "bounded-path-query", status, sorted(all_nodes), sorted(all_edges), paths,
            self._evidence(all_nodes, all_edges), warnings, metadata,
        )

    def pathway(self, kind: str) -> LensResult:
        aliases = {"skip": "residual", "moe": "moe-routing"}
        requested = aliases.get(kind.lower(), kind.lower())
        if requested not in {"residual", "attention", "moe-routing"}:
            return LensResult(
                "pathway-highlight", "unsupported",
                warnings=[{"kind": "unsupported-pattern", "message": f"No evidence rule is defined for {kind!r}."}],
                metadata={"requested": kind},
            )
        nodes: set[str] = set()
        edges: set[str] = set()
        reasons: list[str] = []
        semantic_matches: list[dict[str, Any]] = []
        semantic_types = {
            "residual": {"residual_block", "unet_skip"},
            "attention": {"attention"},
            "moe-routing": {"moe_router_experts"},
        }[requested]
        if self.semantic_view is not None:
            for detection in self.semantic_view.detections:
                if detection.get("semantic_type") not in semantic_types or detection.get("unknown"):
                    continue
                provenance = detection.get("provenance", {})
                source_nodes = [
                    str(item)
                    for item in provenance.get("source_node_ids", [])
                    if str(item) in self.nodes
                ]
                source_edges = [
                    str(item)
                    for item in provenance.get("source_edge_ids", [])
                    if str(item) in self.edges
                ]
                if not source_nodes:
                    continue
                nodes.update(source_nodes)
                edges.update(source_edges)
                reasons.extend(str(item) for item in detection.get("reasons", []))
                semantic_matches.append({
                    "semantic_id": detection.get("semantic_id"),
                    "semantic_type": detection.get("semantic_type"),
                    "confidence": float(detection.get("confidence", 0.0)),
                    "reasons": [str(item) for item in detection.get("reasons", [])],
                    "source_node_ids": source_nodes,
                    "source_edge_ids": source_edges,
                })
        if requested == "residual":
            for edge in self.graph.edges:
                structural = edge.kind.lower() in {"skip", "residual", "shortcut"} or any(
                    key.lower() in {"skip", "residual", "shortcut"} and bool(value)
                    for key, value in edge.attributes.items()
                )
                if structural:
                    edges.add(edge.id)
                    nodes.update((edge.source, edge.target))
            for node in self.graph.nodes:
                canonical_op = node.op_type.lower().replace("_", "").replace("-", "")
                if canonical_op in {"add", "addition", "sum"} and len(self.incoming[node.id]) >= 2:
                    nodes.add(node.id)
                    edges.update(edge.id for edge in self.incoming[node.id])
            if nodes:
                reasons.append("Explicit skip/residual edge metadata or a multi-input addition provides structural evidence.")
        elif requested == "attention":
            for node in self.graph.nodes:
                canonical_op = node.op_type.lower().replace("_", "").replace("-", "")
                explicit_attribute = str(node.attributes.get("operator_family", "")).lower() == "attention"
                if canonical_op in {"attention", "multiheadattention", "scaled dot product attention".replace(" ", "")} or explicit_attribute:
                    nodes.add(node.id)
                    edges.update(edge.id for edge in [*self.incoming[node.id], *self.outgoing[node.id]])
            if nodes:
                reasons.append("Canonical operator type or explicit operator_family metadata identifies attention.")
        else:
            routing_edges = [
                edge for edge in self.graph.edges
                if edge.kind.lower() in {"routing", "dispatch", "combine"}
                or str(edge.attributes.get("operator_family", "")).lower() in {"routing", "moe"}
            ]
            for edge in routing_edges:
                edges.add(edge.id)
                nodes.update((edge.source, edge.target))
            if nodes:
                reasons.append("Explicit routing/dispatch/combine edge metadata identifies the MoE pathway.")
        if not nodes:
            keyword_matches = [
                node.id
                for node in self.graph.nodes
                if any(
                    marker in f"{node.name} {node.op_type} {node.path} {node.namespace}".lower()
                    for marker in {
                        "residual": ("residual", "skip", "shortcut"),
                        "attention": ("attention", "self-attn", "cross-attn"),
                        "moe-routing": ("router", "expert", "moe"),
                    }[requested]
                )
            ]
            reason = (
                f"Only name keywords matched {len(keyword_matches)} node(s); no Semantic View, "
                "canonical operator, port-bound topology, or explicit edge evidence proved the pathway."
                if keyword_matches
                else f"No Semantic View or Graph IR structural evidence proved a {requested} pathway."
            )
            return LensResult(
                "pathway-highlight", "unknown",
                warnings=[{
                    "kind": "insufficient-evidence",
                    "message": reason,
                    "confidence": 0.0,
                    "reason": reason,
                    "positive_claim": False,
                    "candidate_node_ids": keyword_matches,
                }],
                metadata={
                    "requested": requested,
                    "positive_claim": False,
                    "keyword_matches_are_evidence": False,
                    "confidence": 0.0,
                    "reason": reason,
                    "keyword_candidate_node_ids": keyword_matches,
                    "semantic_view_consulted": self.semantic_view is not None,
                },
            )
        confidence = max(
            [item["confidence"] for item in semantic_matches]
            or [0.9 if requested == "attention" else 0.85],
        )
        return LensResult(
            "pathway-highlight", "supported", sorted(nodes), sorted(edges),
            evidence=self._evidence(nodes, edges), metadata={
                "requested": requested,
                "positive_claim": True,
                "keyword_matches_are_evidence": False,
                "confidence": confidence,
                "reason": reasons[0] if reasons else "Graph IR topology supplies positive pathway evidence.",
                "structural_reasons": list(dict.fromkeys(reasons)),
                "semantic_view_consulted": self.semantic_view is not None,
                "semantic_evidence_prioritized": bool(semantic_matches),
                "semantic_detection_evidence": semantic_matches,
            },
        )

    @staticmethod
    def _first_tensor(node: Node, direction: str) -> TensorSpec | None:
        ports = node.outputs if direction == "output" else node.inputs
        return next((port.tensor for port in ports if port.tensor), None)

    def shape_timeline(self, path: Iterable[str]) -> LensResult:
        node_ids = list(path)
        for node_id in node_ids:
            self._require_node(node_id)
        transitions: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        edge_ids: list[str] = []
        for first_id, second_id in zip(node_ids, node_ids[1:]):
            candidates = [edge for edge in self.outgoing[first_id] if edge.target == second_id]
            binding: dict[str, Any]
            if len(candidates) == 1:
                edge = candidates[0]
                edge_ids.append(edge.id)
                source_tensor, target_tensor, binding = self._edge_tensor_pair(edge)
            else:
                source_tensor = target_tensor = None
                binding = {
                    "source_node": first_id,
                    "target_node": second_id,
                    "resolution": "no-edge" if not candidates else "ambiguous-parallel-edges",
                    "candidate_edge_ids": [edge.id for edge in candidates],
                }
            if source_tensor is None or target_tensor is None:
                item = {
                    "source_node": first_id, "target_node": second_id, "status": "unknown",
                    "source": shape_label(source_tensor.shape) if source_tensor else "?",
                    "target": shape_label(target_tensor.shape) if target_tensor else "?",
                    "proven": False, "binding": binding,
                }
            else:
                item = shape_transition(source_tensor.shape, target_tensor.shape)
                item.update({"source_node": first_id, "target_node": second_id, "binding": binding})
            transitions.append(item)
            if item["status"] == "unknown":
                warnings.append({
                    "kind": "unknown-shape-transition", "source_node": first_id, "target_node": second_id,
                    "message": "Dynamic, symbolic, unknown, or absent dimensions prevent a positive shape conclusion.",
                })
        status = "unknown" if transitions and all(item["status"] == "unknown" for item in transitions) else "supported"
        return LensResult(
            "shape-transition-timeline", status, node_ids, edge_ids,
            evidence=self._evidence(node_ids, edge_ids), warnings=warnings,
            metadata={"transitions": transitions, "positive_claims_only_when_proven": True},
        )

    def warnings(self) -> LensResult:
        warnings: list[dict[str, Any]] = []
        affected: set[str] = set()
        for node in self.graph.nodes:
            if not node.source and not self.graph.metadata.get("source_format"):
                affected.add(node.id)
                warnings.append({
                    "kind": "incomplete-provenance", "node_id": node.id,
                    "message": "This node has no source locator; its identity is retained but not attributed.",
                })
        for edge in self.graph.edges:
            source, target = self.nodes[edge.source], self.nodes[edge.target]
            source_tensor, target_tensor, binding = self._edge_tensor_pair(edge)
            if source_tensor is None or target_tensor is None:
                if binding["source_resolution"] == "ambiguous-port" or binding["target_resolution"] == "ambiguous-port":
                    affected.update((source.id, target.id))
                    warnings.append({
                        "kind": "ambiguous-port-binding", "edge_id": edge.id,
                        "source_port": edge.source_port, "target_port": edge.target_port,
                        "message": "The edge does not identify a unique tensor port; no shape compatibility claim was made.",
                        "certainty": "unknown", "positive_claim": False,
                    })
                continue
            left, right = source_tensor.shape, target_tensor.shape
            if len(left) != len(right):
                affected.update((source.id, target.id))
                warnings.append({
                    "kind": "potential-shape-mismatch", "edge_id": edge.id,
                    "source": shape_label(left), "target": shape_label(right),
                    "source_port": edge.source_port, "target_port": edge.target_port,
                    "message": "Connected tensors have different ranks.", "certainty": "potential",
                })
                continue
            comparable = all(isinstance(a, int) and isinstance(b, int) for a, b in zip(left, right))
            if comparable and list(left) != list(right):
                affected.update((source.id, target.id))
                warnings.append({
                    "kind": "potential-shape-mismatch", "edge_id": edge.id,
                    "source": shape_label(left), "target": shape_label(right),
                    "source_port": edge.source_port, "target_port": edge.target_port,
                    "message": "Connected known tensor dimensions differ; an unrecorded transform may explain this.",
                    "certainty": "potential",
                })
        return LensResult(
            "structure-warnings", "supported" if warnings else "unknown", sorted(affected),
            evidence=self._evidence(affected), warnings=warnings,
            metadata={"warning_count": len(warnings), "warnings_are_not_proof_of_failure": True},
        )

    def metric_overlay(self, metric: str) -> LensResult:
        aliases = {"activation-memory": "activation_bytes", "params": "parameters"}
        key = aliases.get(metric, metric)
        if key not in {"parameters", "flops", "activation_bytes"}:
            return LensResult(
                "metric-overlay", "unsupported",
                warnings=[{"kind": "unsupported-metric", "message": f"Metric {metric!r} is unsupported."}],
            )
        values: dict[str, int | float | None] = {}
        unknown: list[str] = []
        for node in self.graph.nodes:
            if key == "parameters":
                value: int | float | None = node.parameters
            elif key == "activation_bytes":
                value = node.analysis.get(key)
                if value is None:
                    sizes = [port.tensor.infer_size_bytes() for port in node.outputs if port.tensor]
                    value = sum(item for item in sizes if item is not None) if sizes and all(item is not None for item in sizes) else None
            else:
                value = node.analysis.get(key)
            values[node.id] = value
            if value is None:
                unknown.append(node.id)
        known = [float(value) for value in values.values() if value is not None]
        maximum = max(known, default=0.0)
        normalized = {node_id: (float(value) / maximum if value is not None and maximum else 0.0) for node_id, value in values.items()}
        status = "unknown" if not known else ("partial" if unknown else "supported")
        return LensResult(
            "metric-overlay", status, sorted(values), evidence=self._evidence(values),
            warnings=([{
                "kind": "incomplete-metric", "node_ids": unknown,
                "message": "Unknown metric values remain uncoloured and are not treated as zero.",
            }] if unknown else []),
            metadata={"metric": key, "values": values, "normalized": normalized, "maximum": maximum},
        )

    def repeated_structures(self) -> LensResult:
        buckets: dict[tuple[Any, ...], list[str]] = defaultdict(list)
        for node in self.graph.nodes:
            input_shapes = tuple(shape_label(port.tensor.shape) for port in node.inputs if port.tensor)
            output_shapes = tuple(shape_label(port.tensor.shape) for port in node.outputs if port.tensor)
            signature = (node.op_type, node.category, input_shapes, output_shapes, tuple(sorted(node.tags)))
            buckets[signature].append(node.id)
        groups: list[dict[str, Any]] = [
            {"count": len(ids), "label": f"×{len(ids)}", "source_node_ids": ids,
             "signature": {"op_type": signature[0], "category": signature[1], "input_shapes": signature[2], "output_shapes": signature[3]}}
            for signature, ids in sorted(buckets.items(), key=lambda item: repr(item[0])) if len(ids) > 1
        ]
        nodes = {node_id for group in groups for node_id in group["source_node_ids"]}
        return LensResult(
            "repeated-structure-detection", "supported" if groups else "unknown", sorted(nodes),
            evidence=self._evidence(nodes),
            warnings=[] if groups else [{"kind": "no-proven-repeat", "message": "No exact evidence signature repeats were found."}],
            metadata={"groups": groups, "aggregation_is_visual_only": True},
        )

    def explain_unknown(self, node_id: str) -> LensResult:
        self._require_node(node_id)
        node = self.nodes[node_id]
        reasons: list[str] = []
        if not node.source:
            reasons.append("no source locator")
        if not node.op_type or node.op_type.lower() in {"unknown", "callfunction", "operation"}:
            reasons.append("operator type is generic or unknown")
        if not node.inputs and not node.outputs:
            reasons.append("no tensor ports")
        if any(port.tensor and any(dim is None or isinstance(dim, str) for dim in port.tensor.shape) for port in [*node.inputs, *node.outputs]):
            reasons.append("dynamic, symbolic, or unknown tensor dimensions")
        if not reasons:
            return LensResult(
                "unknown-explanation", "unsupported", [node_id], evidence=self._evidence([node_id]),
                warnings=[{"kind": "not-unknown", "message": "The selected node has no recorded evidence deficit."}],
            )
        return LensResult(
            "unknown-explanation", "unknown", [node_id], evidence=self._evidence([node_id]),
            warnings=[{
                "kind": "insufficient-evidence", "node_id": node_id,
                "message": "; ".join(reasons) + ". No positive semantic conclusion was generated.",
            }], metadata={"reasons": reasons, "positive_claim": False},
        )


__all__ = ["AnalysisBudget", "LensResult", "STRUCTURE_LENS_VERSION", "StructureLens"]
