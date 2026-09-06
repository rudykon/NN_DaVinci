from __future__ import annotations

from io import BytesIO
import hashlib
import html
import json
from pathlib import Path
import struct
import tempfile
import unittest
from typing import Any
import zipfile
import zlib

from scripts.validate_scene_visual_evidence_0_7 import (
    ARCHITECTURES,
    EXACT_VIEWPORTS,
    RELEASE,
    REPORT_SCHEMA,
    SOURCE_SCHEMA,
    TEMPLATE_ARCHITECTURES,
    main,
    validate_scene_visual_evidence,
)


def png_chunk(name: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + name + payload + struct.pack(">I", zlib.crc32(name + payload) & 0xFFFFFFFF)


def png_bytes(width: int, height: int, marker: str) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0)
    row = b"\x00" + bytes((width + 7) // 8)
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"tEXt", f"evidence-id\x00{marker}".encode())
        + png_chunk(b"IDAT", zlib.compress(row * height, level=1))
        + png_chunk(b"IEND", b"")
    )


def pptx_bytes() -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("ppt/presentation.xml", "<p:presentation xmlns:p='p'/>")
    return buffer.getvalue()


def svg_oracle_bytes() -> bytes:
    stroke_pt = 0.75
    primitives = [
        {"kind": "face", "object_id": "node-input", "depth": 5.0, "points": [[10, 10], [30, 10], [30, 25], [10, 25]]},
        {"kind": "edge", "object_id": "node-input", "depth": 5.1, "points": [[10, 10], [30, 10]]},
        {"kind": "polyline", "object_id": "route-a", "depth": 4.0, "points": [[10, 30], [30, 30]]},
        {"kind": "polyline", "object_id": "route-b", "depth": 3.0, "points": [[50, 35], [70, 35]]},
        {"kind": "label", "object_id": "node-input", "depth": 5.0, "points": [[20, 15]], "text": "input"},
        {"kind": "label", "object_id": "node-output", "depth": 3.0, "points": [[65, 45]], "text": "output"},
    ]
    for primitive in primitives:
        primitive["style"] = {"stroke_width_pt": stroke_pt, "font_size_pt": 7.0}
    metadata = {
        "schema_version": "nndv-scene-projection-1",
        "source_digest": "a" * 64,
        "camera_id": "camera-test",
        "width_mm": 100,
        "height_mm": 60,
        "options": {
            "hidden_edges": True,
            "backface_culling": True,
            "occlusion_samples": 32,
            "stroke_width_pt": stroke_pt,
            "min_label_pt": 7.0,
            "width_mm": 100,
            "height_mm": 60,
        },
        "primitives": primitives,
    }
    metadata_text = html.escape(json.dumps(metadata, separators=(",", ":")), quote=False)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="60mm" viewBox="0 0 100 60" data-nndv-export="nndv-scene-export-1" data-camera-id="camera-test">
<metadata id="nndv-scene-projection">{metadata_text}</metadata>
<polygon id="nndv-face-0" data-kind="face" data-object-id="node-input" data-depth="5" points="10,10 30,10 30,25 10,25" fill="#eee" stroke="#333" stroke-width="0.264583"/>
<polyline id="nndv-edge-1" data-kind="edge" data-object-id="node-input" data-depth="5.1" points="10,10 30,10" fill="none" stroke="#333" stroke-width="0.264583"/>
<polyline id="nndv-polyline-2" data-kind="polyline" data-object-id="route-a" data-depth="4" points="10,30 30,30" fill="none" stroke="#333" stroke-width="0.264583"/>
<polyline id="nndv-polyline-3" data-kind="polyline" data-object-id="route-b" data-depth="3" points="50,35 70,35" fill="none" stroke="#333" stroke-width="0.264583"/>
<text id="nndv-label-4" data-kind="label" data-object-id="node-input" data-depth="5" x="20" y="15" fill="#111" stroke="none" font-size="7pt">input</text>
<text id="nndv-label-5" data-kind="label" data-object-id="node-output" data-depth="3" x="65" y="45" fill="#111" stroke="none" font-size="7pt">output</text>
</svg>""".encode()


class SceneVisualEvidenceFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.screenshots = root / "screenshots"
        self.downloads = root / "downloads"
        self.screenshots.mkdir(parents=True)
        self.downloads.mkdir()
        self.report_path = root / "scene-studio-e2e.json"
        self.report = self._build_report()
        self.write_report()

    def _build_report(self) -> dict[str, Any]:
        coverage: dict[str, list[str]] = {
            "start-center-blank-import-architectures": ["blank", "import", "seven-architectures"],
            "blank-2d-workspace": ["blank", "2d"],
            "blank-3d-scene": ["blank", "3d"],
            "figure-proof-resnet50": ["proof", "figure", "real-model"],
            "scene-export-menu-10-formats": ["export", "menu", "ten-formats"],
            "comparison-resnet50-semantic-2d": ["real-model", "semantic", "2d", "comparison-pair"],
            "comparison-resnet50-scene-3d": ["real-model", "semantic", "structure-lens", "3d", "comparison-pair"],
            "comparison-return-to-2d-selection": ["2d", "3d-to-2d", "selection", "provenance", "comparison-pair"],
            "structure-lens-bounded-result": ["structure-lens", "dialog", "provenance"],
            "autosave-revision-comparison": ["dialog", "autosave-conflict", "cancel-retry"],
            "autosave-restored-after-page-reload": ["autosave", "reload", "3d"],
            "cpu-svg-vector-fallback": ["fallback", "cpu-svg", "stroke", "3d"],
        }
        for theme in ("light", "dark", "high-contrast", "paper"):
            coverage[f"theme-{theme}-scene"] = ["theme", theme, "3d"]
        comparisons: dict[str, dict[str, Any]] = {}
        for index, key in enumerate(ARCHITECTURES):
            two_d_id = f"architecture-{key}-2d"
            three_d_id = f"architecture-{key}-3d"
            coverage[two_d_id] = ["architecture", key, "import", "2d", "comparison-pair"]
            coverage[three_d_id] = ["architecture", key, "3d", "comparison-pair"]
            comparisons[key] = {
                "two_d": {"screenshot_id": two_d_id, "path": f"screenshots/{two_d_id}.png"},
                "three_d": {"screenshot_id": three_d_id, "path": f"screenshots/{three_d_id}.png"},
                "non_helper_model_objects": index + 1,
                "route_objects": index + 1,
                "visible_labels": index + 1,
            }
        template_architectures: dict[str, dict[str, Any]] = {}
        for index, key in enumerate(TEMPLATE_ARCHITECTURES):
            identifier = f"template-architecture-{key}-3d"
            coverage[identifier] = ["template-architecture", key, "3d"]
            template_architectures[key] = {
                "screenshot_id": identifier,
                "path": f"screenshots/{identifier}.png",
                "non_helper_model_objects": index + 1,
                "route_objects": index + 1,
            }
        for width, height in EXACT_VIEWPORTS:
            coverage[f"viewport-{width}x{height}"] = ["responsive", "3d", "exact-viewport"]
        if len(coverage) != 44:
            raise AssertionError(f"fixture must produce 44 distinct screenshots, got {len(coverage)}")

        screenshot_manifest: list[dict[str, Any]] = []
        for identifier, tags in coverage.items():
            width, height = self._dimensions(identifier)
            payload = png_bytes(width, height, identifier)
            path = self.screenshots / f"{identifier}.png"
            path.write_bytes(payload)
            screenshot_manifest.append({
                "id": identifier,
                "path": f"screenshots/{identifier}.png",
                "coverage": tags,
                "viewport": {"width": width, "height": height},
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            })

        download_manifest: list[dict[str, Any]] = []
        for format_name, filename, payload in self._download_payloads():
            path = self.downloads / filename
            path.write_bytes(payload)
            download_manifest.append({
                "format": format_name,
                "path": f"downloads/{filename}",
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            })

        return {
            "schema_version": SOURCE_SCHEMA,
            "release": RELEASE,
            "status": "PASS",
            "succeeded": True,
            "human_participants": 0,
            "failures": [],
            "assertions": [f"runtime assertion {index}" for index in range(78)],
            "assertion_count": 78,
            "viewports": [{"width": width, "height": height} for width, height in EXACT_VIEWPORTS],
            "viewport_results": [self._viewport_result(width, height) for width, height in EXACT_VIEWPORTS],
            "required_workflows": {
                "blank_2d_3d": True,
                "real_model_semantic_scene": True,
                "structure_lens_scene": True,
                "autosave_reload": True,
                "scene_exports_10": True,
                "selection_provenance_3d_to_2d": True,
                "error_cancel_retry": True,
                "architectures_7": True,
                "scene_templates_7": True,
            },
            "quality_checks": {
                "geometry": True,
                "overflow": True,
                "canvas_area": True,
                "topbar_clear": True,
                "compact_drawers_closed": True,
                "dialog": True,
                "menu": True,
                "toolbar": True,
                "focus": True,
                "contrast": True,
                "label": True,
                "accessibility_labels": True,
                "hidden_line": True,
                "font": True,
                "stroke": True,
                "contrast_ratios": {"light": 15.0, "dark": 16.0, "high-contrast": 21.0, "paper": 12.0},
                "scene_label_occlusion": {
                    "passed": True,
                    "label_count": 18,
                    "overlap_count": 0,
                    "clipped_count": 0,
                    "method": "DOM getBoundingClientRect geometry and SVG viewport bounds",
                },
            },
            "screenshot_manifest": screenshot_manifest,
            "architecture_comparisons": comparisons,
            "scene_template_architectures": template_architectures,
            "download_manifest": download_manifest,
            "artifact_root": ".",
            "expected_fallback_errors": [],
            "expected_recovery_errors": ["intentional HTTP 503 recovery exercise"],
            "browser_errors": [],
        }

    @staticmethod
    def _dimensions(identifier: str) -> tuple[int, int]:
        match = None
        if identifier.startswith("viewport-"):
            match = identifier.removeprefix("viewport-").split("x")
        if match is not None:
            return int(match[0]), int(match[1])
        if identifier == "cpu-svg-vector-fallback":
            return 1280, 720
        return 1920, 1080

    @staticmethod
    def _viewport_result(width: int, height: int) -> dict[str, Any]:
        canvas_width = float(width)
        canvas_height = float(height - 60)
        canvas_area = canvas_width * canvas_height
        viewport_area = width * height
        compact = width <= 800
        return {
            "width": width,
            "height": height,
            "viewportWidth": width,
            "viewportHeight": height,
            "documentWidth": width,
            "documentHeight": height,
            "bodyWidth": width,
            "bodyHeight": height,
            "canvasWidth": canvas_width,
            "canvasHeight": canvas_height,
            "canvasArea": canvas_area,
            "viewportArea": viewport_area,
            "canvasAreaRatio": round(canvas_area / viewport_area, 6),
            "minimumAreaRatio": 0.7 if compact else 0.6,
            "compact": compact,
            "canvasBounds": {"left": 0.0, "top": 60.0, "right": canvas_width, "bottom": float(height)},
            "topbarBounds": {"left": 0.0, "top": 0.0, "right": float(width), "bottom": 60.0},
            "topbarOverlap": 0.0,
            "compactDrawersClosed": True,
        }

    @staticmethod
    def _download_payloads() -> list[tuple[str, str, bytes]]:
        png = png_bytes(320, 200, "download")
        return [
            ("svg", "svg-scene.svg", svg_oracle_bytes()),
            ("pdf", "pdf-scene.pdf", b"%PDF-1.4\n%%EOF\n"),
            ("tikz", "tikz-scene.tex", b"\\documentclass{standalone}\n\\begin{tikzpicture}\\end{tikzpicture}\n"),
            ("pptx", "pptx-scene.pptx", pptx_bytes()),
            ("png", "png-scene.png", png),
            ("eps", "eps-scene.eps", b"%!PS-Adobe-3.0 EPSF-3.0\n%%EOF\n"),
            ("html", "html-scene.html", b"<!doctype html><html><body>scene</body></html>"),
            ("json", "json-scene.scene.json", b'{"schema_version":"1.0","layers":[]}'),
            ("gltf", "gltf-scene.gltf", b'{"asset":{"version":"2.0"}}'),
            ("glb", "scene.glb", b"glTF" + struct.pack("<II", 2, 12)),
        ]

    def write_report(self) -> None:
        self.report_path.write_text(json.dumps(self.report, indent=2) + "\n", encoding="utf-8")

    def manifest_item(self, identifier: str) -> dict[str, Any]:
        return next(item for item in self.report["screenshot_manifest"] if item["id"] == identifier)


class SceneVisualEvidence070Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "scene-studio-artifacts"
        self.root.mkdir()
        self.fixture = SceneVisualEvidenceFixture(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_complete_evidence_passes_cli_and_records_independent_scope(self) -> None:
        output = Path(self.temporary.name) / "visual-validation.json"
        exit_code = main([
            str(self.fixture.report_path),
            "--artifact-root",
            str(self.root),
            "--screenshots-root",
            str(self.fixture.screenshots),
            "--output",
            str(output),
        ])
        self.assertEqual(exit_code, 0)
        validated = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(validated["schema_version"], REPORT_SCHEMA)
        self.assertEqual(validated["status"], "PASS")
        self.assertEqual(validated["failures"], [])
        self.assertTrue(all(validated["checks"].values()))
        self.assertEqual(validated["counts"]["screenshots_validated"], 44)
        self.assertEqual(validated["counts"]["architecture_2d_3d_pairs"], 7)
        self.assertEqual(validated["counts"]["scene_template_architectures"], 7)
        self.assertEqual(validated["counts"]["downloads_validated"], 10)
        self.assertEqual(validated["svg_visual_oracle"]["status"], "PASS")
        self.assertEqual(validated["svg_visual_oracle"]["text"]["minimum_font_pt"], 7.0)
        self.assertTrue(validated["svg_visual_oracle"]["stroke"]["uniform"])
        self.assertEqual(validated["svg_visual_oracle"]["routes"]["non_endpoint_intersection_count"], 0)
        self.assertEqual(validated["svg_visual_oracle"]["hidden_line"]["status"], "PASS")
        self.assertEqual(len(validated["screenshot_tree_digest"]), 64)
        download_digest_records = sorted(
            [
                {name: item[name] for name in ("format", "path", "bytes", "sha256")}
                for item in self.fixture.report["download_manifest"]
            ],
            key=lambda item: item["path"],
        )
        expected_download_digest = hashlib.sha256(
            json.dumps(download_digest_records, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.assertEqual(validated["download_tree_digest"], expected_download_digest)
        self.assertFalse(validated["measurement_scope"]["bitmap_ocr_performed"])
        self.assertFalse(validated["measurement_scope"]["application_proof_metadata_trusted_as_measurement"])
        self.assertNotIn(str(self.root), output.read_text(encoding="utf-8"))

    def test_producer_pass_does_not_hide_png_hash_tampering(self) -> None:
        identifier = "architecture-resnet50-3d"
        path = self.fixture.screenshots / f"{identifier}.png"
        path.write_bytes(png_bytes(1920, 1080, "tampered-after-producer-pass"))
        validated = validate_scene_visual_evidence(self.fixture.report_path, self.root)
        self.assertEqual(validated["status"], "FAIL")
        self.assertTrue(any("manifest sha256 does not match" in failure for failure in validated["failures"]))
        self.assertEqual(validated["source_report"]["status"], "PASS")

    def test_independent_ihdr_check_rejects_wrong_viewport_even_with_updated_hash(self) -> None:
        identifier = "viewport-390x844"
        payload = png_bytes(391, 844, "wrong-IHDR-width")
        path = self.fixture.screenshots / f"{identifier}.png"
        path.write_bytes(payload)
        item = self.fixture.manifest_item(identifier)
        item["bytes"] = len(payload)
        item["sha256"] = hashlib.sha256(payload).hexdigest()
        self.fixture.write_report()
        validated = validate_scene_visual_evidence(self.fixture.report_path, self.root)
        self.assertEqual(validated["status"], "FAIL")
        self.assertTrue(any("PNG IHDR dimensions" in failure for failure in validated["failures"]))
        self.assertFalse(validated["checks"]["png_manifest_and_files"])

    def test_path_traversal_and_unmanifested_png_are_rejected(self) -> None:
        item = self.fixture.manifest_item("blank-2d-workspace")
        item["path"] = "screenshots/../blank-2d-workspace.png"
        self.fixture.write_report()
        rogue = self.fixture.screenshots / "rogue.png"
        rogue.write_bytes(png_bytes(1920, 1080, "rogue"))
        validated = validate_scene_visual_evidence(self.fixture.report_path, self.root)
        self.assertEqual(validated["status"], "FAIL")
        failures = "\n".join(validated["failures"])
        self.assertIn("parent traversal", failures)
        self.assertIn("unmanifested PNG", failures)

    def test_architecture_pair_requires_real_3d_objects_and_distinct_png(self) -> None:
        comparison = self.fixture.report["architecture_comparisons"]["topk_moe"]
        comparison["non_helper_model_objects"] = 0
        comparison["route_objects"] = 0
        comparison["visible_labels"] = 0
        comparison["three_d"] = dict(comparison["two_d"])
        self.fixture.write_report()
        validated = validate_scene_visual_evidence(self.fixture.report_path, self.root)
        self.assertEqual(validated["status"], "FAIL")
        failures = "\n".join(validated["failures"])
        self.assertIn("positive non_helper_model_objects", failures)
        self.assertIn("positive route_objects", failures)
        self.assertIn("positive visible_labels", failures)
        self.assertIn("three_d screenshot_id", failures)
        self.assertIn("does not reference its screenshot manifest PNG", failures)

    def test_fourteen_real_architecture_images_must_all_be_distinct(self) -> None:
        source = self.fixture.screenshots / "architecture-resnet50-3d.png"
        duplicate = self.fixture.screenshots / "architecture-topk_moe-3d.png"
        payload = source.read_bytes()
        duplicate.write_bytes(payload)
        item = self.fixture.manifest_item("architecture-topk_moe-3d")
        item["bytes"] = len(payload)
        item["sha256"] = hashlib.sha256(payload).hexdigest()
        self.fixture.write_report()

        validated = validate_scene_visual_evidence(self.fixture.report_path, self.root)
        self.assertEqual(validated["status"], "FAIL")
        self.assertFalse(validated["checks"]["architecture_2d_3d_pairs"])
        self.assertTrue(
            any("all fourteen real-architecture" in failure for failure in validated["failures"]),
        )
        self.assertTrue(
            all(not record["valid"] for record in validated["architecture_comparisons"].values()),
        )

    def test_structured_dom_quality_and_download_payload_are_hard_gates(self) -> None:
        self.fixture.report["quality_checks"]["scene_label_occlusion"] = True
        download = next(item for item in self.fixture.report["download_manifest"] if item["format"] == "glb")
        path = self.root / download["path"]
        path.write_bytes(b"not-a-glb")
        download["bytes"] = path.stat().st_size
        download["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.fixture.write_report()
        validated = validate_scene_visual_evidence(self.fixture.report_path, self.root)
        self.assertEqual(validated["status"], "FAIL")
        failures = "\n".join(validated["failures"])
        self.assertIn("structured DOM-geometry result", failures)
        self.assertIn("download glb has an invalid format signature/container", failures)

    def test_seven_scene_templates_are_separate_from_real_model_pairs(self) -> None:
        templates = self.fixture.report["scene_template_architectures"]
        templates["cnn"]["non_helper_model_objects"] = 0
        templates["cnn"]["route_objects"] = 0
        templates.pop("moe")
        self.fixture.write_report()
        validated = validate_scene_visual_evidence(self.fixture.report_path, self.root)
        self.assertEqual(validated["status"], "FAIL")
        self.assertFalse(validated["checks"]["scene_template_architectures"])
        self.assertTrue(any("exactly the seven required Scene template keys" in failure for failure in validated["failures"]))

    def test_actual_svg_oracle_rejects_small_fonts_and_route_crossing_after_rehash(self) -> None:
        download = next(item for item in self.fixture.report["download_manifest"] if item["format"] == "svg")
        path = self.root / download["path"]
        payload = path.read_bytes().replace(b'font-size="7pt"', b'font-size="6pt"')
        payload = payload.replace(b'points="50,35 70,35"', b'points="20,20 20,40"')
        payload = payload.replace(b'stroke-width="0.264583"', b'stroke-width="0"', 1)
        payload = payload.replace(b'"hidden_edges":true', b'"hidden_edges":false')
        path.write_bytes(payload)
        download["bytes"] = len(payload)
        download["sha256"] = hashlib.sha256(payload).hexdigest()
        self.fixture.write_report()
        validated = validate_scene_visual_evidence(self.fixture.report_path, self.root)
        self.assertEqual(validated["status"], "FAIL")
        self.assertFalse(validated["checks"]["svg_visual_oracle"])
        oracle = validated["svg_visual_oracle"]
        self.assertEqual(oracle["status"], "FAIL")
        self.assertEqual(oracle["text"]["minimum_font_pt"], 6.0)
        self.assertEqual(oracle["routes"]["non_endpoint_intersection_count"], 1)
        self.assertFalse(oracle["stroke"]["uniform"])
        self.assertFalse(oracle["hidden_line"]["hidden_edges_option"])
        failures = "\n".join(validated["failures"])
        self.assertIn("minimum_font_pt is below 7", failures)
        self.assertIn("non-endpoint intersections", failures)


if __name__ == "__main__":
    unittest.main()
