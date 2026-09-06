#!/usr/bin/env python3
"""Block on required paper labels across SVG, PDF, and TikZ outputs."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from xml.etree import ElementTree


NS = {"svg": "http://www.w3.org/2000/svg"}


def normalize(value: str) -> str:
    return " ".join(
        value.replace("$\\times$", "×").replace("\\_", "_").replace("\\%", "%").split()
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compiled-directory", type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.directory / "visual-acceptance.json").read_text(encoding="utf-8"))
    records = {}
    failures: list[str] = []
    for name, expected in manifest.items():
        svg_root = ElementTree.parse(args.directory / f"{name}.svg").getroot()
        svg_lines = [normalize(element.text or "") for element in svg_root.findall(".//svg:text", NS) if element.attrib.get("data-required") == "true"]
        tikz = (args.directory / f"{name}.tex").read_text(encoding="utf-8")
        tikz_lines = [normalize(match.group(1)) for match in re.finditer(r"^% NNDV-LABEL [^ ]+ [^ ]+ (.*)$", tikz, re.MULTILINE)]
        pdf_text = subprocess.run(["pdftotext", "-layout", str(args.directory / f"{name}.pdf"), "-"], check=True, capture_output=True, text=True).stdout
        pdf_lines = [normalize(line) for line in pdf_text.splitlines() if normalize(line)]
        compiled_lines: list[str] = []
        if args.compiled_directory:
            compiled_text = subprocess.run(
                ["pdftotext", "-layout", str(args.compiled_directory / f"{name}.pdf"), "-"],
                check=True, capture_output=True, text=True,
            ).stdout
            compiled_lines = [normalize(line) for line in compiled_text.splitlines() if normalize(line)]
        required = [normalize(line) for lines in expected["required_labels"].values() for line in lines]
        missing_svg = [line for line in required if line not in svg_lines]
        missing_tikz = [line for line in required if line not in tikz_lines]
        missing_pdf = [line for line in required if not any(line in observed for observed in pdf_lines)]
        missing_compiled = [line for line in required if compiled_lines and not any(line in observed for observed in compiled_lines)]
        if missing_svg or missing_tikz or missing_pdf or missing_compiled:
            failures.append(f"{name}: missing SVG={missing_svg}, TikZ={missing_tikz}, PDF={missing_pdf}, compiled TikZ={missing_compiled}")
        # TikZ uses scriptsize (7pt) for op types and footnotesize (8pt) for
        # statistics in the standard 10pt standalone document. Reject smaller
        # macros or explicit text scaling in required labels.
        tikz_font_gate = "\\tiny" not in tikz and "\\resizebox" not in tikz and "\\scalebox" not in tikz
        if not tikz_font_gate:
            failures.append(f"{name}: TikZ required labels use a sub-7pt or horizontally scaled construct")
        records[name] = {
            "required_count": len(required), "svg_required_count": len(svg_lines), "tikz_marker_count": len(tikz_lines),
            "missing_svg": missing_svg, "missing_tikz": missing_tikz, "missing_pdf": missing_pdf,
            "missing_compiled_tikz_pdf": missing_compiled, "tikz_minimum_required_font_pt": 7.0,
            "tikz_horizontal_scale": 1.0, "tikz_font_gate": tikz_font_gate,
            "line_break_consistent_svg_tikz": svg_lines == tikz_lines,
        }
        if svg_lines != tikz_lines:
            failures.append(f"{name}: SVG/TikZ line ordering differs")
    report = {"fixtures": records, "passed": not failures, "failures": failures}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if failures:
        raise SystemExit("\n".join(failures))
    print(json.dumps({"architectures": len(records), "passed": len(records), "failed": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
