from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from nn_davinci.errors import ExportError
from nn_davinci.model_scene import scene_template
from nn_davinci.pdf_fonts import SCENE_PDF_FONT_DIRECTORY, SCENE_PDF_FONT_FILES
from nn_davinci.scene_export import render_scene_pdf


def multilingual_scene(label: str):
    scene = scene_template("resnet")
    next(item for item in scene.iter_objects() if item.kind == "tensor-volume").name = label
    return scene


class ScenePdfFonts072Tests(unittest.TestCase):
    def test_packaged_fonts_and_redistribution_licenses_exist(self) -> None:
        for _resource, font_name, license_name in SCENE_PDF_FONT_FILES:
            with self.subTest(font=font_name):
                self.assertGreater((SCENE_PDF_FONT_DIRECTORY / font_name).stat().st_size, 100_000)
                self.assertGreater((SCENE_PDF_FONT_DIRECTORY / license_name).stat().st_size, 500)

    def test_native_pdf_embeds_unicode_fonts_and_roundtrips_required_scripts(self) -> None:
        label = "中文 ResNet αβ x₂ ∑∞→ ×3"
        payload = render_scene_pdf(multilingual_scene(label))
        self.assertNotIn(b"/BaseFont /Helvetica", payload)
        self.assertIn(b"/FontFile2", payload)
        self.assertIn(b"/ToUnicode", payload)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unicode.pdf"
            path.write_bytes(payload)
            fonts = subprocess.run(
                ["pdffonts", str(path)],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            rows = [line for line in fonts.splitlines()[2:] if line.strip()]
            self.assertGreaterEqual(len(rows), 3)
            self.assertTrue(all(" yes " in f" {row} " for row in rows), fonts)
            extracted = subprocess.run(
                ["pdftotext", str(path), "-"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            self.assertIn(label, extracted)

    def test_missing_font_resource_fails_explicitly_without_base14_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch(
            "nn_davinci.pdf_fonts.SCENE_PDF_FONT_DIRECTORY",
            Path(directory),
        ):
            with self.assertRaisesRegex(ExportError, "Required embedded Scene PDF font resource is missing"):
                render_scene_pdf(multilingual_scene("Input"))

    def test_unsupported_unicode_fails_instead_of_silent_font_substitution(self) -> None:
        with self.assertRaisesRegex(ExportError, "unsupported Unicode character"):
            render_scene_pdf(multilingual_scene("🧬 unsupported emoji"))


if __name__ == "__main__":
    unittest.main()
