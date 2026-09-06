"""Deterministic generalization corpus for Architecture Evidence.

The corpus is intentionally offline.  It separates lexical/reordering
metamorphisms of the seven executable real-model imports from small typed-IR
depth/width variants whose only signals are topology, operations and shapes.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import random
from typing import Any, Iterable

from .architecture_evidence import ArchitectureEvidence
from .ir import Edge, GraphIR, Node, Port, TensorSpec, stable_id
from .real_models import import_real_model
from .semantic import derive_semantic_view


METAMORPHIC_CORPUS_VERSION = "1.0"
REAL_MODEL_KEYS = (
    "resnet50",
    "vision_transformer",
    "bert_encoder",
    "multiscale_unet",
    "diffusion_unet",
    "topk_moe",
    "image_text",
)


def evidence_signature(evidence: ArchitectureEvidence) -> dict[str, Any]:
    """Return the family/role/repetition/route contract unaffected by IDs."""

    return {
        "family": evidence.family,
        "roles": sorted((role.role, role.repeat_count) for role in evidence.detected_roles),
        "repetitions": sorted((item.count, next(role.role for role in evidence.detected_roles if role.id == item.role_id)) for item in evidence.repeated_structure),
        "routes": sorted(route.role for route in evidence.critical_routes),
    }


def _token(rng: random.Random, prefix: str) -> str:
    return f"{prefix}_{rng.getrandbits(64):016x}"


def metamorphic_graph(graph: GraphIR, *, seed: int) -> GraphIR:
    """Rename/re-ID/reorder a graph while preserving typed structure."""

    transformed = deepcopy(graph)
    rng = random.Random(seed)
    node_ids = {node.id: _token(rng, "node") for node in transformed.nodes}
    group_ids = {group.id: _token(rng, "group") for group in transformed.subgraphs}
    edge_ids = {edge.id: _token(rng, "edge") for edge in transformed.edges}
    port_ids = {
        port.id: _token(rng, "port")
        for node in transformed.nodes
        for port in (*node.inputs, *node.outputs)
    }
    target_ids = {**node_ids, **group_ids, **edge_ids}

    transformed.name = _token(rng, "graph")
    graph_view = transformed.metadata.get("graph_view")
    transformed.metadata = {
        "graph_view": graph_view,
        _token(rng, "sample_key"): _token(rng, "sample_value"),
        "metamorphic_seed": seed,
    }
    transformed.analysis = {
        "prelayout": {
            "camera": [rng.uniform(-9000.0, 9000.0) for _ in range(3)],
            "scale": rng.uniform(0.01, 100.0),
        }
    }
    for node in transformed.nodes:
        old_id = node.id
        path_depth = max(1, len([part for part in node.path.split(".") if part]))
        namespace_depth = max(1, len([part for part in node.namespace.split(".") if part]))
        node.id = node_ids[old_id]
        node.name = _token(rng, "display")
        node.path = ".".join(_token(rng, "path") for _ in range(path_depth))
        node.namespace = ".".join(_token(rng, "namespace") for _ in range(namespace_depth))
        if node.parent:
            node.parent = target_ids.get(node.parent, node.parent)
        for port in (*node.inputs, *node.outputs):
            port.id = port_ids[port.id]
            port.name = _token(rng, "port_name")
        node.source = {"kind": "metamorphic", "ordinal": rng.randrange(1_000_000)}
        node.analysis = {
            "x": rng.uniform(-10000.0, 10000.0),
            "y": rng.uniform(-10000.0, 10000.0),
            "z": rng.uniform(-10000.0, 10000.0),
        }
    for edge in transformed.edges:
        old_id = edge.id
        edge.id = edge_ids[old_id]
        edge.source = node_ids[edge.source]
        edge.target = node_ids[edge.target]
        if edge.source_port:
            edge.source_port = port_ids[edge.source_port]
        if edge.target_port:
            edge.target_port = port_ids[edge.target_port]
        edge.label = _token(rng, "edge_label")
    for group in transformed.subgraphs:
        old_id = group.id
        group.id = group_ids[old_id]
        group.name = _token(rng, "group_name")
        group.node_ids = [node_ids[node_id] for node_id in group.node_ids]
        if group.parent:
            group.parent = group_ids[group.parent]
    for annotation in transformed.annotations:
        annotation.id = _token(rng, "annotation")
        annotation.text = _token(rng, "annotation_text")
        annotation.target_ids = [target_ids.get(target_id, target_id) for target_id in annotation.target_ids]
    for constraint in transformed.constraints:
        constraint.target_ids = [target_ids.get(target_id, target_id) for target_id in constraint.target_ids]

    rng.shuffle(transformed.nodes)
    rng.shuffle(transformed.edges)
    rng.shuffle(transformed.subgraphs)
    rng.shuffle(transformed.inputs)
    rng.shuffle(transformed.outputs)
    return transformed.validate()


def _negative_graph(key: str, graph: GraphIR, evidence: ArchitectureEvidence) -> tuple[GraphIR, list[str]]:
    mutated = deepcopy(graph)
    remove_ids: list[str] = []
    if key == "resnet50":
        remove_ids = evidence.critical_routes[0].supporting_edge_ids[:1]
    elif key in {"vision_transformer", "bert_encoder"}:
        attention_role = next(role for role in evidence.detected_roles if role.role == "attention")
        victim = attention_role.supporting_node_ids[0]
        remove_ids = [edge.id for edge in mutated.edges if edge.source == victim or edge.target == victim]
    elif key == "multiscale_unet":
        remove_ids = [route.supporting_edge_ids[0] for route in evidence.critical_routes[:2]]
    elif key == "diffusion_unet":
        conditioning = next(route for route in evidence.critical_routes if route.role == "conditioning")
        remove_ids = conditioning.supporting_edge_ids[:2]
    elif key == "topk_moe":
        router = next(role for role in evidence.detected_roles if role.role == "router")
        topk_ids = {node.id for node in mutated.nodes if node.id in router.supporting_node_ids and "topk" in node.op_type.casefold()}
        remove_ids = [edge.id for edge in mutated.edges if edge.target in topk_ids]
    elif key == "image_text":
        remove_ids = evidence.critical_routes[0].supporting_edge_ids[:1]
    mutated.edges = [edge for edge in mutated.edges if edge.id not in set(remove_ids)]
    return mutated.validate(), remove_ids


class _Builder:
    def __init__(self, name: str, inputs: list[TensorSpec]) -> None:
        self.graph = GraphIR(name=name, inputs=deepcopy(inputs))

    def node(self, op_type: str, shape: Iterable[int], *, category: str = "operation") -> str:
        index = len(self.graph.nodes)
        node_id = stable_id("variant_node", f"{self.graph.name}:{index}:{op_type}")
        tensor = TensorSpec(shape=list(shape), dtype="int64" if category == "input" and len(list(shape)) == 2 else "float32")
        self.graph.nodes.append(Node(
            id=node_id,
            name=f"v{index}",
            op_type=op_type,
            category=category,
            outputs=[Port(f"{node_id}:out", "out", "output", tensor)],
        ))
        return node_id

    def edge(self, source: str, target: str, shape: Iterable[int]) -> str:
        edge = Edge.create(source, target, tensor=TensorSpec(shape=list(shape), dtype="float32"))
        self.graph.edges.append(edge)
        return edge.id

    def output(self, source: str, shape: Iterable[int]) -> None:
        output = self.node("Output", shape, category="output")
        self.edge(source, output, shape)
        self.graph.outputs = [TensorSpec(shape=list(shape), dtype="float32")]


def _resnet_variant(repeats: list[int]) -> GraphIR:
    builder = _Builder(f"typed-residual-{repeats}", [TensorSpec(shape=[1, 3, 64, 64], dtype="float32")])
    current = builder.node("Input", [1, 3, 64, 64], category="input")
    current = builder.node("Conv2d", [1, 64, 32, 32], category="convolution")
    builder.edge(builder.graph.nodes[0].id, current, [1, 64, 32, 32])
    for stage, repeat in enumerate(repeats):
        shape = [1, 64 * (2 ** (stage + 2)), 16 // (2**stage), 16 // (2**stage)]
        for _block in range(repeat):
            branch = builder.node("Conv2d", shape, category="convolution")
            builder.edge(current, branch, shape)
            merge = builder.node("add", shape, category="merge")
            builder.edge(current, merge, shape)
            builder.edge(branch, merge, shape)
            current = merge
    builder.output(current, [1, 1000])
    return builder.graph.validate()


def _transformer_variant(depth: int, width: int) -> GraphIR:
    builder = _Builder(f"typed-transformer-{depth}-{width}", [TensorSpec(shape=[1, 16], dtype="int64")])
    input_node = builder.node("Input", [1, 16], category="input")
    current = builder.node("Embedding", [1, 16, width], category="embedding")
    builder.edge(input_node, current, [1, 16, width])
    for _index in range(depth):
        attention = builder.node("MultiheadAttention", [1, 16, width], category="attention")
        builder.edge(current, attention, [1, 16, width])
        merge1 = builder.node("add", [1, 16, width], category="merge")
        builder.edge(current, merge1, [1, 16, width])
        builder.edge(attention, merge1, [1, 16, width])
        norm = builder.node("LayerNorm", [1, 16, width], category="normalization")
        builder.edge(merge1, norm, [1, 16, width])
        linear1 = builder.node("Linear", [1, 16, width * 4], category="linear")
        builder.edge(norm, linear1, [1, 16, width * 4])
        linear2 = builder.node("Linear", [1, 16, width], category="linear")
        builder.edge(linear1, linear2, [1, 16, width])
        merge2 = builder.node("add", [1, 16, width], category="merge")
        builder.edge(norm, merge2, [1, 16, width])
        builder.edge(linear2, merge2, [1, 16, width])
        current = merge2
    builder.output(current, [1, width])
    return builder.graph.validate()


def _unet_variant(levels: int, width: int) -> GraphIR:
    builder = _Builder(f"typed-unet-{levels}-{width}", [TensorSpec(shape=[1, 3, 64, 64], dtype="float32")])
    current = builder.node("Input", [1, 3, 64, 64], category="input")
    skips: list[tuple[str, list[int]]] = []
    for level in range(levels):
        shape = [1, width * (2**level), 64 // (2**level), 64 // (2**level)]
        encoded = builder.node("Conv2d", shape, category="convolution")
        builder.edge(current, encoded, shape)
        skips.append((encoded, shape))
        pooled_shape = [shape[0], shape[1], shape[2] // 2, shape[3] // 2]
        pooled = builder.node("MaxPool2d", pooled_shape, category="pooling")
        builder.edge(encoded, pooled, pooled_shape)
        current = pooled
    center_shape = [1, width * (2**levels), 64 // (2**levels), 64 // (2**levels)]
    center = builder.node("Conv2d", center_shape, category="convolution")
    builder.edge(current, center, center_shape)
    current = center
    for skip, shape in reversed(skips):
        upsample = builder.node("interpolate", shape, category="operation")
        builder.edge(current, upsample, shape)
        cat_shape = [1, shape[1] * 2, shape[2], shape[3]]
        cat = builder.node("cat", cat_shape, category="operation")
        builder.edge(skip, cat, shape)
        builder.edge(upsample, cat, shape)
        decoded = builder.node("Conv2d", shape, category="convolution")
        builder.edge(cat, decoded, shape)
        current = decoded
    builder.output(current, [1, 4, 64, 64])
    return builder.graph.validate()


def _moe_variant(experts: int, top_k: int, width: int) -> GraphIR:
    builder = _Builder(f"typed-moe-{experts}-{top_k}-{width}", [TensorSpec(shape=[1, 12], dtype="int64")])
    input_node = builder.node("Input", [1, 12], category="input")
    embedding = builder.node("Embedding", [1, 12, width], category="embedding")
    builder.edge(input_node, embedding, [1, 12, width])
    logits = builder.node("Linear", [1, 12, experts], category="linear")
    builder.edge(embedding, logits, [1, 12, experts])
    probabilities = builder.node("softmax", [1, 12, experts], category="activation")
    builder.edge(logits, probabilities, [1, 12, experts])
    topk = builder.node("topk", [1, 12, top_k], category="operation")
    builder.edge(probabilities, topk, [1, 12, top_k])
    terminals: list[str] = []
    for _index in range(experts):
        hidden = builder.node("Linear", [1, 12, width * 2], category="linear")
        builder.edge(embedding, hidden, [1, 12, width * 2])
        terminal = builder.node("Linear", [1, 12, width], category="linear")
        builder.edge(hidden, terminal, [1, 12, width])
        terminals.append(terminal)
    stack = builder.node("stack", [1, 12, experts, width], category="operation")
    for terminal in terminals:
        builder.edge(terminal, stack, [1, 12, width])
    multiply = builder.node("mul", [1, 12, experts, width], category="merge")
    builder.edge(stack, multiply, [1, 12, experts, width])
    builder.edge(topk, multiply, [1, 12, top_k])
    reduction = builder.node("sum", [1, 12, width], category="operation")
    builder.edge(multiply, reduction, [1, 12, width])
    builder.output(reduction, [1, 12, width])
    return builder.graph.validate()


def _fusion_variant(*, swapped: bool, width: int) -> GraphIR:
    inputs = [TensorSpec(shape=[1, 3, 64, 64], dtype="float32"), TensorSpec(shape=[1, 12], dtype="int64")]
    if swapped:
        inputs.reverse()
    builder = _Builder(f"typed-fusion-{swapped}-{width}", inputs)
    image_input = builder.node("Input", [1, 3, 64, 64], category="input")
    text_input = builder.node("Input", [1, 12], category="input")
    image = builder.node("Conv2d", [1, width, 16, 16], category="convolution")
    builder.edge(image_input, image, [1, width, 16, 16])
    image_vector = builder.node("AdaptiveAvgPool2d", [1, width], category="pooling")
    builder.edge(image, image_vector, [1, width])
    text = builder.node("Embedding", [1, 12, width], category="embedding")
    builder.edge(text_input, text, [1, 12, width])
    attention = builder.node("MultiheadAttention", [1, 12, width], category="attention")
    builder.edge(text, attention, [1, 12, width])
    text_vector = builder.node("mean", [1, width], category="operation")
    builder.edge(attention, text_vector, [1, width])
    fusion = builder.node("cat", [1, width * 2], category="operation")
    builder.edge(image_vector, fusion, [1, width])
    builder.edge(text_vector, fusion, [1, width])
    head = builder.node("Linear", [1, 8], category="linear")
    builder.edge(fusion, head, [1, 8])
    builder.output(head, [1, 8])
    if swapped:
        builder.graph.nodes[0], builder.graph.nodes[1] = builder.graph.nodes[1], builder.graph.nodes[0]
    return builder.graph.validate()


def architecture_variants() -> dict[str, GraphIR]:
    return {
        "resnet_repeat_2_2_2_2": _resnet_variant([2, 2, 2, 2]),
        "resnet_repeat_3_3_3_3": _resnet_variant([3, 3, 3, 3]),
        "transformer_depth_2_width_64": _transformer_variant(2, 64),
        "transformer_depth_5_width_128": _transformer_variant(5, 128),
        "unet_levels_2_width_12": _unet_variant(2, 12),
        "unet_levels_4_width_20": _unet_variant(4, 20),
        "moe_experts_3_top1_width48": _moe_variant(3, 1, 48),
        "moe_experts_6_top2_width80": _moe_variant(6, 2, 80),
        "fusion_image_first_width48": _fusion_variant(swapped=False, width=48),
        "fusion_text_first_width96": _fusion_variant(swapped=True, width=96),
    }


def run_generalization_corpus(*, seed: int = 7300) -> dict[str, Any]:
    cases: dict[str, Any] = {}
    failures: list[str] = []
    for index, key in enumerate(REAL_MODEL_KEYS):
        graph = import_real_model(key, view="module")
        original = derive_semantic_view(graph).architecture_evidence
        transformed_graph = metamorphic_graph(graph, seed=seed + index)
        transformed = derive_semantic_view(transformed_graph).architecture_evidence
        original_ids = set(graph.node_map()) | set(graph.edge_map())
        rebound_ids = set(transformed.supporting_node_ids) | set(transformed.supporting_edge_ids)
        signature_equal = evidence_signature(original) == evidence_signature(transformed)
        provenance_rebound = bool(rebound_ids) and not rebound_ids.intersection(original_ids)
        negative_graph, removed_edges = _negative_graph(key, graph, original)
        negative = derive_semantic_view(negative_graph).architecture_evidence
        negative_degraded = (
            negative.family != original.family
            or negative.confidence < original.confidence
            or evidence_signature(negative) != evidence_signature(original)
        )
        if not signature_equal:
            failures.append(f"{key}: rename/reorder signature changed")
        if not provenance_rebound:
            failures.append(f"{key}: provenance did not bind exclusively to transformed IDs")
        if not negative_degraded:
            failures.append(f"{key}: deleted structural evidence did not degrade the claim")
        cases[key] = {
            "seed": seed + index,
            "original": evidence_signature(original),
            "transformed": evidence_signature(transformed),
            "signature_equal": signature_equal,
            "provenance_rebound": provenance_rebound,
            "negative_mutation": {
                "removed_edge_count": len(removed_edges),
                "removed_edge_ids": removed_edges,
                "result_family": negative.family,
                "result_confidence": negative.confidence,
                "result_signature": evidence_signature(negative),
                "degraded": negative_degraded,
            },
        }

    variants: dict[str, Any] = {}
    expected_families = {
        "resnet_": "resnet",
        "transformer_": "transformer",
        "unet_": "unet",
        "moe_": "moe",
        "fusion_": "multimodal-fusion",
    }
    for name, graph in architecture_variants().items():
        evidence = derive_semantic_view(graph).architecture_evidence
        expected = next(family for prefix, family in expected_families.items() if name.startswith(prefix))
        if evidence.family != expected:
            failures.append(f"{name}: expected {expected}, got {evidence.family}")
        variants[name] = {
            "expected_family": expected,
            "evidence": evidence_signature(evidence),
            "role_attributes": {role.role: role.attributes for role in evidence.detected_roles},
        }

    payload: dict[str, Any] = {
        "schema_version": "nndv-0.7.3-generalization-corpus-1",
        "corpus_version": METAMORPHIC_CORPUS_VERSION,
        "seed": seed,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "real_model_metamorphisms": cases,
        "architecture_variants": variants,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["report_digest"] = sha256(canonical).hexdigest()
    return payload


__all__ = [
    "METAMORPHIC_CORPUS_VERSION",
    "REAL_MODEL_KEYS",
    "architecture_variants",
    "evidence_signature",
    "metamorphic_graph",
    "run_generalization_corpus",
]
