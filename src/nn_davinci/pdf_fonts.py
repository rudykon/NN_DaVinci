"""Packaged, dependency-free TrueType support for native Scene PDFs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
from typing import Iterable

from .errors import ExportError


SCENE_PDF_FONT_DIRECTORY = Path(__file__).resolve().parent / "assets" / "fonts"
SCENE_PDF_FONT_FILES = (
    ("NotoSans", "NotoSans-Regular.ttf", "licenses/Noto-OFL-1.1.txt"),
    ("DroidSansFallback", "DroidSansFallbackFull.ttf", "licenses/Droid-Apache-2.0.txt"),
    ("NotoSansMath", "NotoSansMath-Regular.ttf", "licenses/Noto-OFL-1.1.txt"),
)


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from(">H", data, offset)[0]


def _i16(data: bytes, offset: int) -> int:
    return struct.unpack_from(">h", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


@dataclass(frozen=True, slots=True)
class EmbeddedTrueTypeFont:
    resource_name: str
    postscript_name: str
    data: bytes
    cmap: dict[int, int]
    advances: tuple[int, ...]
    units_per_em: int
    ascent: int
    descent: int
    bbox: tuple[int, int, int, int]

    def glyph(self, character: str) -> int | None:
        return self.cmap.get(ord(character))

    def width_1000(self, glyph_id: int) -> int:
        width = self.advances[min(glyph_id, len(self.advances) - 1)]
        return max(1, round(width * 1000 / self.units_per_em))

    def metric_1000(self, value: int) -> int:
        return round(value * 1000 / self.units_per_em)


def _tables(data: bytes) -> dict[str, tuple[int, int]]:
    if len(data) < 12:
        raise ExportError("Packaged Scene PDF font is truncated before its TrueType table directory")
    number = _u16(data, 4)
    result: dict[str, tuple[int, int]] = {}
    for index in range(number):
        record = 12 + index * 16
        if record + 16 > len(data):
            raise ExportError("Packaged Scene PDF font has a truncated TrueType table record")
        tag = data[record : record + 4].decode("latin-1")
        offset, length = _u32(data, record + 8), _u32(data, record + 12)
        if offset + length > len(data):
            raise ExportError(f"Packaged Scene PDF font table {tag!r} exceeds the file boundary")
        result[tag] = (offset, length)
    required = {"cmap", "head", "hhea", "hmtx", "maxp"}
    missing = sorted(required - set(result))
    if missing:
        raise ExportError(f"Packaged Scene PDF font lacks required TrueType tables {missing!r}")
    return result


def _format12(data: bytes, offset: int) -> dict[int, int]:
    groups = _u32(data, offset + 12)
    result: dict[int, int] = {}
    for index in range(groups):
        item = offset + 16 + index * 12
        start, end, glyph = _u32(data, item), _u32(data, item + 4), _u32(data, item + 8)
        for codepoint in range(start, end + 1):
            result[codepoint] = glyph + codepoint - start
    return result


def _format4(data: bytes, offset: int) -> dict[int, int]:
    segment_count = _u16(data, offset + 6) // 2
    end_codes = offset + 14
    start_codes = end_codes + segment_count * 2 + 2
    deltas = start_codes + segment_count * 2
    ranges = deltas + segment_count * 2
    result: dict[int, int] = {}
    for index in range(segment_count):
        start = _u16(data, start_codes + index * 2)
        end = _u16(data, end_codes + index * 2)
        delta = _i16(data, deltas + index * 2)
        range_offset = _u16(data, ranges + index * 2)
        if start == 0xFFFF:
            continue
        for codepoint in range(start, end + 1):
            if range_offset:
                glyph_offset = ranges + index * 2 + range_offset + (codepoint - start) * 2
                if glyph_offset + 2 > len(data):
                    continue
                glyph = _u16(data, glyph_offset)
                if glyph:
                    glyph = (glyph + delta) & 0xFFFF
            else:
                glyph = (codepoint + delta) & 0xFFFF
            if glyph:
                result[codepoint] = glyph
    return result


def _cmap(data: bytes, table: tuple[int, int]) -> dict[int, int]:
    offset, _length = table
    records = _u16(data, offset + 2)
    candidates: list[tuple[int, int, int]] = []
    for index in range(records):
        item = offset + 4 + index * 8
        platform, encoding = _u16(data, item), _u16(data, item + 2)
        subtable = offset + _u32(data, item + 4)
        if subtable + 2 > len(data):
            continue
        format_number = _u16(data, subtable)
        priority = (
            0 if format_number == 12 and platform == 3 and encoding == 10
            else 1 if format_number == 12
            else 2 if format_number == 4 and platform in {0, 3}
            else 99
        )
        candidates.append((priority, format_number, subtable))
    for _priority, format_number, subtable in sorted(candidates):
        if format_number == 12:
            return _format12(data, subtable)
        if format_number == 4:
            return _format4(data, subtable)
    raise ExportError("Packaged Scene PDF font has no supported Unicode cmap format (4 or 12)")


def _advances(data: bytes, tables: dict[str, tuple[int, int]]) -> tuple[int, ...]:
    hhea, _ = tables["hhea"]
    maxp, _ = tables["maxp"]
    hmtx, _ = tables["hmtx"]
    metrics = _u16(data, hhea + 34)
    glyphs = _u16(data, maxp + 4)
    if metrics < 1 or glyphs < 1 or metrics > glyphs:
        raise ExportError("Packaged Scene PDF font declares invalid horizontal metrics")
    widths = [_u16(data, hmtx + index * 4) for index in range(metrics)]
    widths.extend([widths[-1]] * (glyphs - metrics))
    return tuple(widths)


def _load_font(resource_name: str, file_name: str, license_name: str) -> EmbeddedTrueTypeFont:
    path = SCENE_PDF_FONT_DIRECTORY / file_name
    license_path = SCENE_PDF_FONT_DIRECTORY / license_name
    if not path.is_file():
        raise ExportError(
            f"Required embedded Scene PDF font resource is missing: {path}. Reinstall NN_DaVinci with package data."
        )
    if not license_path.is_file():
        raise ExportError(
            f"Required redistribution license for Scene PDF font {file_name!r} is missing: {license_path}."
        )
    data = path.read_bytes()
    tables = _tables(data)
    head, _ = tables["head"]
    hhea, _ = tables["hhea"]
    units = _u16(data, head + 18)
    if not units:
        raise ExportError(f"Packaged Scene PDF font {file_name!r} has unitsPerEm=0")
    return EmbeddedTrueTypeFont(
        resource_name=resource_name,
        postscript_name=file_name.rsplit(".", 1)[0].replace(" ", ""),
        data=data,
        cmap=_cmap(data, tables["cmap"]),
        advances=_advances(data, tables),
        units_per_em=units,
        ascent=_i16(data, hhea + 4),
        descent=_i16(data, hhea + 6),
        bbox=tuple(_i16(data, head + 36 + index * 2) for index in range(4)),  # type: ignore[arg-type]
    )


def load_scene_pdf_fonts() -> tuple[EmbeddedTrueTypeFont, ...]:
    """Load only packaged font resources; system-font fallback is forbidden."""

    return tuple(_load_font(*record) for record in SCENE_PDF_FONT_FILES)


def select_font_runs(
    text: str,
    fonts: Iterable[EmbeddedTrueTypeFont],
) -> list[tuple[EmbeddedTrueTypeFont, list[int], str]]:
    available = tuple(fonts)
    runs: list[tuple[EmbeddedTrueTypeFont, list[int], str]] = []
    for character in text:
        selected = next((font for font in available if font.glyph(character) is not None), None)
        if selected is None:
            raise ExportError(
                f"Scene PDF label contains unsupported Unicode character U+{ord(character):04X} {character!r}; "
                "the packaged Noto/Droid fonts cannot represent it and no unembedded fallback is allowed."
            )
        glyph = selected.glyph(character)
        assert glyph is not None
        if runs and runs[-1][0] is selected:
            runs[-1][1].append(glyph)
            runs[-1] = (runs[-1][0], runs[-1][1], runs[-1][2] + character)
        else:
            runs.append((selected, [glyph], character))
    return runs


__all__ = [
    "EmbeddedTrueTypeFont",
    "SCENE_PDF_FONT_DIRECTORY",
    "SCENE_PDF_FONT_FILES",
    "load_scene_pdf_fonts",
    "select_font_runs",
]
