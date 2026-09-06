"""Deterministic, physical text measurement and wrapping for Figure IR.

The layout model is deliberately conservative.  It does not compress glyphs
or use ``textLength``; instead it estimates advances by Unicode category and
lets the independent browser oracle validate the serialized result.  The
same line breaks and physical boxes are consumed by SVG, TikZ, PDF and PPTX.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
import unicodedata
from typing import Any, Iterable

from .errors import ValidationError
from .units import pt_to_mm


DEFAULT_LINE_HEIGHT = 1.2
DEFAULT_MINIMUM_FONT_PT = 7.0
# The core package cannot assume a platform font engine.  A conservative
# advance reserve keeps browser/PDF fallback metrics inside the allocated
# lane; the final Chrome oracle still measures the serialized glyphs.
METRIC_SAFETY_FACTOR = 1.12
_BREAK_AFTER = frozenset(" ,;/|+-=→×·")
_NARROW = frozenset("'`.,:;!|ijlItf()[]{}")
_WIDE = frozenset("MW@%&QGmwm")


class TextLayoutError(ValidationError):
    """Raised when required text cannot be placed without clipping."""


@dataclass(frozen=True, slots=True)
class FontFallbackRecord:
    requested: tuple[str, ...]
    css_stack: str
    fallback_candidates: tuple[str, ...]
    scripts: tuple[str, ...]
    resolution: str = "browser-oracle-required"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TextMeasurement:
    text: str
    width_mm: float
    height_mm: float
    ascent_mm: float
    descent_mm: float
    font_size_pt: float
    font: FontFallbackRecord


@dataclass(frozen=True, slots=True)
class TextLine:
    text: str
    x_mm: float
    baseline_y_mm: float
    width_mm: float


@dataclass(frozen=True, slots=True)
class TextLayout:
    lines: tuple[TextLine, ...]
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float
    font_size_pt: float
    line_height_pt: float
    horizontal_align: str
    vertical_align: str
    font: FontFallbackRecord

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["font"] = self.font.to_dict()
        return result


def _families(value: str | Iterable[str]) -> tuple[str, ...]:
    raw = value.split(",") if isinstance(value, str) else list(value)
    cleaned = tuple(str(item).strip().strip("'\"") for item in raw if str(item).strip())
    return cleaned or ("DejaVu Sans", "sans-serif")


def _scripts(text: str) -> tuple[str, ...]:
    found: set[str] = set()
    for character in text:
        codepoint = ord(character)
        name = unicodedata.name(character, "")
        if 0x3400 <= codepoint <= 0x9FFF or "CJK" in name or "IDEOGRAPH" in name:
            found.add("cjk")
        elif "GREEK" in name:
            found.add("greek")
        elif unicodedata.category(character) == "Sm" or "MATHEMATICAL" in name:
            found.add("math")
        elif codepoint > 0x7F:
            found.add("unicode")
        elif character.isascii() and (character.isalpha() or character.isdigit()):
            found.add("latin")
    return tuple(sorted(found or {"neutral"}))


def resolve_font_fallback(text: str, font_family: str | Iterable[str]) -> FontFallbackRecord:
    """Return an explicit reproducible fallback stack for the text scripts."""

    requested = _families(font_family)
    scripts = _scripts(text)
    candidates: list[str] = []
    if "cjk" in scripts:
        candidates.extend(("Noto Sans CJK SC", "Source Han Sans SC"))
    if "math" in scripts or "greek" in scripts:
        candidates.extend(("STIX Two Math", "DejaVu Sans"))
    candidates.extend(("DejaVu Sans", "Arial", "sans-serif"))
    combined: list[str] = []
    for family in (*requested, *candidates):
        if family not in combined:
            combined.append(family)
    css_stack = ", ".join(f'"{item}"' if " " in item else item for item in combined)
    fallback = tuple(item for item in combined if item not in requested)
    return FontFallbackRecord(requested, css_stack, fallback, scripts)


def _advance_em(character: str) -> float:
    if not character or unicodedata.combining(character):
        return 0.0
    category = unicodedata.category(character)
    east_asian = unicodedata.east_asian_width(character)
    if east_asian in {"W", "F"}:
        return 1.0
    if character.isspace():
        return 0.33
    if character in _NARROW:
        return 0.32
    if character in _WIDE:
        return 0.86
    if category == "Nd":
        return 0.56
    if category.startswith("P"):
        return 0.42
    if category == "Sm":
        return 0.72
    if character.isupper():
        return 0.64
    if character.islower():
        return 0.54
    if east_asian == "A":
        return 0.72
    return 0.65


def measure_text_line(
    text: str,
    *,
    font_size_pt: float,
    font_family: str | Iterable[str] = "DejaVu Sans, Arial, sans-serif",
    font_weight: int = 400,
) -> TextMeasurement:
    """Measure one line in physical units without consulting renderer state."""

    if "\n" in text or "\r" in text:
        raise TextLayoutError("Single-line measurement received a manual line break")
    size = float(font_size_pt)
    if size <= 0:
        raise TextLayoutError("Text font size must be positive")
    em_mm = pt_to_mm(size)
    weight_factor = 1.025 if int(font_weight) >= 600 else 1.0
    width = sum(_advance_em(character) for character in text) * em_mm * weight_factor * METRIC_SAFETY_FACTOR
    font = resolve_font_fallback(text, font_family)
    return TextMeasurement(text, width, em_mm, em_mm * 0.8, em_mm * 0.2, size, font)


def _split_long_token(
    token: str,
    *,
    maximum_width_mm: float,
    font_size_pt: float,
    font_family: str | Iterable[str],
    font_weight: int,
) -> list[str]:
    pieces: list[str] = []
    current = ""
    for character in token:
        candidate = current + character
        width = measure_text_line(
            candidate,
            font_size_pt=font_size_pt,
            font_family=font_family,
            font_weight=font_weight,
        ).width_mm
        if current and width > maximum_width_mm:
            pieces.append(current.rstrip())
            current = character.lstrip() if character.isspace() else character
        elif not current and width > maximum_width_mm:
            raise TextLayoutError(
                f"The glyph {character!r} cannot fit inside a {maximum_width_mm:.3f} mm text lane at {font_size_pt:g} pt"
            )
        else:
            current = candidate
    if current or not pieces:
        pieces.append(current.rstrip())
    return pieces


def wrap_text(
    text: str,
    *,
    maximum_width_mm: float,
    font_size_pt: float,
    font_family: str | Iterable[str] = "DejaVu Sans, Arial, sans-serif",
    font_weight: int = 400,
) -> tuple[str, ...]:
    """Wrap text to a physical width while preserving manual line breaks."""

    maximum = float(maximum_width_mm)
    if maximum <= 0:
        raise TextLayoutError("Text layout requires a positive maximum width")
    normalized = str(text).replace("\r\n", "\n").replace("\r", "\n")
    output: list[str] = []
    for paragraph in normalized.split("\n"):
        if not paragraph:
            output.append("")
            continue
        units: list[str] = []
        start = 0
        for index, character in enumerate(paragraph):
            if character in _BREAK_AFTER:
                units.append(paragraph[start : index + 1])
                start = index + 1
        if start < len(paragraph):
            units.append(paragraph[start:])
        if not units:
            units = [paragraph]
        line = ""
        for unit in units:
            candidate = line + unit
            candidate_width = measure_text_line(
                candidate.rstrip(),
                font_size_pt=font_size_pt,
                font_family=font_family,
                font_weight=font_weight,
            ).width_mm
            if candidate_width <= maximum:
                line = candidate
                continue
            if line.strip():
                output.append(line.rstrip())
                line = ""
            pieces = _split_long_token(
                unit.lstrip(),
                maximum_width_mm=maximum,
                font_size_pt=font_size_pt,
                font_family=font_family,
                font_weight=font_weight,
            )
            output.extend(pieces[:-1])
            line = pieces[-1] + (" " if unit[-1:].isspace() else "")
        output.append(line.rstrip())
    return tuple(output or ("",))


def layout_text_box(
    text: str,
    *,
    x_mm: float,
    y_mm: float,
    width_mm: float,
    height_mm: float,
    font_size_pt: float,
    font_family: str | Iterable[str] = "DejaVu Sans, Arial, sans-serif",
    font_weight: int = 400,
    minimum_font_pt: float = DEFAULT_MINIMUM_FONT_PT,
    line_height: float = DEFAULT_LINE_HEIGHT,
    horizontal_align: str = "start",
    vertical_align: str = "middle",
) -> TextLayout:
    """Lay out wrapped text inside an explicit millimetre rectangle.

    The function never scales glyphs.  It raises an actionable error if the
    requested text cannot fit at or above the configured minimum font size.
    """

    size = float(font_size_pt)
    minimum = float(minimum_font_pt)
    width = float(width_mm)
    height = float(height_mm)
    if size + 1e-9 < minimum:
        raise TextLayoutError(f"Text requests {size:g} pt, below the required minimum of {minimum:g} pt")
    if width <= 0 or height <= 0:
        raise TextLayoutError("Text layout requires a positive width and height")
    if horizontal_align not in {"start", "middle", "end"}:
        raise TextLayoutError(f"Unsupported horizontal text alignment {horizontal_align!r}")
    if vertical_align not in {"top", "middle", "bottom"}:
        raise TextLayoutError(f"Unsupported vertical text alignment {vertical_align!r}")
    if line_height < 1.0:
        raise TextLayoutError("Text line height must be at least 1.0")
    lines = wrap_text(
        str(text),
        maximum_width_mm=width,
        font_size_pt=size,
        font_family=font_family,
        font_weight=font_weight,
    )
    line_height_mm = pt_to_mm(size * line_height)
    text_height = len(lines) * line_height_mm
    if text_height > height + 1e-9:
        raise TextLayoutError(
            f"Text needs {text_height:.3f} mm ({len(lines)} lines at {size:g} pt) but its lane is only {height:.3f} mm high; "
            "increase the lane or page, shorten the visible label, or move the full name to a legend"
        )
    if vertical_align == "top":
        top = float(y_mm)
    elif vertical_align == "bottom":
        top = float(y_mm) + height - text_height
    else:
        top = float(y_mm) + (height - text_height) / 2.0
    em_mm = pt_to_mm(size)
    baseline_offset = (line_height_mm - em_mm) / 2.0 + em_mm * 0.8
    laid_out: list[TextLine] = []
    measured_widths: list[float] = []
    for index, line in enumerate(lines):
        measurement = measure_text_line(
            line,
            font_size_pt=size,
            font_family=font_family,
            font_weight=font_weight,
        )
        measured_widths.append(measurement.width_mm)
        if horizontal_align == "start":
            x = float(x_mm)
        elif horizontal_align == "end":
            x = float(x_mm) + width
        else:
            x = float(x_mm) + width / 2.0
        laid_out.append(TextLine(line, x, top + index * line_height_mm + baseline_offset, measurement.width_mm))
    font = resolve_font_fallback(str(text), font_family)
    return TextLayout(
        tuple(laid_out),
        float(x_mm),
        top,
        max(measured_widths, default=0.0),
        text_height,
        size,
        size * line_height,
        horizontal_align,
        vertical_align,
        font,
    )


def abbreviated_label(value: str, *, maximum_characters: int = 28) -> tuple[str, str | None]:
    """Return a short visible label and, when changed, its full legend name."""

    text = re.sub(r"\s+", " ", str(value)).strip()
    if len(text) <= maximum_characters:
        return text, None
    words = text.split(" ")
    if len(words) > 1:
        acronym = "".join(word[0].upper() for word in words if word)
        if 2 <= len(acronym) <= maximum_characters:
            return acronym, text
    suffix = "…"
    return text[: max(1, maximum_characters - len(suffix))].rstrip() + suffix, text


__all__ = [
    "DEFAULT_LINE_HEIGHT",
    "DEFAULT_MINIMUM_FONT_PT",
    "METRIC_SAFETY_FACTOR",
    "FontFallbackRecord",
    "TextLayout",
    "TextLayoutError",
    "TextLine",
    "TextMeasurement",
    "abbreviated_label",
    "layout_text_box",
    "measure_text_line",
    "resolve_font_fallback",
    "wrap_text",
]
