#!/usr/bin/env python3
"""Create fresh v0.2 visual acceptance samples and geometry evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from nn_davinci.adapters.manual import ManualAdapter
from nn_davinci.analysis import analyze_graph
from nn_davinci.layout import LayoutEngine, aggregate_repeated_blocks, unroll_recurrent_graph
from nn_davinci.labels import node_label_lines
from nn_davinci.quality import assess_geometry
from nn_davinci.render import SvgRenderer, export_graph
from nn_davinci.themes import get_theme


ARCHITECTURES = ("resnet", "transformer", "unet", "rnn", "moe", "multimodal", "diffusion")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--run-id", default="diagnostic-run")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).parents[1]
    authority = json.loads((root / "verification" / "fixtures" / "visual-authority-0.2.1.json").read_text(encoding="utf-8"))
    records: dict[str, object] = {}
    prepared: dict[str, tuple[object, object, object, dict[str, object]]] = {}
    for name in ARCHITECTURES:
        graph = ManualAdapter().load(root / "examples" / f"{name}.json")
        if name == "rnn":
            graph = unroll_recurrent_graph(graph, steps=3)
        graph = aggregate_repeated_blocks(analyze_graph(graph)["graph"])
        theme = get_theme("neurips", page="double-column")
        layout = LayoutEngine().layout(
            graph,
            algorithm="auto",
            page=theme["page"],
            page_preset="double-column",
            font_size=theme["font_size"],
            minimum_font_pt=theme["minimum_font_pt"],
            label_density="paper",
        )
        fixed = authority["fixtures"][name]
        identity: dict[str, object] = {
            "fixture_id": name,
            "input_sha256": fixed["sha256"],
            "run_id": args.run_id,
            "node_count": len(graph.nodes),
            "edge_count": len(graph.edges),
        }
        prepared[name] = (graph, layout, theme, identity)
    presentation_manifest = {
        "schema_version": "nndv-publication-input-1",
        "run_id": args.run_id,
        "fixtures": {
            name: {
                **identity,
                "source_path": authority["fixtures"][name]["path"],
                "processed_node_ids": authority["fixtures"][name]["processed_node_ids"],
                "processed_edge_ids": authority["fixtures"][name]["processed_edge_ids"],
                "critical_edge_ids": authority["fixtures"][name]["critical_edge_ids"],
                "provenance": authority["fixtures"][name]["provenance"],
                "exceptions": {"crossings": [], "collisions": []},
            }
            for name, (_, _, _, identity) in prepared.items()
        },
    }
    manifest_path = args.output / "publication-input-manifest.json"
    manifest_path.write_text(json.dumps(presentation_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    for name, (graph, layout, theme, identity) in prepared.items():
        paths = export_graph(
            graph, layout, theme, args.output / name,
            formats=["svg", "pdf", "tikz", "png"], label_density="paper",
            publication=True, publication_manifest=identity, show_legend=False,
        )
        svg = SvgRenderer().render(
            graph, layout, theme, label_density="paper", publication=True,
            publication_manifest=identity, show_legend=False,
        )
        quality = assess_geometry(graph, layout, svg)
        if not quality.passed:
            raise RuntimeError(f"{name} failed geometry acceptance: {quality.to_dict()}")
        records[name] = {
            "layout_reason": layout.metadata["paper"]["selection_reason"],
            "paper": layout.metadata["paper"],
            "quality": quality.to_dict(),
            "label_density": "paper",
            "publication_input_manifest_sha256": manifest_sha256,
            "required_labels": {
                node.id: [line.text for line in node_label_lines(
                    node, theme, density="paper",
                    max_width=max(20.0, layout.nodes[node.id].width - 2 * float(theme.get("node_padding", 10))),
                ) if line.mandatory]
                for node in graph.nodes if node.id in layout.nodes
            },
            "graph_ir": {
                "node_ids": sorted(node.id for node in graph.nodes),
                "edge_ids": sorted(edge.id for edge in graph.edges),
            },
            "files": {
                path.suffix.lstrip("."): {
                    "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
                for path in paths
            },
        }
    (args.output / "visual-acceptance.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"architectures": len(records), "output": str(args.output.resolve()), "publication_input_manifest_sha256": manifest_sha256}, ensure_ascii=False))


if __name__ == "__main__":
    main()
