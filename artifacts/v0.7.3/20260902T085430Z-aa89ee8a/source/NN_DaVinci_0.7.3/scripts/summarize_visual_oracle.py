#!/usr/bin/env python3
"""Validate and split the independent final-SVG oracle evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).parents[1]
    source = root / "scripts/svg_quality_oracle.mjs"
    report = json.loads(args.report.read_text(encoding="utf-8"))
    expected_names = {"resnet", "transformer", "unet", "rnn", "moe", "multimodal", "diffusion"}
    observed_names = {Path(item["file"]).stem for item in report["reports"]}
    failures: list[str] = []
    if observed_names != expected_names:
        failures.append(f"authority SVG set drift: {sorted(observed_names)}")
    for item in report["reports"]:
        if not item["passed"]:
            failures.append(f"{Path(item['file']).name}: independent SVG oracle failed")
    source_text = source.read_text(encoding="utf-8")
    forbidden_imports = re.findall(r"(?:from|import)\s+nn_davinci(?:\.layout|\.quality)?", source_text)
    if forbidden_imports:
        failures.append(f"oracle has forbidden application imports: {forbidden_imports}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    process = {
        "oracle": report["oracle"], "browser": report["browser"],
        "separate_process": True, "reads_serialized_disk_svg": True,
        "source": str(source.relative_to(root)), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "forbidden_imports": forbidden_imports, "passed": not failures,
    }
    metadata = {
        "tolerances": report["tolerance"],
        "fixtures": {Path(item["file"]).stem: item["metadata_delta"] for item in report["reports"]},
        "passed": not failures,
    }
    (args.output_dir / "oracle-process.json").write_text(json.dumps(process, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.output_dir / "metadata-comparison.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if failures:
        raise SystemExit("\n".join(failures))
    print(json.dumps({"architectures": len(report["reports"]), "passed": True}, sort_keys=True))


if __name__ == "__main__":
    main()
