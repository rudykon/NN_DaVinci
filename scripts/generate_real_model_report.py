#!/usr/bin/env python3
"""Generate the offline real-model compatibility evidence."""

from __future__ import annotations

import argparse

from nn_davinci.real_models import write_real_model_compatibility_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--model", action="append", dest="models")
    args = parser.parse_args()
    path = write_real_model_compatibility_report(args.output, repeats=max(1, args.repeats), names=args.models)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
