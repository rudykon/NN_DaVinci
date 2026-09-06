#!/usr/bin/env python3
"""Validate Scene Studio visual evidence independently of the E2E producer.

The validator does not launch the application or trust a producer ``PASS``.
It binds the report to the discovered screenshot/download trees, recalculates
file hashes, and parses PNG chunks and IHDR dimensions directly.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable, Sequence
from io import BytesIO
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import sys
from typing import Any, TypeGuard
import unicodedata
import zipfile
import zlib
import xml.etree.ElementTree as ET


REPORT_SCHEMA = "nndv-0.7.1-scene-visual-evidence-validation-1"
SOURCE_SCHEMA = "nndv-0.7.1-scene-studio-e2e-1"
RELEASE = "0.7.1 — 3D Publication Quality & UX Completion"
MIN_ASSERTIONS = 78
MIN_SCREENSHOTS = 44
EXACT_VIEWPORTS = (
    (1920, 1080),
    (1440, 900),
    (1280, 720),
    (1024, 768),
    (800, 600),
    (568, 320),
    (390, 844),
)
THEMES = ("light", "dark", "high-contrast", "paper")
ARCHITECTURES = (
    "resnet50",
    "vision_transformer",
    "bert_encoder",
    "multiscale_unet",
    "diffusion_unet",
    "topk_moe",
    "image_text",
)
TEMPLATE_ARCHITECTURES = ("cnn", "resnet", "unet", "transformer", "moe", "multimodal-fusion", "diffusion-unet")
WORKFLOWS = {
    "blank_2d_3d",
    "real_model_semantic_scene",
    "structure_lens_scene",
    "autosave_reload",
    "scene_exports_10",
    "selection_provenance_3d_to_2d",
    "error_cancel_retry",
    "architectures_7",
    "scene_templates_7",
}
BOOLEAN_QUALITY_CHECKS = (
    "geometry",
    "overflow",
    "canvas_area",
    "topbar_clear",
    "compact_drawers_closed",
    "dialog",
    "menu",
    "toolbar",
    "focus",
    "contrast",
    "label",
    "accessibility_labels",
    "hidden_line",
    "font",
    "stroke",
)
DOWNLOAD_FORMATS = ("svg", "pdf", "tikz", "pptx", "png", "eps", "html", "json", "gltf", "glb")
DOWNLOAD_SUFFIXES = {
    "svg": ".svg",
    "pdf": ".pdf",
    "tikz": ".tex",
    "pptx": ".pptx",
    "png": ".png",
    "eps": ".eps",
    "html": ".html",
    "json": ".json",
    "gltf": ".gltf",
    "glb": ".glb",
}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
SAFE_SCREENSHOT_ID = re.compile(r"[a-z0-9][a-z0-9_-]*")
SVG_LENGTH_PATTERN = re.compile(r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([A-Za-z%]*)\s*")
SVG_NUMBER_PATTERN = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
SVG_NS = "{http://www.w3.org/2000/svg}"

JsonObject = dict[str, Any]


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_digest(records: list[JsonObject]) -> str:
    ordered = sorted(records, key=lambda item: (str(item.get("path", "")), str(item.get("format", ""))))
    payload = json.dumps(ordered, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_png(payload: bytes) -> JsonObject:
    """Parse and CRC-check a PNG, returning independently read IHDR fields."""

    if not payload.startswith(PNG_SIGNATURE):
        raise ValueError("PNG signature is absent")
    offset = len(PNG_SIGNATURE)
    chunks: list[str] = []
    ihdr: JsonObject | None = None
    saw_idat = False
    saw_iend = False
    while offset < len(payload):
        if len(payload) - offset < 12:
            raise ValueError("PNG has a truncated chunk header")
        length = struct.unpack_from(">I", payload, offset)[0]
        chunk_type = payload[offset + 4 : offset + 8]
        data_start = offset + 8
        data_end = data_start + length
        crc_end = data_end + 4
        if crc_end > len(payload):
            raise ValueError("PNG has a truncated chunk payload")
        data = payload[data_start:data_end]
        recorded_crc = struct.unpack_from(">I", payload, data_end)[0]
        calculated_crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        if recorded_crc != calculated_crc:
            name = chunk_type.decode("ascii", errors="replace")
            raise ValueError(f"PNG {name} chunk CRC is invalid")
        try:
            name = chunk_type.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ValueError("PNG chunk type is not ASCII") from exc
        chunks.append(name)
        if len(chunks) == 1 and chunk_type != b"IHDR":
            raise ValueError("PNG first chunk is not IHDR")
        if chunk_type == b"IHDR":
            if ihdr is not None or length != 13:
                raise ValueError("PNG IHDR is duplicated or has the wrong length")
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(">IIBBBBB", data)
            valid_depths = {
                0: {1, 2, 4, 8, 16},
                2: {8, 16},
                3: {1, 2, 4, 8},
                4: {8, 16},
                6: {8, 16},
            }
            if width <= 0 or height <= 0:
                raise ValueError("PNG IHDR has a zero dimension")
            if color_type not in valid_depths or bit_depth not in valid_depths[color_type]:
                raise ValueError("PNG IHDR bit-depth/color-type combination is invalid")
            if compression != 0 or filtering != 0 or interlace not in {0, 1}:
                raise ValueError("PNG IHDR uses an unsupported method value")
            ihdr = {
                "width": width,
                "height": height,
                "bit_depth": bit_depth,
                "color_type": color_type,
                "compression": compression,
                "filter": filtering,
                "interlace": interlace,
            }
        elif chunk_type == b"IDAT":
            saw_idat = True
        elif chunk_type == b"IEND":
            if length != 0:
                raise ValueError("PNG IEND has a payload")
            saw_iend = True
            offset = crc_end
            if offset != len(payload):
                raise ValueError("PNG has trailing bytes after IEND")
            break
        offset = crc_end
    if ihdr is None:
        raise ValueError("PNG IHDR is absent")
    if not saw_idat:
        raise ValueError("PNG IDAT is absent")
    if not saw_iend:
        raise ValueError("PNG IEND is absent")
    return {**ihdr, "chunk_count": len(chunks), "chunks": chunks}


class SceneVisualEvidenceValidator:
    """Aggregate contract and filesystem failures into one deterministic report."""

    def __init__(self, source_report: Path, artifact_root: Path, screenshots_root: Path | None = None) -> None:
        self.source_report_path = source_report
        self.supplied_artifact_root = artifact_root
        self.supplied_screenshots_root = screenshots_root
        self.artifact_root: Path | None = None
        self.screenshots_root: Path | None = None
        self.downloads_root: Path | None = None
        self.source: JsonObject = {}
        self.source_bytes = 0
        self.source_sha256 = ""
        self.failures: list[str] = []
        self.checks: dict[str, bool] = {}
        self.screenshot_records: dict[str, JsonObject] = {}
        self.screenshot_paths: dict[str, Path] = {}
        self.download_records: list[JsonObject] = []
        self.architecture_records: dict[str, JsonObject] = {}
        self.template_architecture_records: dict[str, JsonObject] = {}
        self.svg_visual_oracle: JsonObject = {
            "status": "NOT_MEASURED",
            "reason": "the SVG download was not available for direct inspection",
        }

    def fail(self, message: str) -> None:
        self.failures.append(message)

    def section(self, name: str, action: Callable[[], None]) -> None:
        before = len(self.failures)
        try:
            action()
        except (KeyError, OSError, TypeError, ValueError, struct.error, zipfile.BadZipFile) as exc:
            self.fail(f"{name}: validator could not inspect evidence: {type(exc).__name__}: {exc}")
        self.checks[name] = len(self.failures) == before

    def validate(self) -> JsonObject:
        self.section("roots", self._prepare_roots)
        self.section("source_report", self._load_source)
        self.section("schema_and_status", self._check_source_contract)
        self.section("workflows_and_quality", self._check_workflows_and_quality)
        self.section("exact_viewports", self._check_viewports)
        self.section("png_manifest_and_files", self._check_screenshots)
        self.section("visual_coverage", self._check_visual_coverage)
        self.section("architecture_2d_3d_pairs", self._check_architectures)
        self.section("scene_template_architectures", self._check_template_architectures)
        self.section("download_evidence", self._check_downloads)
        self.section("svg_visual_oracle", self._check_svg_visual_oracle_status)
        return self._report()

    def _check_svg_visual_oracle_status(self) -> None:
        if self.svg_visual_oracle.get("status") != "PASS":
            self.fail("actual downloaded SVG visual oracle did not pass every independently measurable gate")

    def _prepare_roots(self) -> None:
        if self.supplied_artifact_root.is_symlink() or not self.supplied_artifact_root.is_dir():
            self.fail("artifact root is absent, is not a directory, or is a symlink")
            return
        self.artifact_root = self.supplied_artifact_root.resolve(strict=True)
        supplied_screenshots = self.supplied_screenshots_root or (self.artifact_root / "screenshots")
        if supplied_screenshots.is_symlink() or not supplied_screenshots.is_dir():
            self.fail("screenshots root is absent, is not a directory, or is a symlink")
        else:
            resolved_screenshots = supplied_screenshots.resolve(strict=True)
            try:
                resolved_screenshots.relative_to(self.artifact_root)
            except ValueError:
                self.fail("screenshots root escapes the artifact root")
            else:
                self.screenshots_root = resolved_screenshots
        supplied_downloads = self.artifact_root / "downloads"
        if supplied_downloads.is_symlink() or not supplied_downloads.is_dir():
            self.fail("downloads root is absent, is not a directory, or is a symlink")
        else:
            self.downloads_root = supplied_downloads.resolve(strict=True)

    def _load_source(self) -> None:
        path = self.source_report_path
        if path.is_symlink() or not path.is_file():
            self.fail("source E2E report is absent, is not a file, or is a symlink")
            return
        payload = path.read_bytes()
        self.source_bytes = len(payload)
        self.source_sha256 = _sha256_bytes(payload)
        value = json.loads(payload.decode("utf-8"))
        if not isinstance(value, dict):
            self.fail("source E2E report must contain a JSON object")
            return
        self.source = value

    def _check_source_contract(self) -> None:
        source = self.source
        expected_scalars = {
            "schema_version": SOURCE_SCHEMA,
            "release": RELEASE,
            "status": "PASS",
            "succeeded": True,
            "human_participants": 0,
        }
        for name, expected in expected_scalars.items():
            actual = source.get(name)
            if (
                actual != expected
                or (name == "succeeded" and actual is not True)
                or (name == "human_participants" and not _is_int(actual))
            ):
                self.fail(f"source report {name} must equal {expected!r}")
        if source.get("failures") != []:
            self.fail("source report failures must be an empty list")
        if source.get("browser_errors") != []:
            self.fail("source report browser_errors must be an empty list")
        assertions = source.get("assertions")
        assertion_count = source.get("assertion_count")
        if not isinstance(assertions, list) or not all(isinstance(item, str) and item.strip() for item in assertions):
            self.fail("source report assertions must be a list of non-empty strings")
        elif not _is_int(assertion_count) or assertion_count != len(assertions) or assertion_count < MIN_ASSERTIONS:
            self.fail(f"assertion_count must exactly match at least {MIN_ASSERTIONS} assertion records")
        for name in ("expected_fallback_errors", "expected_recovery_errors"):
            values = source.get(name)
            if not isinstance(values, list) or not all(isinstance(item, str) and item for item in values):
                self.fail(f"source report {name} must be a list of strings")
        reported_artifact_root = source.get("artifact_root")
        if self.artifact_root is not None:
            if not isinstance(reported_artifact_root, str) or not reported_artifact_root:
                self.fail("source report artifact_root must be a non-empty path")
            else:
                reported = Path(reported_artifact_root)
                if reported_artifact_root != "." and (
                    not reported.is_absolute()
                    or reported.is_symlink()
                    or reported.resolve(strict=False) != self.artifact_root
                ):
                    self.fail("source report artifact_root does not match the supplied artifact root")

    def _check_workflows_and_quality(self) -> None:
        workflows = self.source.get("required_workflows")
        if not isinstance(workflows, dict) or set(workflows) != WORKFLOWS:
            self.fail("required_workflows must contain exactly the nine Scene workflow keys")
        elif any(workflows.get(name) is not True for name in WORKFLOWS):
            self.fail("every required Scene workflow must be true")

        quality = self.source.get("quality_checks")
        if not isinstance(quality, dict):
            self.fail("quality_checks must be an object")
            return
        for name in BOOLEAN_QUALITY_CHECKS:
            if quality.get(name) is not True:
                self.fail(f"quality_checks.{name} must be true")
        contrast_ratios = quality.get("contrast_ratios")
        if not isinstance(contrast_ratios, dict) or set(contrast_ratios) != set(THEMES):
            self.fail("quality_checks.contrast_ratios must contain exactly four themes")
        else:
            for theme in THEMES:
                ratio = contrast_ratios.get(theme)
                if not _is_number(ratio) or not math.isfinite(float(ratio)) or float(ratio) < 4.5:
                    self.fail(f"theme {theme} must report a numeric contrast ratio of at least 4.5")

        occlusion = quality.get("scene_label_occlusion")
        if not isinstance(occlusion, dict):
            self.fail("quality_checks.scene_label_occlusion must be a structured DOM-geometry result, not a boolean")
            return
        if occlusion.get("passed") is not True:
            self.fail("scene_label_occlusion.passed must be true")
        label_count = occlusion.get("label_count")
        if not _is_int(label_count) or label_count <= 0:
            self.fail("scene_label_occlusion.label_count must be a positive integer")
        for name in ("overlap_count", "clipped_count"):
            if not _is_int(occlusion.get(name)) or occlusion.get(name) != 0:
                self.fail(f"scene_label_occlusion.{name} must be integer zero")
        method = occlusion.get("method")
        normalized_method = method.lower() if isinstance(method, str) else ""
        if not normalized_method or "dom" not in normalized_method or not any(
            token in normalized_method for token in ("rect", "geometry", "bounds")
        ):
            self.fail("scene_label_occlusion.method must identify a DOM rect/geometry/bounds measurement")

    def _check_viewports(self) -> None:
        viewports = self.source.get("viewports")
        observed = self._viewport_pairs(viewports)
        if observed != EXACT_VIEWPORTS:
            self.fail(f"viewports must equal the seven exact ordered sizes {EXACT_VIEWPORTS!r}")
        results = self.source.get("viewport_results")
        if not isinstance(results, list) or len(results) != len(EXACT_VIEWPORTS):
            self.fail("viewport_results must contain exactly seven records")
            return
        for expected, item in zip(EXACT_VIEWPORTS, results):
            if not isinstance(item, dict):
                self.fail(f"viewport result {expected[0]}x{expected[1]} must be an object")
                continue
            width, height = expected
            exact_fields = {
                "width": width,
                "height": height,
                "viewportWidth": width,
                "viewportHeight": height,
            }
            if any(not _is_int(item.get(name)) or item.get(name) != value for name, value in exact_fields.items()):
                self.fail(f"viewport result {width}x{height} does not preserve exact requested dimensions")
            document_width = item.get("documentWidth")
            document_height = item.get("documentHeight")
            body_width = item.get("bodyWidth")
            body_height = item.get("bodyHeight")
            canvas_width = item.get("canvasWidth")
            canvas_height = item.get("canvasHeight")
            if not _is_number(document_width) or not math.isfinite(float(document_width)) or float(document_width) > width:
                self.fail(f"viewport result {width}x{height} reports horizontal clipping/overflow")
            if not _is_number(body_width) or not math.isfinite(float(body_width)) or float(body_width) > width:
                self.fail(f"viewport result {width}x{height} body reports horizontal clipping/overflow")
            if not _is_number(document_height) or not math.isfinite(float(document_height)) or float(document_height) > height:
                self.fail(f"viewport result {width}x{height} reports vertical clipping/overflow")
            if not _is_number(body_height) or not math.isfinite(float(body_height)) or float(body_height) > height:
                self.fail(f"viewport result {width}x{height} body reports vertical clipping/overflow")
            if (
                not _is_number(canvas_width)
                or not _is_number(canvas_height)
                or not math.isfinite(float(canvas_width))
                or not math.isfinite(float(canvas_height))
                or float(canvas_width) <= 250
                or float(canvas_height) <= 120
            ):
                self.fail(f"viewport result {width}x{height} has insufficient Scene canvas geometry")
                continue
            expected_compact = width <= 800
            expected_ratio = 0.7 if expected_compact else 0.6
            if item.get("compact") is not expected_compact:
                self.fail(f"viewport result {width}x{height} has the wrong compact-mode declaration")
            minimum_ratio = item.get("minimumAreaRatio")
            canvas_area = item.get("canvasArea")
            viewport_area = item.get("viewportArea")
            area_ratio = item.get("canvasAreaRatio")
            computed_canvas_area = float(canvas_width) * float(canvas_height)
            computed_viewport_area = width * height
            computed_ratio = computed_canvas_area / computed_viewport_area
            if not _is_number(minimum_ratio) or not math.isclose(float(minimum_ratio), expected_ratio, abs_tol=1.0e-9):
                self.fail(f"viewport result {width}x{height} has the wrong minimum Scene area ratio")
            if not _is_number(canvas_area) or not math.isclose(
                float(canvas_area), computed_canvas_area, rel_tol=1.0e-9, abs_tol=1.0e-6
            ):
                self.fail(f"viewport result {width}x{height} canvasArea disagrees with canvas geometry")
            if not _is_number(viewport_area) or float(viewport_area) != computed_viewport_area:
                self.fail(f"viewport result {width}x{height} viewportArea is inconsistent")
            if (
                not _is_number(area_ratio)
                or not math.isfinite(float(area_ratio))
                or not math.isclose(float(area_ratio), computed_ratio, abs_tol=1.0e-6)
                or float(area_ratio) < expected_ratio
            ):
                self.fail(f"viewport result {width}x{height} does not satisfy a self-consistent Scene canvas area gate")
            self._check_viewport_bounds(item, width, height, float(canvas_width), float(canvas_height), expected_compact)

    def _check_viewport_bounds(
        self,
        item: JsonObject,
        width: int,
        height: int,
        canvas_width: float,
        canvas_height: float,
        compact: bool,
    ) -> None:
        label = f"viewport result {width}x{height}"
        canvas = item.get("canvasBounds")
        topbar = item.get("topbarBounds")
        if not self._is_bounds(canvas):
            self.fail(f"{label} canvasBounds must contain finite left/top/right/bottom values")
        else:
            if (
                float(canvas["left"]) < -0.5
                or float(canvas["top"]) < -0.5
                or float(canvas["right"]) > width + 0.5
                or float(canvas["bottom"]) > height + 0.5
                or not math.isclose(float(canvas["right"]) - float(canvas["left"]), canvas_width, abs_tol=1.0e-6)
                or not math.isclose(float(canvas["bottom"]) - float(canvas["top"]), canvas_height, abs_tol=1.0e-6)
            ):
                self.fail(f"{label} canvasBounds are clipped or inconsistent with canvas dimensions")
        if not self._is_bounds(topbar):
            self.fail(f"{label} topbarBounds must contain finite left/top/right/bottom values")
        elif (
            float(topbar["left"]) < -0.5
            or float(topbar["top"]) < -0.5
            or float(topbar["right"]) > width + 0.5
            or float(topbar["bottom"]) > height + 0.5
        ):
            self.fail(f"{label} topbarBounds are clipped")
        overlap = item.get("topbarOverlap")
        if not _is_number(overlap) or not math.isfinite(float(overlap)) or float(overlap) < 0 or float(overlap) > 0.5:
            self.fail(f"{label} reports a topbar/Scene collision")
        drawers_closed = item.get("compactDrawersClosed")
        if not isinstance(drawers_closed, bool) or (compact and drawers_closed is not True):
            self.fail(f"{label} does not prove compact responsive drawers are closed")

    @staticmethod
    def _is_bounds(value: object) -> TypeGuard[dict[str, int | float]]:
        return (
            isinstance(value, dict)
            and set(value) == {"left", "top", "right", "bottom"}
            and all(_is_number(value.get(name)) and math.isfinite(float(value[name])) for name in ("left", "top", "right", "bottom"))
        )

    @staticmethod
    def _viewport_pairs(value: object) -> tuple[tuple[int, int], ...]:
        if not isinstance(value, list):
            return ()
        pairs: list[tuple[int, int]] = []
        for item in value:
            if not isinstance(item, dict) or not _is_int(item.get("width")) or not _is_int(item.get("height")):
                return ()
            pairs.append((item["width"], item["height"]))
        return tuple(pairs)

    def _safe_manifest_file(self, raw: object, allowed_root: Path | None, label: str) -> Path | None:
        if self.artifact_root is None or allowed_root is None:
            self.fail(f"{label} cannot be resolved because evidence roots are invalid")
            return None
        if not isinstance(raw, str) or not raw or "\x00" in raw:
            self.fail(f"{label} path must be a non-empty string without NUL bytes")
            return None
        raw_path = Path(raw)
        if ".." in raw_path.parts:
            self.fail(f"{label} path contains parent traversal")
            return None
        candidate = raw_path if raw_path.is_absolute() else self.artifact_root / raw_path
        lexical = Path(os.path.abspath(candidate))
        try:
            relative = lexical.relative_to(allowed_root)
        except ValueError:
            self.fail(f"{label} path escapes its allowed evidence root")
            return None
        cursor = allowed_root
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                self.fail(f"{label} path traverses a symlink")
                return None
        try:
            resolved = lexical.resolve(strict=True)
            resolved.relative_to(allowed_root)
        except (FileNotFoundError, ValueError):
            self.fail(f"{label} path is absent or resolves outside its allowed evidence root")
            return None
        if not resolved.is_file():
            self.fail(f"{label} path is not a regular file")
            return None
        return resolved

    def _inventory_files(self, root: Path | None, suffix: str, label: str) -> set[Path]:
        if root is None:
            return set()
        discovered: set[Path] = set()
        for item in sorted(root.rglob("*")):
            if item.is_symlink():
                self.fail(f"{label} tree contains a symlink: {item.relative_to(root)}")
                continue
            if item.is_dir():
                continue
            if not item.is_file():
                self.fail(f"{label} tree contains a non-regular entry: {item.relative_to(root)}")
                continue
            if suffix and item.suffix != suffix:
                self.fail(f"{label} tree contains an unexpected non-{suffix} file: {item.relative_to(root)}")
                continue
            discovered.add(item.resolve(strict=True))
        return discovered

    def _check_screenshots(self) -> None:
        manifest = self.source.get("screenshot_manifest")
        if not isinstance(manifest, list):
            self.fail("screenshot_manifest must be a list")
            return
        if len(manifest) < MIN_SCREENSHOTS:
            self.fail(f"screenshot_manifest must contain at least {MIN_SCREENSHOTS} screenshots")
        manifest_paths: set[Path] = set()
        seen_ids: set[str] = set()
        for index, item in enumerate(manifest):
            entry_start = len(self.failures)
            label = f"screenshot_manifest[{index}]"
            if not isinstance(item, dict):
                self.fail(f"{label} must be an object")
                continue
            identifier = item.get("id")
            if not isinstance(identifier, str) or SAFE_SCREENSHOT_ID.fullmatch(identifier) is None:
                self.fail(f"{label}.id is not a safe screenshot identifier")
                continue
            if identifier in seen_ids:
                self.fail(f"duplicate screenshot id: {identifier}")
                continue
            seen_ids.add(identifier)
            coverage = item.get("coverage")
            if not isinstance(coverage, list) or not coverage or not all(isinstance(value, str) and value for value in coverage):
                self.fail(f"screenshot {identifier} coverage must be a non-empty string list")
                coverage_values: list[str] = []
            else:
                coverage_values = coverage
                if len(coverage_values) != len(set(coverage_values)):
                    self.fail(f"screenshot {identifier} coverage contains duplicates")
            viewport = item.get("viewport")
            viewport_pair = self._single_viewport(viewport)
            if viewport_pair not in EXACT_VIEWPORTS:
                self.fail(f"screenshot {identifier} declares a viewport outside the exact seven-size matrix")
            resolved = self._safe_manifest_file(item.get("path"), self.screenshots_root, f"screenshot {identifier}")
            if resolved is None:
                continue
            if resolved.name != f"{identifier}.png":
                self.fail(f"screenshot {identifier} path basename must be {identifier}.png")
            if resolved in manifest_paths:
                self.fail(f"multiple screenshot IDs reference the same path: {resolved.name}")
            manifest_paths.add(resolved)
            payload = resolved.read_bytes()
            actual_sha256 = _sha256_bytes(payload)
            reported_sha256 = item.get("sha256")
            reported_bytes = item.get("bytes")
            if not isinstance(reported_sha256, str) or SHA256_PATTERN.fullmatch(reported_sha256) is None:
                self.fail(f"screenshot {identifier} manifest sha256 is missing or malformed")
            elif reported_sha256 != actual_sha256:
                self.fail(f"screenshot {identifier} manifest sha256 does not match the file")
            if not _is_int(reported_bytes) or reported_bytes <= 0 or reported_bytes != len(payload):
                self.fail(f"screenshot {identifier} manifest bytes do not match the non-empty file")
            try:
                png = _parse_png(payload)
            except ValueError as exc:
                self.fail(f"screenshot {identifier} is not a structurally valid PNG: {exc}")
                png = {}
            if viewport_pair is not None and png and (png["width"], png["height"]) != viewport_pair:
                self.fail(f"screenshot {identifier} PNG IHDR dimensions do not match its declared viewport")
            relative = resolved.relative_to(self.artifact_root).as_posix() if self.artifact_root is not None else resolved.name
            record: JsonObject = {
                "id": identifier,
                "path": relative,
                "bytes": len(payload),
                "sha256": actual_sha256,
                "coverage": coverage_values,
                "viewport": {"width": viewport_pair[0], "height": viewport_pair[1]} if viewport_pair else None,
                "png": png,
                "valid": len(self.failures) == entry_start,
            }
            self.screenshot_records[identifier] = record
            self.screenshot_paths[identifier] = resolved

        discovered = self._inventory_files(self.screenshots_root, ".png", "screenshots")
        missing = sorted(path.name for path in manifest_paths - discovered)
        unmanifested = sorted(path.relative_to(self.screenshots_root).as_posix() for path in discovered - manifest_paths) if self.screenshots_root else []
        if missing:
            self.fail(f"manifested screenshots are absent from the discovered PNG set: {missing}")
        if unmanifested:
            self.fail(f"screenshots root contains unmanifested PNG files: {unmanifested}")
        if len(discovered) < MIN_SCREENSHOTS:
            self.fail(f"screenshots root must contain at least {MIN_SCREENSHOTS} PNG files")
        if len(self.screenshot_records) != len(manifest):
            self.fail("not every screenshot manifest entry resolved to one unique PNG")

    @staticmethod
    def _single_viewport(value: object) -> tuple[int, int] | None:
        if not isinstance(value, dict) or set(value) != {"width", "height"}:
            return None
        width = value.get("width")
        height = value.get("height")
        if not _is_int(width) or not _is_int(height):
            return None
        return width, height

    def _require_screenshot(self, identifier: str, required_coverage: set[str]) -> JsonObject | None:
        record = self.screenshot_records.get(identifier)
        if record is None:
            self.fail(f"required screenshot is missing: {identifier}")
            return None
        coverage = record.get("coverage", [])
        if not required_coverage.issubset(set(coverage) if isinstance(coverage, list) else set()):
            self.fail(f"screenshot {identifier} lacks required coverage {sorted(required_coverage)}")
        return record

    def _check_visual_coverage(self) -> None:
        required = {
            "start-center-blank-import-architectures": {"blank", "import", "seven-architectures"},
            "blank-2d-workspace": {"blank", "2d"},
            "blank-3d-scene": {"blank", "3d"},
            "figure-proof-resnet50": {"proof", "figure", "real-model"},
            "scene-export-menu-10-formats": {"export", "menu", "ten-formats"},
            "comparison-resnet50-semantic-2d": {"real-model", "semantic", "2d", "comparison-pair"},
            "comparison-resnet50-scene-3d": {"real-model", "semantic", "structure-lens", "3d", "comparison-pair"},
            "comparison-return-to-2d-selection": {"2d", "3d-to-2d", "selection", "provenance", "comparison-pair"},
            "structure-lens-bounded-result": {"structure-lens", "dialog", "provenance"},
            "autosave-revision-comparison": {"dialog", "autosave-conflict", "cancel-retry"},
            "autosave-restored-after-page-reload": {"autosave", "reload", "3d"},
            "cpu-svg-vector-fallback": {"fallback", "cpu-svg", "stroke", "3d"},
        }
        for identifier, coverage in required.items():
            self._require_screenshot(identifier, coverage)
        semantic_2d = self.screenshot_records.get("comparison-resnet50-semantic-2d")
        semantic_3d = self.screenshot_records.get("comparison-resnet50-scene-3d")
        if semantic_2d is not None and semantic_3d is not None and semantic_2d.get("sha256") == semantic_3d.get("sha256"):
            self.fail("the ResNet semantic 2D and Scene 3D comparison PNGs have the same hash")

        theme_hashes: list[str] = []
        for theme in THEMES:
            record = self._require_screenshot(f"theme-{theme}-scene", {"theme", theme, "3d"})
            if record is not None and isinstance(record.get("sha256"), str):
                theme_hashes.append(record["sha256"])
        if len(theme_hashes) == len(THEMES) and len(set(theme_hashes)) != len(THEMES):
            self.fail("the four theme screenshots must have distinct PNG hashes")

        for width, height in EXACT_VIEWPORTS:
            identifier = f"viewport-{width}x{height}"
            record = self._require_screenshot(identifier, {"responsive", "3d", "exact-viewport"})
            if record is not None:
                viewport = record.get("viewport")
                png = record.get("png")
                if viewport != {"width": width, "height": height}:
                    self.fail(f"viewport screenshot {identifier} has the wrong manifest viewport")
                if not isinstance(png, dict) or (png.get("width"), png.get("height")) != (width, height):
                    self.fail(f"viewport screenshot {identifier} has the wrong independently parsed IHDR dimensions")

    def _check_architectures(self) -> None:
        comparisons = self.source.get("architecture_comparisons")
        if not isinstance(comparisons, dict) or set(comparisons) != set(ARCHITECTURES):
            self.fail("architecture_comparisons must contain exactly the seven required architecture keys")
            return
        two_d_hashes: list[str] = []
        three_d_hashes: list[str] = []
        for key in ARCHITECTURES:
            item_start = len(self.failures)
            item = comparisons.get(key)
            if not isinstance(item, dict):
                self.fail(f"architecture comparison {key} must be an object")
                continue
            model_objects = item.get("non_helper_model_objects")
            if not _is_int(model_objects) or model_objects <= 0:
                self.fail(f"architecture comparison {key} must report a positive non_helper_model_objects count")
            route_objects = item.get("route_objects")
            if not _is_int(route_objects) or route_objects <= 0:
                self.fail(f"architecture comparison {key} must report a positive route_objects count")
            visible_labels = item.get("visible_labels")
            if not _is_int(visible_labels) or visible_labels <= 0:
                self.fail(f"architecture comparison {key} must report a positive visible_labels count")
            two_d_id = f"architecture-{key}-2d"
            three_d_id = f"architecture-{key}-3d"
            two_d = self._check_architecture_reference(key, "two_d", item.get("two_d"), two_d_id, {"architecture", key, "import", "2d", "comparison-pair"})
            three_d = self._check_architecture_reference(key, "three_d", item.get("three_d"), three_d_id, {"architecture", key, "3d", "comparison-pair"})
            if two_d is not None and three_d is not None and two_d.get("sha256") == three_d.get("sha256"):
                self.fail(f"architecture {key} 2D and 3D PNGs must have different hashes")
            if two_d is not None and isinstance(two_d.get("sha256"), str):
                two_d_hashes.append(two_d["sha256"])
            if three_d is not None and isinstance(three_d.get("sha256"), str):
                three_d_hashes.append(three_d["sha256"])
            self.architecture_records[key] = {
                "two_d": self._public_screenshot_summary(two_d),
                "three_d": self._public_screenshot_summary(three_d),
                "non_helper_model_objects": model_objects,
                "route_objects": route_objects,
                "visible_labels": visible_labels,
                "valid": len(self.failures) == item_start,
            }
        architecture_hashes = two_d_hashes + three_d_hashes
        if len(architecture_hashes) == 2 * len(ARCHITECTURES) and len(set(architecture_hashes)) != len(architecture_hashes):
            self.fail("all fourteen real-architecture 2D/3D PNGs must have distinct hashes")
            for record in self.architecture_records.values():
                record["valid"] = False

    def _check_architecture_reference(
        self,
        key: str,
        dimension: str,
        reference: object,
        expected_id: str,
        coverage: set[str],
    ) -> JsonObject | None:
        if not isinstance(reference, dict):
            self.fail(f"architecture {key} {dimension} reference must be an object")
            return None
        if reference.get("screenshot_id") != expected_id:
            self.fail(f"architecture {key} {dimension} screenshot_id must equal {expected_id}")
        record = self._require_screenshot(expected_id, coverage)
        path = self._safe_manifest_file(reference.get("path"), self.screenshots_root, f"architecture {key} {dimension}")
        manifest_path = self.screenshot_paths.get(expected_id)
        if path is not None and manifest_path is not None and path != manifest_path:
            self.fail(f"architecture {key} {dimension} path does not reference its screenshot manifest PNG")
        return record

    def _check_template_architectures(self) -> None:
        templates = self.source.get("scene_template_architectures")
        if not isinstance(templates, dict) or set(templates) != set(TEMPLATE_ARCHITECTURES):
            self.fail("scene_template_architectures must contain exactly the seven required Scene template keys")
            return
        screenshot_hashes: list[str] = []
        for key in TEMPLATE_ARCHITECTURES:
            item_start = len(self.failures)
            item = templates.get(key)
            if not isinstance(item, dict):
                self.fail(f"Scene template architecture {key} must be an object")
                continue
            expected_id = f"template-architecture-{key}-3d"
            if item.get("screenshot_id") != expected_id:
                self.fail(f"Scene template architecture {key} screenshot_id must equal {expected_id}")
            model_objects = item.get("non_helper_model_objects")
            if not _is_int(model_objects) or model_objects <= 0:
                self.fail(f"Scene template architecture {key} must report a positive non_helper_model_objects count")
            route_objects = item.get("route_objects")
            if not _is_int(route_objects) or route_objects <= 0:
                self.fail(f"Scene template architecture {key} must report a positive route_objects count")
            record = self._require_screenshot(expected_id, {"template-architecture", key, "3d"})
            path = self._safe_manifest_file(item.get("path"), self.screenshots_root, f"Scene template architecture {key}")
            manifest_path = self.screenshot_paths.get(expected_id)
            if path is not None and manifest_path is not None and path != manifest_path:
                self.fail(f"Scene template architecture {key} path does not reference its screenshot manifest PNG")
            if record is not None and isinstance(record.get("sha256"), str):
                screenshot_hashes.append(record["sha256"])
            self.template_architecture_records[key] = {
                "screenshot": self._public_screenshot_summary(record),
                "non_helper_model_objects": model_objects,
                "route_objects": route_objects,
                "valid": len(self.failures) == item_start,
            }
        if len(screenshot_hashes) == len(TEMPLATE_ARCHITECTURES) and len(set(screenshot_hashes)) != len(TEMPLATE_ARCHITECTURES):
            self.fail("the seven Scene template architecture PNGs must have distinct hashes")
            for record in self.template_architecture_records.values():
                record["valid"] = False

    @staticmethod
    def _public_screenshot_summary(record: JsonObject | None) -> JsonObject | None:
        if record is None:
            return None
        return {name: record.get(name) for name in ("id", "path", "bytes", "sha256", "viewport", "valid")}

    def _check_downloads(self) -> None:
        manifest = self.source.get("download_manifest")
        if not isinstance(manifest, list) or len(manifest) != len(DOWNLOAD_FORMATS):
            self.fail("download_manifest must contain exactly ten records")
            return
        formats = [item.get("format") for item in manifest if isinstance(item, dict)]
        if len(formats) != len(manifest) or set(formats) != set(DOWNLOAD_FORMATS) or len(formats) != len(set(formats)):
            self.fail("download_manifest must contain each of the ten Scene formats exactly once")
        manifest_paths: set[Path] = set()
        for index, item in enumerate(manifest):
            entry_start = len(self.failures)
            label = f"download_manifest[{index}]"
            if not isinstance(item, dict):
                self.fail(f"{label} must be an object")
                continue
            format_name = item.get("format")
            if format_name not in DOWNLOAD_FORMATS:
                self.fail(f"{label}.format is not a required Scene export format")
                continue
            resolved = self._safe_manifest_file(item.get("path"), self.downloads_root, f"download {format_name}")
            if resolved is None:
                continue
            if resolved in manifest_paths:
                self.fail(f"multiple download formats reference the same file: {resolved.name}")
            manifest_paths.add(resolved)
            if not resolved.name.lower().endswith(DOWNLOAD_SUFFIXES[format_name]):
                self.fail(f"download {format_name} does not use the expected {DOWNLOAD_SUFFIXES[format_name]} suffix")
            payload = resolved.read_bytes()
            reported_bytes = item.get("bytes")
            if not _is_int(reported_bytes) or reported_bytes <= 0 or reported_bytes != len(payload):
                self.fail(f"download {format_name} reported bytes do not match the non-empty file")
            actual_sha256 = _sha256_bytes(payload)
            reported_sha256 = item.get("sha256")
            if (
                not isinstance(reported_sha256, str)
                or SHA256_PATTERN.fullmatch(reported_sha256) is None
                or reported_sha256 != actual_sha256
            ):
                self.fail(f"download {format_name} manifest sha256 is missing, malformed, or does not match the file")
            try:
                signature = self._inspect_download(format_name, payload)
            except (UnicodeDecodeError, ValueError, json.JSONDecodeError, struct.error, zipfile.BadZipFile) as exc:
                self.fail(f"download {format_name} has an invalid format signature/container: {exc}")
                signature = {"valid": False, "error": str(exc)}
            relative = resolved.relative_to(self.artifact_root).as_posix() if self.artifact_root is not None else resolved.name
            if format_name == "svg":
                try:
                    oracle, oracle_failures = self._inspect_svg_visual_oracle(payload, relative, actual_sha256)
                except (ET.ParseError, UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    oracle = {
                        "status": "NOT_MEASURED",
                        "source": {"path": relative, "bytes": len(payload), "sha256": actual_sha256},
                        "reason": f"SVG oracle could not parse the payload: {exc}",
                    }
                    oracle_failures = [f"SVG visual oracle could not parse the actual download: {exc}"]
                self.svg_visual_oracle = oracle
                for failure in oracle_failures:
                    self.fail(f"SVG visual oracle: {failure}")
            self.download_records.append({
                "format": format_name,
                "path": relative,
                "bytes": len(payload),
                "sha256": actual_sha256,
                "format_inspection": signature,
                "valid": len(self.failures) == entry_start,
            })
        discovered = self._inventory_files(self.downloads_root, "", "downloads")
        missing = sorted(path.name for path in manifest_paths - discovered)
        unmanifested = sorted(path.relative_to(self.downloads_root).as_posix() for path in discovered - manifest_paths) if self.downloads_root else []
        if missing:
            self.fail(f"manifested downloads are absent from the discovered file set: {missing}")
        if unmanifested:
            self.fail(f"downloads root contains unmanifested files: {unmanifested}")
        if len(discovered) != len(DOWNLOAD_FORMATS):
            self.fail("downloads root must contain exactly ten regular evidence files")
        if len(self.download_records) != len(manifest):
            self.fail("not every download manifest entry resolved to one unique file")

    @classmethod
    def _inspect_svg_visual_oracle(cls, payload: bytes, relative_path: str, sha256: str) -> tuple[JsonObject, list[str]]:
        failures: list[str] = []
        if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
            raise ValueError("DTD/entity declarations are forbidden")
        root = ET.fromstring(payload)
        if root.tag != f"{SVG_NS}svg":
            raise ValueError("root element is not an SVG namespace svg")
        viewbox = cls._parse_viewbox(root.get("viewBox"))
        view_x, view_y, view_width, view_height = viewbox
        physical_width_mm = cls._physical_length_mm(root.get("width"), "SVG width")
        physical_height_mm = cls._physical_length_mm(root.get("height"), "SVG height")
        user_per_mm_x = view_width / physical_width_mm
        user_per_mm_y = view_height / physical_height_mm
        if not math.isclose(user_per_mm_x, user_per_mm_y, rel_tol=1.0e-6, abs_tol=1.0e-9):
            failures.append("viewBox has non-uniform physical x/y scaling")

        elements = list(root.iter())
        tag_counts = Counter(cls._local_name(element.tag) for element in elements)
        geometry_count = sum(tag_counts[name] for name in ("polygon", "polyline", "path"))
        if tag_counts["polygon"] <= 0 or geometry_count <= 0:
            failures.append("actual SVG lacks polygon and vector line/path geometry")

        text_result, text_failures = cls._inspect_svg_text(
            elements,
            viewbox,
            user_per_mm_x,
            user_per_mm_y,
        )
        failures.extend(text_failures)
        stroke_result, stroke_failures = cls._inspect_svg_strokes(elements, user_per_mm_x, user_per_mm_y)
        failures.extend(stroke_failures)
        route_result, route_failures = cls._inspect_svg_routes(elements)
        failures.extend(route_failures)
        hidden_result, hidden_failures = cls._inspect_svg_hidden_line(
            root,
            elements,
            physical_width_mm,
            physical_height_mm,
            stroke_result,
        )
        failures.extend(hidden_failures)
        result: JsonObject = {
            "status": "PASS" if not failures else "FAIL",
            "source": {"path": relative_path, "bytes": len(payload), "sha256": sha256},
            "xml": {
                "parsed": True,
                "export_marker": root.get("data-nndv-export"),
                "camera_id": root.get("data-camera-id"),
                "viewBox": [view_x, view_y, view_width, view_height],
                "physical_size_mm": [physical_width_mm, physical_height_mm],
                "tag_counts": dict(sorted(tag_counts.items())),
                "polygon_polyline_path_count": geometry_count,
            },
            "text": text_result,
            "stroke": stroke_result,
            "routes": route_result,
            "hidden_line": hidden_result,
            "not_measured": [
                {
                    "metric": "exact_glyph_outline_bounds",
                    "reason": "No font engine is used; text boxes are conservative estimates from actual font-size, anchor, and Unicode width classes.",
                },
                {
                    "metric": "source_3d_occlusion_recomputation",
                    "reason": "The oracle cross-checks rendered data-kind edges against embedded projection metadata/options but does not rerun projection from Scene IR.",
                },
            ],
            "failures": failures,
        }
        return result, failures

    @classmethod
    def _inspect_svg_text(
        cls,
        elements: list[ET.Element],
        viewbox: tuple[float, float, float, float],
        user_per_mm_x: float,
        user_per_mm_y: float,
    ) -> tuple[JsonObject, list[str]]:
        failures: list[str] = []
        view_x, view_y, view_width, view_height = viewbox
        boxes: list[JsonObject] = []
        font_sizes: list[float] = []
        unsupported: list[str] = []
        for index, element in enumerate(item for item in elements if cls._local_name(item.tag) == "text"):
            identifier = element.get("id") or f"text-{index}"
            if element.get("transform") or any(cls._local_name(child.tag) == "tspan" for child in element):
                unsupported.append(identifier)
                continue
            text = "".join(element.itertext()).strip()
            font_value = cls._presentation_value(element, "font-size")
            x_value, y_value = element.get("x"), element.get("y")
            if not text or font_value is None or x_value is None or y_value is None:
                unsupported.append(identifier)
                continue
            x = cls._first_svg_number(x_value, f"text {identifier} x")
            y = cls._first_svg_number(y_value, f"text {identifier} y")
            font_pt = cls._svg_length_to_pt(font_value, user_per_mm_y)
            if font_pt <= 0:
                failures.append(f"text {identifier} has a non-positive font size")
                continue
            font_sizes.append(font_pt)
            em_width = font_pt * (25.4 / 72.0) * user_per_mm_x
            em_height = font_pt * (25.4 / 72.0) * user_per_mm_y
            estimated_width = max(0.5, sum(cls._character_em_width(character) for character in text)) * em_width
            anchor = cls._presentation_value(element, "text-anchor") or "start"
            if anchor == "middle":
                left = x - estimated_width / 2.0
            elif anchor == "end":
                left = x - estimated_width
            elif anchor == "start":
                left = x
            else:
                unsupported.append(identifier)
                continue
            box = {
                "id": identifier,
                "text": text,
                "font_pt": round(font_pt, 6),
                "left": round(left, 6),
                "top": round(y - 0.8 * em_height, 6),
                "right": round(left + estimated_width, 6),
                "bottom": round(y + 0.2 * em_height, 6),
            }
            boxes.append(box)
        if unsupported:
            failures.append(f"text bounds are not measurable for elements {unsupported}")
        out_of_bounds = [
            box["id"]
            for box in boxes
            if float(box["left"]) < view_x - 1.0e-6
            or float(box["top"]) < view_y - 1.0e-6
            or float(box["right"]) > view_x + view_width + 1.0e-6
            or float(box["bottom"]) > view_y + view_height + 1.0e-6
        ]
        overlaps: list[list[str]] = []
        for index, first in enumerate(boxes):
            for second in boxes[index + 1 :]:
                overlap_width = min(float(first["right"]), float(second["right"])) - max(
                    float(first["left"]), float(second["left"])
                )
                overlap_height = min(float(first["bottom"]), float(second["bottom"])) - max(
                    float(first["top"]), float(second["top"])
                )
                if overlap_width > 1.0e-6 and overlap_height > 1.0e-6:
                    overlaps.append([str(first["id"]), str(second["id"])])
        minimum_font = min(font_sizes) if font_sizes else None
        if len(boxes) < 2:
            failures.append("actual SVG must contain at least two independently measurable 3D labels")
        if minimum_font is None or minimum_font < 7.0 - 1.0e-6:
            failures.append("actual SVG minimum_font_pt is below 7")
        if out_of_bounds:
            failures.append(f"estimated SVG text boxes leave the viewBox: {out_of_bounds}")
        if overlaps:
            failures.append(f"estimated SVG label boxes overlap: {overlaps}")
        return {
            "status": "PASS" if not unsupported and len(boxes) >= 2 and minimum_font is not None and minimum_font >= 7.0 - 1.0e-6 and not out_of_bounds and not overlaps else "FAIL",
            "measurement": "estimated_from_svg_font_size_anchor_and_unicode_width",
            "label_count": len(boxes),
            "minimum_font_pt": round(minimum_font, 6) if minimum_font is not None else None,
            "out_of_viewBox_count": len(out_of_bounds),
            "overlap_count": len(overlaps),
            "overlap_pairs": overlaps,
            "unsupported_elements": unsupported,
            "estimated_boxes": boxes,
        }, failures

    @classmethod
    def _inspect_svg_strokes(
        cls,
        elements: list[ET.Element],
        user_per_mm_x: float,
        user_per_mm_y: float,
    ) -> tuple[JsonObject, list[str]]:
        failures: list[str] = []
        widths: list[float] = []
        missing_width: list[str] = []
        geometry_tags = {"polygon", "polyline", "path", "line", "rect", "circle", "ellipse"}
        average_scale = (user_per_mm_x + user_per_mm_y) / 2.0
        for index, element in enumerate(elements):
            if cls._local_name(element.tag) not in geometry_tags:
                continue
            stroke = (cls._presentation_value(element, "stroke") or "").strip().lower()
            if not stroke or stroke in {"none", "transparent"}:
                continue
            width_value = cls._presentation_value(element, "stroke-width")
            if width_value is None:
                missing_width.append(element.get("id") or f"geometry-{index}")
                continue
            width_pt = cls._svg_length_to_pt(width_value, average_scale)
            widths.append(width_pt)
        if missing_width:
            failures.append(f"stroked SVG geometry lacks explicit stroke-width: {missing_width}")
        minimum = min(widths) if widths else None
        maximum = max(widths) if widths else None
        uniform = minimum is not None and maximum is not None and math.isclose(minimum, maximum, abs_tol=1.0e-5)
        if minimum is None or minimum <= 0:
            failures.append("actual SVG has no positive stroke width")
        if not uniform:
            failures.append("actual SVG stroke widths are not uniform")
        return {
            "status": "PASS" if not missing_width and minimum is not None and minimum > 0 and uniform else "FAIL",
            "stroked_geometry_count": len(widths),
            "minimum_stroke_pt": round(minimum, 6) if minimum is not None else None,
            "maximum_stroke_pt": round(maximum, 6) if maximum is not None else None,
            "uniform": uniform,
            "unique_stroke_widths_pt": sorted({round(value, 6) for value in widths}),
            "missing_width_elements": missing_width,
        }, failures

    @classmethod
    def _inspect_svg_routes(cls, elements: list[ET.Element]) -> tuple[JsonObject, list[str]]:
        failures: list[str] = []
        route_kinds = {"polyline", "route", "connector", "arrow", "bezier"}
        segments: list[tuple[str, int, tuple[float, float], tuple[float, float]]] = []
        route_ids: list[str] = []
        unsupported: list[str] = []
        for index, element in enumerate(elements):
            kind = (element.get("data-kind") or "").lower()
            if kind not in route_kinds:
                continue
            identifier = element.get("id") or f"route-{index}"
            route_ids.append(identifier)
            tag = cls._local_name(element.tag)
            points: list[tuple[float, float]]
            if tag == "polyline":
                try:
                    points = cls._parse_svg_points(element.get("points"), identifier)
                except ValueError:
                    unsupported.append(identifier)
                    continue
            elif tag == "path" and kind == "bezier":
                try:
                    points = cls._parse_svg_cubic_path(element.get("d"), identifier)
                except ValueError:
                    unsupported.append(identifier)
                    continue
            elif tag == "line":
                try:
                    points = [
                        (
                            cls._first_svg_number(element.get("x1") or "", f"route {identifier} x1"),
                            cls._first_svg_number(element.get("y1") or "", f"route {identifier} y1"),
                        ),
                        (
                            cls._first_svg_number(element.get("x2") or "", f"route {identifier} x2"),
                            cls._first_svg_number(element.get("y2") or "", f"route {identifier} y2"),
                        ),
                    ]
                except ValueError:
                    unsupported.append(identifier)
                    continue
            else:
                unsupported.append(identifier)
                continue
            for segment_index, (point_start, point_end) in enumerate(zip(points, points[1:])):
                if point_start != point_end:
                    segments.append((identifier, segment_index, point_start, point_end))
        intersections: list[JsonObject] = []
        for index, first_segment in enumerate(segments):
            for second_segment in segments[index + 1 :]:
                if first_segment[0] == second_segment[0] and abs(first_segment[1] - second_segment[1]) <= 1:
                    continue
                intersection_kind = cls._non_endpoint_segment_intersection(
                    first_segment[2], first_segment[3], second_segment[2], second_segment[3]
                )
                if intersection_kind is not None:
                    intersections.append({"first": first_segment[0], "second": second_segment[0], "kind": intersection_kind})
        if unsupported:
            failures.append(f"route intersection measurement is not available for SVG elements {unsupported}")
        if not route_ids or not segments:
            failures.append("actual SVG contains no measurable data-kind route/arrow/polyline/bezier geometry")
        if intersections:
            failures.append(f"actual SVG routes have non-endpoint intersections: {intersections}")
        return {
            "status": "PASS" if route_ids and segments and not unsupported and not intersections else "FAIL",
            "measurement": "proper_segment_intersections_excluding_shared_endpoints",
            "route_primitive_count": len(route_ids),
            "segment_count": len(segments),
            "non_endpoint_intersection_count": len(intersections),
            "intersections": intersections,
            "unsupported_elements": unsupported,
        }, failures

    @classmethod
    def _inspect_svg_hidden_line(
        cls,
        root: ET.Element,
        elements: list[ET.Element],
        physical_width_mm: float,
        physical_height_mm: float,
        stroke_result: JsonObject,
    ) -> tuple[JsonObject, list[str]]:
        failures: list[str] = []
        metadata_element = root.find(f"{SVG_NS}metadata")
        if metadata_element is None or not metadata_element.text:
            return {"status": "NOT_MEASURED", "reason": "projection metadata is absent"}, [
                "hidden-line evidence cannot be cross-checked because SVG projection metadata is absent"
            ]
        metadata = json.loads(metadata_element.text)
        if not isinstance(metadata, dict):
            raise ValueError("SVG projection metadata root is not an object")
        options = metadata.get("options")
        primitives = metadata.get("primitives")
        if not isinstance(options, dict) or not isinstance(primitives, list) or not all(isinstance(item, dict) for item in primitives):
            raise ValueError("SVG projection metadata options/primitives are malformed")
        metadata_kinds = Counter(str(item.get("kind", "")) for item in primitives)
        primitive_kinds = set(metadata_kinds)
        dom_primitives = [
            element
            for element in elements
            if element.get("id") and element.get("data-kind") in primitive_kinds
        ]
        dom_kinds = Counter(str(element.get("data-kind", "")) for element in dom_primitives)
        metadata_bindings = Counter((str(item.get("kind", "")), str(item.get("object_id", ""))) for item in primitives)
        dom_bindings = Counter((str(element.get("data-kind", "")), str(element.get("data-object-id", ""))) for element in dom_primitives)
        edge_elements = [element for element in dom_primitives if element.get("data-kind") == "edge"]
        edge_depths: list[float] = []
        for element in edge_elements:
            depth = element.get("data-depth")
            try:
                value = float(depth) if depth is not None else math.nan
            except ValueError:
                value = math.nan
            if math.isfinite(value):
                edge_depths.append(value)
        hidden_edges = options.get("hidden_edges") is True
        backface_culling = options.get("backface_culling") is True
        samples = options.get("occlusion_samples")
        counts_match = metadata_kinds == dom_kinds
        bindings_match = metadata_bindings == dom_bindings
        source_digest = metadata.get("source_digest")
        schema_version = metadata.get("schema_version")
        if not hidden_edges or not backface_culling:
            failures.append("SVG projection metadata does not enable hidden-edge removal and backface culling")
        if not _is_int(samples) or samples < 4:
            failures.append("SVG projection metadata has no valid occlusion sampling evidence")
        if metadata_kinds.get("edge", 0) <= 0 or metadata_kinds.get("face", 0) <= 0:
            failures.append("SVG projection metadata lacks rendered face/edge sets")
        if len(edge_depths) != len(edge_elements):
            failures.append("actual SVG data-kind edge set lacks finite depth evidence")
        if not counts_match or not bindings_match or len(primitives) != len(dom_primitives):
            failures.append("actual SVG primitive kinds/object bindings do not match embedded projection metadata")
        if schema_version != "nndv-scene-projection-1" or not isinstance(source_digest, str) or SHA256_PATTERN.fullmatch(source_digest) is None:
            failures.append("SVG projection metadata schema/source digest is invalid")
        if not math.isclose(float(metadata.get("width_mm", math.nan)), physical_width_mm, abs_tol=1.0e-6) or not math.isclose(
            float(metadata.get("height_mm", math.nan)), physical_height_mm, abs_tol=1.0e-6
        ):
            failures.append("SVG physical dimensions disagree with projection metadata")
        option_stroke = options.get("stroke_width_pt")
        measured_stroke = stroke_result.get("minimum_stroke_pt")
        stroke_matches = _is_number(option_stroke) and _is_number(measured_stroke) and math.isclose(
            float(option_stroke), float(measured_stroke), abs_tol=1.0e-5
        )
        if not stroke_matches:
            failures.append("actual SVG stroke width disagrees with projection metadata")
        return {
            "status": "PASS" if not failures else "FAIL",
            "measurement": "actual_data_kind_edge_set_cross_checked_with_embedded_projection_metadata",
            "hidden_edges_option": hidden_edges,
            "backface_culling_option": backface_culling,
            "occlusion_samples": samples,
            "edge_count": len(edge_elements),
            "face_count": dom_kinds.get("face", 0),
            "finite_edge_depth_count": len(edge_depths),
            "metadata_primitive_count": len(primitives),
            "dom_primitive_count": len(dom_primitives),
            "metadata_kind_counts": dict(sorted(metadata_kinds.items())),
            "dom_kind_counts": dict(sorted(dom_kinds.items())),
            "kind_counts_match": counts_match,
            "object_bindings_match": bindings_match,
            "stroke_option_matches_actual": stroke_matches,
            "source_3d_occlusion_recomputed": False,
        }, failures

    @staticmethod
    def _local_name(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    @staticmethod
    def _presentation_value(element: ET.Element, name: str) -> str | None:
        direct = element.get(name)
        if direct is not None:
            return direct
        style = element.get("style")
        if not style:
            return None
        declarations = {
            key.strip(): value.strip()
            for declaration in style.split(";")
            if ":" in declaration
            for key, value in [declaration.split(":", 1)]
        }
        return declarations.get(name)

    @staticmethod
    def _parse_viewbox(value: str | None) -> tuple[float, float, float, float]:
        if value is None:
            raise ValueError("SVG viewBox is absent")
        parts = value.replace(",", " ").split()
        if len(parts) != 4:
            raise ValueError("SVG viewBox must contain four numbers")
        numbers = tuple(float(part) for part in parts)
        if not all(math.isfinite(number) for number in numbers) or numbers[2] <= 0 or numbers[3] <= 0:
            raise ValueError("SVG viewBox is non-finite or non-positive")
        return numbers[0], numbers[1], numbers[2], numbers[3]

    @staticmethod
    def _parse_svg_length(value: str | None, label: str) -> tuple[float, str]:
        if value is None:
            raise ValueError(f"{label} is absent")
        match = SVG_LENGTH_PATTERN.fullmatch(value)
        if match is None:
            raise ValueError(f"{label} is not a supported SVG length")
        number = float(match.group(1))
        if not math.isfinite(number):
            raise ValueError(f"{label} is non-finite")
        return number, match.group(2).lower()

    @classmethod
    def _physical_length_mm(cls, value: str | None, label: str) -> float:
        number, unit = cls._parse_svg_length(value, label)
        factors = {"mm": 1.0, "cm": 10.0, "in": 25.4, "pt": 25.4 / 72.0, "px": 25.4 / 96.0}
        if unit not in factors or number <= 0:
            raise ValueError(f"{label} must be a positive physical SVG length")
        return number * factors[unit]

    @classmethod
    def _svg_length_to_pt(cls, value: str, user_per_mm: float) -> float:
        number, unit = cls._parse_svg_length(value, "SVG presentation length")
        if unit == "pt":
            return number
        if unit == "px":
            return number * 72.0 / 96.0
        if unit == "mm":
            return number * 72.0 / 25.4
        if unit == "cm":
            return number * 10.0 * 72.0 / 25.4
        if unit == "in":
            return number * 72.0
        if unit == "":
            return (number / user_per_mm) * 72.0 / 25.4
        raise ValueError(f"unsupported SVG presentation unit {unit!r}")

    @staticmethod
    def _first_svg_number(value: str, label: str) -> float:
        match = SVG_NUMBER_PATTERN.match(value.strip())
        if match is None:
            raise ValueError(f"{label} is not numeric")
        number = float(match.group(0))
        if not math.isfinite(number):
            raise ValueError(f"{label} is non-finite")
        return number

    @staticmethod
    def _character_em_width(character: str) -> float:
        if character.isspace():
            return 0.33
        if unicodedata.east_asian_width(character) in {"W", "F"}:
            return 1.0
        if character in "ilI1.,'`|!:;":
            return 0.3
        if character in "MW@#%&":
            return 0.9
        return 0.6

    @staticmethod
    def _parse_svg_points(value: str | None, identifier: str) -> list[tuple[float, float]]:
        if value is None:
            raise ValueError(f"route {identifier} points are absent")
        residual = SVG_NUMBER_PATTERN.sub("", value)
        if residual.replace(",", "").strip():
            raise ValueError(f"route {identifier} points contain unsupported syntax")
        numbers = [float(item) for item in SVG_NUMBER_PATTERN.findall(value)]
        if len(numbers) < 4 or len(numbers) % 2 or not all(math.isfinite(item) for item in numbers):
            raise ValueError(f"route {identifier} points are malformed")
        return list(zip(numbers[0::2], numbers[1::2]))

    @staticmethod
    def _parse_svg_cubic_path(value: str | None, identifier: str) -> list[tuple[float, float]]:
        """Flatten the exact absolute M/C path subset emitted by Scene SVG."""

        if value is None:
            raise ValueError(f"route {identifier} path data are absent")
        residual = SVG_NUMBER_PATTERN.sub("", value)
        commands = re.findall(r"[A-Za-z]", residual)
        if commands != ["M", "C"] or re.sub(r"[MC,\s]", "", residual):
            raise ValueError(f"route {identifier} path contains unsupported syntax")
        numbers = [float(item) for item in SVG_NUMBER_PATTERN.findall(value)]
        if len(numbers) != 8 or not all(math.isfinite(item) for item in numbers):
            raise ValueError(f"route {identifier} cubic path is malformed")
        control = list(zip(numbers[0::2], numbers[1::2]))
        points: list[tuple[float, float]] = []
        for index in range(49):
            amount = index / 48.0
            inverse = 1.0 - amount
            weights = (inverse**3, 3.0 * inverse**2 * amount, 3.0 * inverse * amount**2, amount**3)
            points.append(
                tuple(sum(weights[item] * control[item][axis] for item in range(4)) for axis in range(2))
            )
        return points

    @staticmethod
    def _non_endpoint_segment_intersection(
        first_start: tuple[float, float],
        first_end: tuple[float, float],
        second_start: tuple[float, float],
        second_end: tuple[float, float],
    ) -> str | None:
        epsilon = 1.0e-9
        rx, ry = first_end[0] - first_start[0], first_end[1] - first_start[1]
        sx, sy = second_end[0] - second_start[0], second_end[1] - second_start[1]
        qpx, qpy = second_start[0] - first_start[0], second_start[1] - first_start[1]
        cross_rs = rx * sy - ry * sx
        cross_qp_r = qpx * ry - qpy * rx
        if abs(cross_rs) > epsilon:
            t = (qpx * sy - qpy * sx) / cross_rs
            u = (qpx * ry - qpy * rx) / cross_rs
            return "proper-crossing" if epsilon < t < 1.0 - epsilon and epsilon < u < 1.0 - epsilon else None
        if abs(cross_qp_r) > epsilon:
            return None
        axis = 0 if abs(rx) >= abs(ry) else 1
        first_values = sorted((first_start[axis], first_end[axis]))
        second_values = sorted((second_start[axis], second_end[axis]))
        overlap = min(first_values[1], second_values[1]) - max(first_values[0], second_values[0])
        return "collinear-overlap" if overlap > epsilon else None

    @staticmethod
    def _inspect_download(format_name: str, payload: bytes) -> JsonObject:
        if not payload:
            raise ValueError("file is empty")
        if format_name == "svg":
            text = payload.decode("utf-8").lstrip("\ufeff\r\n\t ")
            if "<svg" not in text[:500]:
                raise ValueError("SVG root is absent")
            return {"valid": True, "signature": "svg-xml"}
        if format_name == "pdf":
            if not payload.startswith(b"%PDF-") or b"%%EOF" not in payload[-1024:]:
                raise ValueError("PDF header/trailer is absent")
            return {"valid": True, "signature": "pdf"}
        if format_name == "tikz":
            text = payload.decode("utf-8")
            if "\\begin{tikzpicture}" not in text:
                raise ValueError("TikZ picture environment is absent")
            return {"valid": True, "signature": "latex-tikz"}
        if format_name == "pptx":
            with zipfile.ZipFile(BytesIO(payload)) as archive:
                names = set(archive.namelist())
            if "[Content_Types].xml" not in names or "ppt/presentation.xml" not in names:
                raise ValueError("PPTX OOXML package roots are absent")
            return {"valid": True, "signature": "ooxml-pptx", "member_count": len(names)}
        if format_name == "png":
            return {"valid": True, "signature": "png", "png": _parse_png(payload)}
        if format_name == "eps":
            if not payload.startswith(b"%!PS-Adobe"):
                raise ValueError("EPS PostScript header is absent")
            return {"valid": True, "signature": "eps-postscript"}
        if format_name == "html":
            text = payload.decode("utf-8").lstrip("\ufeff\r\n\t ").lower()
            if not text.startswith("<!doctype html") or "<html" not in text[:500]:
                raise ValueError("HTML5 document root is absent")
            return {"valid": True, "signature": "html5"}
        if format_name in {"json", "gltf"}:
            document = json.loads(payload.decode("utf-8"))
            if not isinstance(document, dict):
                raise ValueError("JSON root is not an object")
            if format_name == "gltf" and document.get("asset", {}).get("version") != "2.0":
                raise ValueError("glTF asset.version is not 2.0")
            return {"valid": True, "signature": "gltf-json" if format_name == "gltf" else "scene-json"}
        if format_name == "glb":
            if len(payload) < 12 or payload[:4] != b"glTF":
                raise ValueError("GLB magic is absent")
            version, declared_length = struct.unpack_from("<II", payload, 4)
            if version != 2 or declared_length != len(payload):
                raise ValueError("GLB version or declared length is invalid")
            return {"valid": True, "signature": "glb-2"}
        raise ValueError(f"unsupported format {format_name}")

    def _report(self) -> JsonObject:
        screenshots = sorted(self.screenshot_records.values(), key=lambda item: str(item.get("path", "")))
        downloads = sorted(self.download_records, key=lambda item: str(item.get("format", "")))
        valid_screenshots = sum(item.get("valid") is True for item in screenshots)
        valid_downloads = sum(item.get("valid") is True for item in downloads)
        architecture_pairs = sum(item.get("valid") is True for item in self.architecture_records.values())
        template_architectures = sum(item.get("valid") is True for item in self.template_architecture_records.values())
        source_assertions = self.source.get("assertion_count")
        browser_errors = self.source.get("browser_errors")
        source_quality = self.source.get("quality_checks")
        quality = source_quality if isinstance(source_quality, dict) else {}
        source_occlusion = quality.get("scene_label_occlusion")
        occlusion = source_occlusion if isinstance(source_occlusion, dict) else {}
        screenshots_logical_root = self._logical_root(self.screenshots_root, "screenshots")
        downloads_logical_root = self._logical_root(self.downloads_root, "downloads")
        status = "PASS" if not self.failures else "FAIL"
        return {
            "schema_version": REPORT_SCHEMA,
            "release": RELEASE,
            "status": status,
            "validator_is_independent_of_e2e_producer": True,
            "source_report": {
                "path": self.source_report_path.name,
                "bytes": self.source_bytes,
                "sha256": self.source_sha256,
                "schema_version": self.source.get("schema_version"),
                "status": self.source.get("status"),
            },
            "roots": {
                "artifact": ".",
                "screenshots": screenshots_logical_root,
                "downloads": downloads_logical_root,
            },
            "checks": self.checks,
            "counts": {
                "assertions": source_assertions if _is_int(source_assertions) else 0,
                "browser_errors": len(browser_errors) if isinstance(browser_errors, list) else None,
                "exact_viewports": len(self._viewport_pairs(self.source.get("viewports"))),
                "screenshots_reported": len(self.source.get("screenshot_manifest", []))
                if isinstance(self.source.get("screenshot_manifest"), list)
                else 0,
                "screenshots_validated": valid_screenshots,
                "themes": len(THEMES),
                "architectures": len(self.architecture_records),
                "architecture_2d_3d_pairs": architecture_pairs,
                "scene_template_architectures": template_architectures,
                "downloads_validated": valid_downloads,
            },
            "screenshots": screenshots,
            "screenshot_tree_digest": _canonical_digest([
                {name: item.get(name) for name in ("path", "bytes", "sha256")}
                for item in screenshots
            ]),
            "architecture_comparisons": self.architecture_records,
            "scene_template_architectures": self.template_architecture_records,
            "downloads": downloads,
            "download_tree_digest": _canonical_digest([
                {name: item.get(name) for name in ("format", "path", "bytes", "sha256")}
                for item in downloads
            ]),
            "svg_visual_oracle": self.svg_visual_oracle,
            "quality_evidence": {
                "reported_dom_geometry_contract_passed": self.checks.get("workflows_and_quality", False),
                "reported_boolean_flags": {name: quality.get(name) is True for name in BOOLEAN_QUALITY_CHECKS},
                "reported_label_occlusion": {
                    "passed": occlusion.get("passed") is True,
                    "label_count": occlusion.get("label_count"),
                    "collision_free": occlusion.get("overlap_count") == 0 and _is_int(occlusion.get("overlap_count")),
                    "clipping_free": occlusion.get("clipped_count") == 0 and _is_int(occlusion.get("clipped_count")),
                    "method": occlusion.get("method"),
                },
                "png_files_independently_parsed": self.checks.get("png_manifest_and_files", False),
                "viewport_png_dimensions_independently_cross_checked": self.checks.get("visual_coverage", False),
            },
            "measurement_scope": {
                "producer_dom_geometry_claim_checked": True,
                "application_proof_metadata_trusted_as_measurement": False,
                "bitmap_ocr_performed": False,
                "svg_visual_oracle": self.svg_visual_oracle.get("status", "NOT_MEASURED"),
                "svg_exact_glyph_bounds": "not_measured",
                "svg_source_3d_occlusion_recomputation": "not_measured",
                "statement": (
                    "This validator contract-checks the producer's DOM geometry measurements; it independently verifies the file set, "
                    "hashes, PNG structure/IHDR dimensions, report associations, and the actual downloaded SVG's XML geometry, estimated "
                    "label boxes, strokes, route intersections, and projection metadata bindings. It does not infer text collision from bitmap "
                    "OCR or recompute hidden-line removal from source 3D geometry."
                ),
            },
            "failures": self.failures,
        }

    def _logical_root(self, root: Path | None, fallback: str) -> str:
        if root is None or self.artifact_root is None:
            return fallback
        try:
            relative = root.relative_to(self.artifact_root).as_posix()
        except ValueError:
            return fallback
        return relative or "."


def validate_scene_visual_evidence(
    source_report: Path,
    artifact_root: Path,
    screenshots_root: Path | None = None,
) -> JsonObject:
    """Return a complete PASS/FAIL validation report without writing files."""

    return SceneVisualEvidenceValidator(source_report, artifact_root, screenshots_root).validate()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("e2e_report", type=Path, help="Scene Studio E2E JSON report")
    parser.add_argument("--artifact-root", type=Path, required=True, help="root containing screenshots/ and downloads/")
    parser.add_argument("--screenshots-root", type=Path, help="explicit screenshot root (defaults to ARTIFACT_ROOT/screenshots)")
    parser.add_argument("--output", type=Path, required=True, help="validation JSON to write")
    args = parser.parse_args(argv)
    report = validate_scene_visual_evidence(args.e2e_report, args.artifact_root, args.screenshots_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        "status": report["status"],
        "screenshots": report["counts"]["screenshots_validated"],
        "architecture_pairs": report["counts"]["architecture_2d_3d_pairs"],
        "scene_templates": report["counts"]["scene_template_architectures"],
        "downloads": report["counts"]["downloads_validated"],
        "failures": len(report["failures"]),
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    if report["status"] != "PASS":
        for failure in report["failures"]:
            print(f"- {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
