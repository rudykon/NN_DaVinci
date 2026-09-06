from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from typing import Any

from .ir import GraphIR
from .layout import LayoutResult


@dataclass(slots=True)
class GeometryQuality:
    no_clipping: bool
    node_overlap_count: int
    text_overflow_count: int
    final_body_font_pt: float
    minimum_body_font_pt: float
    content_occupancy: float
    rendered_content_width: float
    rendered_content_height: float
    critical_edges_expected: int
    critical_edges_present: int
    selected_page: str
    warnings: list[str]

    @property
    def passed(self) -> bool:
        return (
            self.no_clipping
            and self.node_overlap_count == 0
            and self.text_overflow_count == 0
            and self.final_body_font_pt + 1e-9 >= self.minimum_body_font_pt
            and self.critical_edges_present == self.critical_edges_expected
            and not self.warnings
        )

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "passed": self.passed}


def assess_geometry(graph: GraphIR, layout: LayoutResult, svg: str) -> GeometryQuality:
    """Inspect vector geometry and page metrics without screenshot comparisons."""
    paper = layout.metadata.get("paper", {})
    scale = float(paper.get("diagram_scale", 1.0))
    content_width = float(paper.get("content_width", layout.width))
    content_height = float(paper.get("content_height", layout.height))
    page = paper.get("page", {})
    margin = float(page.get("margin", 0.0))
    if paper.get("selected_page") == "fit-content":
        no_clipping = True
    else:
        no_clipping = (
            content_width * scale <= float(page.get("width", layout.width)) - 2 * margin + 1e-6
            and content_height * scale <= float(page.get("height", layout.height)) - 2 * margin + 1e-6
        )

    root = ET.fromstring(svg)
    overflow = 0
    for text in root.iter("{http://www.w3.org/2000/svg}text"):
        maximum = text.attrib.get("data-max-width")
        if maximum is None:
            continue
        font_size = float(text.attrib.get("font-size", 10.0))
        fallback = len("".join(text.itertext())) * font_size * 0.58
        measured = float(text.attrib.get("data-natural-width-estimate", fallback))
        rendered = float(text.attrib.get("textLength", measured))
        if rendered > float(maximum) + 1e-6:
            overflow += 1

    critical = layout.metadata.get("critical_edges", [])
    routed = set(layout.edges)
    present = sum(item.get("edge_id") in routed for item in critical)
    return GeometryQuality(
        no_clipping=no_clipping,
        node_overlap_count=int(paper.get("node_overlap_count", 0)),
        text_overflow_count=overflow,
        final_body_font_pt=float(paper.get("final_body_font_pt", 0.0)),
        minimum_body_font_pt=float(paper.get("minimum_body_font_pt", 7.0)),
        content_occupancy=float(paper.get("content_occupancy", 0.0)),
        rendered_content_width=content_width * scale,
        rendered_content_height=content_height * scale,
        critical_edges_expected=len(critical),
        critical_edges_present=present,
        selected_page=str(paper.get("selected_page", "fit-content")),
        warnings=list(paper.get("warnings", [])),
    )
