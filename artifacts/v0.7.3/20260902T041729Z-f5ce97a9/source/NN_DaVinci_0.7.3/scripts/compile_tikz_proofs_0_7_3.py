#!/usr/bin/env python3
"""Compile the seven landed real-model TikZ sources into isolated PDF proofs."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()

    case_root = args.input_root / "real-models"
    cases = sorted(path for path in case_root.iterdir() if path.is_dir())
    if len(cases) != 7:
        raise SystemExit(f"expected seven real-model case directories, found {len(cases)}")
    if args.output_root.exists() and any(args.output_root.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty proof root: {args.output_root}")
    args.output_root.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    failures: list[str] = []
    for case in cases:
        source = case / "scene.tex"
        destination = args.output_root / case.name
        destination.mkdir()
        with tempfile.TemporaryDirectory(prefix=f"nndv-073-tikz-{case.name}-") as temporary_name:
            temporary = Path(temporary_name)
            environment = os.environ.copy()
            for variable, leaf in (
                ("TEXMFVAR", "texmf-var"),
                ("TEXMFCONFIG", "texmf-config"),
                ("TEXMFCACHE", "texmf-cache"),
            ):
                cache = temporary / leaf
                cache.mkdir()
                environment[variable] = str(cache)
            commands = []
            for pass_index in range(2):
                command = [
                    "pdflatex",
                    "-halt-on-error",
                    "-interaction=nonstopmode",
                    "-jobname=scene-tikz",
                    "-output-directory",
                    str(temporary),
                    str(source),
                ]
                result = subprocess.run(command, cwd=case, env=environment, text=True, capture_output=True, check=False)
                commands.append({"pass": pass_index + 1, "returncode": result.returncode})
                if result.returncode:
                    failures.append(f"{case.name}: pdflatex pass {pass_index + 1} failed: {(result.stdout + result.stderr)[-800:]}")
                    break
            compiled = temporary / "scene-tikz.pdf"
            if compiled.is_file() and not any(item.startswith(f"{case.name}:") for item in failures):
                landed = destination / compiled.name
                shutil.copy2(compiled, landed)
                records.append(
                    {
                        "case": case.name,
                        "source": str(source),
                        "source_sha256": _digest(source),
                        "pdf": str(landed),
                        "pdf_sha256": _digest(landed),
                        "bytes": landed.stat().st_size,
                        "commands": commands,
                    }
                )
            elif not compiled.is_file():
                failures.append(f"{case.name}: pdflatex did not create scene-tikz.pdf")
    report = {
        "schema_version": "nndv-0.7.3-tikz-pdf-proofs-1",
        "release": "0.7.3 — Reader-Visible Scientific Completeness & Generalization Hotfix",
        "status": "PASS" if len(records) == 7 and not failures else "FAIL",
        "case_count": len(records),
        "proofs": records,
        "failures": failures,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "case_count": len(records), "failures": failures}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
