#!/usr/bin/env python3
"""Run eight negative semantic-presentation mutations and record exact blockers."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any, Callable
import xml.etree.ElementTree as ET

from nn_davinci.ir import Edge, GraphIR, Node
from nn_davinci.semantic import derive_semantic_view


def _load_oracle() -> Any:
    path = Path(__file__).with_name("semantic_presentation_oracle_0_7_3.py")
    spec = importlib.util.spec_from_file_location("nndv_semantic_presentation_oracle_073", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load semantic presentation oracle: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _svg(destination: Path) -> tuple[ET.ElementTree, ET.Element]:
    tree = ET.parse(destination / "scene.svg")
    return tree, tree.getroot()


def _write(tree: ET.ElementTree, destination: Path) -> None:
    tree.write(destination / "scene.svg", encoding="utf-8", xml_declaration=True)


def _delete_label(destination: Path) -> None:
    tree, root = _svg(destination)
    victim = next(item for item in root.iter() if item.attrib.get("data-kind") == "label")
    for parent in root.iter():
        if victim in list(parent):
            parent.remove(victim)
            break
    _write(tree, destination)


def _hide_label(destination: Path) -> None:
    tree, root = _svg(destination)
    victim = next(item for item in root.iter() if item.attrib.get("data-kind") == "label")
    victim.set("style", "display:none")
    _write(tree, destination)


def _off_page_label(destination: Path) -> None:
    tree, root = _svg(destination)
    victim = next(item for item in root.iter() if item.attrib.get("data-kind") == "label")
    victim.set("x", "99999")
    _write(tree, destination)


def _wrong_role_id(destination: Path) -> None:
    tree, root = _svg(destination)
    labels = [item for item in root.iter() if item.attrib.get("data-kind") == "label"]
    labels[0].set("data-architecture-role-id", labels[1].attrib["data-architecture-role-id"])
    _write(tree, destination)


def _delete_and_reverse_routes(destination: Path) -> None:
    tree, root = _svg(destination)
    arrows = [
        item
        for item in root.iter()
        if item.attrib.get("data-kind") == "arrow" and item.attrib.get("data-architecture-route-id")
    ]
    route_ids = list(dict.fromkeys(item.attrib["data-architecture-route-id"] for item in arrows))
    if len(route_ids) < 2:
        raise RuntimeError("route mutation requires a case with at least two critical routes")
    for parent in root.iter():
        for child in list(parent):
            if child.attrib.get("data-architecture-route-id") == route_ids[0]:
                parent.remove(child)
    reverse = next(item for item in arrows if item.attrib["data-architecture-route-id"] == route_ids[1])
    reverse.set("data-architecture-direction", "target-to-source")
    endpoints = json.loads(reverse.attrib["data-endpoint-role-ids"])
    reverse.set("data-endpoint-role-ids", json.dumps(list(reversed(endpoints))))
    _write(tree, destination)


def _repeat_count(destination: Path) -> None:
    tree, root = _svg(destination)
    victim = next(
        item
        for item in root.iter()
        if item.attrib.get("data-kind") == "label" and int(item.attrib.get("data-repeat-count", "1")) > 1
    )
    victim.set("data-repeat-count", "99")
    _write(tree, destination)


def _stale_digest(destination: Path) -> None:
    tree, root = _svg(destination)
    victim = next(item for item in root.iter() if item.attrib.get("data-kind") == "label")
    victim.set("data-evidence-digest", "0" * 64)
    _write(tree, destination)


def _lexical_false_positive() -> dict[str, Any]:
    nodes = [
        Node("node_a", "Residual Attention Encoder", "Identity", path="resnet.encoder.expert", category="operation"),
        Node("node_b", "Diffusion U-Net Router", "Identity", path="unet.router.fusion", category="operation"),
        Node("node_c", "Top-k MoE Fusion", "Identity", path="moe.attention.decoder", category="operation"),
    ]
    graph = GraphIR(
        name="ResNet50 Transformer U-Net Diffusion Top-k MoE Image-Text",
        nodes=nodes,
        edges=[Edge("edge_a", "node_a", "node_b"), Edge("edge_b", "node_b", "node_c")],
        metadata={"corpus_key": "resnet50", "requested_layout_family": "transformer"},
        analysis={"prelayout": {"coordinates": [[-9000, 5000, 12], [0, 0, 0], [9000, -5000, -12]]}},
    ).validate()
    evidence = derive_semantic_view(graph).architecture_evidence
    passed = evidence.family == "unknown" and bool(evidence.unknown_reason)
    return {
        "id": "name_corpus_false_positive",
        "status": "PASS" if passed else "FAIL",
        "expected_blockers": ["name_corpus_false_positive_prevented"],
        "observed_blockers": ["name_corpus_false_positive_prevented"] if passed else [],
        "result_family": evidence.family,
        "unknown_reason": evidence.unknown_reason,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    oracle = _load_oracle()
    mutations: list[tuple[str, Callable[[Path], None], set[str]]] = [
        ("deleted_role_label", _delete_label, {"svg_missing_role_label"}),
        ("metadata_only_hidden_label", _hide_label, {"svg_hidden_role_label"}),
        ("off_page_label", _off_page_label, {"svg_role_label_off_page"}),
        ("wrong_role_id", _wrong_role_id, {"svg_role_binding_mismatch"}),
        (
            "deleted_and_reversed_critical_routes",
            _delete_and_reverse_routes,
            {"svg_missing_route", "svg_route_direction_mismatch", "svg_route_endpoint_mismatch"},
        ),
        ("modified_repeat_count", _repeat_count, {"svg_repeat_count_mismatch"}),
        ("stale_evidence_digest", _stale_digest, {"stale_evidence_digest"}),
    ]
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="nndv-073-semantic-mutations-") as temporary_name:
        temporary = Path(temporary_name)
        for identifier, mutate, expected in mutations:
            destination = temporary / identifier
            shutil.copytree(args.case_dir, destination)
            mutate(destination)
            inspection = oracle.inspect_case(destination, require_pptx=True, require_tikz_pdf=False)
            observed = {item["code"] for item in inspection["blockers"]}
            passed = inspection["status"] == "FAIL" and expected.issubset(observed)
            results.append(
                {
                    "id": identifier,
                    "status": "PASS" if passed else "FAIL",
                    "expected_blockers": sorted(expected),
                    "observed_blockers": sorted(observed),
                }
            )
    results.append(_lexical_false_positive())
    report = {
        "schema_version": "nndv-0.7.3-semantic-negative-mutations-1",
        "release": "0.7.3 — Reader-Visible Scientific Completeness & Generalization Hotfix",
        "status": "PASS" if len(results) == 8 and all(item["status"] == "PASS" for item in results) else "FAIL",
        "mutation_count": len(results),
        "mutations": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "mutation_count": len(results)}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
