#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from nn_davinci.trial_models import build_external_model_compatibility_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    report = build_external_model_compatibility_report(args.output_root, repeats=args.repeats)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "cases": len(report["models"]), "repeats": args.repeats}, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
