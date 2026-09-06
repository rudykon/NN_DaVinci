from __future__ import annotations

import math
import unittest

from nn_davinci.figure_export import render_figure_svg, render_figure_tikz
from nn_davinci.figure_ir import FigureObject, FigureProvenance, FigureStyle, new_figure
from nn_davinci.figure_templates import instantiate_template
from nn_davinci.text_layout import TextLayoutError, layout_text_box, measure_text_line, wrap_text
from nn_davinci.units import (
    css_px_to_mm,
    effective_font_pt,
    effective_stroke_pt,
    mm_to_css_px,
    mm_to_pt,
    pt_to_mm,
)
from nn_davinci.version import __version__


class PhysicalUnitTests(unittest.TestCase):
    def test_exact_point_millimetre_and_css_pixel_conversions(self) -> None:
        self.assertAlmostEqual(25.4, pt_to_mm(72.0), places=12)
        self.assertAlmostEqual(72.0, mm_to_pt(25.4), places=12)
        self.assertAlmostEqual(96.0, mm_to_css_px(25.4), places=12)
        self.assertAlmostEqual(25.4, css_px_to_mm(96.0), places=12)
        self.assertAlmostEqual(178.0, css_px_to_mm(mm_to_css_px(178.0)), places=12)

    def test_effective_font_and_stroke_use_the_complete_ctm(self) -> None:
        root_scale = 96.0 / 25.4
        self.assertAlmostEqual(7.0, effective_font_pt(pt_to_mm(7.0), (root_scale, 0, 0, root_scale)), places=9)
        self.assertAlmostEqual(0.8, effective_stroke_pt(pt_to_mm(0.8), (root_scale, 0, 0, root_scale)), places=9)
        compressed = effective_font_pt(pt_to_mm(7.0), (root_scale, 0, 0, root_scale * 0.5))
        self.assertAlmostEqual(3.5, compressed, places=9)
        self.assertTrue(math.isfinite(compressed))


class FigureTextLayoutTests(unittest.TestCase):
    def test_single_line_manual_wrap_cjk_math_and_fallback_record(self) -> None:
        measured = measure_text_line("Attention α 中文", font_size_pt=7.0)
        self.assertGreater(measured.width_mm, 0)
        self.assertIn("cjk", measured.font.scripts)
        self.assertIn("greek", measured.font.scripts)
        self.assertIn("Noto Sans CJK SC", measured.font.fallback_candidates)
        lines = wrap_text("manual\nbreak 中文数学 α+β", maximum_width_mm=18.0, font_size_pt=7.0)
        self.assertEqual("manual", lines[0])
        self.assertGreaterEqual(len(lines), 3)

    def test_layout_never_compresses_and_fails_actionably_when_lane_is_too_short(self) -> None:
        layout = layout_text_box(
            "A long node label that wraps",
            x_mm=2,
            y_mm=3,
            width_mm=18,
            height_mm=14,
            font_size_pt=7,
            horizontal_align="middle",
        )
        self.assertGreater(len(layout.lines), 1)
        self.assertEqual(7.0, layout.font_size_pt)
        with self.assertRaisesRegex(TextLayoutError, "increase the lane or page"):
            layout_text_box(
                "caption " * 300,
                x_mm=0,
                y_mm=0,
                width_mm=30,
                height_mm=10,
                font_size_pt=7,
            )
        with self.assertRaisesRegex(TextLayoutError, "below the required minimum"):
            layout_text_box("hidden six point", x_mm=0, y_mm=0, width_mm=40, height_mm=10, font_size_pt=6)

    def test_svg_uses_mm_user_units_and_tikz_applies_each_object_font(self) -> None:
        _, figure = instantiate_template("cnn-feature-pipeline")
        svg = render_figure_svg(figure)
        self.assertIn(f'data-nndv-version="{__version__}"', svg)
        self.assertIn(f'&quot;nn_davinci_version&quot;:&quot;{__version__}&quot;', svg)
        self.assertIn('data-geometry-unit="mm"', svg)
        self.assertIn(f'font-size="{pt_to_mm(7):g}"', svg)
        self.assertIn(f'stroke-width="{pt_to_mm(0.8):g}"', svg)
        self.assertNotIn('font-size="7pt"', svg)
        self.assertNotIn("vector-effect=", svg)
        self.assertNotIn("data-horizontal-scale", svg)
        tikz = render_figure_tikz(figure)
        self.assertIn(r"font=\sffamily\fontsize{7}{8.4}\selectfont", tikz)
        self.assertIn("line width=0.8pt", tikz)
        self.assertIn("line width=0.35pt", tikz)

    def test_six_point_local_style_is_rejected_instead_of_silently_clamped(self) -> None:
        figure = new_figure("Minimum font")
        panel = next(figure.iter_panels())
        layer = next(item for item in panel.layers if item.role == "model-data")
        layer.objects.append(
            FigureObject.create(
                "node-glyph",
                "Six point",
                {"x": 20, "y": 20, "width": 30, "height": 12},
                FigureProvenance.author(),
                style=FigureStyle(overrides={"font_size": 6.0}),
            )
        )
        with self.assertRaisesRegex(TextLayoutError, "below the required minimum"):
            render_figure_svg(figure)


if __name__ == "__main__":
    unittest.main()
