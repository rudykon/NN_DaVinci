"""Evidence-preserving Graph/Semantic/Figure to editable Scene conversion.

Architecture names and operator names are deliberately not used as evidence.
An architecture family is considered known only when a structured Graph IR
``architecture_evidence`` record or a persisted Semantic View detection names
the family and cites source IDs.  A caller may request one of the seven layout
profiles, but that request remains an authoring choice while the evidenced
family stays ``unknown``.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import heapq
import math
from typing import Any, Iterable, Mapping, Sequence

from .architecture_evidence import ArchitectureEvidence, ArchitectureRole
from .architecture_role_graph import build_architecture_role_graph
from .errors import ValidationError
from .figure_ir import FigureIR
from .ir import Edge, GraphIR, Node, TensorSpec
from .scene_ir import (
    MAX_SCENE_OBJECTS,
    Material3D,
    Object3D,
    Scene,
    SceneProvenance,
    Transform3D,
    new_scene,
)
from .semantic import SemanticView, normalize_semantic_level


MODEL_SCENE_PIPELINE_VERSION = "1.0"
MAXIMUM_MODEL_SCENE_OBJECTS = 250
MAXIMUM_EXACT_SUMMARY_SOURCE_IDS = 10_000
ARCHITECTURE_FAMILIES = (
    "cnn",
    "resnet",
    "unet",
    "transformer",
    "moe",
    "multimodal-fusion",
    "diffusion-unet",
)
_ARCHITECTURE_ALIASES = {
    "convolutional": "cnn",
    "residual": "resnet",
    "u-net": "unet",
    "mixture-of-experts": "moe",
    "multimodal": "multimodal-fusion",
    "multimodal_fusion": "multimodal-fusion",
    "diffusion": "diffusion-unet",
    "diffusion_unet": "diffusion-unet",
}
_NODE_ROLE_ALIASES = {
    "tensor": "tensor-volume",
    "tensor_volume": "tensor-volume",
    "feature_maps": "feature-map-stack",
    "layer": "layer-plane",
    "operation": "operation-block",
    "conv": "convolution-window",
    "conv_window": "convolution-window",
    "attention": "attention-head",
    "tokens": "token-sequence",
    "router": "moe-router",
    "expert": "operation-block",
    "modality": "multimodal-stream",
    "time": "timestep-conditioning",
}
_NODE_ROLES = frozenset(
    {
        "tensor-volume",
        "tensor-stack",
        "feature-map-stack",
        "layer-plane",
        "operation-block",
        "convolution-window",
        "conv-window",
        "pooling",
        "downsample",
        "upsample",
        "attention-head",
        "token-sequence",
        "moe-router",
        "merge",
        "multimodal-stream",
        "fusion",
        "timestep-conditioning",
        "unknown",
    }
)
_EDGE_ROLES = frozenset(
    {
        "arrow",
        "tube",
        "polyline",
        "bezier-route",
        "residual-skip",
        "unet-skip",
        "attention-ribbon",
        "qkv-branch",
        "expert-branch",
        "multimodal-stream",
    }
)

_COLORS = {
    "tensor": "#bfdbfe",
    "operation": "#f8fafc",
    "accent": "#8b5cf6",
    "skip": "#ef4444",
    "attention": "#f59e0b",
    "expert": "#a7f3d0",
    "modality_image": "#93c5fd",
    "modality_text": "#f0abfc",
    "conditioning": "#fbbf24",
    "unknown": "#e2e8f0",
}


def _family(value: str) -> str:
    normalized = str(value).strip().lower().replace(" ", "-")
    normalized = _ARCHITECTURE_ALIASES.get(normalized, normalized)
    if normalized not in ARCHITECTURE_FAMILIES:
        raise ValidationError(
            f"Unknown Scene architecture family {value!r}",
            hint=f"Choose one of: {', '.join(ARCHITECTURE_FAMILIES)}.",
        )
    return normalized


def _template_material(color: str, *, opacity: float = 1.0) -> Material3D:
    return Material3D(
        base_color=color,
        face_colors={"top": color, "front": color},
        stroke_color="#334155",
        stroke_width=0.8,
        opacity=opacity,
        roughness=0.9,
        unlit=True,
    )


def _template_object(
    family: str,
    key: str,
    kind: str,
    name: str,
    position: Sequence[float],
    size: Sequence[float],
    *,
    color: str = _COLORS["operation"],
    metadata: Mapping[str, Any] | None = None,
) -> Object3D:
    return Object3D.create(
        kind,
        name,
        {"size": list(size)},
        SceneProvenance.template(f"scene-template:{family}:{key}"),
        transform=Transform3D(list(position)),
        material=_template_material(color),
        identity=f"scene-template:{family}:{key}",
        metadata={
            "architecture_family": family,
            "architecture_role": key,
            "editable": True,
            "model_fact": False,
            "template_only": True,
            **dict(metadata or {}),
        },
    )


def _template_route(
    family: str,
    key: str,
    kind: str,
    name: str,
    points: Sequence[Sequence[float]],
    *,
    color: str = "#475569",
    radius: float = 0.07,
    metadata: Mapping[str, Any] | None = None,
) -> Object3D:
    material = _template_material(color)
    # Route colour carries architecture semantics (for example red residual
    # skips and blue U-Net skips).  Using the generic object outline made
    # those paths look like accidental empty group frames in paper exports.
    material.stroke_color = color
    return Object3D.create(
        kind,
        name,
        {"points": [list(point) for point in points], "radius": radius},
        SceneProvenance.template(f"scene-template:{family}:{key}"),
        material=material,
        identity=f"scene-template:{family}:{key}",
        metadata={
            "architecture_family": family,
            "architecture_role": key,
            "editable": True,
            "model_fact": False,
            "template_only": True,
            **dict(metadata or {}),
        },
    )


def _finish_template(scene: Scene, family: str) -> Scene:
    if scene.layers:
        layer = scene.layers[0]
        # Template routes are authored against nearby object surfaces.  Bind
        # their semantic endpoints explicitly so landed-output validators can
        # distinguish a required endpoint contact from a route crossing an
        # unrelated node.  This is derived only from template authoring
        # geometry and never invents Graph/Semantic evidence.
        endpoint_candidates = [
            item
            for item in layer.objects
            if not isinstance(item.geometry.get("points"), list)
        ]
        for item in layer.objects:
            raw_points = item.geometry.get("points")
            if not isinstance(raw_points, list) or len(raw_points) < 2 or not endpoint_candidates:
                continue

            def nearest_identifier(point: Sequence[float]) -> str:
                return min(
                    endpoint_candidates,
                    key=lambda candidate: sum(
                        (float(point[axis]) - float(candidate.transform.position[axis])) ** 2
                        for axis in range(3)
                    ),
                ).id

            item.metadata["endpoint_object_ids"] = list(
                dict.fromkeys(
                    (
                        nearest_identifier(raw_points[0]),
                        nearest_identifier(raw_points[-1]),
                    )
                )
            )
        frame = _template_object(
            family,
            "group-frame",
            "group-frame",
            "Architecture group frame",
            (0.0, 0.0, 0.0),
            (17.0, 11.0, 8.0),
            color="#e2e8f0",
            metadata={
                "frame_role": "template-boundary",
                "decorative": True,
                "exclude_from_framing": True,
                "default_hidden_in_publication": True,
            },
        )
        frame.material.opacity = 0.025
        frame.order = -100
        legend = Object3D.create(
            "legend",
            "Geometry mapping legend",
            {
                "text": "3D depth and thickness are editable visual mappings, not literal tensor dimensions.",
                "size": [10.0, 0.5, 0.2],
            },
            SceneProvenance.template(f"scene-template:{family}:geometry-legend"),
            transform=Transform3D([0.0, -5.0, 0.0]),
            material=_template_material("#f8fafc"),
            identity=f"scene-template:{family}:geometry-legend",
            metadata={
                "architecture_family": family,
                "architecture_role": "legend",
                "editable": True,
                "model_fact": False,
                "template_only": True,
                "visual_geometry_is_literal_tensor_size": False,
                "caption": True,
                "exclude_from_framing": True,
            },
            order=1_000_000,
        )
        layer.objects.extend([frame, legend])
    scene.metadata.update(
        {
            "architecture_family": family,
            "evidenced_architecture_family": "template",
            "template_id": f"nn-davinci-scene-{family}-1.0",
            "template_provenance_only": True,
            "contains_model_evidence": False,
            "model_scene_pipeline": {
                "version": MODEL_SCENE_PIPELINE_VERSION,
                "mode": "explicit-template",
                "architecture_was_not_inferred": True,
            },
            "provenance_index": {
                "graph_to_scene": {},
                "semantic_to_scene": {},
                "figure_to_scene": {},
                "scene_to_source": {},
            },
        }
    )
    scene.refresh_records()
    return scene.validate()


def cnn_scene_template(name: str = "CNN 3D template") -> Scene:
    family = "cnn"
    scene = new_scene(name)
    layer = scene.layers[0]
    layer.objects.extend(
        [
            _template_object(
                family,
                "input",
                "tensor-volume",
                "Input image",
                (-7.0, 0.0, 0.0),
                (1.0, 5.0, 5.0),
                color=_COLORS["tensor"],
                metadata={"tensor_shape": ["B", "C", "H", "W"]},
            ),
            _template_object(family, "kernel", "convolution-window", "Convolution window", (-5.4, 0.0, 1.7), (0.25, 1.6, 1.6), color=_COLORS["accent"]),
            _template_object(
                family,
                "features-1",
                "feature-map-stack",
                "Feature maps",
                (-3.5, 0.0, 0.0),
                (2.0, 4.0, 4.0),
                color="#93c5fd",
                metadata={"tensor_shape": ["B", "C1", "H1", "W1"]},
            ),
            _template_object(family, "pool", "downsample", "Pooling / downsample", (-0.5, 0.0, 0.0), (1.6, 3.0, 3.0), color="#a7f3d0"),
            _template_object(
                family,
                "features-2",
                "feature-map-stack",
                "Deep features",
                (2.3, 0.0, 0.0),
                (2.2, 2.2, 2.2),
                color="#60a5fa",
                metadata={"tensor_shape": ["B", "C2", "H2", "W2"]},
            ),
            _template_object(family, "head", "operation-block", "Classifier head", (5.3, 0.0, 0.0), (2.1, 1.6, 1.6), color="#fde68a"),
        ]
    )
    positions = [(-6.5, 0, 0), (-4.5, 0, 0), (-2.5, 0, 0), (0.4, 0, 0), (3.4, 0, 0), (4.3, 0, 0)]
    for index, (start, end) in enumerate(zip(positions[::2], positions[1::2])):
        layer.objects.append(_template_route(family, f"flow-{index}", "arrow", "Data flow", (start, end)))
    return _finish_template(scene, family)


def resnet_scene_template(name: str = "ResNet 3D template") -> Scene:
    family = "resnet"
    scene = new_scene(name)
    layer = scene.layers[0]
    blocks = [
        ("input", "tensor-volume", "Input", -7.0, _COLORS["tensor"]),
        ("stem", "operation-block", "Stem", -4.8, "#bfdbfe"),
        ("block-1", "operation-block", "Residual block 1", -1.8, "#ddd6fe"),
        ("block-2", "operation-block", "Residual block 2", 1.8, "#c4b5fd"),
        ("head", "operation-block", "Head", 5.2, "#fde68a"),
    ]
    for key, kind, label, x, color in blocks:
        layer.objects.append(_template_object(family, key, kind, label, (x, 0.0, 0.0), (1.8, 2.0, 2.0), color=color))
    for index, (start, end) in enumerate(((-6.1, -5.7), (-3.9, -2.7), (-0.9, 0.9), (2.7, 4.3))):
        layer.objects.append(_template_route(family, f"main-{index}", "arrow", "Residual main path", ((start, 0.0, 0.0), (end, 0.0, 0.0))))
    layer.objects.extend(
        [
            _template_route(
                family,
                "skip-1",
                "residual-skip",
                "Residual skip 1",
                ((-2.7, 0.0, 0.0), (-2.7, 1.8, -1.8), (0.9, 1.8, -1.8), (0.9, 0.0, 0.0)),
                color=_COLORS["skip"],
                radius=0.1,
            ),
            _template_route(
                family,
                "skip-2",
                "residual-skip",
                "Residual skip 2",
                ((0.9, 0.0, 0.0), (0.9, -2.6, 2.8), (4.3, -2.6, 2.8), (4.3, 0.0, 0.0)),
                color=_COLORS["skip"],
                radius=0.1,
            ),
        ]
    )
    return _finish_template(scene, family)


def unet_scene_template(name: str = "U-Net 3D template") -> Scene:
    family = "unet"
    scene = new_scene(name)
    layer = scene.layers[0]
    positions = {
        "enc-1": (-6.0, 3.2, 0.0),
        "enc-2": (-3.4, 1.3, 0.8),
        "bottleneck": (0.0, -1.2, 1.8),
        "dec-2": (3.4, 1.3, 0.8),
        "dec-1": (6.0, 3.2, 0.0),
    }
    for key, position in positions.items():
        if key == "bottleneck":
            kind, label, size, color = "operation-block", "Bottleneck", (2.0, 1.8, 1.8), "#c4b5fd"
        elif key.startswith("enc"):
            kind, label, size, color = "downsample", f"Encoder {key[-1]}", (1.8, 2.2, 2.2), "#93c5fd"
        else:
            kind, label, size, color = "upsample", f"Decoder {key[-1]}", (1.8, 2.2, 2.2), "#a7f3d0"
        layer.objects.append(_template_object(family, key, kind, label, position, size, color=color, metadata={"depth_stage": key}))
    main_order = ["enc-1", "enc-2", "bottleneck", "dec-2", "dec-1"]
    for index, (source, target) in enumerate(zip(main_order, main_order[1:])):
        layer.objects.append(_template_route(family, f"main-{index}", "arrow", "U-Net main flow", (positions[source], positions[target])))
    for index, (source, target) in enumerate((("enc-1", "dec-1"), ("enc-2", "dec-2"))):
        start, end = positions[source], positions[target]
        # Route skips behind the U rather than through its projected centre.
        # Separate depth lanes keep both branches clear of the bottleneck and
        # the opposite encoder/decoder blocks in the publication camera.
        lane_depth = -2.0 - index
        layer.objects.append(
            _template_route(
                family,
                f"skip-{index}",
                "unet-skip",
                "Cross-level skip",
                (start, (start[0], start[1], lane_depth), (end[0], end[1], lane_depth), end),
                color=_COLORS["skip"],
                radius=0.09,
            )
        )
    return _finish_template(scene, family)


def transformer_scene_template(name: str = "Transformer 3D template") -> Scene:
    family = "transformer"
    scene = new_scene(name)
    layer = scene.layers[0]
    layer.objects.extend(
        [
            _template_object(
                family,
                "tokens",
                "token-sequence",
                "Token sequence",
                (-6.0, 0.0, 0.0),
                (2.4, 1.0, 3.8),
                color=_COLORS["tensor"],
                metadata={"tensor_shape": ["B", "T", "D"]},
            ),
            _template_object(family, "q", "layer-plane", "Q", (-3.4, 2.0, 0.0), (1.2, 1.0, 2.6), color="#fef3c7"),
            _template_object(family, "k", "layer-plane", "K", (-3.4, 0.0, 0.0), (1.2, 1.0, 2.6), color="#fde68a"),
            _template_object(family, "v", "layer-plane", "V", (-3.4, -2.0, 0.0), (1.2, 1.0, 2.6), color="#fcd34d"),
        ]
    )
    for head in range(4):
        layer.objects.append(
            _template_object(
                family,
                f"head-{head}",
                "attention-head",
                f"Attention head {head + 1}",
                (0.0, -2.25 + head * 1.5, -1.5 + head),
                (1.5, 1.0, 1.2),
                color="#fbbf24",
                metadata={"head_index": head, "expanded_heads": 4},
            )
        )
    layer.objects.extend(
        [
            _template_object(family, "concat", "merge", "Concatenate heads", (3.0, 0.0, 0.0), (1.8, 2.2, 2.2), color="#c4b5fd"),
            _template_object(family, "ffn", "operation-block", "Feed-forward network", (6.0, 0.0, 0.0), (2.2, 2.2, 2.2), color="#a7f3d0"),
            _template_route(family, "qkv", "qkv-branch", "Q/K/V branches", ((-4.8, 0.0, 0.0), (-4.2, 0.0, 2.0), (-3.4, 2.0, 0.0)), color=_COLORS["attention"]),
            _template_route(
                family,
                "attention",
                "attention-ribbon",
                "Multi-head attention",
                ((-2.8, 0.0, 0.0), (0.0, 0.0, -2.0), (2.1, 0.0, 0.0)),
                color=_COLORS["attention"],
                radius=0.12,
            ),
            _template_route(family, "ffn-flow", "arrow", "Attention to FFN", ((3.9, 0.0, 0.0), (4.9, 0.0, 0.0))),
        ]
    )
    return _finish_template(scene, family)


def moe_scene_template(name: str = "MoE 3D template") -> Scene:
    family = "moe"
    scene = new_scene(name)
    layer = scene.layers[0]
    layer.objects.extend(
        [
            _template_object(family, "tokens", "token-sequence", "Tokens", (-6.0, 0.0, 0.0), (2.0, 1.2, 3.5), color=_COLORS["tensor"]),
            _template_object(family, "router", "moe-router", "Top-k router", (-3.0, 0.0, 0.0), (1.8, 2.0, 2.0), color="#fbbf24", metadata={"top_k": "k"}),
        ]
    )
    for expert in range(4):
        position = (0.5, -3.0 + expert * 2.0, -1.5 + expert)
        layer.objects.append(
            _template_object(
                family,
                f"expert-{expert}",
                "operation-block",
                f"Expert {expert + 1}",
                position,
                (1.8, 1.2, 1.4),
                color=_COLORS["expert"],
                metadata={"expert_index": expert},
            )
        )
        layer.objects.append(
            _template_route(family, f"route-{expert}", "expert-branch", "Top-k expert route", ((-2.1, 0.0, 0.0), position), color="#10b981", radius=0.075)
        )
    layer.objects.extend(
        [
            _template_object(family, "merge", "merge", "Weighted merge", (4.0, 0.0, 0.0), (2.0, 2.2, 2.2), color="#c4b5fd"),
            _template_route(family, "input-route", "arrow", "Tokens to router", ((-5.0, 0.0, 0.0), (-3.9, 0.0, 0.0))),
        ]
    )
    for expert in range(4):
        position = (0.5, -3.0 + expert * 2.0, -1.5 + expert)
        merge_points: tuple[tuple[float, float, float], ...]
        if expert == 3:
            # A compact dogleg skirts the projected Expert 3 footprint while
            # keeping the Expert 4 route and label visually unambiguous.
            merge_points = (position, (2.0, 3.0, 1.5), (3.0, 1.5, 0.0), (3.0, 0.0, 0.0))
        else:
            merge_points = (position, (3.0, 0.0, 0.0))
        layer.objects.append(
            _template_route(
                family,
                f"merge-route-{expert}",
                "expert-branch",
                "Expert merge route",
                merge_points,
                color="#8b5cf6",
                radius=0.075,
            )
        )
    return _finish_template(scene, family)


def multimodal_fusion_scene_template(name: str = "Multimodal Fusion 3D template") -> Scene:
    family = "multimodal-fusion"
    scene = new_scene(name)
    layer = scene.layers[0]
    streams = [
        ("image", "Image stream", -3.0, _COLORS["modality_image"]),
        ("text", "Text stream", 0.0, _COLORS["modality_text"]),
        ("audio", "Audio stream", 3.0, "#a7f3d0"),
    ]
    for key, label, y, color in streams:
        layer.objects.extend(
            [
                _template_object(
                    family, f"{key}-input", "multimodal-stream", f"{label} input", (-6.0, y, 0.0), (1.8, 1.4, 2.0), color=color, metadata={"modality": key}
                ),
                _template_object(
                    family, f"{key}-encoder", "operation-block", f"{label} encoder", (-2.5, y, 0.0), (2.0, 1.6, 2.0), color=color, metadata={"modality": key}
                ),
                _template_route(family, f"{key}-stream", "multimodal-stream", f"{label} remains independent", ((-5.1, y, 0.0), (-3.5, y, 0.0)), color=color),
            ]
        )
    layer.objects.extend(
        [
            _template_object(family, "fusion", "fusion", "Fusion", (1.5, 0.0, 0.0), (2.2, 3.0, 2.5), color="#c4b5fd"),
            _template_object(family, "head", "operation-block", "Prediction head", (5.0, 0.0, 0.0), (2.0, 1.8, 2.0), color="#fde68a"),
            _template_route(family, "output", "arrow", "Fused output", ((2.6, 0.0, 0.0), (4.0, 0.0, 0.0))),
        ]
    )
    for key, _label, y, color in streams:
        layer.objects.append(
            _template_route(family, f"{key}-fusion", "multimodal-stream", "Modality enters fusion", ((-1.5, y, 0.0), (0.4, 0.0, 0.0)), color=color)
        )
    return _finish_template(scene, family)


def diffusion_unet_scene_template(name: str = "Diffusion U-Net 3D template") -> Scene:
    family = "diffusion-unet"
    scene = new_scene(name)
    layer = scene.layers[0]
    positions = {
        "noisy-latent": (-7.0, 3.0, 0.0),
        "encoder": (-3.8, 1.0, 0.8),
        "bottleneck": (0.0, -1.3, 1.8),
        "decoder": (3.8, 1.0, 0.8),
        "denoised": (7.0, 3.0, 0.0),
        "timestep": (0.0, 4.2, 4.0),
    }
    objects = [
        ("noisy-latent", "tensor-volume", "Noisy latent", (1.8, 2.4, 2.4), _COLORS["tensor"]),
        ("encoder", "downsample", "Conditioned encoder", (2.1, 2.2, 2.2), "#93c5fd"),
        ("bottleneck", "operation-block", "Bottleneck", (2.2, 2.0, 2.0), "#c4b5fd"),
        ("decoder", "upsample", "Conditioned decoder", (2.1, 2.2, 2.2), "#a7f3d0"),
        ("denoised", "tensor-volume", "Denoised output", (1.8, 2.4, 2.4), "#bfdbfe"),
        ("timestep", "timestep-conditioning", "Timestep embedding", (2.2, 1.4, 1.6), _COLORS["conditioning"]),
    ]
    for key, kind, label, size, color in objects:
        layer.objects.append(_template_object(family, key, kind, label, positions[key], size, color=color, metadata={"conditioning": key == "timestep"}))
    main = ["noisy-latent", "encoder", "bottleneck", "decoder", "denoised"]
    for index, (source, target) in enumerate(zip(main, main[1:])):
        layer.objects.append(_template_route(family, f"main-{index}", "arrow", "Denoising path", (positions[source], positions[target])))
    layer.objects.extend(
        [
            _template_route(
                family,
                "unet-skip",
                "unet-skip",
                "Diffusion U-Net skip",
                (positions["encoder"], (-3.8, 2.8, 4.0), (3.8, 2.8, 4.0), positions["decoder"]),
                color=_COLORS["skip"],
                radius=0.09,
            ),
            _template_route(
                family,
                "time-encoder",
                "polyline",
                "Timestep conditions encoder",
                (positions["timestep"], (-3.8, 1.0, 2.8), positions["encoder"]),
                color=_COLORS["conditioning"],
            ),
            _template_route(
                family,
                "time-decoder",
                "polyline",
                "Timestep conditions decoder",
                (positions["timestep"], (3.8, 1.0, 2.8), positions["decoder"]),
                color=_COLORS["conditioning"],
            ),
        ]
    )
    return _finish_template(scene, family)


_TEMPLATE_BUILDERS = {
    "cnn": cnn_scene_template,
    "resnet": resnet_scene_template,
    "unet": unet_scene_template,
    "transformer": transformer_scene_template,
    "moe": moe_scene_template,
    "multimodal-fusion": multimodal_fusion_scene_template,
    "diffusion-unet": diffusion_unet_scene_template,
}


def scene_template(family: str, *, name: str | None = None) -> Scene:
    normalized = _family(family)
    builder = _TEMPLATE_BUILDERS[normalized]
    return builder(name or f"{normalized} 3D template")


@dataclass(slots=True)
class _SourceRecord:
    key: str
    name: str
    nodes: list[Node]
    edges: list[Edge]
    role: str
    stage: str
    modality: str
    summary: bool = False

    @property
    def node_ids(self) -> list[str]:
        return [node.id for node in self.nodes]


def _topological_nodes(graph: GraphIR) -> list[Node]:
    order = {node.id: index for index, node in enumerate(graph.nodes)}
    indegree = {node.id: 0 for node in graph.nodes}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        if edge.source == edge.target:
            continue
        outgoing[edge.source].append(edge.target)
        indegree[edge.target] += 1
    ready = [(order[node_id], node_id) for node_id, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    result: list[Node] = []
    node_map = graph.node_map()
    while ready:
        _, node_id = heapq.heappop(ready)
        result.append(node_map[node_id])
        for target in sorted(outgoing[node_id], key=order.__getitem__):
            indegree[target] -= 1
            if indegree[target] == 0:
                heapq.heappush(ready, (order[target], target))
    return result if len(result) == len(graph.nodes) else list(graph.nodes)


def _graph_ids(graph: GraphIR) -> set[str]:
    return {
        *(node.id for node in graph.nodes),
        *(edge.id for edge in graph.edges),
        *(port.id for node in graph.nodes for port in [*node.inputs, *node.outputs]),
    }


def _architecture_evidence(graph: GraphIR, semantic: SemanticView | None) -> tuple[str, dict[str, Any] | None]:
    if semantic is not None and semantic.architecture_evidence is not None:
        evidence = semantic.architecture_evidence.validate(
            graph,
            source_digest=semantic.source_digest,
        )
        if evidence.family == "unknown":
            return "unknown", evidence.to_dict()
        return _family(evidence.family), evidence.to_dict()
    known_graph_ids = _graph_ids(graph)
    records: list[dict[str, Any]] = []
    graph_record = graph.metadata.get("architecture_evidence")
    if isinstance(graph_record, dict):
        records.append({**graph_record, "origin": "graph_ir.metadata.architecture_evidence"})
    if semantic is not None:
        for detection in semantic.detections:
            if isinstance(detection, dict) and detection.get("architecture_family"):
                provenance = detection.get("provenance", {})
                records.append(
                    {
                        "family": detection.get("architecture_family"),
                        "graph_ir_ids": [
                            *provenance.get("source_node_ids", []),
                            *provenance.get("source_edge_ids", []),
                        ]
                        if isinstance(provenance, dict)
                        else [],
                        "semantic_view_ids": [detection.get("semantic_id")] if detection.get("semantic_id") else [],
                        "reason": "; ".join(map(str, detection.get("reasons", []))),
                        "origin": "semantic_view.detections",
                    }
                )
    valid: list[dict[str, Any]] = []
    for record in records:
        try:
            family = _family(str(record.get("family", "")))
        except ValidationError:
            continue
        raw_ids = record.get("graph_ir_ids", [])
        ids = list(dict.fromkeys(map(str, raw_ids))) if isinstance(raw_ids, list) else []
        reason = str(record.get("reason", "")).strip()
        if ids and set(ids).issubset(known_graph_ids) and reason:
            valid.append({**record, "family": family, "graph_ir_ids": ids})
    families = {record["family"] for record in valid}
    if len(families) > 1:
        raise ValidationError(f"Conflicting evidence-backed Scene architecture families {sorted(families)!r}")
    if not valid:
        return "unknown", None
    return valid[0]["family"], valid[0]


def _node_role(node: Node) -> tuple[str, str]:
    raw = node.attributes.get("scene_role")
    if raw is not None:
        normalized = str(raw).strip().lower().replace(" ", "-")
        normalized = _NODE_ROLE_ALIASES.get(normalized, normalized)
        if normalized not in _NODE_ROLES:
            raise ValidationError(f"Graph node {node.id!r} has unsupported explicit scene_role {raw!r}")
        return normalized, "graph_ir.attributes.scene_role"
    if node.category in {"input", "output"}:
        return "tensor-volume", "graph_ir.category"
    return "operation-block", "unknown-no-explicit-architecture-role"


def _edge_role(edge: Edge) -> tuple[str, str]:
    raw = edge.attributes.get("scene_role")
    if raw is None:
        return "arrow", "graph_ir-edge-generic"
    normalized = str(raw).strip().lower().replace(" ", "-")
    if normalized not in _EDGE_ROLES:
        raise ValidationError(f"Graph edge {edge.id!r} has unsupported explicit scene_role {raw!r}")
    return normalized, "graph_ir.attributes.scene_role"


def _focus_nodes(
    graph: GraphIR,
    semantic: SemanticView | None,
    figure: FigureIR | None,
    focus_ids: Iterable[str],
    hops: int,
) -> set[str]:
    requested = list(dict.fromkeys(map(str, focus_ids)))
    if not requested:
        return {node.id for node in graph.nodes}
    if isinstance(hops, bool) or not isinstance(hops, int) or not 0 <= hops <= 20:
        raise ValidationError("Scene focus_hops must be an integer between 0 and 20")
    node_ids = {node.id for node in graph.nodes}
    selected: set[str] = set(requested).intersection(node_ids)
    if semantic is not None:
        for identifier in requested:
            provenance = semantic.semantic_to_source.get(identifier)
            if provenance is not None:
                selected.update(provenance.source_node_ids)
    if figure is not None:
        figure_objects = {item.id: item for item in figure.iter_objects()}
        for identifier in requested:
            item = figure_objects.get(identifier)
            if item is not None:
                selected.update(set(item.provenance.graph_ir_ids).intersection(node_ids))
    if not selected:
        raise ValidationError("None of the requested Scene focus IDs map to Graph IR nodes")
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in graph.edges:
        adjacency[edge.source].add(edge.target)
        adjacency[edge.target].add(edge.source)
    frontier = set(selected)
    for _ in range(hops):
        frontier = {neighbor for node_id in frontier for neighbor in adjacency[node_id]} - selected
        if not frontier:
            break
        selected.update(frontier)
    return selected


def _records(
    graph: GraphIR,
    selected: set[str],
    *,
    maximum_objects: int,
    focused: bool,
) -> tuple[list[_SourceRecord], dict[str, str], dict[str, Any]]:
    ordered = [node for node in _topological_nodes(graph) if node.id in selected]
    retained_edges = [edge for edge in graph.edges if edge.source in selected and edge.target in selected]
    if not ordered:
        return [], {}, {"summary_first": False, "source_node_count": 0, "source_edge_count": 0}
    needs_summary = len(ordered) + len(retained_edges) > maximum_objects
    if not needs_summary:
        records = []
        assignment = {}
        for node in ordered:
            role, _origin = _node_role(node)
            record = _SourceRecord(
                node.id,
                node.name,
                [node],
                [edge for edge in retained_edges if edge.source == node.id or edge.target == node.id],
                role,
                str(node.attributes.get("architecture_stage", "")),
                str(node.attributes.get("modality", "")),
            )
            records.append(record)
            assignment[node.id] = record.key
        return (
            records,
            assignment,
            {
                "summary_first": False,
                "source_node_count": len(ordered),
                "source_edge_count": len(retained_edges),
                "focused": focused,
            },
        )
    node_budget = max(1, maximum_objects // 2)
    chunk_size = max(1, math.ceil(len(ordered) / node_budget))
    chunks = [ordered[index : index + chunk_size] for index in range(0, len(ordered), chunk_size)]
    assignment = {node.id: f"summary-{chunk_index}" for chunk_index, chunk in enumerate(chunks) for node in chunk}
    records = []
    for chunk_index, chunk in enumerate(chunks):
        member_ids = {node.id for node in chunk}
        incident = [edge for edge in retained_edges if edge.source in member_ids or edge.target in member_ids]
        prominent: tuple[Node, str] | None = None
        for node in chunk:
            node_role, _origin = _node_role(node)
            if node_role not in {"unknown", "operation-block"} or any(
                token in node.name.casefold() for token in ("input", "output", "router", "merge", "attention", "token")
            ):
                prominent = (node, node_role)
                break
        record_name = prominent[0].name if prominent else f"Summary {chunk_index + 1} ({len(chunk)} operations)"
        record_role = prominent[1] if prominent else "operation-block"
        records.append(
            _SourceRecord(
                f"summary-{chunk_index}",
                record_name,
                chunk,
                incident,
                record_role,
                "summary",
                "",
                True,
            )
        )
    return (
        records,
        assignment,
        {
            "summary_first": True,
            "summary_reason": "source nodes plus edges exceeded the explicit Scene object budget",
            "source_node_count": len(ordered),
            "source_edge_count": len(retained_edges),
            "summary_object_count": len(records),
            "focused": focused,
        },
    )


def _shape_record(record: _SourceRecord) -> tuple[list[int | str | None], str, str]:
    tensors: list[TensorSpec] = [port.tensor for node in record.nodes for port in [*node.outputs, *node.inputs] if port.tensor is not None]
    tensor = tensors[0] if tensors else None
    shape = list(tensor.shape) if tensor is not None else [None]
    label = "[" + ", ".join("?" if value is None else str(value) for value in shape) + "]"
    return shape, label, tensor.dtype if tensor is not None else "unknown"


def _visual_size(record: _SourceRecord) -> list[float]:
    shape, _label, _dtype = _shape_record(record)
    numeric = [value for value in shape if isinstance(value, int) and not isinstance(value, bool) and value > 0]
    if not numeric:
        return [2.0, 1.8, 1.8]
    mapped = [max(1.0, min(4.5, 0.8 + math.log2(value + 1.0) * 0.32)) for value in numeric[-3:]]
    while len(mapped) < 3:
        mapped.insert(0, 1.2)
    return [2.0 if record.role == "operation-block" else mapped[0], mapped[1], mapped[2]]


def _position(
    record: _SourceRecord,
    index: int,
    total: int,
    layout_family: str,
    modalities: Sequence[str] = (),
) -> list[float]:
    x = (index - (total - 1) / 2.0) * 3.5
    stage = record.stage.strip().lower().replace("_", "-")
    if layout_family in {"unet", "diffusion-unet"} and stage in {"encoder", "down", "bottleneck", "decoder", "up", "output"}:
        if stage in {"encoder", "down"}:
            return [x, max(0.0, 3.0 - index * 0.7), min(3.0, index * 0.5)]
        if stage == "bottleneck":
            return [x, -2.0, 3.0]
        if stage in {"decoder", "up"}:
            return [x, min(3.0, index * 0.5), max(0.0, 3.0 - index * 0.3)]
    if layout_family == "moe":
        role = record.role
        if role == "moe-router":
            return [-3.0, 0.0, 0.0]
        if str(record.nodes[0].attributes.get("scene_role", "")) == "expert":
            expert_index = int(record.nodes[0].attributes.get("expert_index", index))
            return [0.5, (expert_index - 1.5) * 2.0, expert_index * 0.6]
        if role in {"merge", "fusion"}:
            return [4.0, 0.0, 0.0]
    if layout_family == "multimodal-fusion" and record.modality:
        lane = list(modalities).index(record.modality) if record.modality in modalities else index
        center = (len(modalities) - 1) / 2.0 if modalities else 0.0
        return [x, (lane - center) * 2.8, lane * 0.5]
    if layout_family == "transformer" and record.role in {"attention-head", "layer-plane"}:
        head = int(record.nodes[0].attributes.get("head_index", index))
        return [x, (head % 4 - 1.5) * 1.5, (head % 3) * 0.8]
    if layout_family == "diffusion-unet" and record.role == "timestep-conditioning":
        return [x, 3.5, 4.0]
    return [x, 0.0, 0.0]


def _semantic_ids_for_graph_ids(semantic: SemanticView | None, graph_ids: Iterable[str], level: str) -> list[str]:
    if semantic is None:
        return []
    return list(dict.fromkeys(semantic_id for graph_id in graph_ids for semantic_id in semantic.trace_semantic(str(graph_id), level=level)))


def _figure_links(figure: FigureIR | None, graph_ids: Iterable[str]) -> list[str]:
    if figure is None:
        return []
    requested = set(map(str, graph_ids))
    # Derive links from each Figure object's actual provenance instead of
    # trusting a possibly stale or tampered forward index.
    return [item.id for item in figure.iter_objects() if requested.intersection(map(str, item.provenance.graph_ir_ids))]


def _record_graph_ids(record: _SourceRecord) -> list[str]:
    node_ids = [node.id for node in record.nodes]
    port_ids = [port.id for node in record.nodes for port in [*node.inputs, *node.outputs]]
    edge_ids = [edge.id for edge in record.edges]
    return list(dict.fromkeys([*node_ids, *edge_ids, *port_ids]))


def _identifier_digest(values: Iterable[str]) -> str:
    encoded = "\n".join(map(str, values)).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _summary_provenance(
    record: _SourceRecord,
    *,
    compact: bool,
) -> tuple[list[str], dict[str, Any], list[str]]:
    """Return truthful exact or digest-backed provenance for one summary.

    Normal bounded summaries retain every source ID.  At 50k-model scale the
    duplicated object/forward/reverse indexes would itself violate the Scene
    JSON safety budget, so summaries retain deterministic representatives and
    collision-resistant ordered digests instead.  The record explicitly says
    that its representatives are not complete membership; focus/search can
    regenerate exact objects from the unchanged Graph IR.
    """

    graph_ids = _record_graph_ids(record)
    node_ids = record.node_ids
    if not record.summary or not compact:
        return graph_ids, {}, node_ids
    edge_ids = list(dict.fromkeys(edge.id for edge in record.edges))
    representatives = list(
        dict.fromkeys(
            [
                *node_ids[:2],
                *node_ids[-2:],
                *edge_ids[:1],
                *edge_ids[-1:],
            ]
        )
    )
    if not representatives:
        raise ValidationError("A compact Scene summary requires at least one source representative")
    operation_counts = Counter(node.op_type for node in record.nodes)
    summary = {
        "mode": "digest-and-bounded-representatives",
        "representatives_are_complete_membership": False,
        "representative_graph_ir_ids": representatives,
        "source_node_count": len(node_ids),
        "source_edge_count": len(edge_ids),
        "source_node_ids_sha256": _identifier_digest(node_ids),
        "source_edge_ids_sha256": _identifier_digest(edge_ids),
        "operation_type_counts": dict(sorted(operation_counts.items())),
        "exact_membership_available_via": "Graph IR summary/focus/search",
    }
    return representatives, summary, list(dict.fromkeys([*node_ids[:2], *node_ids[-2:]]))


def _provenance(
    graph_ids: list[str],
    *,
    semantic: SemanticView | None,
    semantic_level: str,
    figure: FigureIR | None,
    evidence: Mapping[str, Any],
) -> SceneProvenance:
    semantic_ids = _semantic_ids_for_graph_ids(semantic, graph_ids, semantic_level)
    figure_ids = _figure_links(figure, graph_ids)
    if semantic_ids:
        return SceneProvenance(
            "semantic_view",
            source_id=semantic_ids[0],
            graph_ir_ids=graph_ids,
            semantic_view_ids=semantic_ids,
            figure_ir_ids=figure_ids,
            evidence=dict(evidence),
        )
    return SceneProvenance(
        "graph_ir",
        source_id=graph_ids[0],
        graph_ir_ids=graph_ids,
        figure_ir_ids=figure_ids,
        evidence=dict(evidence),
    )


def _reconcile(scene: Scene, existing: Scene | None) -> None:
    if existing is None:
        return
    old = {item.id: item for item in existing.iter_objects()}
    selected: list[str] = []
    for item in scene.iter_objects():
        previous = old.get(item.id)
        if previous is None:
            continue
        item.visible = previous.visible
        item.material = deepcopy(previous.material)
        if previous.locked:
            item.transform = deepcopy(previous.transform)
            item.locked = True
        if previous.selected:
            item.selected = True
            selected.append(item.id)
    scene.selection_ids = selected
    previous_camera = next((camera for camera in existing.cameras if camera.id == existing.active_camera_id), None)
    if previous_camera is not None:
        scene.cameras[0] = deepcopy(previous_camera)
        scene.active_camera_id = previous_camera.id


def _architecture_object_kind(role: ArchitectureRole) -> str:
    return {
        "input-stem": "tensor-stack",
        "input": "tensor-volume",
        "embedding": "token-sequence",
        "attention": "attention-head",
        "feed-forward": "operation-block",
        "residual-norm": "layer-plane",
        "residual-stage": "operation-block",
        "encoder-level": "downsample",
        "down-path": "downsample",
        "bottleneck": "operation-block",
        "decoder-level": "upsample",
        "up-path": "upsample",
        "conditioning": "timestep-conditioning",
        "router": "moe-router",
        "experts": "operation-block",
        "weighted-combine": "merge",
        # The lane roles are substantive nodes; only the protected edges
        # between them and fusion use the ``multimodal-stream`` route kind.
        # Keeping the two concepts distinct prevents a role block with size
        # geometry from being projected as a dangling polyline.
        "image-lane": "tensor-stack",
        "text-lane": "token-sequence",
        "fusion": "fusion",
        "output-head": "tensor-volume",
    }.get(role.role, "operation-block")


def _spread_architecture_positions(
    positions: Mapping[str, Sequence[float]],
    *,
    factor: float = 1.85,
) -> dict[str, list[float]]:
    """Leave physical room for direct 7 pt labels around every role block."""

    return {
        role_id: [float(component) * factor for component in position]
        for role_id, position in positions.items()
    }


def _architecture_positions(evidence: ArchitectureEvidence) -> dict[str, list[float]]:
    roles = sorted(evidence.detected_roles, key=lambda item: (item.order, item.id))
    result: dict[str, list[float]] = {}
    if evidence.family == "unet":
        encoders = [role for role in roles if role.role == "encoder-level"]
        decoders = [role for role in roles if role.role == "decoder-level"]
        for index, role in enumerate(encoders):
            result[role.id] = [-8.0 + index * 3.0, 2.2 - index * 2.0, index * 0.8]
        for index, role in enumerate(decoders):
            result[role.id] = [2.0 + index * 3.0, -1.8 + index * 2.0, (len(decoders) - index - 1) * 0.8]
        for role in roles:
            if role.role == "input":
                result[role.id] = [-11.5, 3.4, 0.0]
            elif role.role == "bottleneck":
                result[role.id] = [0.0, -4.0, 2.8]
            elif role.role == "output-head":
                result[role.id] = [11.5, 3.4, 0.0]
        return _spread_architecture_positions(result)
    if evidence.family == "diffusion-unet":
        fixed = {
            "input": [-9.0, 0.0, 0.0],
            "conditioning": [0.0, 5.0, 4.2],
            "down-path": [-5.0, -1.2, 1.0],
            "bottleneck": [0.0, -3.3, 2.5],
            "up-path": [5.0, -1.2, 1.0],
            "output-head": [9.0, 0.0, 0.0],
        }
        return _spread_architecture_positions({role.id: list(fixed[role.role]) for role in roles})
    if evidence.family == "moe":
        fixed = {
            "input": [-9.0, 0.0, 0.0],
            "router": [-5.0, 3.0, 1.0],
            "experts": [0.0, -1.0, 2.0],
            "weighted-combine": [5.0, 0.0, 1.0],
            "output-head": [9.0, 0.0, 0.0],
        }
        return _spread_architecture_positions({role.id: list(fixed[role.role]) for role in roles})
    if evidence.family == "multimodal-fusion":
        fixed = {
            "image-lane": [-7.0, -3.0, 0.5],
            "text-lane": [-7.0, 3.0, 1.5],
            "fusion": [1.0, 0.0, 2.0],
            "output-head": [7.0, 0.0, 0.5],
        }
        return _spread_architecture_positions({role.id: list(fixed[role.role]) for role in roles})
    spacing = 4.0 if evidence.family == "resnet" else 4.4
    center = (len(roles) - 1) / 2.0
    for index, role in enumerate(roles):
        y = 0.0
        z = 0.0
        if evidence.family == "resnet" and role.role == "residual-stage":
            y = -0.35 * int(role.attributes.get("stage_index", index))
            z = 0.55 * int(role.attributes.get("stage_index", index))
        elif evidence.family == "transformer":
            y = {"attention": 1.6, "feed-forward": -1.4, "residual-norm": 1.2}.get(role.role, 0.0)
            z = {"attention": 1.2, "feed-forward": 1.5, "residual-norm": 2.2}.get(role.role, 0.0)
        result[role.id] = [(index - center) * spacing, y, z]
    return _spread_architecture_positions(result)


def _architecture_scene_role_pairs(evidence: ArchitectureEvidence) -> list[tuple[str, str]]:
    roles = sorted(evidence.detected_roles, key=lambda item: (item.order, item.id))
    by_kind: dict[str, list[ArchitectureRole]] = defaultdict(list)
    for role in roles:
        by_kind[role.role].append(role)
    if evidence.family == "multimodal-fusion":
        fusion, output = by_kind["fusion"][0], by_kind["output-head"][0]
        return [
            (by_kind["image-lane"][0].id, fusion.id),
            (by_kind["text-lane"][0].id, fusion.id),
            (fusion.id, output.id),
        ]
    if evidence.family == "moe":
        input_role, router = by_kind["input"][0], by_kind["router"][0]
        experts, combine, output = by_kind["experts"][0], by_kind["weighted-combine"][0], by_kind["output-head"][0]
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


def _architecture_route_points(
    source: Sequence[float],
    target: Sequence[float],
    *,
    role: str,
    attributes: Mapping[str, Any],
    publication_up: Sequence[float] = (0.0, 1.0, 0.0),
    layout_lane: int = 0,
) -> list[list[float]]:
    start, end = list(source), list(target)
    if role in {"residual-skip", "unet-skip"}:
        # Protected bypasses use lanes in the release camera's image plane.
        # Increasing arbitrary world Y/Z coordinates is not projection-safe:
        # the isometric camera can turn that movement into a lateral sweep
        # through unrelated blocks.  Translating along the camera-up basis
        # preserves each endpoint's projected x coordinate and puts the
        # middle segment visibly above the architecture.
        base_clearance = 7.0 if role == "unet-skip" else 5.5
        clearance = base_clearance + layout_lane * 0.9
        offset = [float(component) * clearance for component in publication_up]
        return [
            start,
            [start[axis] + offset[axis] for axis in range(3)],
            [end[axis] + offset[axis] for axis in range(3)],
            end,
        ]
    if role == "conditioning":
        # Conditioning starts in a dedicated upper role block, so a direct
        # source-to-target ray is both scientifically clearer and leaves the
        # outside edge free for its mandatory reader-visible label.
        return [start, end]
    if role == "expert-branch":
        expert_index = int(attributes.get("expert_index", 1))
        lane = (expert_index - 2.5) * 1.25
        return [start, [(start[0] + end[0]) / 2.0, lane, max(start[2], end[2]) + 1.0], end]
    if role == "multimodal-stream":
        return [start, [(start[0] + end[0]) / 2.0, start[1], max(start[2], end[2]) + 0.8], end]
    return [start, end]


def _architecture_scene_from_evidence(
    graph: GraphIR,
    evidence: ArchitectureEvidence,
    *,
    semantic_view: SemanticView,
    figure_ir: FigureIR | None,
    semantic_level: str,
    maximum_objects: int,
    existing_scene: Scene | None,
    projection: str,
    requested_family: str | None,
) -> Scene:
    """Materialize the same protected architecture roles/routes used by Figure IR."""

    evidence.validate(graph, source_digest=semantic_view.source_digest)
    role_graph = build_architecture_role_graph(graph, evidence)
    roles = sorted(evidence.detected_roles, key=lambda item: (item.order, item.id))
    required_objects = len(roles) + len(role_graph.edges)
    if required_objects > maximum_objects:
        raise ValidationError(
            f"The protected architecture summary requires {required_objects} Scene objects, above the requested limit {maximum_objects}",
            hint="Increase maximum_objects; protected scientific structure cannot be removed by information-density controls.",
        )
    scene = new_scene(f"{graph.name} · Architecture Evidence 3D", projection=projection)
    layer = scene.layers[0]
    # Row 1 of the view matrix is the normalized camera-up basis used by the
    # paper projection.  Architecture bypasses remain ordinary editable 3D
    # polylines; this basis only chooses a publication-safe authoring lane.
    publication_up = list(scene.active_camera().view_matrix()[1][:3])
    positions = _architecture_positions(evidence)
    node_map = graph.node_map()
    edge_map = graph.edge_map()
    port_map = {
        port.id: port
        for node in graph.nodes
        for port in (*node.inputs, *node.outputs)
    }
    object_by_role: dict[str, Object3D] = {}
    graph_to_scene: dict[str, set[str]] = defaultdict(set)
    semantic_to_scene: dict[str, set[str]] = defaultdict(set)
    figure_to_scene: dict[str, set[str]] = defaultdict(set)
    scene_to_source: dict[str, dict[str, Any]] = {}

    def register(item: Object3D) -> None:
        provenance = item.provenance
        for identifier in provenance.graph_ir_ids:
            graph_to_scene[identifier].add(item.id)
        for identifier in provenance.semantic_view_ids:
            semantic_to_scene[identifier].add(item.id)
        for identifier in provenance.figure_ir_ids:
            figure_to_scene[identifier].add(item.id)
        scene_to_source[item.id] = {
            "kind": provenance.kind,
            "source_id": provenance.source_id,
            "graph_ir_ids": list(provenance.graph_ir_ids),
            "semantic_view_ids": list(provenance.semantic_view_ids),
            "figure_ir_ids": list(provenance.figure_ir_ids),
        }

    for index, role in enumerate(roles):
        graph_ids = list(dict.fromkeys([
            *role.supporting_node_ids,
            *role.supporting_edge_ids,
            *role.supporting_port_ids,
        ]))
        members = [node_map[node_id] for node_id in role.supporting_node_ids]
        record = _SourceRecord(
            role.id,
            role.label,
            members,
            [edge_map[edge_id] for edge_id in role.supporting_edge_ids],
            _architecture_object_kind(role),
            role.role,
            str(role.attributes.get("modality", "")),
            True,
        )
        shape, shape_label, dtype = _shape_record(record)
        representative_tensor = next(
            (
                port_map[port_id].tensor
                for port_id in role.supporting_port_ids
                if port_id in port_map and port_map[port_id].tensor is not None
            ),
            None,
        )
        if representative_tensor is not None:
            shape = list(representative_tensor.shape)
            shape_label = "[" + ", ".join("?" if value is None else str(value) for value in shape) + "]"
            dtype = representative_tensor.dtype
        provenance = _provenance(
            graph_ids,
            semantic=semantic_view,
            semantic_level=semantic_level,
            figure=figure_ir,
            evidence={
                "architecture_role_id": role.id,
                "architecture_role": role.role,
                "node_ids": list(role.supporting_node_ids),
                "edge_ids": list(role.supporting_edge_ids),
                "port_ids": list(role.supporting_port_ids),
                "reasons": list(role.reasons),
                "confidence": role.confidence,
            },
        )
        kind = _architecture_object_kind(role)
        color = (
            _COLORS["attention"] if role.role == "attention"
            else _COLORS["expert"] if role.role == "experts"
            else _COLORS["modality_image"] if role.role == "image-lane"
            else _COLORS["modality_text"] if role.role == "text-lane"
            else _COLORS["conditioning"] if role.role == "conditioning"
            else _COLORS["tensor"] if kind.startswith("tensor") or kind == "token-sequence"
            else _COLORS["accent"] if role.role in {"fusion", "weighted-combine", "bottleneck"}
            else _COLORS["operation"]
        )
        size = _visual_size(record)
        if role.repeat_count > 1:
            size[2] = min(5.5, size[2] + math.log2(role.repeat_count + 1) * 0.55)
        item = Object3D.create(
            kind,
            role.label,
            {"size": size},
            provenance,
            transform=Transform3D(positions[role.id]),
            material=_template_material(color),
            identity=f"model-scene:architecture-role:{role.id}",
            metadata={
                "graph_ir_node_ids": list(role.supporting_node_ids),
                "graph_ir_edge_ids": list(role.supporting_edge_ids),
                "graph_ir_port_ids": list(role.supporting_port_ids),
                "semantic_view_ids": list(provenance.semantic_view_ids),
                "figure_ir_ids": list(provenance.figure_ir_ids),
                "tensor_shape": shape,
                "architecture_tensor_shape": shape,
                "shape_label": shape_label,
                "dtype": dtype,
                "architecture_tensor_dtype": dtype,
                "unknown_dimensions_preserved": any(value is None or isinstance(value, str) for value in shape),
                "architecture_family": evidence.family,
                "architecture_role_id": role.id,
                "architecture_role": role.role,
                "architecture_role_origin": "architecture-evidence",
                "architecture_evidence_digest": evidence.provenance_digest,
                "architecture_role_graph_digest": role_graph.digest,
                "semantic_level": semantic_level,
                "architecture_confidence": role.confidence,
                "architecture_reasons": list(role.reasons),
                "architecture_attributes": deepcopy(role.attributes),
                "repeat_count": role.repeat_count,
                "repeat_label": f"×{role.repeat_count}" if role.repeat_count > 1 else None,
                "protected_semantic_structure": role.protected,
                "summary": True,
                "summary_member_count": len(role.supporting_node_ids),
                "expansion_trace_available": True,
                "expand_focus_ids": list(role.supporting_node_ids),
                "expanded_member_node_ids": deepcopy(role.attributes.get("expanded_members", [])),
                "visual_geometry_mapping": "bounded-logarithmic-authoring-cue",
                "visual_geometry_is_literal_tensor_size": False,
            },
            order=index * 10,
        )
        layer.objects.append(item)
        object_by_role[role.id] = item
        register(item)

    represented_edge_ids = {edge_id for role in roles for edge_id in role.supporting_edge_ids}

    def add_route(
        source_role_id: str,
        target_role_id: str,
        source_edge_ids: Sequence[str],
        *,
        label: str,
        route_role: str,
        identity: str,
        attributes: Mapping[str, Any],
        protected: bool,
        order: int,
        direction: str,
        role_graph_edge_id: str,
        layout_lane: int = 0,
    ) -> None:
        traced = [edge_map[edge_id] for edge_id in source_edge_ids]
        if not traced:
            return
        graph_ids = list(dict.fromkeys([
            *source_edge_ids,
            *(edge.source for edge in traced),
            *(edge.target for edge in traced),
            *(str(port_id) for edge in traced for port_id in (edge.source_port, edge.target_port) if port_id),
        ]))
        provenance = _provenance(
            graph_ids,
            semantic=semantic_view,
            semantic_level=semantic_level,
            figure=figure_ir,
            evidence={
                "architecture_route_role": route_role,
                "edge_ids": list(source_edge_ids),
                "protected_semantic_structure": protected,
                "attributes": dict(attributes),
            },
        )
        source_object, target_object = object_by_role[source_role_id], object_by_role[target_role_id]
        points = _architecture_route_points(
            source_object.transform.position,
            target_object.transform.position,
            role=route_role,
            attributes=attributes,
            publication_up=publication_up,
            layout_lane=layout_lane,
        )
        kind = route_role if route_role in _EDGE_ROLES else "tube"
        connector = Object3D.create(
            kind,
            label,
            {"points": points, "radius": 0.09 if protected else 0.065},
            provenance,
            material=_template_material(
                _COLORS["skip"] if route_role in {"residual-skip", "unet-skip"}
                else _COLORS["conditioning"] if route_role == "conditioning"
                else _COLORS["accent"] if protected
                else "#475569"
            ),
            identity=f"model-scene:architecture-route:{identity}",
            metadata={
                "graph_ir_edge_ids": list(source_edge_ids),
                "semantic_view_ids": list(provenance.semantic_view_ids),
                "figure_ir_ids": list(provenance.figure_ir_ids),
                "endpoint_object_ids": [source_object.id, target_object.id],
                "endpoint_role_ids": [source_role_id, target_role_id],
                "architecture_role": route_role,
                "architecture_route_role": route_role,
                "architecture_route_id": identity if protected else None,
                "architecture_role_graph_edge_id": role_graph_edge_id,
                "architecture_direction": direction,
                "architecture_evidence_digest": evidence.provenance_digest,
                "architecture_role_graph_digest": role_graph.digest,
                "architecture_route_attributes": dict(attributes),
                "architecture_role_origin": "architecture-evidence" if protected else "source-topology",
                "protected_semantic_structure": protected,
                "bundled_edge_count": len(source_edge_ids),
            },
            order=100_000 + order,
        )
        layer.objects.append(connector)
        register(connector)
        represented_edge_ids.update(source_edge_ids)

    critical_lane = 0
    for route_order, role_edge in enumerate(role_graph.edges):
        layout_lane = critical_lane if role_edge.critical else 0
        if role_edge.critical:
            critical_lane += 1
        add_route(
            role_edge.source_role_id,
            role_edge.target_role_id,
            role_edge.supporting_edge_ids,
            label=role_edge.label,
            route_role=role_edge.role if role_edge.critical else "arrow",
            identity=role_edge.id,
            attributes=role_edge.attributes,
            protected=role_edge.critical,
            order=route_order,
            layout_lane=layout_lane,
            direction=role_edge.direction,
            role_graph_edge_id=role_edge.id,
        )

    omitted_noncritical = sorted(set(edge_map) - represented_edge_ids)
    _reconcile(scene, existing_scene)
    scene.metadata.update({
        "architecture_family": evidence.family,
        "evidenced_architecture_family": evidence.family,
        "requested_layout_family": requested_family,
        "layout_family": evidence.family,
        "architecture_evidence": evidence.to_dict(),
        "architecture_role_graph": role_graph.to_dict(),
        "architecture_role_graph_digest": role_graph.digest,
        "architecture_name_inference_used": False,
        "graph_ir": {
            "name": graph.name,
            "ir_version": graph.ir_version,
            "node_count": len(graph.nodes),
            "edge_count": len(graph.edges),
        },
        "semantic_view": {
            "version": semantic_view.semantic_version,
            "source_digest": semantic_view.source_digest,
            "selected_level": semantic_level,
            "view": "paper",
        },
        "model_scene_pipeline": {
            "version": MODEL_SCENE_PIPELINE_VERSION,
            "mode": "architecture-evidence-summary",
            "bounded_object_limit": maximum_objects,
            "visible_object_count": len(layer.objects),
            "summary_first": True,
            "protected_semantic_summary": True,
            "information_density_may_remove_protected_structure": False,
            "focus_ids": [],
            "focus_hops": 0,
            "unknown_dimensions_are_not_inferred": True,
            "visual_geometry_is_not_a_literal_tensor_measurement": True,
            "architecture_role_count": len(roles),
            "critical_route_count": len(evidence.critical_routes),
            "landed_critical_route_count": sum(edge.critical for edge in role_graph.edges),
            "omitted_critical_edges": 0,
            "omitted_critical_edge_ids": [],
            "omitted_noncritical_edge_count": len(omitted_noncritical),
        },
        "omitted_connector_graph_ir_ids": omitted_noncritical,
        "omitted_connector_summary": {
            "count": len(omitted_noncritical),
            "critical_count": 0,
            "ids_sha256": _identifier_digest(omitted_noncritical),
            "ids_are_complete": True,
        },
        "provenance_index": {
            "graph_to_scene": {key: sorted(value) for key, value in sorted(graph_to_scene.items())},
            "semantic_to_scene": {key: sorted(value) for key, value in sorted(semantic_to_scene.items())},
            "figure_to_scene": {key: sorted(value) for key, value in sorted(figure_to_scene.items())},
            "scene_to_source": dict(sorted(scene_to_source.items())),
        },
    })
    scene.validate()
    report = validate_model_scene_provenance(scene, graph, semantic_view, figure_ir)
    if not report["passed"]:
        raise ValidationError(
            "Generated Architecture Evidence Scene provenance does not match its Graph/Semantic/Figure evidence",
            details={"provenance_validation": report},
        )
    return scene


def model_scene_from_graph(
    graph: GraphIR,
    *,
    semantic_view: SemanticView | None = None,
    figure_ir: FigureIR | None = None,
    architecture: str | None = None,
    level: str = "operation",
    view: str = "faithful",
    focus_ids: Iterable[str] = (),
    focus_hops: int = 1,
    maximum_objects: int = MAXIMUM_MODEL_SCENE_OBJECTS,
    existing_scene: Scene | None = None,
    projection: str = "orthographic",
) -> Scene:
    """Generate a bounded editable Scene from exact source evidence.

    ``architecture`` selects a layout vocabulary.  It is never treated as an
    evidence claim; ``evidenced_architecture_family`` remains ``unknown`` unless
    Graph IR/Semantic View carries a structured, source-ID-backed record.
    """

    graph.validate()
    semantic_level = normalize_semantic_level(level)
    if view not in {"faithful", "paper"}:
        raise ValidationError("Scene view must be 'faithful' or 'paper'")
    if semantic_view is not None:
        semantic_view.validate(graph)
    if figure_ir is not None:
        figure_ir.validate()
    if isinstance(maximum_objects, bool) or not isinstance(maximum_objects, int) or not 4 <= maximum_objects <= MAX_SCENE_OBJECTS:
        raise ValidationError(f"Scene maximum_objects must be an integer in [4, {MAX_SCENE_OBJECTS}]")
    requested_family = _family(architecture) if architecture else None
    evidenced_family, architecture_record = _architecture_evidence(graph, semantic_view)
    if requested_family and evidenced_family != "unknown" and requested_family != evidenced_family:
        raise ValidationError(f"Requested Scene layout {requested_family!r} conflicts with evidence-backed architecture {evidenced_family!r}")
    layout_family = requested_family or (evidenced_family if evidenced_family != "unknown" else "cnn")
    focus = list(dict.fromkeys(map(str, focus_ids)))
    if (
        view == "paper"
        and not focus
        and semantic_view is not None
        and semantic_view.architecture_evidence is not None
        and semantic_view.architecture_evidence.family != "unknown"
    ):
        return _architecture_scene_from_evidence(
            graph,
            semantic_view.architecture_evidence,
            semantic_view=semantic_view,
            figure_ir=figure_ir,
            semantic_level=semantic_level,
            maximum_objects=maximum_objects,
            existing_scene=existing_scene,
            projection=projection,
            requested_family=requested_family,
        )
    selected = _focus_nodes(graph, semantic_view, figure_ir, focus, focus_hops)
    record_budget = min(maximum_objects, 28) if view == "paper" and not focus else maximum_objects
    records, assignment, pipeline = _records(
        graph,
        selected,
        maximum_objects=record_budget,
        focused=bool(focus),
    )
    pipeline["requested_object_budget"] = maximum_objects
    pipeline["record_materialization_budget"] = record_budget
    pipeline["paper_aggregation"] = view == "paper" and not focus
    scene = new_scene(f"{graph.name} · 3D", projection=projection)
    layer = scene.layers[0]
    graph_to_scene: dict[str, set[str]] = defaultdict(set)
    semantic_to_scene: dict[str, set[str]] = defaultdict(set)
    figure_to_scene: dict[str, set[str]] = defaultdict(set)
    scene_to_source: dict[str, dict[str, Any]] = {}
    object_by_record: dict[str, Object3D] = {}
    modality_lanes = sorted({record.modality for record in records if record.modality})
    compact_summary_provenance = bool(pipeline["summary_first"] and int(pipeline["source_node_count"]) > MAXIMUM_EXACT_SUMMARY_SOURCE_IDS)

    def register(item: Object3D) -> None:
        provenance = item.provenance
        for identifier in provenance.graph_ir_ids:
            graph_to_scene[identifier].add(item.id)
        for identifier in provenance.semantic_view_ids:
            semantic_to_scene[identifier].add(item.id)
        for identifier in provenance.figure_ir_ids:
            figure_to_scene[identifier].add(item.id)
        scene_to_source[item.id] = {
            "kind": provenance.kind,
            "source_id": provenance.source_id,
            "graph_ir_ids": list(provenance.graph_ir_ids),
            "semantic_view_ids": list(provenance.semantic_view_ids),
            "figure_ir_ids": list(provenance.figure_ir_ids),
        }

    for index, record in enumerate(records):
        graph_ids, compact_summary, displayed_node_ids = _summary_provenance(
            record,
            compact=compact_summary_provenance,
        )
        shape, shape_label, dtype = _shape_record(record)
        role_origin = "summary-no-architecture-claim" if record.summary else _node_role(record.nodes[0])[1]
        provenance = _provenance(
            graph_ids,
            semantic=semantic_view,
            semantic_level=semantic_level,
            figure=figure_ir,
            evidence={
                "node_ids": displayed_node_ids,
                "op_types": (sorted({node.op_type for node in record.nodes}) if compact_summary else [node.op_type for node in record.nodes]),
                "scene_role_origin": role_origin,
                "summary": record.summary,
                "summary_source": compact_summary,
                "tensor_shape": shape,
                "dtype": dtype,
                "visual_geometry_mapping": "nonliteral bounded authoring cue",
            },
        )
        role = record.role
        item = Object3D.create(
            role,
            record.name,
            {"size": _visual_size(record)},
            provenance,
            transform=Transform3D(_position(record, index, len(records), layout_family, modality_lanes)),
            material=_template_material(
                _COLORS["unknown"] if role_origin.startswith("unknown") else (_COLORS["tensor"] if role.startswith("tensor") else _COLORS["operation"])
            ),
            identity=f"model-scene:node:{record.key}",
            metadata={
                "graph_ir_node_ids": displayed_node_ids,
                "semantic_view_ids": list(provenance.semantic_view_ids),
                "figure_ir_ids": list(provenance.figure_ir_ids),
                "tensor_shape": shape,
                "shape_label": shape_label,
                "dtype": dtype,
                "unknown_dimensions_preserved": any(value is None or isinstance(value, str) for value in shape),
                "visual_geometry_mapping": "bounded-logarithmic-authoring-cue",
                "visual_geometry_is_literal_tensor_size": False,
                "architecture_role": record.role if role_origin != "unknown-no-explicit-architecture-role" else "unknown",
                "architecture_role_origin": role_origin,
                "evidenced_architecture_family": evidenced_family,
                "layout_family": layout_family,
                "summary": record.summary,
                "summary_member_count": len(record.nodes),
                "summary_source": compact_summary,
            },
            order=index * 10,
        )
        layer.objects.append(item)
        object_by_record[record.key] = item
        register(item)

    retained_edges = [edge for edge in graph.edges if edge.source in selected and edge.target in selected]
    edge_bundles: dict[tuple[str, str, str], list[Edge]] = defaultdict(list)
    for edge in retained_edges:
        source_key, target_key = assignment.get(edge.source), assignment.get(edge.target)
        if not source_key or not target_key or source_key == target_key:
            continue
        role, _role_origin = _edge_role(edge)
        edge_bundles[(source_key, target_key, role)].append(edge)
    connector_budget = max(0, maximum_objects - len(layer.objects))
    omitted_edge_ids: list[str] = []
    paper_incidence: dict[str, int] = defaultdict(int)
    for route_index, ((source_key, target_key, role), edges) in enumerate(sorted(edge_bundles.items())):
        if route_index >= connector_budget or (view == "paper" and not focus and (paper_incidence[source_key] >= 5 or paper_incidence[target_key] >= 5)):
            omitted_edge_ids.extend(edge.id for edge in edges)
            continue
        source_object, target_object = object_by_record[source_key], object_by_record[target_key]
        start, end = source_object.transform.position, target_object.transform.position
        if role in {"residual-skip", "unet-skip"}:
            depth = max(start[2], end[2]) + 2.5
            points = [start, [start[0], start[1] + 2.0, depth], [end[0], end[1] + 2.0, depth], end]
        elif role in {"expert-branch", "multimodal-stream", "qkv-branch"}:
            middle = [(start[0] + end[0]) / 2.0, start[1], max(start[2], end[2]) + 1.0]
            points = [start, middle, end]
        else:
            points = [start, end]
        graph_ids = list(
            dict.fromkeys(
                [
                    *(edge.id for edge in edges),
                    *(str(port_id) for edge in edges for port_id in (edge.source_port, edge.target_port) if port_id),
                    *(edge.source for edge in edges),
                    *(edge.target for edge in edges),
                ]
            )
        )
        role_origins = sorted({_edge_role(edge)[1] for edge in edges})
        provenance = _provenance(
            graph_ids,
            semantic=semantic_view,
            semantic_level=semantic_level,
            figure=figure_ir,
            evidence={
                "edge_ids": [edge.id for edge in edges],
                "source_ports": [edge.source_port for edge in edges],
                "target_ports": [edge.target_port for edge in edges],
                "scene_role_origin": role_origins,
            },
        )
        connector = Object3D.create(
            role,
            edges[0].label or f"{source_object.name} to {target_object.name}",
            {"points": [list(point) for point in points], "radius": 0.07},
            provenance,
            material=_template_material(_COLORS["skip"] if role in {"residual-skip", "unet-skip"} else "#475569"),
            identity=f"model-scene:edge:{':'.join(edge.id for edge in edges)}",
            metadata={
                "graph_ir_edge_ids": [edge.id for edge in edges],
                "semantic_view_ids": list(provenance.semantic_view_ids),
                "figure_ir_ids": list(provenance.figure_ir_ids),
                "endpoint_object_ids": [source_object.id, target_object.id],
                "architecture_role": role if role_origins != ["graph_ir-edge-generic"] else "unknown",
                "architecture_role_origin": role_origins,
                "bundled_edge_count": len(edges),
            },
            order=100_000 + route_index,
        )
        layer.objects.append(connector)
        register(connector)
        paper_incidence[source_key] += 1
        paper_incidence[target_key] += 1

    _reconcile(scene, existing_scene)
    scene.metadata.update(
        {
            "architecture_family": evidenced_family,
            "evidenced_architecture_family": evidenced_family,
            "requested_layout_family": requested_family,
            "layout_family": layout_family,
            "architecture_evidence": architecture_record,
            "architecture_name_inference_used": False,
            "graph_ir": {
                "name": graph.name,
                "ir_version": graph.ir_version,
                "node_count": len(graph.nodes),
                "edge_count": len(graph.edges),
            },
            "semantic_view": {
                "version": semantic_view.semantic_version if semantic_view else None,
                "source_digest": semantic_view.source_digest if semantic_view else None,
                "selected_level": semantic_level,
                "view": view,
            },
            "model_scene_pipeline": {
                "version": MODEL_SCENE_PIPELINE_VERSION,
                "bounded_object_limit": maximum_objects,
                "visible_object_count": len(layer.objects),
                "summary_first": bool(pipeline["summary_first"]),
                "summary_provenance_mode": ("digest-and-bounded-representatives" if compact_summary_provenance else "exact-source-ids"),
                "summary_provenance_compaction_threshold": MAXIMUM_EXACT_SUMMARY_SOURCE_IDS,
                "focus_ids": focus,
                "focus_hops": focus_hops,
                "unknown_dimensions_are_not_inferred": True,
                "visual_geometry_is_not_a_literal_tensor_measurement": True,
                **pipeline,
            },
            "omitted_connector_graph_ir_ids": (
                sorted(set(omitted_edge_ids)) if len(omitted_edge_ids) <= MAXIMUM_EXACT_SUMMARY_SOURCE_IDS else sorted(set(omitted_edge_ids))[:8]
            ),
            "omitted_connector_summary": {
                "count": len(set(omitted_edge_ids)),
                "ids_sha256": _identifier_digest(sorted(set(omitted_edge_ids))),
                "ids_are_complete": len(omitted_edge_ids) <= MAXIMUM_EXACT_SUMMARY_SOURCE_IDS,
            },
            "provenance_index": {
                "graph_to_scene": {key: sorted(value) for key, value in sorted(graph_to_scene.items())},
                "semantic_to_scene": {key: sorted(value) for key, value in sorted(semantic_to_scene.items())},
                "figure_to_scene": {key: sorted(value) for key, value in sorted(figure_to_scene.items())},
                "scene_to_source": dict(sorted(scene_to_source.items())),
            },
        }
    )
    scene.validate()
    report = validate_model_scene_provenance(scene, graph, semantic_view, figure_ir)
    if not report["passed"]:
        raise ValidationError(
            "Generated Scene provenance does not match its Graph/Semantic/Figure evidence",
            details={"provenance_validation": report},
        )
    return scene


def validate_model_scene_provenance(
    scene: Scene,
    graph: GraphIR,
    semantic_view: SemanticView | None = None,
    figure_ir: FigureIR | None = None,
) -> dict[str, Any]:
    """Validate exact forward/reverse Graph/Semantic/Figure Scene indexes."""

    graph.validate()
    failures: list[dict[str, Any]] = []
    try:
        scene.validate()
    except ValidationError as exc:
        failures.append({"scene_invalid": str(exc)})
    if semantic_view is not None:
        try:
            semantic_view.validate(graph)
        except ValidationError as exc:
            failures.append({"semantic_view_invalid": str(exc)})
    if figure_ir is not None:
        try:
            figure_ir.validate()
        except ValidationError as exc:
            failures.append({"figure_ir_invalid": str(exc)})
    known_graph = _graph_ids(graph)
    semantic_entities = {entity.id: entity for entity in semantic_view.entities} if semantic_view else {}
    known_semantic = set(semantic_entities)
    figure_objects = {item.id: item for item in figure_ir.iter_objects()} if figure_ir else {}
    known_figure = set(figure_objects)
    semantic_metadata = scene.metadata.get("semantic_view", {})
    selected_semantic_level = str(semantic_metadata.get("selected_level", "operation")) if isinstance(semantic_metadata, dict) else "operation"
    claimed = {item.id: item for item in scene.iter_objects() if item.provenance.kind in {"graph_ir", "semantic_view", "figure_ir"}}
    expected_graph: dict[str, set[str]] = defaultdict(set)
    expected_semantic: dict[str, set[str]] = defaultdict(set)
    expected_figure: dict[str, set[str]] = defaultdict(set)
    expected_reverse: dict[str, dict[str, Any]] = {}
    for item in claimed.values():
        provenance = item.provenance
        missing_graph = sorted(set(provenance.graph_ir_ids) - known_graph)
        if missing_graph:
            failures.append({"object_id": item.id, "missing_graph_ir_ids": missing_graph})
        if provenance.kind == "semantic_view" and semantic_view is None:
            failures.append({"object_id": item.id, "semantic_view_not_supplied": True})
        if provenance.kind == "graph_ir" and provenance.source_id not in provenance.graph_ir_ids:
            failures.append({"object_id": item.id, "graph_primary_source_is_not_claimed": provenance.source_id})
        if provenance.kind == "semantic_view" and provenance.source_id not in provenance.semantic_view_ids:
            failures.append({"object_id": item.id, "semantic_primary_source_is_not_claimed": provenance.source_id})
        if provenance.kind == "figure_ir" and provenance.source_id not in provenance.figure_ir_ids:
            failures.append({"object_id": item.id, "figure_primary_source_is_not_claimed": provenance.source_id})
        missing_semantic = sorted(set(provenance.semantic_view_ids) - known_semantic)
        if missing_semantic:
            failures.append({"object_id": item.id, "missing_semantic_view_ids": missing_semantic})
        if semantic_view is not None and provenance.kind == "semantic_view":
            expected_semantic_ids = set(
                _semantic_ids_for_graph_ids(
                    semantic_view,
                    provenance.graph_ir_ids,
                    selected_semantic_level,
                )
            )
            if set(provenance.semantic_view_ids) != expected_semantic_ids:
                failures.append(
                    {
                        "object_id": item.id,
                        "semantic_links_disagree_with_graph_evidence": {
                            "expected": sorted(expected_semantic_ids),
                            "actual": sorted(provenance.semantic_view_ids),
                        },
                    }
                )
        if provenance.figure_ir_ids and figure_ir is None:
            failures.append({"object_id": item.id, "figure_ir_not_supplied": True})
        missing_figure = sorted(set(provenance.figure_ir_ids) - known_figure)
        if missing_figure:
            failures.append({"object_id": item.id, "missing_figure_ir_ids": missing_figure})
        if figure_ir is not None:
            expected_figure_ids = set(_figure_links(figure_ir, provenance.graph_ir_ids))
            if set(provenance.figure_ir_ids) != expected_figure_ids:
                failures.append(
                    {
                        "object_id": item.id,
                        "figure_links_disagree_with_shared_graph_evidence": {
                            "expected": sorted(expected_figure_ids),
                            "actual": sorted(provenance.figure_ir_ids),
                        },
                    }
                )
        for semantic_id in set(provenance.semantic_view_ids).intersection(semantic_entities):
            entity = semantic_entities[semantic_id]
            semantic_graph_ids = set(entity.provenance.source_node_ids) | set(entity.provenance.source_edge_ids)
            if semantic_graph_ids.isdisjoint(provenance.graph_ir_ids):
                failures.append({"object_id": item.id, "semantic_entity_has_no_shared_graph_evidence": semantic_id})
        for figure_id in set(provenance.figure_ir_ids).intersection(figure_objects):
            figure_graph_ids = set(figure_objects[figure_id].provenance.graph_ir_ids)
            if figure_graph_ids and figure_graph_ids.isdisjoint(provenance.graph_ir_ids):
                failures.append({"object_id": item.id, "figure_object_has_no_shared_graph_evidence": figure_id})
        for identifier in provenance.graph_ir_ids:
            expected_graph[identifier].add(item.id)
        for identifier in provenance.semantic_view_ids:
            expected_semantic[identifier].add(item.id)
        for identifier in provenance.figure_ir_ids:
            expected_figure[identifier].add(item.id)
        expected_reverse[item.id] = {
            "kind": provenance.kind,
            "source_id": provenance.source_id,
            "graph_ir_ids": list(provenance.graph_ir_ids),
            "semantic_view_ids": list(provenance.semantic_view_ids),
            "figure_ir_ids": list(provenance.figure_ir_ids),
        }

    index = scene.metadata.get("provenance_index", {})
    if not isinstance(index, dict):
        failures.append({"malformed_provenance_index": type(index).__name__})
        index = {}

    def normalize_forward(name: str, raw: Any, known: set[str]) -> dict[str, set[str]]:
        if not isinstance(raw, dict):
            failures.append({f"malformed_{name}": type(raw).__name__})
            return {}
        result: dict[str, set[str]] = {}
        for source_id, raw_object_ids in raw.items():
            if str(source_id) not in known:
                failures.append({name: str(source_id), "orphan_source_id": True})
            if not isinstance(raw_object_ids, list):
                failures.append({name: str(source_id), "object_ids_must_be_array": True})
                continue
            object_ids = list(map(str, raw_object_ids))
            if len(object_ids) != len(set(object_ids)):
                failures.append({name: str(source_id), "duplicate_object_ids": object_ids})
            missing_objects = sorted(set(object_ids) - set(claimed))
            if missing_objects:
                failures.append({name: str(source_id), "orphan_scene_object_ids": missing_objects})
            result[str(source_id)] = set(object_ids)
        return result

    actual_graph = normalize_forward("graph_to_scene", index.get("graph_to_scene", {}), known_graph)
    actual_semantic = normalize_forward("semantic_to_scene", index.get("semantic_to_scene", {}), known_semantic)
    actual_figure = normalize_forward("figure_to_scene", index.get("figure_to_scene", {}), known_figure)
    for name, actual, expected in (
        ("graph_to_scene", actual_graph, expected_graph),
        ("semantic_to_scene", actual_semantic, expected_semantic),
        ("figure_to_scene", actual_figure, expected_figure),
    ):
        actual_links = {(source_id, object_id) for source_id, objects in actual.items() for object_id in objects}
        expected_links = {(source_id, object_id) for source_id, objects in expected.items() for object_id in objects}
        if actual_links != expected_links:
            failures.append(
                {
                    f"{name}_bidirectional_mismatch": {
                        "missing": sorted(expected_links - actual_links),
                        "extra": sorted(actual_links - expected_links),
                    }
                }
            )
    reverse = index.get("scene_to_source", {})
    if not isinstance(reverse, dict):
        failures.append({"malformed_scene_to_source": type(reverse).__name__})
    elif reverse != expected_reverse:
        failures.append(
            {
                "scene_to_source_bidirectional_mismatch": {
                    "expected_object_ids": sorted(expected_reverse),
                    "actual_object_ids": sorted(map(str, reverse)),
                }
            }
        )
    # Architecture metadata is a contract of this automatic generator, not a
    # requirement imposed on hand-authored Scene documents that merely link
    # exact Graph/Figure evidence.
    pipeline_metadata = scene.metadata.get("model_scene_pipeline")
    if isinstance(pipeline_metadata, dict) and pipeline_metadata.get("mode") != "explicit-template":
        metadata_family = str(scene.metadata.get("evidenced_architecture_family", "unknown"))
        actual_family, _record = _architecture_evidence(graph, semantic_view)
        if metadata_family != actual_family:
            failures.append({"architecture_evidence_mismatch": {"scene": metadata_family, "source": actual_family}})
        if scene.metadata.get("architecture_name_inference_used") is not False:
            failures.append({"architecture_name_inference_must_be_false": True})
    return {
        "schema_version": "nndv-model-scene-provenance-1",
        "linked_object_count": len(claimed),
        "known_graph_ir_id_count": len(known_graph),
        "known_semantic_entity_count": len(known_semantic),
        "known_figure_object_count": len(known_figure),
        "failures": failures,
        "passed": not failures,
    }


# Spelling aliases keep callers terse without changing canonical family IDs.
template_cnn_scene = cnn_scene_template
template_resnet_scene = resnet_scene_template
template_unet_scene = unet_scene_template
template_transformer_scene = transformer_scene_template
template_moe_scene = moe_scene_template
template_multimodal_fusion_scene = multimodal_fusion_scene_template
template_diffusion_unet_scene = diffusion_unet_scene_template


__all__ = [
    "ARCHITECTURE_FAMILIES",
    "MAXIMUM_MODEL_SCENE_OBJECTS",
    "MODEL_SCENE_PIPELINE_VERSION",
    "cnn_scene_template",
    "diffusion_unet_scene_template",
    "model_scene_from_graph",
    "moe_scene_template",
    "multimodal_fusion_scene_template",
    "resnet_scene_template",
    "scene_template",
    "template_cnn_scene",
    "template_diffusion_unet_scene",
    "template_moe_scene",
    "template_multimodal_fusion_scene",
    "template_resnet_scene",
    "template_transformer_scene",
    "template_unet_scene",
    "transformer_scene_template",
    "unet_scene_template",
    "validate_model_scene_provenance",
]
