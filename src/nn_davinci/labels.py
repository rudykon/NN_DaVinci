"""Deterministic node-label content shared by vector renderers."""

from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from .ir import Node


LABEL_DENSITIES = {"compact", "paper", "detailed"}


@lru_cache(maxsize=64)
def _measurement_font(font_family: str, pixel_size: int):
    """Load the same deterministic local font used by publication examples.

    Pillow is already part of the verified export environment.  Keeping the
    import lazy preserves the dependency boundary for users who only consume
    Graph IR without rendering figures.
    """
    try:
        from PIL import ImageFont
    except ImportError:  # pragma: no cover - the minimal, non-export install
        return None
    candidates: list[str] = []
    lowered = font_family.lower()
    if "serif" in lowered and "sans" not in lowered:
        candidates.extend(("DejaVuSerif.ttf", "LiberationSerif-Regular.ttf"))
    else:
        candidates.extend(("DejaVuSans.ttf", "LiberationSans-Regular.ttf"))
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, max(1, pixel_size))
        except OSError:
            continue
    return ImageFont.load_default()


def measure_text_width(text: str, font_size: float, font_family: str = "DejaVu Sans") -> float:
    """Return a real glyph advance in SVG px with a deterministic fallback."""
    if not text:
        return 0.0
    rounded_size = max(1, int(round(font_size * 4)))
    font = _measurement_font(font_family, rounded_size)
    if font is None:
        return len(text) * float(font_size) * 0.58
    try:
        advance = float(font.getlength(text))
    except AttributeError:  # pragma: no cover - compatibility with old Pillow
        box = font.getbbox(text)
        advance = float(box[2] - box[0])
    return advance / 4.0


@dataclass(frozen=True, slots=True)
class LabelLine:
    role: str
    text: str
    font_scale: float = 1.0
    mandatory: bool = True


def _human_count(value: int | float | None) -> str:
    if value is None:
        return "?"
    number = float(value)
    for unit in ("", "K", "M", "G", "T"):
        if abs(number) < 1000:
            return f"{number:.3g}{unit}"
        number /= 1000
    return f"{number:.3g}P"


def format_count(value: int | float | None, mode: str) -> str:
    if value is None:
        return "?"
    if mode == "raw":
        return f"{value:,}"
    if mode == "scientific":
        return f"{float(value):.3e}"
    return _human_count(value)


def shape_label(node: Node, theme: dict[str, Any]) -> str:
    specs = [port.tensor for port in node.outputs if port.tensor and port.tensor.shape]
    if not specs:
        specs = [port.tensor for port in node.inputs if port.tensor and port.tensor.shape]
    if not specs:
        return ""
    value = str(theme.get("shape_separator", " × ")).join(
        "?" if item is None else str(item) for item in specs[0].shape
    )
    return f"[{value}]" if theme.get("shape_brackets") else value


def _analysis_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.5g}"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value)


def _wrap(
    line: LabelLine,
    *,
    max_width: float,
    font_size: float,
    font_family: str,
) -> list[LabelLine]:
    line_size = font_size * line.font_scale
    if measure_text_width(line.text, line_size, font_family) <= max_width:
        return [line]
    # Use textwrap only to identify pleasant word boundaries, then enforce the
    # physical width using the actual glyph advances.  Long framework paths
    # still split deterministically when no natural boundary is available.
    words = textwrap.wrap(line.text, width=max(5, len(line.text)), break_long_words=False)
    source_words = words[0].split() if words else [line.text]
    pieces: list[str] = []
    current = ""
    for word in source_words:
        candidate = f"{current} {word}".strip()
        if current and measure_text_width(candidate, line_size, font_family) > max_width:
            pieces.append(current)
            current = word
        else:
            current = candidate
    if current:
        pieces.append(current)
    fitted: list[str] = []
    for piece in pieces or [line.text]:
        remainder = piece
        while measure_text_width(remainder, line_size, font_family) > max_width and len(remainder) > 1:
            low, high = 1, len(remainder)
            while low < high:
                middle = (low + high + 1) // 2
                if measure_text_width(remainder[:middle], line_size, font_family) <= max_width:
                    low = middle
                else:
                    high = middle - 1
            fitted.append(remainder[:max(1, low)])
            remainder = remainder[max(1, low):]
        if remainder:
            fitted.append(remainder)
    pieces = fitted
    return [LabelLine(line.role, piece, line.font_scale, line.mandatory) for piece in pieces]


def node_label_lines(
    node: Node,
    theme: dict[str, Any],
    *,
    density: str = "paper",
    show_shapes: bool = True,
    show_parameters: bool = True,
    show_flops: bool = True,
    max_width: float | None = None,
) -> list[LabelLine]:
    if density not in LABEL_DENSITIES:
        raise ValueError(f"Unknown label density {density!r}; choose compact, paper, or detailed")
    lines = [LabelLine("name", node.name, 1.0), LabelLine("op-type", node.op_type, 0.84)]
    if density != "compact":
        shape = shape_label(node, theme)
        if show_shapes and shape:
            lines.append(LabelLine("shape", f"S {shape}", 0.84))
        if show_parameters and node.parameters:
            lines.append(
                LabelLine("parameters", f"P {format_count(node.parameters, str(theme.get('parameter_format', 'human')))}", 0.84)
            )
        if show_flops and node.analysis.get("flops") is not None:
            lines.append(
                LabelLine("flops", f"F {format_count(node.analysis['flops'], str(theme.get('flops_format', 'human')))}", 0.84)
            )
    if density == "detailed":
        bias = node.attributes.get("bias", node.attributes.get("bias_count"))
        if bias is not None:
            value = format_count(bias, str(theme.get("parameter_format", "human"))) if isinstance(bias, (int, float)) else bias
            lines.append(LabelLine("bias", f"bias: {value}", 0.78))
        for key, value in sorted(node.analysis.items()):
            if key != "flops":
                lines.append(LabelLine(f"analysis-{key}", f"{key}: {_analysis_value(value)}", 0.78))
    if max_width is None:
        return lines
    result: list[LabelLine] = []
    base_font = max(10.0, float(theme["font_size"]))
    font_family = str(theme.get("font_family", "DejaVu Sans"))
    for line in lines:
        result.extend(_wrap(line, max_width=max_width, font_size=base_font, font_family=font_family))
    return result


def required_label_text(node: Node, theme: dict[str, Any], *, density: str = "paper") -> list[str]:
    return [line.text for line in node_label_lines(node, theme, density=density) if line.mandatory]


__all__ = ["LABEL_DENSITIES", "LabelLine", "format_count", "measure_text_width", "node_label_lines", "required_label_text", "shape_label"]
