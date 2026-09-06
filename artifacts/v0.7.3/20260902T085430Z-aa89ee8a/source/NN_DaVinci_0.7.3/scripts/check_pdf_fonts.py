#!/usr/bin/env python3
"""Require every font reported by pdffonts to be embedded."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def parse_embedded_table(text: str) -> list[bool]:
    lines = text.splitlines()
    if len(lines) < 3 or "emb" not in lines[0]:
        raise ValueError("pdffonts output has no emb column")
    start = lines[0].index("emb")
    values = [line[start : start + 3].strip() for line in lines[2:] if line.strip()]
    if not values:
        raise ValueError("pdffonts reported no fonts")
    if any(value not in {"yes", "no"} for value in values):
        raise ValueError(f"unrecognized pdffonts emb values: {values}")
    return [value == "yes" for value in values]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = subprocess.run(["pdffonts", str(args.pdf)], check=True, capture_output=True, text=True)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(result.stdout, encoding="utf-8")
    embedded = parse_embedded_table(result.stdout)
    if not all(embedded):
        raise SystemExit(f"PDF has non-embedded fonts: {args.pdf}")
    print(f"embedded_fonts={len(embedded)} pdf={args.pdf}")


if __name__ == "__main__":
    main()
