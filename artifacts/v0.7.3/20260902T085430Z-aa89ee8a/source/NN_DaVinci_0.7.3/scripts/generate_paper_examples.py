#!/usr/bin/env python3
from __future__ import annotations

import argparse

from nn_davinci.paper_production import generate_real_paper_examples


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the three offline 0.4.2 publication-quality and scientific-fidelity examples")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = generate_real_paper_examples(args.output)
    print("PASS" if report["passed"] else "FAIL")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
