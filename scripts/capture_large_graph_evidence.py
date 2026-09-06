#!/usr/bin/env python3
"""Emit current-run corpus and Web large-graph preflight evidence."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from nn_davinci.server import create_app

from stress_graphs import GENERATOR_VERSION, SEED, canonical_graph_hash, corpus, deep_chain


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).parents[1]
    expected = json.loads((root / "verification/fixtures/stress-corpus-0.2.1.json").read_text(encoding="utf-8"))
    observed = {
        name: {"nodes": len(graph.nodes), "edges": len(graph.edges), "sha256": canonical_graph_hash(graph)}
        for name, graph in corpus().items()
    }
    failures = [name for name, values in observed.items() if values != expected["corpora"].get(name)]
    corpus_report = {
        "generator_version": GENERATOR_VERSION,
        "seed": SEED,
        "corpora": observed,
        "failures": failures,
        "passed": not failures and expected["seed"] == SEED and expected["generator_version"] == GENERATOR_VERSION,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "corpus-manifest-check.json").write_text(json.dumps(corpus_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    graph = deep_chain(10_000)
    client = create_app().test_client()
    started = time.perf_counter()
    response = client.post("/api/render", json={"graph": graph.to_dict()})
    elapsed = time.perf_counter() - started
    body = response.get_json()
    web_report = {
        "nodes": len(graph.nodes), "edges": len(graph.edges), "http_status": response.status_code,
        "elapsed_seconds": elapsed, "response": body,
        "passed": response.status_code == 422 and elapsed <= 2 and body.get("error") == "graph_too_large"
        and all(word in body.get("hint", "") for word in ("focus", "summary")),
    }
    (args.output / "web-preflight.json").write_text(json.dumps(web_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not corpus_report["passed"] or not web_report["passed"]:
        raise SystemExit("large-graph corpus or Web preflight evidence failed")
    print(json.dumps({"corpora": len(observed), "web_preflight_seconds": elapsed, "passed": True}, sort_keys=True))


if __name__ == "__main__":
    main()
