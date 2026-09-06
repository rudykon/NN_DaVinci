from __future__ import annotations

from hashlib import sha1
from typing import Any

from ..ir import GraphIR
from ..labels import node_label_lines
from ..layout import LayoutResult


def _tex(value: Any) -> str:
    text = str(value)
    replacements = {
        "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
        "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
        # Raw UTF-8 multiplication signs are mis-decoded by pdfTeX's default
        # text encoding (and extract as Ö). The Computer Modern math glyph
        # has an embedded Unicode mapping and remains searchable as ×.
        "×": r"$\times$",
    }
    return "".join(replacements.get(char, char) for char in text)


def _color(value: str) -> str:
    return value.lstrip("#") if value.startswith("#") else "FFFFFF"


class TikzRenderer:
    def render(
        self, graph: GraphIR, layout: LayoutResult, theme: dict[str, Any], *,
        standalone: bool = True, title: str | None = None, show_shapes: bool = True,
        show_parameters: bool = True, show_flops: bool = True, show_legend: bool = True,
        label_density: str = "paper",
        **_: Any,
    ) -> str:
        scale = 0.018
        lines = []
        if standalone:
            lines.extend([r"\documentclass[tikz,border=4pt]{standalone}", r"\usepackage{xcolor}", r"\usetikzlibrary{arrows.meta,positioning,fit,backgrounds}", r"\begin{document}"])
        lines.extend([
            f"\\definecolor{{nndvborder}}{{HTML}}{{{_color(theme['border'])}}}",
            f"\\definecolor{{nndvedge}}{{HTML}}{{{_color(theme['edge'])}}}",
            f"\\definecolor{{nndvtext}}{{HTML}}{{{_color(theme['foreground'])}}}",
            rf"\begin{{tikzpicture}}[x=1cm,y=-1cm,>=Stealth,every node/.style={{font=\{'rmfamily' if any(token in theme['font_family'].lower() for token in ('times', 'georgia', 'libertine')) else 'sffamily'}}}]",
        ])
        if title:
            lines.append(f"\\node[font=\\bfseries\\large] at ({layout.width * scale / 2:.3f},0) {{{_tex(title)}}};")
        for category, color in sorted(theme["category_colors"].items()):
            lines.append(f"\\definecolor{{nndv{category.replace('-', '')}}}{{HTML}}{{{_color(color)}}}")
        group_map = {group.id: group for group in graph.subgraphs}
        for group_id, box in sorted(layout.groups.items()):
            group = group_map.get(group_id)
            if group:
                lines.append(f"\\draw[rounded corners,dashed,nndvborder!50,fill=nndvborder!4] ({box['x']*scale:.3f},{box['y']*scale:.3f}) rectangle ({(box['x']+box['width'])*scale:.3f},{(box['y']+box['height'])*scale:.3f}) node[anchor=north west,font=\\scriptsize\\bfseries] {{{_tex(group.name)}}};")
        edge_map = graph.edge_map()
        for edge_id, route in sorted(layout.edges.items()):
            edge = edge_map.get(edge_id)
            if edge is None:
                continue
            coords = " -- ".join(f"({x*scale:.3f},{y*scale:.3f})" for x, y in route.points)
            arrow = {"end": "->", "start": "<-", "both": "<->", "none": "-"}.get(str(edge.attributes.get("arrow", theme.get("edge_arrow", "end"))).lower(), "->")
            dashed = bool(theme.get("edge_dash")) or edge.attributes.get("dashed", False) or route.back_edge or edge.kind in {"control", "annotation", "recurrent", "semantic-connection"}
            style = "dashed," if dashed else ""
            color_name = "nndvedge"
            edge_color = edge.attributes.get("color")
            if edge_color:
                color_name = f"nndve{sha1(edge_id.encode('utf-8')).hexdigest()[:10]}"
                lines.append(f"\\definecolor{{{color_name}}}{{HTML}}{{{_color(str(edge_color))}}}")
            width = float(edge.attributes.get("line_width", theme["edge_width"]))
            lines.append(f"\\draw[{arrow},{style}{color_name},line width={width*0.35:.2f}pt,rounded corners=2pt] {coords};")
            if edge.label:
                x, y = route.points[len(route.points) // 2]
                lines.append(f"\\node[font=\\scriptsize,text=nndvtext,fill=white,inner sep=1pt] at ({x*scale:.3f},{y*scale:.3f}) {{{_tex(edge.label)}}};")
        node_map = graph.node_map()
        for node_id, placement in sorted(layout.nodes.items(), key=lambda item: (item[1].rank, item[1].order, item[0])):
            node = node_map.get(node_id)
            if node is None:
                continue
            category = node.category.replace("-", "") if node.category in theme["category_colors"] else "operation"
            fill_name = f"nndv{category}"
            custom_fill = node.attributes.get("fill", node.attributes.get("color"))
            if custom_fill:
                fill_name = f"nndvn{sha1(node_id.encode('utf-8')).hexdigest()[:10]}"
                lines.append(f"\\definecolor{{{fill_name}}}{{HTML}}{{{_color(str(custom_fill))}}}")
            label_lines = node_label_lines(
                node, theme, density=label_density, show_shapes=show_shapes,
                show_parameters=show_parameters, show_flops=show_flops,
                max_width=max(20.0, placement.width - 2 * float(theme.get("node_padding", 10))),
            )
            formatted = []
            for line in label_lines:
                value = _tex(line.text)
                if line.role == "name" and float(theme.get("font_weight", 600)) >= 600:
                    value = f"\\textbf{{{value}}}"
                elif line.role == "op-type":
                    value = f"{{\\scriptsize {value}}}"
                elif line.role != "name":
                    value = f"{{\\footnotesize {value}}}"
                formatted.append(value)
                lines.append(f"% NNDV-LABEL {node.id} {line.role} {_tex(line.text)}")
            label = "\\\\".join(formatted)
            tikz_id = sha1(node_id.encode("utf-8")).hexdigest()[:12]
            opacity = max(0.0, min(1.0, float(theme.get("node_opacity", 1.0)) * float(node.attributes.get("opacity", 1.0))))
            lines.append(f"\\node[draw=nndvborder,fill={fill_name},fill opacity={opacity:.3g},text opacity=1,rounded corners=2pt,minimum width={placement.width*scale:.3f}cm,minimum height={placement.height*scale:.3f}cm,align=center,text=nndvtext] (n{tikz_id}) at ({(placement.x+placement.width/2)*scale:.3f},{(placement.y+placement.height/2)*scale:.3f}) {{{label}}};")
        for annotation in graph.annotations:
            geometry = annotation.geometry
            x, y = float(geometry.get("x", 0)) * scale, float(geometry.get("y", 0)) * scale
            if annotation.kind in {"text", "title", "formula", "panel-label"}:
                weight = "\\bfseries " if annotation.kind in {"title", "panel-label"} else ""
                lines.append(f"\\node[anchor=west,font={weight}\\small,text=nndvtext] at ({x:.3f},{y:.3f}) {{{_tex(annotation.text)}}};")
            elif annotation.kind in {"region", "zoom", "panel"}:
                width, height = float(geometry.get("width", 100)) * scale, float(geometry.get("height", 80)) * scale
                lines.append(f"\\draw[dashed,nndvborder] ({x:.3f},{y:.3f}) rectangle ({x+width:.3f},{y+height:.3f}) node[anchor=north west,font=\\scriptsize] {{{_tex(annotation.text)}}};")
            elif annotation.kind == "arrow":
                x2, y2 = float(geometry.get("x2", 80)) * scale, float(geometry.get("y2", 0)) * scale
                lines.append(f"\\draw[->,nndvedge] ({x:.3f},{y:.3f}) -- ({x2:.3f},{y2:.3f}) node[midway,above,font=\\scriptsize] {{{_tex(annotation.text)}}};")
        if show_legend:
            categories = sorted({node.category for node in graph.nodes if node.visible})
            for index, category in enumerate(categories[:8]):
                color = f"nndv{category.replace('-', '')}" if category in theme["category_colors"] else "nndvoperation"
                lines.append(f"\\node[draw=nndvborder,fill={color},font=\\footnotesize,anchor=west,inner sep=2pt] at ({0.25+index*1.25:.3f},{layout.height*scale+0.18:.3f}) {{{_tex(category)}}};")
        lines.append(r"\end{tikzpicture}")
        if standalone:
            lines.append(r"\end{document}")
        return "\n".join(lines) + "\n"
