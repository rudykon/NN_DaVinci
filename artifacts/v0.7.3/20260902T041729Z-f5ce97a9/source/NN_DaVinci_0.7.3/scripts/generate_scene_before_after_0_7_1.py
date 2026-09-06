#!/usr/bin/env python3
"""Bind the fourteen 0.7.0→0.7.1 Scene PNG before/after proofs."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin


CASES = (
    ("templates", "cnn"),
    ("templates", "resnet"),
    ("templates", "unet"),
    ("templates", "transformer"),
    ("templates", "moe"),
    ("templates", "multimodal-fusion"),
    ("templates", "diffusion-unet"),
    ("real-models", "resnet50"),
    ("real-models", "vision_transformer"),
    ("real-models", "bert_encoder"),
    ("real-models", "multiscale_unet"),
    ("real-models", "diffusion_unet"),
    ("real-models", "topk_moe"),
    ("real-models", "image_text"),
)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PARENT_RUN_ID = "20260831T044446Z-9e6cd3cf"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_png(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"PNG is absent or unsafe: {path}")
    if path.read_bytes()[:8] != PNG_SIGNATURE:
        raise ValueError(f"PNG signature is invalid: {path}")
    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        return {
            "width": image.width,
            "height": image.height,
            "mode": image.mode,
            "dpi": [round(float(value), 3) for value in image.info.get("dpi", (0.0, 0.0))],
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def comparison(
    before: Path,
    after: Path,
    destination: Path,
    case_id: str,
    *,
    before_release: str,
    after_release: str,
    before_run_id: str,
    proof_schema: str,
) -> None:
    with Image.open(before) as old_image, Image.open(after) as new_image:
        old = old_image.convert("RGB")
        new = new_image.convert("RGB")
        header = 112
        gutter = 36
        width = old.width + gutter + new.width
        height = header + max(old.height, new.height)
        canvas = Image.new("RGB", (width, height), "white")
        canvas.paste(old, (0, header))
        canvas.paste(new, (old.width + gutter, header))
        draw = ImageDraw.Draw(canvas)
        title_font = font(34)
        caption_font = font(25)
        draw.text((22, 14), case_id, fill="#0f172a", font=title_font)
        draw.text((22, 62), f"Before · NN_DaVinci {before_release}", fill="#475569", font=caption_font)
        draw.text((old.width + gutter + 22, 62), f"After · NN_DaVinci {after_release}", fill="#0f766e", font=caption_font)
        draw.line((old.width + gutter // 2, 0, old.width + gutter // 2, height), fill="#94a3b8", width=3)
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text(
            "nndv.before_after",
            json.dumps(
                {
                    "schema_version": proof_schema,
                    "case": case_id,
                    "before_release": before_release,
                    "before_run_id": before_run_id,
                    "after_release": after_release,
                    "panels_preserve_original_pixels": True,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        canvas.save(destination, format="PNG", dpi=(300, 300), pnginfo=metadata)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-root", type=Path, required=True)
    parser.add_argument("--after-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--before-release", default="0.7.0")
    parser.add_argument("--after-release", default="0.7.1")
    parser.add_argument("--before-run-id", default=PARENT_RUN_ID)
    parser.add_argument("--release-title", default="0.7.1 — 3D Publication Quality & UX Completion")
    parser.add_argument("--report-schema", default="nndv-0.7.1-scene-before-after-report-1")
    parser.add_argument("--proof-schema", default="nndv-0.7.1-scene-before-after-proof-1")
    parser.add_argument(
        "--allow-identical",
        action="store_true",
        help="Record unchanged parent/current panels as a valid preservation result.",
    )
    args = parser.parse_args()
    before_root = args.before_root.resolve(strict=True)
    after_root = args.after_root.resolve(strict=True)
    output_root = args.output_root.resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty proof root: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)

    cases: list[dict[str, Any]] = []
    failures: list[str] = []
    for kind, name in CASES:
        case_id = f"{kind}:{name}"
        destination = output_root / kind / name
        destination.mkdir(parents=True, exist_ok=True)
        before_source = before_root / kind / name / "scene.png"
        after_source = after_root / kind / name / "scene.png"
        try:
            before_metrics = inspect_png(before_source)
            after_metrics = inspect_png(after_source)
            before_copy = destination / f"before-{args.before_release}.png"
            after_copy = destination / f"after-{args.after_release}.png"
            shutil.copy2(before_source, before_copy)
            shutil.copy2(after_source, after_copy)
            comparison_path = destination / "before-after.png"
            comparison(
                before_copy,
                after_copy,
                comparison_path,
                case_id,
                before_release=args.before_release,
                after_release=args.after_release,
                before_run_id=args.before_run_id,
                proof_schema=args.proof_schema,
            )
            comparison_metrics = inspect_png(comparison_path)
            changed = before_metrics["sha256"] != after_metrics["sha256"]
            if not changed and not args.allow_identical:
                raise ValueError("before and after PNGs are byte-identical")
            if inspect_png(before_copy)["sha256"] != before_metrics["sha256"]:
                raise ValueError("copied before proof changed bytes")
            if inspect_png(after_copy)["sha256"] != after_metrics["sha256"]:
                raise ValueError("copied after proof changed bytes")
            case_failures: list[str] = []
        except (OSError, ValueError) as exc:
            before_metrics = {}
            after_metrics = {}
            comparison_metrics = {}
            changed = None
            case_failures = [str(exc)]
            failures.append(f"{case_id}: {exc}")
        cases.append(
            {
                "case": case_id,
                "status": "PASS" if not case_failures else "FAIL",
                "before": before_metrics,
                "after": after_metrics,
                "comparison": comparison_metrics,
                "changed": changed,
                "paths": {
                    "before": f"{kind}/{name}/before-{args.before_release}.png",
                    "after": f"{kind}/{name}/after-{args.after_release}.png",
                    "comparison": f"{kind}/{name}/before-after.png",
                },
                "failures": case_failures,
            }
        )

    report = {
        "schema_version": args.report_schema,
        "release": args.release_title,
        "status": "PASS" if not failures else "FAIL",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "before": {"release": args.before_release, "run_id": args.before_run_id, "read_only": True},
        "after": {"release": args.after_release, "fresh_current_output": True},
        "case_count": len(cases),
        "proof_png_count": sum(3 for case in cases if case["status"] == "PASS"),
        "original_pixels_preserved": all(case["status"] == "PASS" for case in cases),
        "cases": cases,
        "failures": failures,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "cases": len(cases), "proof_pngs": report["proof_png_count"]}, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
