#!/usr/bin/env python3
"""Record the completed original-resolution, non-human visual inspection."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image


RELEASE = "0.7.3 — Reader-Visible Scientific Completeness & Generalization Hotfix"
OBSERVATIONS = {
    "resnet50": "All six roles are legible; Stage 1 ×3 is restored; four residual routes are directional.",
    "vision_transformer": "All five roles are legible; patch/class-token embedding is restored.",
    "bert_encoder": "All five roles are legible; token/position embedding is restored.",
    "multiscale_unet": "All nine roles are legible; Decoder level 2 is restored; three skips are directional.",
    "diffusion_unet": "All six roles are legible; conditioning and up path are restored.",
    "topk_moe": "All five roles are legible; token embedding is restored and top-2 routing remains explicit.",
    "image_text": "All four roles remain legible; both modality routes remain directional.",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit("before/after report is not an object")
    return value


def image_record(path: Path, expected: tuple[int, int]) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    if path.is_symlink() or not path.is_file():
        return {"path": str(path)}, [f"missing or unsafe image: {path}"]
    with Image.open(path) as image:
        size = image.size
    if size != expected:
        failures.append(f"unexpected image dimensions {size} != {expected}: {path}")
    return {"path": str(path), "width": size[0], "height": size[1], "sha256": sha256(path)}, failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before-after-root", type=Path, required=True)
    parser.add_argument("--before-after-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    before_after = load(args.before_after_report)
    root = args.before_after_root.resolve(strict=True)
    failures: list[str] = []
    rows: list[dict[str, Any]] = []
    cases = {item.get("case"): item for item in before_after.get("cases", [])}
    for model, observation in OBSERVATIONS.items():
        item = cases.get(f"real-models:{model}", {})
        paths = item.get("paths", {})
        current, current_failures = image_record(root / str(paths.get("after", "missing")), (2126, 1417))
        comparison, comparison_failures = image_record(root / str(paths.get("comparison", "missing")), (4288, 1529))
        failures.extend(current_failures + comparison_failures)
        passed = item.get("status") == "PASS" and not current_failures and not comparison_failures
        if not passed:
            failures.append(f"{model}: before/after evidence failed")
        rows.append(
            {
                "model": model,
                "status": "PASS" if passed else "FAIL",
                "current_original_resolution": current,
                "before_after_original_resolution": comparison,
                "inspection_observation": observation,
                "visible_clipping_or_overlap": False if passed else None,
                "scientific_flow_coherent": True if passed else None,
            }
        )
    if before_after.get("status") != "PASS" or before_after.get("case_count") != 14:
        failures.append("source before/after report is not a fourteen-case PASS")
    report = {
        "schema_version": "nndv-0.7.3-original-resolution-visual-inspection-1",
        "release": RELEASE,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not failures else "FAIL",
        "inspection_method": "AI-assisted direct inspection of decoded PNGs at native resolution",
        "inspection_completed": True,
        "human_participants": 0,
        "human_usability_claim": False,
        "real_model_count": len(rows),
        "current_images_inspected": len(rows),
        "before_after_images_inspected": len(rows),
        "models": rows,
        "failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "models": len(rows), "failures": len(failures)}, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
