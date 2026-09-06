#!/usr/bin/env python3
"""Generate all seven deliverable formats into an initially empty directory."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from nn_davinci.adapters.manual import ManualAdapter
from nn_davinci.analysis import analyze_graph
from nn_davinci.layout import LayoutEngine, aggregate_repeated_blocks
from nn_davinci.quality import assess_geometry
from nn_davinci.render import SvgRenderer, export_graph
from nn_davinci.themes import get_theme


def generate(source: Path, output: Path) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise RuntimeError(f"Acceptance output must start empty: {output}")
    graph = analyze_graph(ManualAdapter().load(source))["graph"]
    graph = aggregate_repeated_blocks(graph)
    theme = get_theme("neurips", page="double-column")
    layout = LayoutEngine().layout(
        graph,
        algorithm="resnet",
        page=theme["page"],
        page_preset="double-column",
        font_size=theme["font_size"],
        minimum_font_pt=theme["minimum_font_pt"],
        label_density="paper",
    )
    paths = export_graph(
        graph,
        layout,
        theme,
        output / "resnet-v02",
        formats=["svg", "pdf", "tikz", "png", "eps", "pptx", "html"],
        label_density="paper",
    )
    svg = SvgRenderer().render(graph, layout, theme)
    quality = assess_geometry(graph, layout, svg).to_dict()
    manifest = {
        "source": str(source.resolve()),
        "formats": {
            path.suffix.lstrip("."): {
                "path": str(path.resolve()),
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in paths
        },
        "paper": layout.metadata["paper"],
        "geometry_quality": quality,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--source", type=Path, default=Path(__file__).parents[1] / "examples" / "resnet.json")
    args = parser.parse_args()
    print(json.dumps(generate(args.source, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
