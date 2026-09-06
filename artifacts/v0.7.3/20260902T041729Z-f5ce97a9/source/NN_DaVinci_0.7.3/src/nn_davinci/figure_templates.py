"""Bundled, original, offline scientific-figure templates."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .errors import ValidationError
from .figure_ir import (
    FigureIR,
    FigureObject,
    FigureProvenance,
    FigureStyle,
    new_figure,
)
from .ir import Edge, GraphIR, Node, Port, TensorSpec, stable_id
from .project import Project


FIGURE_TEMPLATE_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class TemplateSpec:
    slug: str
    title: str
    roles: tuple[str, ...]
    operators: tuple[str, ...]
    shapes: tuple[tuple[int | str | None, ...], ...]
    edges: tuple[tuple[int, int, str], ...]
    description: str


TEMPLATE_SPECS: tuple[TemplateSpec, ...] = (
    TemplateSpec(
        "cnn-feature-pipeline", "CNN feature pipeline",
        ("Input", "Stem", "Feature stage", "Classifier"),
        ("generic", "convolution", "convolution", "generic"),
        (("B", 3, "H", "W"), ("B", 64, "H/2", "W/2"), ("B", "C", "H/s", "W/s"), ("B", "K")),
        ((0, 1, "data"), (1, 2, "data"), (2, 3, "data")),
        "Editable feature-extraction stages with symbolic spatial dimensions.",
    ),
    TemplateSpec(
        "resnet-overview", "ResNet overview + bottleneck detail",
        ("Input", "Residual stage", "Bottleneck", "Add", "Output"),
        ("generic", "convolution", "convolution", "addition", "generic"),
        (("B", "C", "H", "W"), ("B", "C", "H", "W"), ("B", "C'", "H", "W"), ("B", "C", "H", "W"), ("B", "K")),
        ((0, 1, "data"), (1, 2, "data"), (2, 3, "data"), (1, 3, "residual"), (3, 4, "data")),
        "Overview and editable bottleneck detail; the skip is visually explicit.",
    ),
    TemplateSpec(
        "unet-encoder-decoder", "U-Net encoder/decoder + skip",
        ("Input", "Encoder", "Bottleneck", "Decoder", "Output"),
        ("generic", "pooling", "convolution", "upsample", "generic"),
        (("B", "C", "H", "W"), ("B", "2C", "H/2", "W/2"), ("B", "C_b", "H/s", "W/s"), ("B", "C", "H", "W"), ("B", "K", "H", "W")),
        ((0, 1, "data"), (1, 2, "data"), (2, 3, "data"), (1, 3, "skip"), (3, 4, "data")),
        "Symmetric encoder/decoder schematic with an editable skip route.",
    ),
    TemplateSpec(
        "transformer-attention-ffn", "Transformer attention + FFN",
        ("Tokens", "Attention", "Add & norm", "FFN", "Output"),
        ("generic", "attention", "normalization", "generic", "generic"),
        (("B", "T", "D"), ("B", "T", "D"), ("B", "T", "D"), ("B", "T", "D_ff"), ("B", "T", "D")),
        ((0, 1, "data"), (1, 2, "data"), (0, 2, "residual"), (2, 3, "data"), (3, 4, "data")),
        "Attention and feed-forward stages with symbolic sequence length.",
    ),
    TemplateSpec(
        "moe-router-experts", "MoE router + experts",
        ("Tokens", "Router", "Expert 1", "Expert 2", "Merge"),
        ("generic", "routing", "expert", "expert", "concatenate"),
        (("B", "T", "D"), ("B", "T", "E"), ("?", "D"), ("?", "D"), ("B", "T", "D")),
        ((0, 1, "routing"), (1, 2, "routing"), (1, 3, "routing"), (2, 4, "routing"), (3, 4, "routing")),
        "Router and expert branches; unknown expert loads remain '?'.",
    ),
    TemplateSpec(
        "multimodal-fusion", "Multimodal fusion",
        ("Vision", "Text", "Fusion", "Head"),
        ("generic", "generic", "concatenate", "generic"),
        (("B", "N_v", "D"), ("B", "T", "D"), ("B", "N_v+T", "D"), ("B", "K")),
        ((0, 2, "data"), (1, 2, "data"), (2, 3, "data")),
        "Two explicit input modalities converge through an editable fusion operator.",
    ),
    TemplateSpec(
        "diffusion-unet-conditioning", "Diffusion U-Net / timestep conditioning",
        ("Noisy sample", "Encoder", "Bottleneck", "Decoder", "Prediction", "Timestep"),
        ("generic", "pooling", "attention", "upsample", "generic", "generic"),
        (("B", "C", "H", "W"), ("B", "C_e", "H/s", "W/s"), ("B", "C_b", "H/s", "W/s"), ("B", "C_d", "H", "W"), ("B", "C", "H", "W"), ("B", "D_t")),
        ((0, 1, "data"), (1, 2, "data"), (2, 3, "data"), (1, 3, "skip"), (3, 4, "data"), (5, 1, "conditioning"), (5, 2, "conditioning"), (5, 3, "conditioning")),
        "U-Net path and separate timestep-conditioning edges without accuracy claims.",
    ),
)

TEMPLATE_REGISTRY = {item.slug: item for item in TEMPLATE_SPECS}


def template_catalog() -> list[dict[str, Any]]:
    return [
        {
            "slug": item.slug, "title": item.title, "description": item.description,
            "modes": ["schematic", "tensor-geometry", "mixed"],
            "page_presets": ["single-column", "double-column", "178mm"],
            "offline": True, "editable": True,
        }
        for item in TEMPLATE_SPECS
    ]


def _template_provenance(spec: TemplateSpec, role: str) -> FigureProvenance:
    return FigureProvenance(
        "template",
        source_id=f"nndv-template:{spec.slug}:{role}",
        source_locator={"package": f"nn_davinci/figure_templates/{spec.slug}.json", "template_version": FIGURE_TEMPLATE_VERSION},
        evidence={"role": role, "claim_scope": "schematic archetype", "model_instance": False},
        reason="Bundled original template definition; values are symbolic unless a project supplies Graph IR evidence.",
    )


def _template_graph(spec: TemplateSpec) -> GraphIR:
    nodes: list[Node] = []
    for index, (role, operator, shape) in enumerate(zip(spec.roles, spec.operators, spec.shapes)):
        tensor = TensorSpec(f"{role} tensor", list(shape), "unknown")
        node_id = stable_id("node", f"template:{spec.slug}:{role}")
        nodes.append(Node(
            node_id, role, operator, category=operator if operator != "generic" else "operation",
            path=f"template/{spec.slug}/{index}",
            inputs=[] if index == 0 else [Port(stable_id("port", f"{node_id}:in"), "input", "input", tensor)],
            outputs=[Port(stable_id("port", f"{node_id}:out"), "output", "output", tensor)],
            source={
                "kind": "bundled-template", "template": spec.slug, "role": role,
                "claim_scope": "schematic archetype", "model_instance": False,
            },
            attributes={"template_role": role, "operator_family": operator},
            tags=["template", operator],
        ))
    edges: list[Edge] = []
    for source_index, target_index, kind in spec.edges:
        source, target = nodes[source_index], nodes[target_index]
        edge = Edge.create(source.id, target.id, kind=kind)
        edge.tensor = source.outputs[0].tensor
        edge.attributes = {"template": spec.slug, "schematic_only": True, "provenance": "bundled-template"}
        edges.append(edge)
    return GraphIR(
        spec.title, nodes, edges,
        metadata={
            "source_format": "nndv-bundled-figure-template", "template": spec.slug,
            "template_version": FIGURE_TEMPLATE_VERSION, "model_instance": False,
            "paper_claims": False, "accuracy_claims": False,
        },
    ).validate()


def instantiate_template(slug: str, *, page_preset: str = "double-column") -> tuple[GraphIR, FigureIR]:
    if slug not in TEMPLATE_REGISTRY:
        raise ValidationError(f"Unknown Figure Studio template {slug!r}")
    if page_preset not in {"single-column", "double-column", "178mm"}:
        raise ValidationError("Figure templates support single-column, double-column, or 178mm pages")
    spec = TEMPLATE_REGISTRY[slug]
    graph = _template_graph(spec)
    figure = new_figure(spec.title, page_preset=page_preset, panel_modes=("schematic", "tensor-geometry"))
    figure.theme = "neurips"
    figure.metadata.update({
        "template": spec.slug, "template_version": FIGURE_TEMPLATE_VERSION,
        "offline": True, "editable": True, "supported_modes": ["schematic", "tensor-geometry", "mixed"],
        "supported_page_presets": ["single-column", "double-column", "178mm"],
        "paper_claims": False, "accuracy_claims": False,
    })
    schematic, tensors = list(figure.iter_panels())
    page = figure.pages[0]
    panel_gap = 4.0
    panel_height = (page.height_mm - 2 * page.margin_mm - panel_gap) / 2.0
    for panel_index, panel in enumerate((schematic, tensors)):
        panel.geometry.update({
            "x": page.margin_mm,
            "y": page.margin_mm + panel_index * (panel_height + panel_gap),
            "width": page.width_mm - 2 * page.margin_mm,
            "height": panel_height,
        })
    page.columns = 1
    schematic.title = "Schematic"
    tensors.title = "Tensor geometry"
    model_a = next(layer for layer in schematic.layers if layer.role == "model-data")
    model_b = next(layer for layer in tensors.layers if layer.role == "model-data")
    caption_layer = next(layer for layer in tensors.layers if layer.role == "legend-caption")
    count = max(1, len(spec.roles))
    usable_a = schematic.geometry["width"] - 12.0
    usable_b = tensors.geometry["width"] - 12.0
    step_a, step_b = usable_a / count, usable_b / count
    schematic_objects: list[FigureObject] = []
    tensor_objects: list[FigureObject] = []
    for index, (role, operator, shape) in enumerate(zip(spec.roles, spec.operators, spec.shapes)):
        node_x = schematic.geometry["x"] + 6.0 + index * step_a
        tensor_x = tensors.geometry["x"] + 6.0 + index * step_b
        node_y = schematic.geometry["y"] + 18.0
        tensor_y = tensors.geometry["y"] + 10.0
        short_label: str | None = None
        if spec.slug == "moe-router-experts":
            # Experts are parallel branches, not consecutive boxes in a row.
            # Giving them a shared column makes the routing graph planar and is
            # considerably easier to read than interleaved crossover lines.
            if index == 3:
                node_x -= step_a
                tensor_x -= step_b
            if index == 2:
                node_y = schematic.geometry["y"] + 7.0
                tensor_y = tensors.geometry["y"] + 3.0
            elif index == 3:
                node_y = schematic.geometry["y"] + 29.0
                tensor_y = tensors.geometry["y"] + 20.0
        elif spec.slug == "diffusion-unet-conditioning":
            # A planar K4 embedding: encoder/decoder form the upper corners,
            # the bottleneck is the lower corner, and timestep conditioning is
            # inside that triangle.  The main U-Net and all three conditioning
            # spokes can therefore be followed without line crossings.
            diffusion_x = (10.0, 39.0, 76.0, 113.0, 150.0, 80.0)
            node_x = diffusion_x[index]
            tensor_x = diffusion_x[index]
            if index in {1, 3}:
                node_y = schematic.geometry["y"] + 6.0
                tensor_y = tensors.geometry["y"] + 4.0
            elif index == 2:
                node_y = schematic.geometry["y"] + 35.0
                tensor_y = tensors.geometry["y"] + 30.0
            elif index == 5:
                node_y = schematic.geometry["y"] + 16.0
                tensor_y = tensors.geometry["y"] + 15.0
                short_label = "t"
        node = FigureObject.create(
            "operator-glyph", role,
            {"x": node_x, "y": node_y, "width": min(14.0, step_a - 4.0), "height": 12.0},
            _template_provenance(spec, role), identity=f"{spec.slug}:schematic:{role}",
            style=FigureStyle(overrides={"font_size": 7.0}),
            metadata={
                "operator_family": operator,
                "label": role,
                **({"short_label": short_label} if short_label is not None else {}),
                "label_lane_width_mm": max(7.0, step_a - 1.5),
                "template": spec.slug,
            },
            order=index * 2,
        )
        schematic_objects.append(node)
        tensor = FigureObject.create(
            "tensor-glyph", role,
            {"x": tensor_x, "y": tensor_y, "width": max(6.5, min(10.0, step_b - 3.0)), "height": 8.0, "depth": 2.8},
            _template_provenance(spec, role), identity=f"{spec.slug}:tensor:{role}",
            style=FigureStyle(overrides={"font_size": 7.0}),
            metadata={
                "tensor_shape": list(shape), "shape_label": "[" + ", ".join("?" if item is None else str(item) for item in shape) + "]",
                "layout": "auto", "geometry_scale": "manual", "template": spec.slug,
                "label_lane_width_mm": max(7.0, step_b - 1.5),
                "visual_scale_note": "manual template geometry; label is authoritative",
            }, order=index * 2,
        )
        tensor_objects.append(tensor)
    model_a.objects.extend(schematic_objects)
    model_b.objects.extend(tensor_objects)

    def visual_box(item: FigureObject, *, tensor: bool) -> tuple[float, float, float, float]:
        """Return the actually painted front/symbol box, not its layout slot."""
        width = float(item.geometry["width"])
        height = float(item.geometry["height"])
        x = float(item.geometry["x"])
        y = float(item.geometry["y"])
        if tensor:
            return x + float(item.geometry.get("depth", 0.0)), y, width, height
        # Operator text is part of the painted symbol and may approach its
        # right side.  Its layout slot deliberately supplies a small, visible
        # port gutter around the symbol.
        return x, y, width, height

    def boundary_port(
        box: tuple[float, float, float, float],
        toward: tuple[float, float],
    ) -> tuple[float, float]:
        """Intersect a center-to-center ray with an axis-aligned glyph box."""
        x, y, width, height = box
        cx, cy = x + width / 2.0, y + height / 2.0
        dx, dy = toward[0] - cx, toward[1] - cy
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return cx, cy
        factors = []
        if abs(dx) >= 1e-9:
            factors.append((width / 2.0) / abs(dx))
        if abs(dy) >= 1e-9:
            factors.append((height / 2.0) / abs(dy))
        factor = min(factors)
        return cx + dx * factor, cy + dy * factor

    def direct_ports(
        source: FigureObject,
        target: FigureObject,
        *,
        tensor: bool,
    ) -> tuple[tuple[float, float], tuple[float, float]]:
        source_box = visual_box(source, tensor=tensor)
        target_box = visual_box(target, tensor=tensor)
        source_center = (source_box[0] + source_box[2] / 2.0, source_box[1] + source_box[3] / 2.0)
        target_center = (target_box[0] + target_box[2] / 2.0, target_box[1] + target_box[3] / 2.0)
        return boundary_port(source_box, target_center), boundary_port(target_box, source_center)

    for edge_index, (source_index, target_index, kind) in enumerate(spec.edges):
        for layer, objects, y_offset, identity_suffix in (
            (model_a, schematic_objects, 0.0, "schematic"),
            (model_b, tensor_objects, 2.0, "tensor"),
        ):
            source, target = objects[source_index], objects[target_index]
            is_tensor = layer is model_b
            (sx, sy), (tx, ty) = direct_ports(source, target, tensor=is_tensor)
            if spec.slug in {"moe-router-experts", "diffusion-unet-conditioning"}:
                route = [[sx, sy], [tx, ty]]
                if spec.slug == "diffusion-unet-conditioning" and is_tensor:
                    source_box = visual_box(source, tensor=True)
                    target_box = visual_box(target, tensor=True)
                    source_left, source_top, source_width, source_height = source_box
                    target_left, target_top, target_width, target_height = target_box
                    if edge_index == 1:
                        # Leave the encoder below its front face, clear its
                        # long shape label, then enter the bottleneck at the
                        # exposed front-top edge.
                        sx, sy = source_left + source_width, source_top + source_height
                        tx, ty = target_left + 1.2, target_top
                        route = [[sx, sy], [sx + 6.0, sy], [tx, ty]]
                    elif edge_index == 2:
                        # The decoder label occupies the direct lower-left
                        # approach.  This outside rail enters from the right
                        # without crossing the decoder-to-prediction edge.
                        sx, sy = source_left + source_width, source_top + source_height / 2.0
                        tx, ty = target_left + target_width, target_top + target_height / 2.0
                        rail_x = tx + 9.2
                        route = [[sx, sy], [rail_x, sy], [rail_x, ty + 11.0], [tx, ty]]
                    elif edge_index == 4:
                        # Continue from the decoder through the same right-side
                        # port used by the incoming lower branch.  The two
                        # strokes meet at one endpoint instead of crossing just
                        # outside the tensor face.
                        sx, sy = source_left + source_width, source_top + source_height / 2.0
                        tx, ty = target_left, target_top + target_height / 2.0
                        route = [[sx, sy], [tx, ty]]
                    elif edge_index == 5:
                        sx, sy = source_left + source_width / 2.0, source_top
                        tx, ty = target_left + target_width, target_top + target_height / 2.0
                        route = [[sx, sy], [tx, ty]]
                    elif edge_index == 6:
                        # The timestep shape label sits immediately below its
                        # tensor.  A short left rail keeps the conditioning
                        # spoke legible before it enters the bottleneck top.
                        sx, sy = source_left, source_top + source_height / 2.0
                        tx, ty = target_left + 3.2, target_top
                        route = [[sx, sy], [sx - 3.8, sy], [sx - 3.8, ty - 2.0], [tx, ty]]
                    elif edge_index == 7:
                        sx, sy = source_left + source_width / 2.0, source_top
                        tx, ty = target_left, target_top + target_height / 2.0
                        route = [[sx, sy], [tx, ty]]
            elif target_index <= source_index or target_index - source_index > 1 or kind in {"residual", "skip", "conditioning"}:
                active_panel = schematic if layer is model_a else tensors
                source_box = visual_box(source, tensor=is_tensor)
                target_box = visual_box(target, tensor=is_tensor)
                sx = source_box[0] + source_box[2] / 2.0
                sy = source_box[1]
                tx = target_box[0] + target_box[2] / 2.0
                ty = target_box[1]
                detour = min(source_box[1], target_box[1]) - 5.0 - y_offset
                detour = max(detour, active_panel.geometry["y"] + 5.0)
                route = [[sx, sy], [sx, detour], [tx, detour], [tx, ty]]
            else:
                route = [[sx, sy], [tx, ty]]
            layer.objects.append(FigureObject.create(
                "edge", kind,
                {"x": sx, "y": sy, "x2": tx, "y2": ty},
                _template_provenance(spec, f"edge-{edge_index}"),
                identity=f"{spec.slug}:{identity_suffix}:edge:{edge_index}", manual_route=route,
                style=FigureStyle(overrides={"dash": "4 3"} if kind not in {"data"} else {}),
                metadata={"edge_semantics": "model-data" if kind == "data" else "semantic-annotation", "template_edge_kind": kind, "endpoint_object_ids": [source.id, target.id]},
                order=10_000 + edge_index,
            ))
    caption_layer.objects.append(FigureObject.create(
        "caption", f"{spec.title}: {spec.description}",
        {"x": tensors.geometry["x"] + 3.0, "y": tensors.geometry["y"] + tensors.geometry["height"] - 2.0},
        FigureProvenance.author("Bundled editable caption describing only the template structure."),
        identity=f"{spec.slug}:caption",
        style=FigureStyle(overrides={"font_size": 7.0}),
        metadata={"text": f"{spec.title}: {spec.description}"},
    ))
    return graph, figure.validate()


def template_project(slug: str, *, page_preset: str = "double-column") -> dict[str, Any]:
    graph, figure = instantiate_template(slug, page_preset=page_preset)
    project: dict[str, Any] = Project(
        name=figure.name,
        graph=graph,
        figure_ir=figure.to_dict(),
        model_source={"kind": "bundled-figure-template", "template": slug, "model_instance": False},
        theme=figure.theme,
        environment={"nn_davinci": "0.7.1", "template_version": FIGURE_TEMPLATE_VERSION},
        created_at="2026-08-29T00:00:00+00:00",
        updated_at="2026-08-29T00:00:00+00:00",
    ).to_dict()
    return project


def materialize_templates(*roots: str | Path) -> list[Path]:
    outputs: list[Path] = []
    for root_value in roots:
        root = Path(root_value)
        root.mkdir(parents=True, exist_ok=True)
        for spec in TEMPLATE_SPECS:
            destination = root / f"{spec.slug}.nndv.json"
            destination.write_text(json.dumps(template_project(spec.slug), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            outputs.append(destination)
    return outputs


__all__ = [
    "FIGURE_TEMPLATE_VERSION", "TEMPLATE_REGISTRY", "TEMPLATE_SPECS", "TemplateSpec",
    "instantiate_template", "materialize_templates", "template_catalog", "template_project",
]
