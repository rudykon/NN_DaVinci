#!/usr/bin/env python3
"""Release-block the three paper examples against executable semantic goldens."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _nested_matches(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    for key, value in expected.items():
        if isinstance(value, dict):
            if not isinstance(actual.get(key), dict) or not _nested_matches(actual[key], value):
                return False
        elif actual.get(key) != value:
            return False
    return True


def _validate_source_path(
    path: dict[str, Any],
    edge_map: dict[str, dict[str, Any]],
) -> bool:
    edge_ids = list(path.get("source_edge_ids", []))
    node_ids = list(path.get("source_node_ids", []))
    if path.get("direction") != "forward" or not edge_ids or len(node_ids) != len(edge_ids) + 1:
        return False
    return all(
        edge_id in edge_map
        and edge_map[edge_id]["source"] == node_ids[index]
        and edge_map[edge_id]["target"] == node_ids[index + 1]
        for index, edge_id in enumerate(edge_ids)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper-examples", type=Path, required=True)
    parser.add_argument("--golden-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paper = _load(args.paper_examples)
    root = args.paper_examples.parent
    examples: dict[str, Any] = {}
    for golden_path in sorted(args.golden_dir.glob("*.json")):
        golden = _load(golden_path)
        name = str(golden["example"])
        item = paper.get("examples", {}).get(name, {})
        evidence_path = root / str(item.get("scientific_fidelity", ""))
        project_path = root / str(item.get("project", ""))
        caption_path = root / str(item.get("caption", ""))
        source_paths_path = root / str(item.get("source_path_provenance", ""))
        failures: list[str] = []
        if not all(path.is_file() for path in (evidence_path, project_path, caption_path, source_paths_path)):
            failures.append("required landed scientific evidence is missing")
            examples[name] = {"passed": False, "failures": failures}
            continue
        evidence = _load(evidence_path)
        project = _load(project_path)
        source_paths = _load(source_paths_path)
        caption = caption_path.read_text(encoding="utf-8")
        graph = project.get("graph", {})
        edge_map = {edge["id"]: edge for edge in graph.get("edges", [])}
        panel_name = str(golden["panel"])
        panel = evidence.get("panels", {}).get(panel_name, {})
        nodes = list(panel.get("nodes", []))
        edges = list(panel.get("edges", []))
        roles = {str(node.get("role")) for node in nodes}
        required_roles = set(golden.get("required_roles", []))
        if not required_roles.issubset(roles):
            failures.append(f"missing roles: {sorted(required_roles - roles)}")
        actual_edges = {
            (str(edge.get("source_role")), str(edge.get("target_role")), str(edge.get("kind")))
            for edge in edges
        }
        required_edges = {tuple(edge) for edge in golden.get("required_edges", [])}
        if not required_edges.issubset(actual_edges):
            failures.append(f"missing key edges: {sorted(required_edges - actual_edges)}")
        indegree = panel.get("merge_indegree", {})
        if not _nested_matches(indegree, golden.get("merge_indegree", {})):
            failures.append("merge indegree does not match the golden graph")
        if not _nested_matches(evidence.get("repetition", {}), golden.get("repetition", {})):
            failures.append("repetition evidence does not match full-structure golden counts")

        role_sources: dict[str, set[str]] = {}
        for node in nodes:
            role_sources.setdefault(str(node.get("role")), set()).update(node.get("source_node_ids", []))
        path_count = 0
        for edge in edges:
            paths = list(edge.get("source_paths", []))
            if not paths or edge.get("source_path") != paths[0]:
                failures.append(f"paper edge {edge.get('id')} lacks stable source-path provenance")
                continue
            for path in paths:
                path_count += 1
                if not _validate_source_path(path, edge_map):
                    failures.append(f"paper edge {edge.get('id')} has a non-forward or broken source path")
                    continue
                node_ids = path["source_node_ids"]
                if node_ids[0] not in role_sources.get(str(edge.get("source_role")), set()):
                    failures.append(f"paper edge {edge.get('id')} source path starts outside its source aggregate")
                if node_ids[-1] not in role_sources.get(str(edge.get("target_role")), set()):
                    failures.append(f"paper edge {edge.get('id')} source path ends outside its target aggregate")
        if not path_count:
            failures.append("no source paths were independently replayed")
        landed_path_count = sum(
            len(paths) for paths in source_paths.get("panels", {}).values()
        )
        expected_path_count = sum(
            len(edge.get("source_paths", []))
            for candidate in evidence.get("panels", {}).values()
            for edge in candidate.get("edges", [])
        )
        if landed_path_count != expected_path_count:
            failures.append("source-path provenance report is incomplete")

        expected_caption = golden.get("caption", {})
        input_names = [item.get("name") for item in graph.get("inputs", [])]
        output_names = [item.get("name") for item in graph.get("outputs", [])]
        if input_names != expected_caption.get("input_names"):
            failures.append(f"Graph IR input names differ: {input_names}")
        if output_names != expected_caption.get("output_names"):
            failures.append(f"Graph IR output names differ: {output_names}")
        if any(name in input_names for name in expected_caption.get("forbidden_input_names", [])):
            failures.append("a Graph IR input still uses an output tensor name")
        if not all(name in caption for name in input_names + output_names):
            failures.append("caption omits an evidenced input or output")
        if "receives input" not in caption or "produces output" not in caption:
            failures.append("caption does not distinguish input from output")
        if evidence.get("passed") is not True or not all(evidence.get("invariants", {}).values()):
            failures.append("generator scientific invariants did not pass")
        examples[name] = {
            "passed": not failures,
            "failures": failures,
            "panel": panel_name,
            "roles": sorted(roles),
            "key_edges": len(required_edges),
            "source_paths_replayed": path_count,
            "merge_indegree": {key: indegree.get(key) for key in golden.get("merge_indegree", {})},
            "repetition": evidence.get("repetition"),
            "inputs": input_names,
            "outputs": output_names,
        }
    failures = [name for name, item in examples.items() if not item["passed"]]
    report = {
        "schema_version": "0.4.2-scientific-fidelity-acceptance-1",
        "acceptance": "PASS" if len(examples) == 3 and not failures else "FAIL",
        "counts": {"total": len(examples), "passed": len(examples) - len(failures), "failed": len(failures)},
        "examples": examples,
        "failures": failures,
        "passed": len(examples) == 3 and not failures,
        "independence": (
            "Golden roles/edges/counts are compared with landed panel evidence; every source edge ID and "
            "directed node chain is replayed against the Graph IR saved in the landed project."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"acceptance": report["acceptance"], **report["counts"]}, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
