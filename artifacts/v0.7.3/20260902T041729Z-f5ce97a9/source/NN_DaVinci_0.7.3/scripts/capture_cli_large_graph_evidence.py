#!/usr/bin/env python3
"""Capture subprocess-level CLI large-graph rejection and recovery evidence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from xml.etree import ElementTree

from stress_graphs import deep_chain


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).parents[1]
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="nndv-cli-large-") as directory:
        temporary = Path(directory)
        source = temporary / "large graph.json"
        focused_svg = temporary / "focused.svg"
        source.write_text(json.dumps(deep_chain(10_000).to_dict()), encoding="utf-8")
        environment = {**os.environ, "PYTHONPATH": f"{root / 'src'}:{root}"}
        base = [sys.executable, "-m", "nn_davinci", "render", str(source), "--no-analysis", "--format", "svg"]
        started = time.perf_counter()
        rejected = subprocess.run(base, cwd=root, env=environment, capture_output=True, text=True, check=False)
        rejected_seconds = time.perf_counter() - started
        try:
            rejected_payload = json.loads(rejected.stderr)
        except json.JSONDecodeError:
            rejected_payload = {}
        if rejected.returncode != 2 or rejected_seconds > 2 or rejected_payload.get("error") != "graph_too_large":
            failures.append("10k no-focus CLI render did not reject with graph_too_large within two seconds")
        if "--focus NODE_ID --focus-hops 2" not in rejected_payload.get("hint", "") or "--summary" not in rejected_payload.get("hint", ""):
            failures.append("CLI recovery message is not copyable")
        focused = subprocess.run(
            [*base, "--focus", "n05000", "--focus-hops", "2", "-o", str(focused_svg)],
            cwd=root, env=environment, capture_output=True, text=True, check=False,
        )
        rendered_nodes = 0
        if focused.returncode == 0 and focused_svg.is_file():
            rendered_nodes = len(ElementTree.parse(focused_svg).findall(".//*[@data-nndv-role='node']"))
        if focused.returncode or not 0 < rendered_nodes <= 500:
            failures.append(f"focus recovery failed or exceeded 500 nodes: status={focused.returncode}, nodes={rendered_nodes}")
        summary = subprocess.run([*base, "--summary"], cwd=root, env=environment, capture_output=True, text=True, check=False)
        try:
            structure = json.loads(summary.stdout)
        except json.JSONDecodeError:
            structure = {}
        if summary.returncode or (structure.get("nodes"), structure.get("edges")) != (10_000, 9_999):
            failures.append("summary recovery did not preserve 10k-chain structure")
        if structure.get("layout_constructed") is not False or structure.get("svg_constructed") is not False:
            failures.append("summary recovery unexpectedly constructed layout/SVG")
    report = {
        "schema_version": "0.2.2-cli-scale-1",
        "rejection": {"seconds": rejected_seconds, "returncode": rejected.returncode, "payload": rejected_payload},
        "focus": {"returncode": focused.returncode, "rendered_nodes": rendered_nodes},
        "summary": {"returncode": summary.returncode, "structure": structure},
        "failures": failures,
        "passed": not failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"passed": not failures, "rejection_seconds": rejected_seconds, "rendered_nodes": rendered_nodes}, sort_keys=True))
    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
