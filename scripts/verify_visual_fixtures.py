#!/usr/bin/env python3
"""Block on authoritative visual input, IR identity, and provenance drift."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from nn_davinci.adapters.manual import ManualAdapter
from nn_davinci.layout import aggregate_repeated_blocks, unroll_recurrent_graph


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).parents[1]
    authority = json.loads((root / "verification/fixtures/visual-authority-0.2.1.json").read_text(encoding="utf-8"))
    records: dict[str, object] = {}
    failures: list[str] = []
    for name, expected in authority["fixtures"].items():
        source_path = root / expected["path"]
        digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        source = ManualAdapter().load(source_path)
        processed = unroll_recurrent_graph(source, steps=3) if name == "rnn" else source.copy()
        processed = aggregate_repeated_blocks(processed)
        observed = {
            "sha256": digest,
            "source_node_ids": sorted(node.id for node in source.nodes),
            "source_edge_ids": sorted(edge.id for edge in source.edges),
            "processed_node_ids": sorted(node.id for node in processed.nodes),
            "processed_edge_ids": sorted(edge.id for edge in processed.edges),
            "critical_edge_ids_present": sorted(set(expected["critical_edge_ids"]) & {edge.id for edge in processed.edges}),
            "bridge_or_junction_nodes": sorted(node.id for node in processed.nodes if node.op_type.lower() in {"bridge", "junction"} or "bridge" in node.tags or "junction" in node.tags),
        }
        for key in ("sha256", "source_node_ids", "source_edge_ids", "processed_node_ids", "processed_edge_ids"):
            if observed[key] != expected[key]:
                failures.append(f"{name}: {key} drifted")
        if observed["critical_edge_ids_present"] != sorted(expected["critical_edge_ids"]):
            failures.append(f"{name}: critical edge missing")
        if observed["bridge_or_junction_nodes"]:
            failures.append(f"{name}: authority fixture contains bridge/junction marker")
        if name == "rnn":
            provenance = expected["provenance"]
            copies = [node for node in processed.nodes if node.attributes.get("unrolled_from") == provenance["source_node_id"]]
            if sorted(node.id for node in copies) != sorted(provenance["unrolled_node_ids"]):
                failures.append("rnn: unrolled node provenance incomplete")
            for edge_id, source_ids in provenance["source_edge_mapping"].items():
                edge = processed.edge_map().get(edge_id)
                if edge is None or not any(edge.attributes.get(key) in source_ids for key in ("unrolled_from", "unrolled_from_node")):
                    failures.append(f"rnn: missing edge provenance {edge_id}")
        if name == "moe":
            provenance = expected["provenance"]
            proxy = processed.node_map().get(provenance["proxy_id"])
            if proxy is None or proxy.attributes.get("repeat_count") != provenance["repeat_count"] or sorted(proxy.attributes.get("aggregated_node_ids", [])) != sorted(provenance["aggregated_node_ids"]):
                failures.append("moe: aggregate node provenance incomplete")
            for edge_id, source_ids in provenance["source_edge_mapping"].items():
                edge = processed.edge_map().get(edge_id)
                if edge is None or sorted(edge.attributes.get("source_edges", [])) != sorted(source_ids):
                    failures.append(f"moe: aggregate edge provenance incomplete {edge_id}")
        records[name] = observed
    report = {"manifest": "visual-authority-0.2.1.json", "fixtures": records, "failures": failures, "passed": not failures}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if failures:
        raise SystemExit("\n".join(failures))
    print(json.dumps({"visual_fixtures": len(records), "passed": len(records), "failed": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
