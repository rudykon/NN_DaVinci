#!/usr/bin/env python3
"""Generate adversarial, hand-authored final Figure SVG oracle fixtures.

The fixtures deliberately contain producer-side PASS metadata and scale claims.
The independent Chrome oracle must classify the serialized geometry instead.
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


PAGE_WIDTH = 160.0
PAGE_HEIGHT = 120.0
PAGE_GAP = 6.0
PANEL = (8.0, 8.0, 144.0, 104.0)


def pt_mm(value: float) -> float:
    return value * 25.4 / 72.0


def producer_metadata(name: str) -> str:
    payload = {
        "schema_version": "deliberately-untrusted-fixture-proof-1",
        "fixture": name,
        "proof": {"pass": True, "minimum_font_pt": 99, "collisions": 0, "cropped": False},
    }
    return f'<metadata id="nndv-figure-ir">{html.escape(json.dumps(payload, sort_keys=True))}</metadata>'


MARKER = """
<marker id="arrow" markerUnits="userSpaceOnUse" markerWidth="4" markerHeight="4"
        refX="4" refY="2" orient="auto" viewBox="0 0 4 4">
  <path d="M0,0 L4,2 L0,4 Z" fill="context-stroke"/>
</marker>
<marker id="forward-arrow" markerUnits="userSpaceOnUse" markerWidth="4" markerHeight="4"
        refX="0" refY="2" orient="auto" viewBox="0 0 4 4">
  <path d="M0,0 L4,2 L0,4 Z" fill="context-stroke"/>
</marker>
"""


def text(
    object_id: str,
    content: str,
    x: float,
    y: float,
    *,
    role: str = "annotation",
    size_pt: float = 8.0,
    anchor: str = "start",
    family: str = "sans-serif",
    extra: str = "",
    page_id: str = "page-1",
    panel_id: str = "panel-1",
) -> str:
    escaped = html.escape(content)
    return (
        f'<text data-figure-object-id="{html.escape(object_id, quote=True)}" '
        f'data-page-id="{page_id}" data-panel-id="{panel_id}" '
        f'data-nndv-role="required-text" data-primitive-kind="text" '
        f'data-text-role="{role}" data-font-size-pt="99" '
        f'data-horizontal-scale="1" data-transform-text-scale="1" '
        f'x="{x:g}" y="{y:g}" text-anchor="{anchor}" '
        f'font-family="{html.escape(family, quote=True)}" font-size="{pt_mm(size_pt):.7f}" '
        f'fill="#111827" {extra}><tspan x="{x:g}" y="{y:g}">{escaped}</tspan></text>'
    )


def panel_label(content: str = "A", *, x: float = 11, y: float = 17, page_id: str = "page-1", panel_id: str = "panel-1") -> str:
    return (
        f'<text class="panel-label" data-nndv-role="required-text" data-text-role="panel-label" '
        f'data-page-id="{page_id}" data-panel-id="{panel_id}" x="{x:g}" y="{y:g}" '
        f'font-family="sans-serif" font-size="{pt_mm(8):.7f}" font-weight="700" fill="#111827">'
        f'{html.escape(content)}</text>'
    )


def rect(
    object_id: str,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    page_id: str = "page-1",
    panel_id: str = "panel-1",
    extra: str = "",
) -> str:
    return (
        f'<rect data-figure-object-id="{object_id}" data-page-id="{page_id}" '
        f'data-panel-id="{panel_id}" data-nndv-role="figure-object" data-primitive-kind="rect" '
        f'x="{x:g}" y="{y:g}" width="{width:g}" height="{height:g}" rx="1" '
        f'fill="#e0f2fe" stroke="#334155" stroke-width="0.3" {extra}/>'
    )


def polygon(
    object_id: str,
    points: str,
    *,
    face: str = "front",
    page_id: str = "page-1",
    panel_id: str = "panel-1",
) -> str:
    return (
        f'<polygon data-figure-object-id="{object_id}" data-page-id="{page_id}" '
        f'data-panel-id="{panel_id}" data-nndv-role="figure-object" data-primitive-kind="polygon" '
        f'data-tensor-face="{face}" points="{points}" fill="#bfdbfe" '
        f'stroke="#334155" stroke-width="0.3"/>'
    )


def polyline(
    object_id: str,
    points: str,
    *,
    marker: str = "",
    page_id: str = "page-1",
    panel_id: str = "panel-1",
) -> str:
    marker_attr = f' marker-end="url(#{marker})"' if marker else ""
    return (
        f'<polyline data-figure-object-id="{object_id}" data-page-id="{page_id}" '
        f'data-panel-id="{panel_id}" data-nndv-role="edge" data-primitive-kind="polyline" '
        f'points="{points}" fill="none" stroke="#111827" stroke-width="0.5"{marker_attr}/>'
    )


def path_edge(
    object_id: str,
    data: str,
    *,
    page_id: str = "page-1",
    panel_id: str = "panel-1",
) -> str:
    return (
        f'<path data-figure-object-id="{object_id}" data-page-id="{page_id}" '
        f'data-panel-id="{panel_id}" data-nndv-role="edge" data-primitive-kind="path" '
        f'd="{data}" fill="none" stroke="#111827" stroke-width="0.5"/>'
    )


def page_group(page_id: str, panel_id: str, content: str, *, offset: float = 0.0) -> str:
    panel_x, panel_y, panel_width, panel_height = PANEL
    transform = f' transform="translate(0,{offset:g})"' if offset else ""
    return f"""
<g class="figure-page" data-page-id="{page_id}"{transform}>
  <rect class="page-boundary" x="0" y="0" width="{PAGE_WIDTH:g}" height="{PAGE_HEIGHT:g}" fill="none" stroke="none"/>
  <g class="figure-panel" data-page-id="{page_id}" data-panel-id="{panel_id}">
    <rect class="panel-boundary" data-nndv-role="panel" data-page-id="{page_id}" data-panel-id="{panel_id}"
          x="{panel_x:g}" y="{panel_y:g}" width="{panel_width:g}" height="{panel_height:g}"
          fill="none" stroke="#94a3b8" stroke-width="0.2"/>
    {content}
  </g>
</g>
"""


def document(name: str, pages: str, *, page_count: int = 1, styles: str = "") -> str:
    height = PAGE_HEIGHT * page_count + PAGE_GAP * max(0, page_count - 1)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{PAGE_WIDTH:g}mm" height="{height:g}mm"
     viewBox="0 0 {PAGE_WIDTH:g} {height:g}" data-nndv-document="figure-ir"
     data-horizontal-scale="1" data-transform-text-scale="1">
  <title>{html.escape(name)}</title>
  {producer_metadata(name)}
  <style>{styles}</style>
  <defs>{MARKER}</defs>
  <rect class="figure-background" width="100%" height="100%" fill="white"/>
  {pages}
</svg>
"""


def fixtures() -> dict[str, str]:
    result: dict[str, str] = {}

    positive = (
        panel_label()
        + text("title", "Measured final SVG", 15, 18, role="title", size_pt=8)
        + rect("node-a", 22, 39, 34, 22)
        + text("node-a", "Input", 39, 52, role="node-label", anchor="middle")
        + rect("node-b", 104, 39, 34, 22)
        + text("node-b", "Output", 121, 52, role="node-label", anchor="middle")
        + polyline("edge-a-b", "56,50 104,50", marker="arrow")
        + text("caption", "All geometry is measured in Chromium.", 15, 103, role="caption", size_pt=7)
    )
    result["positive.svg"] = document("positive", page_group("page-1", "panel-1", positive))

    cjk = (
        panel_label()
        + rect("cjk-node", 20, 42, 120, 30)
        + text(
            "cjk-node",
            "卷积 H′×W′ = ⌊(H+2p−k)/s⌋ + α∑ᵢxᵢ",
            80,
            60,
            role="node-label",
            anchor="middle",
            family="sans-serif",
        )
    )
    result["cjk-math-pass.svg"] = document("cjk-math-pass", page_group("page-1", "panel-1", cjk))

    caption_1000 = "C" * 1000
    content = (
        rect("occupancy", 20, 55, 120, 30)
        + text("caption-1000", caption_1000, 12, 31, role="caption", size_pt=7)
    )
    result["caption-1000.svg"] = document("caption-1000", page_group("page-1", "panel-1", content))

    long_name = "ResidualProjectionBlockWithAnExtremelyLongScientificOperatorNameThatCannotFit"
    content = rect("long-node", 50, 45, 60, 24) + text(
        "long-node", long_name, 80, 60, role="node-label", anchor="middle"
    )
    result["long-node-name.svg"] = document("long-node-name", page_group("page-1", "panel-1", content))

    content = (
        polygon("tensor-a", "25,42 65,42 65,62 25,62")
        + polygon("tensor-b", "95,42 135,42 135,62 95,62")
        + text("shape-label-a", "[1, 2048, 64, 64]", 75, 83, role="tensor-shape-label", anchor="middle")
        + text("shape-label-b", "[1, 2048, 64, 64]", 87, 83, role="tensor-shape-label", anchor="middle")
    )
    result["adjacent-shape-labels.svg"] = document(
        "adjacent-shape-labels", page_group("page-1", "panel-1", content)
    )

    content = rect("six-point", 30, 40, 100, 30) + text(
        "six-point", "Local six point style", 80, 58, role="node-label", anchor="middle", extra='class="local-six"'
    )
    result["local-6pt-style.svg"] = document(
        "local-6pt-style",
        page_group("page-1", "panel-1", content),
        styles=f".local-six {{ font-size: {pt_mm(6):.7f}px !important; }}",
    )

    content = rect("scaled-text", 30, 40, 100, 30) + text(
        "scaled-text",
        "Translated and scaled",
        75,
        58,
        role="node-label",
        anchor="middle",
        extra='transform="translate(5 0) scale(.55 1)"',
    )
    result["text-translate-scale.svg"] = document(
        "text-translate-scale", page_group("page-1", "panel-1", content)
    )

    content = rect("compressed-text", 25, 40, 110, 30) + text(
        "compressed-text",
        "Artificially compressed scientific label",
        80,
        58,
        role="node-label",
        anchor="middle",
        extra='textLength="22" lengthAdjust="spacingAndGlyphs"',
    )
    result["textlength-compression.svg"] = document(
        "textlength-compression", page_group("page-1", "panel-1", content)
    )

    content = rect("obstacle-node", 60, 45, 40, 24) + polyline("through-node", "20,57 140,57")
    result["polyline-through-node.svg"] = document(
        "polyline-through-node", page_group("page-1", "panel-1", content)
    )

    content = polygon("tensor-obstacle", "64,70 96,70 96,91 64,91") + path_edge(
        "curve-through-tensor", "M20 30 C45 100 115 100 140 30"
    )
    result["curve-through-tensor.svg"] = document(
        "curve-through-tensor", page_group("page-1", "panel-1", content)
    )

    content = rect("occupancy", 25, 35, 110, 30) + text(
        "panel-caption", "Caption crossing the reserved Panel boundary", 20, 114, role="caption"
    )
    result["caption-outside-panel.svg"] = document(
        "caption-outside-panel", page_group("page-1", "panel-1", content)
    )

    content = (
        panel_label("A", x=12, y=18)
        + text("panel-title", "A title", 12, 18, role="title")
        + rect("occupancy", 30, 45, 100, 30)
    )
    result["panel-label-title-collision.svg"] = document(
        "panel-label-title-collision", page_group("page-1", "panel-1", content)
    )

    content = (
        rect("occupancy", 28, 78, 104, 24)
        + text("hidden-text", "display none", 20, 30, extra='style="display:none"')
        + text("transparent-text", "transparent", 20, 43, extra='fill-opacity="0"')
        + text("zero-text", "zero size", 20, 56, extra='transform="scale(0)"')
        + text("off-page-text", "off page", 180, 68)
    )
    result["hidden-transparent-zero-offpage.svg"] = document(
        "hidden-transparent-zero-offpage", page_group("page-1", "panel-1", content)
    )

    missing_family = "NN DaVinci Definitely Missing Font 987654"
    content = rect("fallback-node", 25, 42, 110, 30) + text(
        "fallback-node",
        "Fallback must be observed",
        80,
        60,
        role="node-label",
        anchor="middle",
        family=f"'{missing_family}', monospace",
    )
    result["font-fallback.svg"] = document("font-fallback", page_group("page-1", "panel-1", content))

    first_page = page_group(
        "page-1",
        "panel-1",
        rect("page-one-node", 25, 42, 110, 30, page_id="page-1", panel_id="panel-1"),
    )
    second_content = (
        rect("page-two-node", 25, 35, 110, 30, page_id="page-2", panel_id="panel-2")
        + text(
            "page-two-caption",
            "Second page clipped caption",
            20,
            122,
            role="caption",
            page_id="page-2",
            panel_id="panel-2",
        )
    )
    second_page = page_group(
        "page-2", "panel-2", second_content, offset=PAGE_HEIGHT + PAGE_GAP
    )
    result["multipage-second-page-clip.svg"] = document(
        "multipage-second-page-clip", first_page + second_page, page_count=2
    )

    content = rect("node-overlap", 38, 40, 58, 34) + polygon(
        "tensor-overlap", "70,52 122,52 122,84 70,84"
    )
    result["node-tensor-overlap.svg"] = document(
        "node-tensor-overlap", page_group("page-1", "panel-1", content)
    )

    content = polyline("cross-a", "20,30 140,90") + polyline("cross-b", "20,90 140,30")
    result["edge-crossing.svg"] = document("edge-crossing", page_group("page-1", "panel-1", content))

    content = rect("occupancy", 25, 35, 90, 45) + polyline(
        "clipped-marker", "116,60 159,60", marker="forward-arrow"
    )
    result["marker-clipped.svg"] = document("marker-clipped", page_group("page-1", "panel-1", content))

    content = rect("tiny-object", 79, 59, 2, 2)
    result["low-occupancy.svg"] = document("low-occupancy", page_group("page-1", "panel-1", content))

    content = rect("off-page-object", 170, 45, 24, 20) + rect("occupancy", 30, 72, 100, 24)
    result["off-page-object.svg"] = document("off-page-object", page_group("page-1", "panel-1", content))

    content = rect("collision-node", 48, 42, 64, 28) + text(
        "foreign-caption", "caption over node", 80, 60, role="caption", anchor="middle"
    )
    result["text-shape-collision.svg"] = document(
        "text-shape-collision", page_group("page-1", "panel-1", content)
    )

    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    generated = fixtures()
    for filename, source in sorted(generated.items()):
        (args.output_dir / filename).write_text(source, encoding="utf-8")
    index = {
        "schema_version": "nndv-figure-svg-oracle-fixture-index-1",
        "fixtures": sorted(generated),
    }
    (args.output_dir / "fixture-index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"fixtures": len(generated), "output_dir": str(args.output_dir)}, sort_keys=True))


if __name__ == "__main__":
    main()
