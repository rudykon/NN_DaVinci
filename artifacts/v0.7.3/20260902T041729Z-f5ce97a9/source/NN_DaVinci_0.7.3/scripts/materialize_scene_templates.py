#!/usr/bin/env python3
"""Materialize the seven deterministic, editable Scene IR templates."""

from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nn_davinci.model_scene import ARCHITECTURE_FAMILIES, scene_template  # noqa: E402


def main() -> int:
    destinations = (
        ROOT / "templates" / "scene_studio",
        ROOT / "src" / "nn_davinci" / "scene_templates",
    )
    for destination in destinations:
        destination.mkdir(parents=True, exist_ok=True)
    for family in ARCHITECTURE_FAMILIES:
        payload = scene_template(family).to_dict()
        encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        filename = f"{family}.scene.json"
        for destination in destinations:
            (destination / filename).write_text(encoded, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
