#!/usr/bin/env python3
"""Write the deterministic offline 0.7.3 Architecture Evidence generalization report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from nn_davinci.metamorphic_corpus import run_generalization_corpus


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=7300)
    args = parser.parse_args()
    report = run_generalization_corpus(seed=args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": report["status"],
        "real_models": 7,
        "variants": len(report["architecture_variants"]),
        "output": str(args.output.resolve()),
    }, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
