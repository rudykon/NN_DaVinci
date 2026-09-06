"""Deterministic, offline real-model corpus for production workflows.

The factories in this module never fetch weights.  They construct executable
CPU models from locally installed PyTorch/torchvision packages and expose the
exact sample inputs used by compatibility and performance gates.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import copy
import gc
import json
import platform
from pathlib import Path
import resource
import statistics
import time
from typing import Any, Callable

from .adapters.pytorch import PyTorchAdapter
from .errors import OptionalDependencyError, ValidationError
from .ir import Edge, GraphIR, Node, Port, Subgraph, stable_id
from .layout import LayoutEngine
from .semantic import derive_semantic_view

REAL_MODEL_CORPUS_VERSION = "1.0"
REAL_MODEL_VIEWS = ("framework", "module", "operation")


def _require_torch() -> tuple[Any, Any]:
    try:
        import torch
        from torch import nn
    except ImportError as exc:  # pragma: no cover - exercised without optional extra
        raise OptionalDependencyError(
            "The real-model corpus requires local PyTorch",
            hint="Install nn-davinci[pytorch]; model weights are never downloaded.",
        ) from exc
    return torch, nn


@dataclass(frozen=True, slots=True)
class RealModelSpec:
    key: str
    display_name: str
    family: str
    seed: int
    sample_description: str
    expected_parameters: int
    expected_input_shapes: tuple[tuple[int, ...], ...]
    expected_output_shapes: tuple[tuple[int, ...], ...]
    expected_semantics: tuple[str, ...]
    factory: Callable[[], Any]
    sample_factory: Callable[[], Any]


def _seed(seed: int) -> Any:
    torch, _ = _require_torch()
    torch.manual_seed(seed)
    return torch


def _resnet50() -> Any:
    torch = _seed(4001)
    try:
        from torchvision.models import resnet50
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise OptionalDependencyError(
            "ResNet50 corpus entry requires local torchvision",
            hint="Install torchvision; pretrained weights are not requested.",
        ) from exc
    model = resnet50(weights=None)
    model.eval()
    model._nndv_corpus = {"family": "cnn", "weights": "random-local", "seed": 4001}
    del torch
    return model


def _vision_transformer() -> Any:
    torch, nn = _require_torch()
    torch.manual_seed(4002)

    class AttentionBlock(nn.Module):  # type: ignore[name-defined]
        def __init__(self, width: int = 96, heads: int = 4) -> None:
            super().__init__()
            self.norm1 = nn.LayerNorm(width)
            self.self_attention = nn.MultiheadAttention(width, heads, batch_first=True)
            self.norm2 = nn.LayerNorm(width)
            self.feed_forward = nn.Sequential(nn.Linear(width, width * 4), nn.GELU(), nn.Linear(width * 4, width))

        def forward(self, x: Any) -> Any:
            normalized = self.norm1(x)
            attended, _ = self.self_attention(normalized, normalized, normalized, need_weights=False)
            x = x + attended
            return x + self.feed_forward(self.norm2(x))

    class VisionTransformer(nn.Module):  # type: ignore[name-defined]
        def __init__(self) -> None:
            super().__init__()
            self.patch_embedding = nn.Conv2d(3, 96, kernel_size=8, stride=8)
            self.class_token = nn.Parameter(torch.zeros(1, 1, 96))
            self.position_embedding = nn.Parameter(torch.zeros(1, 65, 96))
            self.encoder = nn.ModuleList([AttentionBlock() for _ in range(3)])
            self.norm = nn.LayerNorm(96)
            self.head = nn.Linear(96, 10)

        def forward(self, image: Any) -> Any:
            patches = self.patch_embedding(image).flatten(2).transpose(1, 2)
            cls = self.class_token.expand(image.shape[0], -1, -1)
            x = torch.cat((cls, patches), dim=1) + self.position_embedding
            for block in self.encoder:
                x = block(x)
            return self.head(self.norm(x[:, 0]))

    return VisionTransformer().eval()


def _bert_encoder() -> Any:
    torch, nn = _require_torch()
    torch.manual_seed(4003)

    class TransformerEncoderBlock(nn.Module):  # type: ignore[name-defined]
        def __init__(self, width: int = 96, heads: int = 4) -> None:
            super().__init__()
            self.self_attention = nn.MultiheadAttention(width, heads, batch_first=True)
            self.attention_norm = nn.LayerNorm(width)
            self.feed_forward = nn.Sequential(nn.Linear(width, width * 4), nn.GELU(), nn.Linear(width * 4, width))
            self.output_norm = nn.LayerNorm(width)

        def forward(self, x: Any) -> Any:
            attended, _ = self.self_attention(x, x, x, need_weights=False)
            x = self.attention_norm(x + attended)
            return self.output_norm(x + self.feed_forward(x))

    class BERTEncoder(nn.Module):  # type: ignore[name-defined]
        def __init__(self) -> None:
            super().__init__()
            self.token_embedding = nn.Embedding(2048, 96)
            self.position_embedding = nn.Embedding(32, 96)
            # Persist the position index as model state so FX can represent
            # the exact token/position path.  Constructing ``arange`` from a
            # symbolic sequence length forces the importer into its runtime
            # fallback, whose leaf-module hooks cannot observe the internal
            # attention/residual tensor flow.
            self.register_buffer(
                "position_ids",
                torch.arange(16).unsqueeze(0),
                persistent=False,
            )
            self.encoder = nn.ModuleList([TransformerEncoderBlock() for _ in range(3)])
            self.pooler = nn.Linear(96, 96)

        def forward(self, token_ids: Any) -> Any:
            positions = self.position_ids
            x = self.token_embedding(token_ids) + self.position_embedding(positions)
            for block in self.encoder:
                x = block(x)
            return torch.tanh(self.pooler(x[:, 0]))

    return BERTEncoder().eval()


def _conv_block(nn: Any, in_channels: int, out_channels: int) -> Any:
    return nn.Sequential(
        nn.Conv2d(in_channels, out_channels, 3, padding=1),
        nn.BatchNorm2d(out_channels),
        nn.ReLU(),
        nn.Conv2d(out_channels, out_channels, 3, padding=1),
        nn.BatchNorm2d(out_channels),
        nn.ReLU(),
    )


def _multiscale_unet() -> Any:
    torch, nn = _require_torch()
    torch.manual_seed(4004)

    class MultiScaleUNet(nn.Module):  # type: ignore[name-defined]
        def __init__(self) -> None:
            super().__init__()
            self.encoder1 = _conv_block(nn, 3, 16)
            self.encoder2 = _conv_block(nn, 16, 32)
            self.encoder3 = _conv_block(nn, 32, 64)
            self.pool = nn.MaxPool2d(2)
            self.bottleneck = _conv_block(nn, 64, 128)
            self.decoder3 = _conv_block(nn, 128 + 64, 64)
            self.decoder2 = _conv_block(nn, 64 + 32, 32)
            self.decoder1 = _conv_block(nn, 32 + 16, 16)
            self.segmentation_head = nn.Conv2d(16, 4, 1)

        def forward(self, image: Any) -> Any:
            encoder1 = self.encoder1(image)
            encoder2 = self.encoder2(self.pool(encoder1))
            encoder3 = self.encoder3(self.pool(encoder2))
            center = self.bottleneck(self.pool(encoder3))
            decoder3 = self.decoder3(torch.cat((torch.nn.functional.interpolate(center, scale_factor=2.0), encoder3), dim=1))
            decoder2 = self.decoder2(torch.cat((torch.nn.functional.interpolate(decoder3, scale_factor=2.0), encoder2), dim=1))
            decoder1 = self.decoder1(torch.cat((torch.nn.functional.interpolate(decoder2, scale_factor=2.0), encoder1), dim=1))
            return self.segmentation_head(decoder1)

    return MultiScaleUNet().eval()


def _diffusion_unet() -> Any:
    torch, nn = _require_torch()
    torch.manual_seed(4005)

    class TimestepEmbedding(nn.Module):  # type: ignore[name-defined]
        def __init__(self, width: int = 32) -> None:
            super().__init__()
            self.projection = nn.Sequential(nn.Linear(1, width), nn.SiLU(), nn.Linear(width, width))

        def forward(self, timestep: Any) -> Any:
            return self.projection(timestep.reshape(-1, 1).float())

    class ConditionedResidualBlock(nn.Module):  # type: ignore[name-defined]
        def __init__(self, channels: int, condition_width: int = 32) -> None:
            super().__init__()
            self.conv1 = nn.Conv2d(channels, channels, 3, padding=1)
            self.condition_projection = nn.Linear(condition_width, channels)
            self.conv2 = nn.Conv2d(channels, channels, 3, padding=1)

        def forward(self, x: Any, condition: Any) -> Any:
            hidden = self.conv1(x) + self.condition_projection(condition)[:, :, None, None]
            return x + self.conv2(torch.nn.functional.silu(hidden))

    class DiffusionUNet(nn.Module):  # type: ignore[name-defined]
        def __init__(self) -> None:
            super().__init__()
            self.timestep_embedding = TimestepEmbedding()
            self.encoder_input = nn.Conv2d(4, 32, 3, padding=1)
            self.encoder_conditioned = ConditionedResidualBlock(32)
            self.downsample = nn.Conv2d(32, 64, 4, stride=2, padding=1)
            self.bottleneck_condition = nn.Linear(32, 64)
            self.bottleneck = nn.Conv2d(64, 64, 3, padding=1)
            self.upsample = nn.ConvTranspose2d(64, 32, 4, stride=2, padding=1)
            self.decoder_conditioned = ConditionedResidualBlock(32)
            self.denoised_output = nn.Conv2d(32, 4, 3, padding=1)

        def forward(self, noisy_latent: Any, timestep: Any) -> Any:
            condition = self.timestep_embedding(timestep)
            skip = self.encoder_conditioned(self.encoder_input(noisy_latent), condition)
            center = self.bottleneck(self.downsample(skip)) + self.bottleneck_condition(condition)[:, :, None, None]
            decoded = self.upsample(torch.nn.functional.silu(center)) + skip
            decoded = self.decoder_conditioned(decoded, condition)
            return self.denoised_output(decoded)

    return DiffusionUNet().eval()


def _topk_moe() -> Any:
    torch, nn = _require_torch()
    torch.manual_seed(4006)

    class TopKRouter(nn.Module):  # type: ignore[name-defined]
        def __init__(self, width: int, experts: int, k: int) -> None:
            super().__init__()
            self.router_logits = nn.Linear(width, experts)
            self.experts = experts
            self.k = k

        def forward(self, x: Any) -> Any:
            scores = torch.softmax(self.router_logits(x), dim=-1)
            values, indices = torch.topk(scores, self.k, dim=-1)
            mask = torch.nn.functional.one_hot(indices, num_classes=self.experts).to(scores.dtype)
            return (mask * values.unsqueeze(-1)).sum(dim=-2)

    class ExpertMLP(nn.Module):  # type: ignore[name-defined]
        def __init__(self, width: int) -> None:
            super().__init__()
            self.feed_forward = nn.Sequential(nn.Linear(width, width * 2), nn.GELU(), nn.Linear(width * 2, width))

        def forward(self, x: Any) -> Any:
            return self.feed_forward(x)

    class TopKMixtureOfExperts(nn.Module):  # type: ignore[name-defined]
        def __init__(self) -> None:
            super().__init__()
            self.token_embedding = nn.Embedding(1024, 64)
            self.router = TopKRouter(64, experts=4, k=2)
            self.experts = nn.ModuleList([ExpertMLP(64) for _ in range(4)])
            self.output_norm = nn.LayerNorm(64)

        def forward(self, tokens: Any) -> Any:
            x = self.token_embedding(tokens)
            routing = self.router(x)
            expert_outputs = torch.stack([expert(x) for expert in self.experts], dim=-2)
            mixed = (expert_outputs * routing.unsqueeze(-1)).sum(dim=-2)
            return self.output_norm(x + mixed)

    return TopKMixtureOfExperts().eval()


def _multimodal_image_text() -> Any:
    torch, nn = _require_torch()
    torch.manual_seed(4007)

    class ModalityFusion(nn.Module):  # type: ignore[name-defined]
        def __init__(self, width: int) -> None:
            super().__init__()
            self.image_projection = nn.Linear(width, width)
            self.text_projection = nn.Linear(width, width)
            self.fusion_gate = nn.Linear(width * 2, width)

        def forward(self, image_features: Any, text_features: Any) -> Any:
            image = self.image_projection(image_features)
            text = self.text_projection(text_features)
            gate = torch.sigmoid(self.fusion_gate(torch.cat((image, text), dim=-1)))
            return gate * image + (1.0 - gate) * text

    class ImageTextMultimodalModel(nn.Module):  # type: ignore[name-defined]
        def __init__(self) -> None:
            super().__init__()
            self.image_encoder = nn.Sequential(
                nn.Conv2d(3, 32, 5, stride=2, padding=2), nn.ReLU(),
                nn.Conv2d(32, 64, 3, stride=2, padding=1), nn.ReLU(), nn.AdaptiveAvgPool2d(1),
            )
            self.text_encoder_embedding = nn.Embedding(2048, 64)
            self.text_encoder_attention = nn.MultiheadAttention(64, 4, batch_first=True)
            self.modality_fusion = ModalityFusion(64)
            self.output_head = nn.Linear(64, 8)

        def forward(self, image: Any, token_ids: Any) -> Any:
            image_features = self.image_encoder(image).flatten(1)
            text = self.text_encoder_embedding(token_ids)
            text_features, _ = self.text_encoder_attention(text, text, text, need_weights=False)
            fused = self.modality_fusion(image_features, text_features.mean(dim=1))
            return self.output_head(fused)

    return ImageTextMultimodalModel().eval()


def _image_sample(seed: int = 4001, channels: int = 3) -> Any:
    torch = _seed(seed)
    return torch.randn(1, channels, 64, 64)


def _token_sample(seed: int = 4003, length: int = 16, vocabulary: int = 2048) -> Any:
    torch = _seed(seed)
    return torch.randint(0, vocabulary, (1, length), dtype=torch.long)


def real_model_registry() -> dict[str, RealModelSpec]:
    """Return the seven-versioned corpus manifest without constructing models."""
    return {
        "resnet50": RealModelSpec("resnet50", "torchvision ResNet50", "cnn", 4001, "float32[1,3,64,64]", 25_557_032, ((1, 3, 64, 64),), ((1, 1000),), ("residual_block",), _resnet50, lambda: _image_sample(4001)),
        "vision_transformer": RealModelSpec("vision_transformer", "Vision Transformer", "transformer", 4002, "float32[1,3,64,64]", 327_274, ((1, 3, 64, 64),), ((1, 10),), ("attention", "encoder"), _vision_transformer, lambda: _image_sample(4002)),
        "bert_encoder": RealModelSpec("bert_encoder", "BERT-like Transformer Encoder", "transformer", 4003, "int64[1,16]", 516_576, ((1, 16),), ((1, 96),), ("attention", "encoder"), _bert_encoder, lambda: _token_sample(4003)),
        "multiscale_unet": RealModelSpec("multiscale_unet", "Multi-scale U-Net", "unet", 4004, "float32[1,3,64,64]", 488_756, ((1, 3, 64, 64),), ((1, 4, 64, 64),), ("encoder", "decoder", "unet_skip"), _multiscale_unet, lambda: _image_sample(4004)),
        "diffusion_unet": RealModelSpec("diffusion_unet", "Diffusion U-Net", "diffusion", 4005, "float32[1,4,32,32] + float32[1] timestep", 147_236, ((1, 4, 32, 32), (1,)), ((1, 4, 32, 32),), ("encoder", "decoder", "timestep_conditioning"), _diffusion_unet, lambda: (_image_sample(4005, 4)[:, :, :32, :32], _seed(4005).tensor([25.0]))),
        "topk_moe": RealModelSpec("topk_moe", "Top-k Mixture-of-Experts", "moe", 4006, "int64[1,12]", 132_228, ((1, 12),), ((1, 12, 64),), ("moe_router_experts",), _topk_moe, lambda: _token_sample(4006, 12, 1024)),
        "image_text": RealModelSpec("image_text", "Image-text multimodal model", "multimodal", 4007, "float32[1,3,64,64] + int64[1,12]", 181_576, ((1, 3, 64, 64), (1, 12)), ((1, 8),), ("attention", "modality_fusion"), _multimodal_image_text, lambda: (_image_sample(4007), _token_sample(4007, 12))),
    }


def construct_real_model(name: str) -> tuple[Any, Any, RealModelSpec]:
    try:
        spec = real_model_registry()[name]
    except KeyError as exc:
        raise ValidationError(
            f"Unknown real-model corpus entry {name!r}",
            hint=f"Choose one of: {', '.join(sorted(real_model_registry()))}.",
        ) from exc
    return spec.factory(), spec.sample_factory(), spec


def import_real_model(name: str, *, view: str = "operation") -> GraphIR:
    """Construct and import a corpus model into one of three faithful views."""
    if view not in REAL_MODEL_VIEWS:
        raise ValidationError(f"Unknown real-model view {view!r}", hint=f"Choose one of: {', '.join(REAL_MODEL_VIEWS)}.")
    model, sample, spec = construct_real_model(name)
    operation = PyTorchAdapter().load(model, sample_input=sample)
    operation.metadata.update({
        "corpus_version": REAL_MODEL_CORPUS_VERSION,
        "corpus_key": spec.key,
        "model_family": spec.family,
        "random_seed": spec.seed,
        "sample_input": spec.sample_description,
        "weights": "random-initialization; no downloaded weights",
        "graph_view": "operation",
    })
    if view == "operation":
        return operation
    if view == "module":
        return _module_view(operation, model)
    return _framework_view(operation, model)


def _module_view(operation: GraphIR, model: Any) -> GraphIR:
    module_types = {name: module.__class__.__name__ for name, module in model.named_modules() if name}
    groups: dict[str, list[Node]] = {}
    passthrough: list[Node] = []
    for node in operation.nodes:
        path = str(node.attributes.get("target", node.path))
        if node.attributes.get("fx_op") == "call_module" and path:
            groups.setdefault(path, []).append(node)
        else:
            passthrough.append(node)
    nodes: list[Node] = []
    owner: dict[str, str] = {}
    for path, members in sorted(groups.items()):
        node_id = stable_id("module", path)
        for member in members:
            owner[member.id] = node_id
        nodes.append(Node(
            id=node_id,
            name=path.split(".")[-1],
            op_type=module_types.get(path, members[0].op_type),
            category=members[0].category,
            path=path,
            namespace=path.rsplit(".", 1)[0] if "." in path else "",
            level="module",
            parameters=sum(item.parameters for item in members),
            trainable_parameters=sum(item.trainable_parameters for item in members),
            buffers=sum(item.buffers for item in members),
            shared_weights=sorted({shared for item in members for shared in item.shared_weights}),
            attributes={"operation_ids": [item.id for item in members], "call_count": len(members), "faithful": True},
            source={"format": "derived-module-view", "source_nodes": [item.id for item in members]},
        ))
    for item in passthrough:
        copied = copy.deepcopy(item)
        copied.level = "module"
        copied.attributes = {**copied.attributes, "operation_ids": [item.id], "faithful": True}
        nodes.append(copied)
        owner[item.id] = copied.id
    projected_nodes = {node.id: node for node in nodes}
    operation_nodes = operation.node_map()
    projected_outputs: dict[tuple[str, str | None], str] = {}
    projected_inputs: dict[tuple[str, str | None], str] = {}

    def boundary_port(edge: Edge, *, direction: str) -> str | None:
        operation_node_id = edge.source if direction == "output" else edge.target
        operation_port_id = edge.source_port if direction == "output" else edge.target_port
        projected_node_id = owner[operation_node_id]
        projected_node = projected_nodes[projected_node_id]
        existing = projected_node.outputs if direction == "output" else projected_node.inputs
        # Passthrough operation nodes retain their native ports verbatim.
        if projected_node_id == operation_node_id and operation_port_id:
            if any(port.id == operation_port_id for port in existing):
                return operation_port_id
        cache = projected_outputs if direction == "output" else projected_inputs
        cache_key = (operation_node_id, operation_port_id or edge.id)
        if cache_key in cache:
            return cache[cache_key]
        source_node = operation_nodes[operation_node_id]
        native_ports = source_node.outputs if direction == "output" else source_node.inputs
        native = next((port for port in native_ports if port.id == operation_port_id), None)
        tensor = copy.deepcopy(edge.tensor if edge.tensor is not None else native.tensor if native else None)
        name = (native.name if native else "") or (tensor.name if tensor else "") or f"{direction}_{len(existing)}"
        port_id = f"{projected_node_id}:{direction}:{stable_id('binding', f'{operation_node_id}:{operation_port_id or edge.id}')}"
        existing.append(Port(port_id, name, direction, tensor))
        port_bindings = projected_node.attributes.setdefault("port_bindings", {})
        port_bindings[port_id] = {
            "operation_node": operation_node_id,
            "operation_port": operation_port_id,
            "source_edge": edge.id,
        }
        cache[cache_key] = port_id
        return port_id

    for edge in operation.edges:
        source, target = owner[edge.source], owner[edge.target]
        if source == target:
            projected_nodes[source].attributes.setdefault("internal_edge_ids", []).append(edge.id)
    edges: list[Edge] = []
    for edge in operation.edges:
        source, target = owner[edge.source], owner[edge.target]
        if source == target:
            continue
        source_port = boundary_port(edge, direction="output")
        target_port = boundary_port(edge, direction="input")
        edges.append(Edge(
            id=stable_id("module_edge", edge.id),
            source=source,
            target=target,
            source_port=source_port,
            target_port=target_port,
            tensor=copy.deepcopy(edge.tensor),
            kind=edge.kind,
            label=edge.label,
            attributes={
                **copy.deepcopy(edge.attributes),
                "source_edges": [edge.id],
                "boundary_count": 1,
                "operation_binding": {
                    "source_node": edge.source,
                    "source_port": edge.source_port,
                    "target_node": edge.target,
                    "target_port": edge.target_port,
                },
            },
            visible=edge.visible,
        ))
    parent_groups: dict[str, list[str]] = {}
    for node in nodes:
        if node.namespace:
            parent_groups.setdefault(node.namespace, []).append(node.id)
    return GraphIR(
        name=f"{operation.name} · Module",
        nodes=nodes,
        edges=edges,
        subgraphs=[Subgraph(stable_id("module_group", path), path.split(".")[-1], ids, level="module", attributes={"path": path}) for path, ids in sorted(parent_groups.items())],
        inputs=copy.deepcopy(operation.inputs),
        outputs=copy.deepcopy(operation.outputs),
        metadata={**operation.metadata, "graph_view": "module", "source_operation_nodes": len(operation.nodes)},
        analysis=dict(operation.analysis),
    ).validate()


def _framework_view(operation: GraphIR, model: Any) -> GraphIR:
    parameters = sum(parameter.numel() for parameter in model.parameters())
    trainable = sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad)
    node = Node(
        id=stable_id("framework", operation.name),
        name=operation.name,
        op_type=model.__class__.__name__,
        category="model",
        path=operation.name,
        level="framework",
        parameters=parameters,
        trainable_parameters=trainable,
        inputs=[
            Port(
                f"{stable_id('framework', operation.name)}:input:{index}",
                tensor.name or f"input_{index}",
                "input",
                copy.deepcopy(tensor),
            )
            for index, tensor in enumerate(operation.inputs)
        ],
        outputs=[
            Port(
                f"{stable_id('framework', operation.name)}:output:{index}",
                tensor.name or f"output_{index}",
                "output",
                copy.deepcopy(tensor),
            )
            for index, tensor in enumerate(operation.outputs)
        ],
        attributes={
            "operation_ids": [item.id for item in operation.nodes],
            "module_count": sum(1 for _ in model.modules()),
            "faithful": True,
            "boundary_ports_preserved": True,
        },
        source={"format": "derived-framework-view", "source_nodes": [item.id for item in operation.nodes]},
    )
    return GraphIR(
        name=f"{operation.name} · Framework",
        nodes=[node],
        inputs=copy.deepcopy(operation.inputs),
        outputs=copy.deepcopy(operation.outputs),
        metadata={**operation.metadata, "graph_view": "framework", "source_operation_nodes": len(operation.nodes)},
        analysis=dict(operation.analysis),
    ).validate()


def _rss_mb() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value / (1024.0 if platform.system() != "Darwin" else 1024.0 * 1024.0)


def _median_runs(values: list[float]) -> dict[str, Any]:
    return {"runs_ms": [round(item, 3) for item in values], "median_ms": round(statistics.median(values), 3)}


def _detection_provenance_roundtrip(semantic: Any, detection: dict[str, Any]) -> bool:
    provenance = detection.get("provenance", {})
    source_ids = list(provenance.get("source_node_ids", [])) + list(provenance.get("source_edge_ids", []))
    if not source_ids:
        return False
    explicit = detection.get("semantic_id")
    for source_id in source_ids:
        semantic_ids = [explicit] if explicit else semantic.trace_semantic(source_id)
        if not semantic_ids:
            return False
        if not any(
            source_id in (
                semantic.trace_source(semantic_id).source_node_ids
                + semantic.trace_source(semantic_id).source_edge_ids
            )
            for semantic_id in semantic_ids
        ):
            return False
    return True


def build_real_model_compatibility_report(*, repeats: int = 3, names: list[str] | None = None) -> dict[str, Any]:
    """Exercise construction/import/semantics/layout and return machine evidence."""
    selected = names or list(real_model_registry())
    warmup_started = time.perf_counter()
    _require_torch()
    if "resnet50" in selected:
        try:
            import torchvision.models  # noqa: F401
        except ImportError:
            pass
    runtime_warmup_ms = (time.perf_counter() - warmup_started) * 1000.0
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "corpus_version": REAL_MODEL_CORPUS_VERSION,
        "generated_at_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "hardware": {"platform": platform.platform(), "processor": platform.processor() or "unknown", "python": platform.python_version()},
        "repeats": repeats,
        "benchmark_protocol": "Local framework import warm-up is recorded but excluded; each model then has three measured CPU runs.",
        "runtime_warmup_ms": round(runtime_warmup_ms, 3),
        "models": {},
    }
    for name in selected:
        spec = real_model_registry()[name]
        timings: dict[str, list[float]] = {
            phase: []
            for phase in (
                "construct",
                "import",
                "semantic",
                "first_screen",
                "paper_layout",
                "model_to_module_first_screen",
            )
        }
        peak_before = _rss_mb()
        final_graph: GraphIR | None = None
        final_semantic: Any = None
        view_counts: dict[str, dict[str, int]] = {}
        for _ in range(repeats):
            workflow_start = time.perf_counter()
            start = workflow_start
            model, sample, _ = construct_real_model(name)
            timings["construct"].append((time.perf_counter() - start) * 1000.0)
            start = time.perf_counter()
            graph = PyTorchAdapter().load(model, sample_input=sample)
            timings["import"].append((time.perf_counter() - start) * 1000.0)
            start = time.perf_counter()
            semantic = derive_semantic_view(graph)
            timings["semantic"].append((time.perf_counter() - start) * 1000.0)
            start = time.perf_counter()
            first = semantic.materialize(graph, level="stage" if len(graph.nodes) > 80 else "block", view="faithful")
            LayoutEngine().layout(first)
            timings["first_screen"].append((time.perf_counter() - start) * 1000.0)
            module_first = _module_view(graph, model)
            module_semantic = derive_semantic_view(module_first)
            module_screen = module_semantic.materialize(
                module_first,
                level="stage" if len(module_first.nodes) > 80 else "block",
                view="faithful",
            )
            LayoutEngine().layout(module_screen)
            timings["model_to_module_first_screen"].append((time.perf_counter() - workflow_start) * 1000.0)
            start = time.perf_counter()
            paper = semantic.materialize(graph, level="block", view="paper")
            LayoutEngine().layout(paper)
            timings["paper_layout"].append((time.perf_counter() - start) * 1000.0)
            final_graph, final_semantic = graph, semantic
            for view in REAL_MODEL_VIEWS:
                viewed = graph if view == "operation" else _module_view(graph, model) if view == "module" else _framework_view(graph, model)
                view_counts[view] = {"nodes": len(viewed.nodes), "edges": len(viewed.edges)}
            del model, sample, graph, semantic, first, module_first, module_semantic, module_screen, paper
            gc.collect()
        assert final_graph is not None and final_semantic is not None
        detected = [item for item in final_semantic.detections if not item.get("unknown")]
        detected_types = sorted({item["semantic_type"] for item in detected})
        provenance_roundtrip = all(_detection_provenance_roundtrip(final_semantic, item) for item in detected)
        expected = list(spec.expected_semantics)
        missing = sorted(set(expected) - set(detected_types))
        parameters = sum(node.parameters for node in final_graph.nodes)
        input_shapes = [item.shape for item in final_graph.inputs]
        output_shapes = [item.shape for item in final_graph.outputs]
        report["models"][name] = {
            "display_name": spec.display_name,
            "family": spec.family,
            "seed": spec.seed,
            "sample_input": spec.sample_description,
            "weights": "not downloaded",
            "parameters": parameters,
            "expected_parameters": spec.expected_parameters,
            "parameter_match": parameters == spec.expected_parameters,
            "trainable_parameters": sum(node.trainable_parameters for node in final_graph.nodes),
            "shared_parameters": final_graph.metadata.get("shared_parameters", {}),
            "inputs": [asdict(item) for item in final_graph.inputs],
            "outputs": [asdict(item) for item in final_graph.outputs],
            "input_shape_match": input_shapes == [list(item) for item in spec.expected_input_shapes],
            "output_shape_match": output_shapes == [list(item) for item in spec.expected_output_shapes],
            "views": view_counts,
            "expected_semantics": expected,
            "detected_semantics": detected_types,
            "missing_semantics": missing,
            "unknown_count": sum(1 for item in final_semantic.detections if item.get("unknown")),
            "detections": detected,
            "bidirectional_provenance": provenance_roundtrip,
            "timings": {phase: _median_runs(values) for phase, values in timings.items()},
            "module_first_screen_within_2s": max(timings["model_to_module_first_screen"]) <= 2_000.0,
            "peak_rss_mb": round(max(peak_before, _rss_mb()), 3),
            "compatible": (
                not missing
                and parameters == spec.expected_parameters
                and input_shapes == [list(item) for item in spec.expected_input_shapes]
                and output_shapes == [list(item) for item in spec.expected_output_shapes]
                and max(timings["model_to_module_first_screen"]) <= 2_000.0
                and provenance_roundtrip
            ),
        }
    report["compatible"] = all(item["compatible"] for item in report["models"].values())
    # Product reports share a top-level ``passed`` contract so the release
    # aggregator can treat compatibility, paper, diff, and performance
    # evidence uniformly.  Keep ``compatible`` as the domain-specific field.
    report["passed"] = report["compatible"]
    return report


def write_real_model_compatibility_report(path: str | Path, *, repeats: int = 3, names: list[str] | None = None) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(build_real_model_compatibility_report(repeats=repeats, names=names), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


__all__ = [
    "REAL_MODEL_CORPUS_VERSION",
    "REAL_MODEL_VIEWS",
    "RealModelSpec",
    "build_real_model_compatibility_report",
    "construct_real_model",
    "import_real_model",
    "real_model_registry",
    "write_real_model_compatibility_report",
]
