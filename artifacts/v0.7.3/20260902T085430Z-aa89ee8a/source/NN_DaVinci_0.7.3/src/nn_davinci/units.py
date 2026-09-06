"""Physical-unit conversions shared by every Figure Studio backend.

Figure IR geometry is expressed in millimetres.  Public style APIs use
PostScript points, while browser measurements are CSS pixels at 96 dpi.
Keeping the conversions here prevents renderers from treating a point value
as an SVG user-unit value (an SVG user unit represents one millimetre in
Figure Studio documents).
"""

from __future__ import annotations

import math
from typing import Iterable

from .errors import ValidationError


MM_PER_INCH = 25.4
PT_PER_INCH = 72.0
CSS_PX_PER_INCH = 96.0
MM_PER_PT = MM_PER_INCH / PT_PER_INCH
MM_PER_CSS_PX = MM_PER_INCH / CSS_PX_PER_INCH
CSS_PX_PER_PT = CSS_PX_PER_INCH / PT_PER_INCH


def _number(value: float, *, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValidationError(f"{name} must be a finite number")
    return result


def pt_to_mm(value: float) -> float:
    """Convert PostScript points to millimetres (72 pt = 25.4 mm)."""

    return _number(value, name="point value") * MM_PER_PT


def mm_to_pt(value: float) -> float:
    """Convert millimetres to PostScript points."""

    return _number(value, name="millimetre value") / MM_PER_PT


def css_px_to_mm(value: float) -> float:
    """Convert CSS pixels to millimetres using the normative 96 dpi rule."""

    return _number(value, name="CSS pixel value") * MM_PER_CSS_PX


def mm_to_css_px(value: float) -> float:
    """Convert millimetres to CSS pixels using the normative 96 dpi rule."""

    return _number(value, name="millimetre value") / MM_PER_CSS_PX


def pt_to_css_px(value: float) -> float:
    """Convert PostScript points to CSS pixels."""

    return _number(value, name="point value") * CSS_PX_PER_PT


def css_px_to_pt(value: float) -> float:
    """Convert CSS pixels to PostScript points."""

    return _number(value, name="CSS pixel value") / CSS_PX_PER_PT


def ctm_scales(a: float, b: float, c: float, d: float) -> tuple[float, float, float, float]:
    """Return axis scales and singular values for a two-dimensional CTM.

    The matrix maps an SVG element's local user coordinates to CSS pixels.
    ``scale_x`` and ``scale_y`` preserve axis meaning; singular values expose
    rotation-independent anisotropic or singular transforms.
    """

    matrix = tuple(_number(value, name="CTM component") for value in (a, b, c, d))
    ma, mb, mc, md = matrix
    scale_x = math.hypot(ma, mb)
    scale_y = math.hypot(mc, md)
    trace = ma * ma + mb * mb + mc * mc + md * md
    determinant = ma * md - mb * mc
    discriminant = math.sqrt(max(0.0, trace * trace - 4.0 * determinant * determinant))
    sigma_max = math.sqrt(max(0.0, (trace + discriminant) / 2.0))
    sigma_min = math.sqrt(max(0.0, (trace - discriminant) / 2.0))
    return scale_x, scale_y, sigma_min, sigma_max


def effective_font_pt(
    font_size_user_units: float,
    ctm: Iterable[float],
) -> float:
    """Measure a final SVG font size in points under its complete CTM.

    Figure SVG stores numeric font sizes in millimetre user units.  A browser
    CTM maps those local units to CSS pixels, so the vertical CTM magnitude is
    applied before the 96 dpi CSS-pixel-to-point conversion.
    """

    values = tuple(ctm)
    if len(values) != 4:
        raise ValidationError("effective_font_pt requires CTM components a, b, c, d")
    _scale_x, scale_y, _sigma_min, _sigma_max = ctm_scales(*values)
    return css_px_to_pt(_number(font_size_user_units, name="font size") * scale_y)


def effective_stroke_pt(
    stroke_width_user_units: float,
    ctm: Iterable[float],
    *,
    non_scaling: bool = False,
) -> float:
    """Measure a final SVG stroke width in points under its complete CTM.

    For ordinary strokes the geometric mean of the two singular values gives
    the rotation-independent area scale.  A non-scaling stroke is already in
    CSS pixels and therefore bypasses the CTM; Figure Studio's own output does
    not use non-scaling strokes because its API width is physical.
    """

    width = _number(stroke_width_user_units, name="stroke width")
    values = tuple(ctm)
    if len(values) != 4:
        raise ValidationError("effective_stroke_pt requires CTM components a, b, c, d")
    if non_scaling:
        return css_px_to_pt(width)
    _scale_x, _scale_y, sigma_min, sigma_max = ctm_scales(*values)
    scale = math.sqrt(max(0.0, sigma_min * sigma_max))
    return css_px_to_pt(width * scale)


__all__ = [
    "CSS_PX_PER_INCH",
    "CSS_PX_PER_PT",
    "MM_PER_CSS_PX",
    "MM_PER_INCH",
    "MM_PER_PT",
    "PT_PER_INCH",
    "css_px_to_mm",
    "css_px_to_pt",
    "ctm_scales",
    "effective_font_pt",
    "effective_stroke_pt",
    "mm_to_css_px",
    "mm_to_pt",
    "pt_to_css_px",
    "pt_to_mm",
]
