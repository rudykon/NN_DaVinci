#!/usr/bin/env python3
from __future__ import annotations

import argparse

from nn_davinci.diff_corpus import generate_diff_corpus_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate fixed real-model diff evidence")
    parser.add_argument("--output", required=True)
    parser.add_argument("--no-figures", action="store_true")
    args = parser.parse_args()
    report = generate_diff_corpus_report(args.output, export_figures=not args.no_figures)
    print("PASS" if report["passed"] else "FAIL")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
