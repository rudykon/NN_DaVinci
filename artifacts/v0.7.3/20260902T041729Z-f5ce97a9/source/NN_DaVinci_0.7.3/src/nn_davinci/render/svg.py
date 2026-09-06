from __future__ import annotations

import html
import json
from typing import Any

from ..ir import Annotation, GraphIR, Node
from ..labels import measure_text_width, node_label_lines
from ..layout import LayoutResult


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _text_fit(value: Any, font_size: float, max_width: float, font_family: str = "DejaVu Sans") -> str:
    measured = measure_text_width(str(value), float(font_size), font_family)
    # Never compress glyphs with textLength/lengthAdjust.  Long node labels are
    # wrapped by node_label_lines; auxiliary labels expose their estimate so the
    # independent Chrome oracle can compare it with the real font measurement.
    return (
        f' data-max-width="{max_width:g}" data-natural-width-estimate="{measured:g}"'
        ' data-horizontal-scale-estimate="1" data-measurement="pillow-glyph-advance"'
    )


class SvgRenderer:
    def render(
        self,
        graph: GraphIR,
        layout: LayoutResult,
        theme: dict[str, Any],
        *,
        title: str | None = None,
        transparent: bool = False,
        show_shapes: bool = True,
        show_parameters: bool = True,
        show_flops: bool = True,
        show_legend: bool = True,
        analysis_metric: str | None = None,
        label_density: str = "paper",
        crop: bool = True,
        embed_metadata: bool = True,
        publication: bool = True,
        publication_manifest: dict[str, Any] | None = None,
        **_: Any,
    ) -> str:
        paper = layout.metadata.get("paper", {})
        page = paper.get("page", theme["page"])
        precomposed_page = bool(paper.get("precomposed_page"))
        content_width = max(layout.width, 200)
        content_height = max(layout.height + (34 if title else 0), 120)
        selected_page = paper.get("selected_page", theme.get("page_preset", "auto"))
        fit_page = selected_page not in {"auto", "fit-content"} and crop
        physical_scale = float(paper.get("physical_scale", 1.0)) if precomposed_page else 1.0
        if precomposed_page:
            width, height = float(page["width"]), float(page["height"])
            content_width, content_height = width, height
            diagram_scale, diagram_tx, diagram_ty = 1.0, 0.0, 0.0
        elif fit_page:
            width, height = float(page["width"]), float(page["height"])
            margin = float(page.get("margin", 24))
            bbox = paper.get("content_bbox", [0, 0, content_width, content_height])
            fitted_width = float(paper.get("content_width", content_width))
            fitted_height = float(paper.get("content_height", content_height)) + (30 if title else 0)
            diagram_scale = min((width - 2 * margin) / fitted_width, (height - 2 * margin) / fitted_height, 1.0)
            diagram_tx = (width - fitted_width * diagram_scale) / 2 - float(bbox[0]) * diagram_scale
            diagram_ty = (height - fitted_height * diagram_scale) / 2 - float(bbox[1]) * diagram_scale
        elif selected_page == "fit-content" and crop:
            margin = float(page.get("margin", 34))
            bbox = paper.get("content_bbox", [0, 0, content_width, content_height])
            width = float(page.get("width") or paper.get("content_width", content_width) + 2 * margin)
            height = float(page.get("height") or paper.get("content_height", content_height) + 2 * margin)
            diagram_scale = 1.0
            diagram_tx = margin - float(bbox[0])
            diagram_ty = margin - float(bbox[1])
        else:
            width = max(content_width, float(page["width"])) if not crop else content_width
            height = max(content_height, float(page["height"])) if not crop else content_height
            diagram_scale, diagram_tx, diagram_ty = 1.0, 0.0, 0.0
        smallest_scale = 0.78 if label_density == "detailed" else 0.84
        body_font_px = max(10.0, float(theme["font_size"])) * smallest_scale
        effective_scale = diagram_scale * physical_scale
        body_font_pt = body_font_px * 0.75 * effective_scale
        foreground = theme["foreground"]
        background = "none" if transparent else theme["background"]
        width_attribute = f'{float(paper["physical_width_mm"]):g}mm' if precomposed_page else f"{width:g}"
        height_attribute = f'{float(paper["physical_height_mm"]):g}mm' if precomposed_page else f"{height:g}"
        parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{_esc(width_attribute)}" height="{_esc(height_attribute)}" viewBox="0 0 {width:g} {height:g}" role="img" aria-labelledby="title desc" data-nndv-role="publication-root" data-publication-layer="{str(publication).lower()}" data-page-preset="{_esc(selected_page)}" data-diagram-scale="{effective_scale:g}" data-final-body-font-pt="{body_font_pt:g}" data-page-margin="{float(page.get("margin", 0)) * physical_scale:g}" data-content-occupancy="{float(paper.get("content_occupancy", 0)):g}" data-label-density="{_esc(label_density)}">',
            f'<title id="title">{_esc(title or graph.name)}</title>',
            f'<desc id="desc">NN_DaVinci vector neural-network diagram with {len(layout.nodes)} nodes and {len(layout.edges)} edges.</desc>',
        ]
        if embed_metadata:
            metadata = {
                "schema_version": "nndv-publication-svg-metadata-1",
                "metrics_version": "chrome-final-svg-v2",
                "identity": publication_manifest,
                "name": graph.name,
                "ir_version": graph.ir_version,
                "node_count": len(layout.nodes),
                "edge_count": len(layout.edges),
                "layout": layout.metadata,
                "theme": theme.get("name", "custom"),
                "paper": paper,
            }
            parts.append(f'<metadata>{_esc(json.dumps(metadata, ensure_ascii=False, sort_keys=True))}</metadata>')
        parts.extend([
            "<defs>",
            f'<marker id="arrow" data-nndv-role="marker" markerWidth="9" markerHeight="7" refX="8" refY="3.5" orient="auto-start-reverse"><path data-nndv-role="marker" d="M0,0 L9,3.5 L0,7 Z" fill="{_esc(theme["edge"])}"/></marker>',
            f'<filter id="selection"><feDropShadow dx="0" dy="0" stdDeviation="2" flood-color="{_esc(theme["selection"])}"/></filter>',
            "</defs>",
            f'<rect data-nndv-role="decoration" class="canvas-background" width="100%" height="100%" fill="{_esc(background)}"/>',
            f'<g data-nndv-role="container" class="diagram" font-family="{_esc(theme["font_family"])}" fill="{_esc(foreground)}" transform="translate({diagram_tx:g},{diagram_ty:g}) scale({diagram_scale:g})">',
        ])
        if title:
            title_y = float(page.get("margin", 0)) + 17.0 if precomposed_page else 25.0
            parts.append(f'<g data-nndv-role="container" class="text-group text-title"><text data-nndv-role="required-text" class="diagram-title" x="{content_width / 2:g}" y="{title_y:g}" text-anchor="middle" font-size="{theme["title_size"]}" font-weight="600">{_esc(title)}</text></g>')
        title_offset = 0 if precomposed_page else (30 if title else 0)
        parts.append('<g data-nndv-role="container" class="architecture-content">')
        parts.append('<g data-nndv-role="container" class="panels">')
        for panel_name, box in sorted(layout.metadata.get("panels", {}).items()):
            panel_width = max(20.0, float(box["width"]) - 14.0)
            parts.append(
                f'<g data-nndv-role="group" class="panel" data-panel="{_esc(panel_name)}"><rect data-nndv-role="group" x="{box["x"]:g}" y="{box["y"] + title_offset:g}" width="{box["width"]:g}" height="{box["height"]:g}" rx="{theme["node_radius"]:g}" fill="none" stroke="{_esc(theme["border"])}" stroke-width="1"/>'
                f'<g data-nndv-role="container" class="text-group text-panel"><text data-nndv-role="group-label" x="{box["x"] + 7:g}" y="{box["y"] + title_offset + 16:g}" font-size="{theme["font_size"]:g}" font-weight="700"{_text_fit(panel_name, float(theme["font_size"]), panel_width, str(theme["font_family"]))}>{_esc(panel_name)}</text></g></g>'
            )
        parts.append('</g>')
        parts.append('<g data-nndv-role="container" class="subgraphs">')
        groups = {group.id: group for group in graph.subgraphs}
        group_items = sorted(layout.groups.items(), key=lambda item: (item[1]["y"], item[1]["x"], item[0]))
        occupied_group_labels: list[tuple[float, float, float]] = []
        for group_id, box in group_items:
            group = groups.get(group_id)
            if group is None:
                continue
            label_x = float(box["x"]) + 8.0
            label_y = float(box["y"]) + title_offset + 14.0
            label_width = max(20.0, float(box["width"]) - 16.0)
            estimated_width = min(label_width, len(group.name) * body_font_px * 0.58)
            while True:
                collisions = [
                    (other_x1, other_y, other_x2)
                    for other_x1, other_y, other_x2 in occupied_group_labels
                    if abs(label_y - other_y) < body_font_px + 3.0
                    and label_x < other_x2 + 5.0
                    and label_x + estimated_width + 5.0 > other_x1
                ]
                if not collisions:
                    break
                shifted_x = max(other_x2 for _, _, other_x2 in collisions) + 8.0
                if shifted_x + estimated_width <= float(box["x"]) + float(box["width"]) - 8.0:
                    label_x = shifted_x
                else:
                    label_y += body_font_px + 3.0
            occupied_group_labels.append((label_x, label_y, label_x + estimated_width))
            available_label_width = max(20.0, float(box["x"]) + float(box["width"]) - label_x - 8.0)
            parts.append(
                f'<g data-nndv-role="group" id="group-{_esc(group_id)}" class="subgraph" data-level="{_esc(group.level)}">'
                f'<rect data-nndv-role="group" x="{box["x"]:g}" y="{box["y"] + title_offset:g}" width="{box["width"]:g}" height="{box["height"]:g}" rx="{theme["node_radius"]:g}" fill="{_esc(theme["group_fill"])}" fill-opacity="0.5" stroke="{_esc(theme["border"])}" stroke-opacity="0.45" stroke-dasharray="5 4"/>'
                f'<g data-nndv-role="container" class="text-group text-subgraph"><text data-nndv-role="group-label" x="{label_x:g}" y="{label_y:g}" font-size="{body_font_px:g}" font-weight="600"{_text_fit(group.name, body_font_px, available_label_width, str(theme["font_family"]))}>{_esc(group.name)}</text></g></g>'
            )
        parts.append("</g>")
        parts.append('<g data-nndv-role="container" class="edges" fill="none">')
        edge_map = graph.edge_map()
        metric_values = [float(node.analysis.get(analysis_metric, 0)) for node in graph.nodes] if analysis_metric else []
        metric_max = max(metric_values, default=0)
        for edge_id, route in sorted(layout.edges.items()):
            edge = edge_map.get(edge_id)
            if edge is None:
                continue
            points = [(x, y + title_offset) for x, y in route.points]
            path = self._rounded_path(points)
            source = graph.node_map().get(edge.source)
            intensity = float(source.analysis.get(analysis_metric, 0)) / metric_max if source and analysis_metric and metric_max else 0
            width_value = float(edge.attributes.get("line_width", theme["edge_width"] * (1 + 2 * intensity)))
            sign_colors = {"positive": theme.get("positive_weight", "#2563eb"), "negative": theme.get("negative_weight", "#dc2626"), "false-negative": theme.get("false_negative_weight", "#f59e0b")}
            sign = edge.attributes.get("sign")
            sign_color = sign_colors.get(str(sign), theme["edge"])
            edge_color = edge.attributes.get("color", sign_color)
            theme_dash = str(theme.get("edge_dash", ""))
            is_dashed = bool(theme_dash) or edge.attributes.get("dashed", False) or edge.attributes.get("sign") == "false-negative" or edge.kind in {"control", "annotation", "recurrent", "semantic-connection"} or route.back_edge
            dash_value = edge.attributes.get("dash") or theme_dash or "6 4"
            dash = f' stroke-dasharray="{_esc(dash_value)}"' if is_dashed else ""
            arrow_style = str(edge.attributes.get("arrow", theme.get("edge_arrow", "end"))).lower()
            markers = ""
            if arrow_style in {"start", "both"}:
                markers += ' marker-start="url(#arrow)"'
            if arrow_style in {"end", "both", "true"}:
                markers += ' marker-end="url(#arrow)"'
            parts.append(
                f'<g data-nndv-role="edge" data-edge-id="{_esc(edge.id)}" id="edge-{_esc(edge.id)}" class="edge edge-{_esc(edge.kind)}" data-source="{_esc(edge.source)}" data-target="{_esc(edge.target)}">'
                f'<path data-nndv-role="edge" data-edge-id="{_esc(edge.id)}" d="{path}" stroke="{_esc(edge_color)}" stroke-width="{width_value:g}"{markers} vector-effect="non-scaling-stroke"{dash}/>'
            )
            if edge.label:
                start, end = max(zip(points, points[1:]), key=lambda pair: abs(pair[1][0] - pair[0][0]) + abs(pair[1][1] - pair[0][1]))
                middle = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
                horizontal = abs(end[0] - start[0]) >= abs(end[1] - start[1])
                label_x, label_y = (middle[0], middle[1] - 5) if horizontal else (middle[0] + 5, middle[1])
                anchor = "middle" if horizontal else "start"
                parts.append(f'<g data-nndv-role="edge-label" class="text-group text-edge-label"><text data-nndv-role="edge-label" x="{label_x:g}" y="{label_y:g}" text-anchor="{anchor}" font-size="{body_font_px:g}" fill="{_esc(theme["muted"])}">{_esc(edge.label)}</text></g>')
            parts.append("</g>")
        parts.append("</g>")
        parts.append('<g data-nndv-role="container" class="nodes">')
        node_map = graph.node_map()
        for node_id, placement in sorted(layout.nodes.items(), key=lambda item: (item[1].rank, item[1].order, item[0])):
            node = node_map.get(node_id)
            if node is None:
                continue
            parts.extend(self._node(node, placement, theme, title_offset, show_shapes, show_parameters, show_flops, analysis_metric, metric_max, label_density, publication))
        parts.append("</g>")
        parts.append('<g data-nndv-role="container" class="annotations">')
        for annotation in graph.annotations:
            if annotation.kind == "panel-label" and annotation.panel in layout.metadata.get("panels", {}):
                continue
            parts.extend(self._annotation(annotation, theme, title_offset))
        parts.append("</g>")
        parts.append("</g>")
        if show_legend:
            parts.extend(self._legend(graph, theme, content_width, content_height))
        parts.append("</g>")
        warnings = list(paper.get("warnings", []))
        if body_font_pt + 1e-9 < float(paper.get("minimum_body_font_pt", 7)):
            warnings.append(
                f"标题占位后正文预计为 {body_font_pt:.2f} pt；请改用 fit-content/widescreen 或移除标题。"
            )
        for warning in dict.fromkeys(warnings):
            parts.append(f'<g data-nndv-role="annotation" class="layout-warning"><text data-nndv-role="annotation" x="{float(page.get("margin", 12)):g}" y="{height - 8:g}" font-size="10" fill="#b42318">{_esc(warning)}</text></g>')
        parts.append("</svg>")
        return "\n".join(parts)

    @staticmethod
    def _rounded_path(points: list[tuple[float, float]]) -> str:
        if not points:
            return ""
        commands = [f"M {points[0][0]:g} {points[0][1]:g}"]
        if len(points) == 2:
            commands.append(f"L {points[1][0]:g} {points[1][1]:g}")
            return " ".join(commands)
        radius = 8.0
        for index in range(1, len(points) - 1):
            previous, current, following = points[index - 1], points[index], points[index + 1]
            dx1, dy1 = current[0] - previous[0], current[1] - previous[1]
            dx2, dy2 = following[0] - current[0], following[1] - current[1]
            length1, length2 = max(abs(dx1), abs(dy1), 1), max(abs(dx2), abs(dy2), 1)
            before = (current[0] - dx1 / length1 * min(radius, length1 / 2), current[1] - dy1 / length1 * min(radius, length1 / 2))
            after = (current[0] + dx2 / length2 * min(radius, length2 / 2), current[1] + dy2 / length2 * min(radius, length2 / 2))
            commands.extend([f"L {before[0]:g} {before[1]:g}", f"Q {current[0]:g} {current[1]:g} {after[0]:g} {after[1]:g}"])
        commands.append(f"L {points[-1][0]:g} {points[-1][1]:g}")
        return " ".join(commands)

    @staticmethod
    def _node(node: Node, placement: Any, theme: dict, offset: float, show_shapes: bool, show_parameters: bool, show_flops: bool, metric: str | None, metric_max: float, label_density: str, publication: bool) -> list[str]:
        x, y = placement.x, placement.y + offset
        color = node.attributes.get("fill", node.attributes.get("color", theme["category_colors"].get(node.category, theme["node_fill"])))
        metric_value = float(node.analysis.get(metric, 0)) if metric else 0
        base_opacity = max(0.0, min(1.0, float(theme.get("node_opacity", 1.0))))
        base_opacity *= max(0.0, min(1.0, float(node.attributes.get("opacity", 1.0))))
        if metric and metric_max:
            alpha = base_opacity * (0.22 + 0.78 * metric_value / metric_max)
        else:
            alpha = base_opacity
        classes = ["node", f"node-{node.category}"] + [f"tag-{tag}" for tag in node.tags]
        result = [
            f'<g data-nndv-role="node" id="node-{_esc(node.id)}" class="{" ".join(_esc(item) for item in classes)}" data-node-id="{_esc(node.id)}" data-path="{_esc(node.path)}" data-op-type="{_esc(node.op_type)}" transform="translate({x:g},{y:g})">',
        ]
        tensor_shape: list[int | str | None] = next(
            (port.tensor.shape for port in node.outputs if port.tensor and port.tensor.shape), []
        )
        if node.category in {"input", "convolution", "pooling"} and len(tensor_shape) >= 3:
            channels = tensor_shape[-3] if len(tensor_shape) >= 3 else None
            stack_count = 3 if isinstance(channels, int) and channels > 3 else 2
            for stack_index in range(stack_count, 0, -1):
                offset = stack_index * 1.0
                result.append(f'<rect data-nndv-role="decoration" class="feature-map-sheet" x="{offset:g}" y="{offset:g}" width="{placement.width - offset:g}" height="{placement.height - offset:g}" rx="{theme["node_radius"]:g}" fill="{_esc(color)}" fill-opacity="{max(.18, alpha * .38):g}" stroke="{_esc(theme["border"])}" stroke-opacity=".55" vector-effect="non-scaling-stroke"/>')
            if isinstance(channels, int) and channels > 64:
                result.append(f'<g data-nndv-role="decoration" class="omission-mark" fill="{_esc(theme["muted"])}"><circle data-nndv-role="decoration" cx="6" cy="{placement.height/2-5:g}" r="1.5"/><circle data-nndv-role="decoration" cx="6" cy="{placement.height/2:g}" r="1.5"/><circle data-nndv-role="decoration" cx="6" cy="{placement.height/2+5:g}" r="1.5"/></g>')
        border_color = theme["border"]
        if "diff-added" in node.tags:
            border_color = "#16a34a"
        elif "diff-removed" in node.tags:
            border_color = "#dc2626"
        elif "diff-changed" in node.tags:
            border_color = "#f59e0b"
        result.extend([
            f'<rect data-nndv-role="node" class="node-body" width="{placement.width:g}" height="{placement.height:g}" rx="{theme["node_radius"]:g}" fill="{_esc(color)}" fill-opacity="{.38 if "diff-removed" in node.tags else alpha:g}" stroke="{_esc(border_color)}" stroke-width="{3 if any(tag.startswith("diff-") for tag in node.tags) else theme["stroke_width"]:g}" vector-effect="non-scaling-stroke"/>',
        ])
        icon = node.attributes.get("icon_href") or node.attributes.get("image_href")
        text_x = placement.width / 2
        if icon:
            result.append(f'<image data-nndv-role="decoration" class="node-icon" href="{_esc(icon)}" x="8" y="12" width="24" height="24" preserveAspectRatio="xMidYMid meet"/>')
            text_x += 10
        name_size = max(10.0, float(theme["font_size"]))
        max_text_width = max(20.0, placement.width - 2 * float(theme.get("node_padding", 10)))
        lines = node_label_lines(
            node, theme, density=str(node.attributes.get("figure_panel_label_density", label_density)), show_shapes=show_shapes,
            show_parameters=show_parameters, show_flops=show_flops,
            max_width=max_text_width,
        )
        line_gap = name_size * 1.12
        block_height = line_gap * max(len(lines) - 1, 0)
        first_baseline = placement.height / 2 - block_height / 2 + name_size * 0.34
        for index, line in enumerate(lines):
            line_size = name_size * line.font_scale
            natural_estimate = measure_text_width(line.text, line_size, str(theme["font_family"]))
            css_class = "node-name" if line.role == "name" else ("node-type" if line.role == "op-type" else "node-stats")
            fill = "" if line.role == "name" else f' fill="{_esc(theme["muted"])}"'
            weight = f' font-weight="{theme.get("font_weight", 600):g}"' if line.role == "name" else ""
            result.append(
                f'<g data-nndv-role="container" class="text-group text-{_esc(line.role)}"><text data-nndv-role="{"required-text" if line.mandatory else "decoration"}" class="{css_class}" data-label-role="{_esc(line.role)}" data-required="{str(line.mandatory).lower()}" x="{text_x:g}" y="{first_baseline + index * line_gap:g}" text-anchor="middle" font-size="{line_size:g}"{weight}{fill} data-max-width="{max_text_width:g}" data-natural-width-estimate="{natural_estimate:g}" data-horizontal-scale-estimate="1" data-measurement="pillow-glyph-advance">{_esc(line.text)}</text></g>'
            )
        if "collapsed" in node.tags and not publication:
            result.append(f'<g data-nndv-role="editor-control" class="text-group text-collapse"><text data-nndv-role="editor-control" x="{placement.width - 10:g}" y="15" text-anchor="end" font-size="12">⊞</text></g>')
        result.append("</g>")
        return result

    @staticmethod
    def _annotation(annotation: Annotation, theme: dict, offset: float) -> list[str]:
        geometry = annotation.geometry
        x, y = geometry.get("x", 0), geometry.get("y", 0) + offset
        style = annotation.style
        color = style.get("color", theme["foreground"])
        if annotation.kind in {"text", "title", "formula", "panel-label"}:
            size = max(10.0, float(style.get("font_size", theme["font_size"] + (4 if annotation.kind == "title" else 0))))
            weight = style.get("font_weight", 700 if annotation.kind in {"title", "panel-label"} else 400)
            return [f'<g data-nndv-role="annotation" data-annotation-id="{_esc(annotation.id)}" id="annotation-{_esc(annotation.id)}" class="annotation annotation-{_esc(annotation.kind)}"><g data-nndv-role="container" class="text-group text-annotation"><text data-nndv-role="annotation" x="{x:g}" y="{y:g}" font-size="{size:g}" font-weight="{weight}" fill="{_esc(color)}">{_esc(annotation.text)}</text></g></g>']
        if annotation.kind in {"region", "zoom", "panel"}:
            size = max(10.0, float(theme["font_size"]) - 1.0)
            return [f'<g data-nndv-role="annotation" data-annotation-id="{_esc(annotation.id)}" id="annotation-{_esc(annotation.id)}" class="annotation annotation-{_esc(annotation.kind)}"><rect data-nndv-role="annotation" x="{x:g}" y="{y:g}" width="{geometry.get("width", 100):g}" height="{geometry.get("height", 80):g}" rx="{style.get("radius", 5):g}" fill="{_esc(style.get("fill", "none"))}" stroke="{_esc(color)}" stroke-width="{style.get("stroke_width", 1.5):g}" stroke-dasharray="{_esc(style.get("dash", "6 4"))}"/><g data-nndv-role="container" class="text-group text-annotation"><text data-nndv-role="annotation" x="{x + 6:g}" y="{y + 15:g}" font-size="{size:g}">{_esc(annotation.text)}</text></g></g>']
        if annotation.kind == "image" and style.get("href"):
            return [f'<g data-nndv-role="annotation" data-annotation-id="{_esc(annotation.id)}" id="annotation-{_esc(annotation.id)}" class="annotation annotation-image"><image data-nndv-role="annotation" href="{_esc(style["href"])}" x="{x:g}" y="{y:g}" width="{geometry.get("width", 100):g}" height="{geometry.get("height", 100):g}" preserveAspectRatio="xMidYMid meet"/></g>']
        if annotation.kind == "arrow":
            x2, y2 = geometry.get("x2", x + 80), geometry.get("y2", y) + offset
            size = max(10.0, float(theme["font_size"]) - 1.0)
            return [f'<g data-nndv-role="annotation" data-annotation-id="{_esc(annotation.id)}" id="annotation-{_esc(annotation.id)}" class="annotation annotation-arrow"><line data-nndv-role="annotation" x1="{x:g}" y1="{y:g}" x2="{x2:g}" y2="{y2:g}" stroke="{_esc(color)}" stroke-width="{style.get("stroke_width", 1.8):g}" marker-end="url(#arrow)"/><g data-nndv-role="container" class="text-group text-annotation"><text data-nndv-role="annotation" x="{(x+x2)/2:g}" y="{(y+y2)/2 - 5:g}" text-anchor="middle" font-size="{size:g}">{_esc(annotation.text)}</text></g></g>']
        return []

    @staticmethod
    def _legend(graph: GraphIR, theme: dict, width: float, height: float) -> list[str]:
        categories = sorted({node.category for node in graph.nodes if node.visible})
        if len(categories) < 2:
            return []
        x, y = 15.0, height - 18
        parts = ['<g data-nndv-role="legend" class="legend">']
        for category in categories:
            color = theme["category_colors"].get(category, theme["node_fill"])
            parts.append(f'<rect data-nndv-role="legend" x="{x:g}" y="{y - 9:g}" width="10" height="10" rx="2" fill="{_esc(color)}" stroke="{_esc(theme["border"])}" stroke-width="0.5"/>')
            legend_size = max(10.0, float(theme["font_size"]) - 3.0)
            parts.append(f'<g data-nndv-role="legend" class="text-group text-legend"><text data-nndv-role="legend" x="{x + 14:g}" y="{y:g}" font-size="{legend_size:g}">{_esc(category)}</text></g>')
            x += 22 + len(category) * legend_size * 0.58
            if x > width - 120:
                break
        parts.append("</g>")
        return parts
