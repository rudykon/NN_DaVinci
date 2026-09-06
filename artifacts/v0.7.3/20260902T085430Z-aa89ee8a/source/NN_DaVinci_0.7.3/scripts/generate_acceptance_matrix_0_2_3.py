#!/usr/bin/env python3
"""Generate/check the 0.2.3 post-seal semantic-parity matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from generate_acceptance_matrix_0_2_2 import matrix as previous_matrix


ROOT = Path(__file__).parents[1]
TARGET = ROOT / "verification" / "acceptance-matrix-0.2.3.json"
MUTATION_CASES = 54


def matrix() -> dict:
    document = previous_matrix()
    document["schema_version"] = "3.1.0"
    document["release"] = "0.2.3"
    document["policy"] = (
        "Each canonical blocker requires its declared JSON Pointer/type/comparison and an independent "
        "post-seal semantic replay; aliases and diagnostic assertions are not counted."
    )
    document["migration"]["source"] = "acceptance-matrix-0.2.2.json"
    document["migration"]["reason"] = (
        "The 34 canonical blocker identities are unchanged; 0.2.3 adds post-seal predicate parity "
        "and expands the mutation evidence without creating duplicate blocker counts."
    )
    rows = {row["requirement_id"]: row for row in document["requirements"]}
    rows["TEST-01"]["inputs"] = [
        "tests/trust-anchor-check.json",
        "tests/collected-test-ids.txt",
        "tests/frozen-test-ids.txt",
    ]
    rows["STAT-02"]["inputs"].append("e2e/semantic-workflow.json")
    rows["LOCK-01"]["inputs"] = ["requirements/verification-linux-x86_64-py313-0.2.3.lock"]
    rows["GRAPH-02"].update({
        "validator_id": "graph_semantics", "requirement_class": "graph",
        "evidence_path": "stress/results.json", "json_pointer": "/named_graph_corpora",
        "observed_value_type": "object", "comparison": "ne", "expected_value": {},
        "inputs": [],
    })
    rows["MATRIX-01"]["expected_value"] = MUTATION_CASES
    rows["MATRIX-01"]["title"] = "Canonical predicate parity and composite post-seal mutations are killed"
    return document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(matrix(), ensure_ascii=False, indent=2) + "\n"
    if args.write:
        TARGET.write_text(rendered, encoding="utf-8")
    elif not TARGET.is_file() or TARGET.read_text(encoding="utf-8") != rendered:
        raise SystemExit("versioned 0.2.3 acceptance matrix differs from its deterministic definition")
    print(json.dumps({
        "independent_blockers": len(matrix()["requirements"]),
        "mutation_cases": MUTATION_CASES, "target": str(TARGET),
        "matched": TARGET.is_file() and TARGET.read_text(encoding="utf-8") == rendered,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
