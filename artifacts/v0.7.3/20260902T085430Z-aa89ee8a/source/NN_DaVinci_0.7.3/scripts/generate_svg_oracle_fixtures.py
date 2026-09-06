#!/usr/bin/env python3
"""Generate strict, hand-authored final-SVG oracle truth fixtures."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


WIDTH, HEIGHT = 300, 200


def identity(name: str, nodes: int, edges: int) -> dict[str, object]:
    return {
        "fixture_id": name,
        "input_sha256": f"fixture-input-{name}",
        "run_id": "oracle-truth-run",
        "node_count": nodes,
        "edge_count": edges,
    }


def metadata(name: str, nodes: int, edges: int, width: float, height: float, *, final_font_pt: float = 0, stale: bool = False) -> str:
    item = identity(name, nodes, edges)
    if stale:
        item["input_sha256"] = "stale-input-sha256"
    payload = {
        "schema_version": "nndv-publication-svg-metadata-1",
        "metrics_version": "chrome-final-svg-v2",
        "identity": item,
        "node_count": nodes,
        "edge_count": edges,
        "paper": {
            "content_occupancy": width * height / (WIDTH * HEIGHT),
            "final_body_font_pt": final_font_pt,
            "content_width": width,
            "content_height": height,
            "node_overlap_count": 0,
            "cropped": False,
        },
    }
    return f"<metadata>{html.escape(json.dumps(payload, sort_keys=True))}</metadata>"


def svg(name: str, content: str, *, nodes: int, edges: int, content_width: float, content_height: float, final_font_pt: float = 0, include_metadata: bool = True, stale: bool = False, definitions: str = "") -> str:
    meta = metadata(name, nodes, edges, content_width, content_height, final_font_pt=final_font_pt, stale=stale) if include_metadata else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" '
        'data-nndv-role="publication-root" data-publication-layer="true" data-page-margin="0" data-diagram-scale="1">'
        f"{meta}<defs>{definitions}</defs>"
        f'<g data-nndv-role="container" class="architecture-content">{content}</g></svg>\n'
    )


def node(node_id: str, x: float, y: float, width: float, height: float, *, text: str | None = None, transform: str | None = None) -> str:
    transform_attr = f' transform="{transform}"' if transform else ""
    label = ""
    if text is not None:
        label = (
            f'<text data-nndv-role="required-text" data-required="true" data-label-role="name" '
            f'x="{width / 2:g}" y="{height / 2 + 4:g}" text-anchor="middle" font-size="12">{html.escape(text)}</text>'
        )
    return (
        f'<g data-nndv-role="node" class="node" data-node-id="{node_id}" transform="translate({x:g},{y:g})">'
        f'<rect data-nndv-role="node" class="node-body" width="{width:g}" height="{height:g}" fill="white" stroke="black"/>'
        f'<g data-nndv-role="container"{transform_attr}>{label}</g></g>'
    )


def edge(edge_id: str, source: str, target: str, path_data: str, *, marker: bool = False, transform: str | None = None) -> str:
    marker_attr = ' marker-end="url(#arrow)"' if marker else ""
    transform_attr = f' transform="{transform}"' if transform else ""
    return (
        f'<g data-nndv-role="edge" data-edge-id="{edge_id}" id="edge-{edge_id}" class="edge" '
        f'data-source="{source}" data-target="{target}"{transform_attr}>'
        f'<path data-nndv-role="edge" data-edge-id="{edge_id}" d="{path_data}" fill="none" stroke="black" stroke-width="2"{marker_attr}/></g>'
    )


MARKER = '<marker data-nndv-role="marker" id="arrow" markerWidth="9" markerHeight="7" refX="8" refY="3.5" orient="auto" viewBox="0 0 9 7"><path data-nndv-role="marker" d="M0,0 L9,3.5 L0,7 Z"/></marker>'


def fixtures() -> dict[str, str]:
    result: dict[str, str] = {}
    result["metadata-pass.svg"] = svg("metadata-pass", node("n", 80, 60, 140, 60), nodes=1, edges=0, content_width=140, content_height=60)
    result["uniform-scale-pass.svg"] = svg(
        "uniform-scale-pass",
        '<g data-nndv-role="container" transform="scale(.8)">' + node("n", 80, 60, 140, 60, text="Readable") + "</g>",
        nodes=1, edges=0, content_width=112, content_height=48, final_font_pt=7.2,
    )
    result["nested-transform-pass.svg"] = svg(
        "nested-transform-pass",
        '<g data-nndv-role="container" transform="translate(40,30)"><g data-nndv-role="container" transform="scale(1.5)">'
        + node("n", 10, 10, 40, 30)
        + "</g></g>",
        nodes=1, edges=0, content_width=60, content_height=45,
    )
    result["rotation-pass.svg"] = svg(
        "rotation-pass",
        '<g data-nndv-role="container" transform="translate(100,40) rotate(90)">' + node("n", 0, 0, 40, 40, text="OK") + "</g>",
        nodes=1, edges=0, content_width=40, content_height=40, final_font_pt=9,
    )
    result["legal-annotation-pass.svg"] = svg(
        "legal-annotation-pass",
        node("n", 20, 50, 80, 50)
        + '<g data-nndv-role="annotation" data-annotation-id="note"><rect data-nndv-role="annotation" x="180" y="55" width="60" height="35" fill="none" stroke="black"/></g>',
        nodes=1, edges=0, content_width=220, content_height=50,
    )
    endpoints = node("a", 20, 50, 60, 60) + node("b", 220, 50, 60, 60)
    result["marker-connection-pass.svg"] = svg(
        "marker-connection-pass", endpoints + edge("ab", "a", "b", "M80 80 L220 80", marker=True),
        nodes=2, edges=1, content_width=260, content_height=60, definitions=MARKER,
    )
    result["anisotropic-svg-scale-0.5-1.svg"] = svg(
        "anisotropic-svg-scale-0.5-1",
        node("n", 80, 60, 140, 60, text="Compressed", transform="scale(.5 1)"),
        nodes=1, edges=0, content_width=140, content_height=60, final_font_pt=9,
    )
    css_node = node("n", 80, 60, 140, 60).replace(
        "</g>",
        '<g data-nndv-role="container"><text data-nndv-role="required-text" data-required="true" x="70" y="34" text-anchor="middle" font-size="12" style="font-stretch:50%;transform:scaleX(.5);transform-origin:center">Compressed</text></g></g>',
        1,
    )
    result["css-font-stretch-compression.svg"] = svg(
        "css-font-stretch-compression", css_node, nodes=1, edges=0, content_width=140, content_height=60, final_font_pt=9,
    )
    result["annotation-over-node.svg"] = svg(
        "annotation-over-node",
        node("n", 80, 60, 140, 60)
        + '<g data-nndv-role="annotation" data-annotation-id="cover"><rect data-nndv-role="annotation" x="70" y="50" width="160" height="80" fill="none" stroke="red"/></g>',
        nodes=1, edges=0, content_width=160, content_height=80,
    )
    result["legend-over-node-or-page.svg"] = svg(
        "legend-over-node-or-page",
        node("n", 80, 60, 140, 60)
        + '<g data-nndv-role="legend" class="legend"><rect data-nndv-role="legend" x="100" y="70" width="180" height="150" fill="none" stroke="blue"/></g>',
        nodes=1, edges=0, content_width=200, content_height=160,
    )
    result["missing-authoritative-metadata.svg"] = svg(
        "missing-authoritative-metadata", node("n", 80, 60, 140, 60), nodes=1, edges=0,
        content_width=140, content_height=60, include_metadata=False,
    )
    result["stale-fixture-or-input-metadata.svg"] = svg(
        "stale-fixture-or-input-metadata", node("n", 80, 60, 140, 60), nodes=1, edges=0,
        content_width=140, content_height=60, stale=True,
    )
    marker_obstacle = endpoints + node("obstacle", 204, 73, 12, 5) + edge("ab", "a", "b", "M80 80 L220 80", marker=True)
    result["marker-body-enters-non-endpoint-node.svg"] = svg(
        "marker-body-enters-non-endpoint-node", marker_obstacle, nodes=3, edges=1,
        content_width=260, content_height=60, definitions=MARKER,
    )
    curve_nodes = node("a", 4, 20, 16, 16) + node("b", 52, 20, 16, 16) + node("obstacle", 31, 5, 10, 15)
    result["large-transform-curve-enters-node.svg"] = svg(
        "large-transform-curve-enters-node",
        '<g data-nndv-role="container" transform="scale(4)">' + curve_nodes + edge("curve", "a", "b", "M20 28 C30 0 42 0 52 28") + "</g>",
        nodes=3, edges=1, content_width=256, content_height=144,
    )
    result["nested-transform-clipping-or-text-overflow.svg"] = svg(
        "nested-transform-clipping-or-text-overflow",
        '<g data-nndv-role="container" transform="translate(-80,-30) scale(2)">' + node("n", 10, 10, 140, 60, text="Overflow") + "</g>",
        nodes=1, edges=0, content_width=280, content_height=120, final_font_pt=18,
    )
    result["unknown-role.svg"] = svg(
        "unknown-role", node("n", 80, 60, 140, 60) + '<circle data-nndv-role="mystery" cx="20" cy="20" r="4"/>',
        nodes=1, edges=0, content_width=204, content_height=104,
    )
    result["tangent-pass.svg"] = svg(
        "tangent-pass", node("block", 100, 40, 50, 40) + edge("t", "x", "y", "M20 38 L280 38"),
        nodes=1, edges=1, content_width=260, content_height=42,
    )
    result["tangent-fail.svg"] = svg(
        "tangent-fail", node("block", 100, 40, 50, 40) + edge("t", "x", "y", "M20 39.5 L280 39.5"),
        nodes=1, edges=1, content_width=260, content_height=40.5,
    )
    result["collinear-pass.svg"] = svg(
        "collinear-pass", edge("a", "a1", "a2", "M20 60 L120 60") + edge("b", "b1", "b2", "M150 60 L280 60"),
        nodes=0, edges=2, content_width=260, content_height=0,
    )
    result["collinear-fail.svg"] = svg(
        "collinear-fail", edge("a", "a1", "a2", "M20 60 L180 60") + edge("b", "b1", "b2", "M120 60 L280 60"),
        nodes=0, edges=2, content_width=260, content_height=0,
    )
    curve_endpoints = node("a", 20, 20, 40, 160) + node("b", 240, 20, 40, 160)
    s_curve = edge("curve", "a", "b", "M60 100 L70 100 C95 40 125 40 150 100 S205 160 230 100 L240 100")
    result["s-curve-pass.svg"] = svg(
        "s-curve-pass", curve_endpoints + s_curve,
        nodes=2, edges=1, content_width=260, content_height=160,
    )
    result["s-curve-collision.svg"] = svg(
        "s-curve-collision",
        curve_endpoints + node("obstacle", 105, 50, 24, 20) + s_curve,
        nodes=3, edges=1, content_width=260, content_height=160,
    )
    loop_curve = edge(
        "curve", "a", "b",
        "M60 100 L70 100 C130 0 190 0 120 100 C190 200 130 200 120 100 L230 100 L240 100",
    )
    result["loop-curve-pass.svg"] = svg(
        "loop-curve-pass", curve_endpoints + loop_curve,
        nodes=2, edges=1, content_width=260, content_height=160,
    )
    result["loop-curve-collision.svg"] = svg(
        "loop-curve-collision",
        curve_endpoints + node("obstacle", 142, 36, 24, 22) + loop_curve,
        nodes=3, edges=1, content_width=260, content_height=160,
    )
    multi_turn = edge(
        "curve", "a", "b",
        "M60 100 L70 100 C88 42 110 42 128 100 S174 158 196 100 S212 42 230 100 L240 100",
    )
    result["multi-turn-curve-pass.svg"] = svg(
        "multi-turn-curve-pass", curve_endpoints + multi_turn,
        nodes=2, edges=1, content_width=260, content_height=160,
    )
    result["multi-turn-curve-collision.svg"] = svg(
        "multi-turn-curve-collision",
        curve_endpoints + node("obstacle", 158, 138, 24, 22) + multi_turn,
        nodes=3, edges=1, content_width=260, content_height=160,
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    generated = fixtures()
    manifest = {"schema_version": "nndv-publication-input-1", "run_id": "oracle-truth-run", "fixtures": {}}
    for filename, content in generated.items():
        (args.output / filename).write_text(content, encoding="utf-8")
        name = Path(filename).stem
        expected = identity(name, content.count('class="node"'), content.count('class="edge"'))
        manifest["fixtures"][name] = {**expected, "exceptions": {"crossings": [], "collisions": []}}
    (args.output / "publication-input-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
