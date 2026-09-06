from __future__ import annotations

from copy import deepcopy
from typing import Any

BASE = {
    "font_family": "Inter, Arial, sans-serif",
    "font_size": 12,
    "font_weight": 600,
    "title_size": 16,
    "minimum_font_pt": 7,
    "node_width": 154,
    "node_height": 66,
    "node_radius": 8,
    "node_padding": 10,
    "node_opacity": 1.0,
    "stroke_width": 1.4,
    "edge_width": 1.45,
    "edge_arrow": "end",
    "edge_dash": "",
    "parameter_format": "human",
    "flops_format": "human",
    "shape_separator": " × ",
    "shape_brackets": False,
    "background": "#ffffff",
    "foreground": "#172033",
    "muted": "#657085",
    "border": "#334155",
    "edge": "#64748b",
    "accent": "#2563eb",
    "node_fill": "#f8fafc",
    "group_fill": "#f1f5f9",
    "selection": "#f59e0b",
    "category_colors": {
        "input": "#dbeafe", "output": "#dcfce7", "convolution": "#dbeafe",
        "attention": "#f3e8ff", "normalization": "#fef3c7", "activation": "#fee2e2",
        "pooling": "#cffafe", "merge": "#fce7f3", "linear": "#dcfce7",
        "embedding": "#ede9fe", "routing": "#ffedd5", "operation": "#f8fafc",
    },
    "page": {"width": 960, "height": 540, "margin": 34},
}

THEMES: dict[str, dict[str, Any]] = {
    "neurips": BASE,
    "ieee": {
        **BASE, "font_family": "Times New Roman, Times, serif", "font_size": 11,
        "accent": "#1d4ed8", "stroke_width": 1.2, "node_radius": 2,
    },
    "acm": {
        **BASE, "font_family": "Linux Libertine, Georgia, serif", "font_size": 11,
        "accent": "#006d77", "node_radius": 3,
    },
    "grayscale": {
        **BASE, "accent": "#111827", "node_fill": "#f3f4f6", "group_fill": "#e5e7eb",
        "category_colors": {key: value for key, value in {
            "input": "#fafafa", "output": "#d4d4d4", "convolution": "#e5e5e5",
            "attention": "#d4d4d4", "normalization": "#f5f5f5", "activation": "#e5e5e5",
            "pooling": "#d4d4d4", "merge": "#a3a3a3", "linear": "#e5e5e5",
            "embedding": "#d4d4d4", "routing": "#a3a3a3", "operation": "#fafafa",
        }.items()},
    },
    "colorblind": {
        **BASE, "accent": "#0072B2",
        "category_colors": {
            "input": "#b9e4f6", "output": "#b8e3d5", "convolution": "#f7d7a1",
            "attention": "#e8b8d5", "normalization": "#fff3a6", "activation": "#f3b8a8",
            "pooling": "#b5d8ec", "merge": "#e8b8d5", "linear": "#b8e3d5",
            "embedding": "#b9e4f6", "routing": "#f7d7a1", "operation": "#f8fafc",
        },
    },
    "dark": {
        **BASE, "background": "#0b1020", "foreground": "#f1f5f9", "muted": "#a8b3c7",
        "border": "#94a3b8", "edge": "#94a3b8", "accent": "#60a5fa",
        "node_fill": "#172033", "group_fill": "#111827",
    },
    "teaching": {
        **BASE, "font_size": 15, "title_size": 22, "node_width": 178,
        "node_height": 78, "stroke_width": 2, "edge_width": 2.2,
    },
}

PAGE_PRESETS = {
    "single-column": {"width": 420, "height": 620, "margin": 24},
    "double-column": {"width": 840, "height": 620, "margin": 28},
    "widescreen": {"width": 1280, "height": 720, "margin": 42},
    "slide": {"width": 1280, "height": 720, "margin": 42},
    "wide-two-column": {"width": 1020, "height": 620, "margin": 30},
    "multi-panel": {"width": 1020, "height": 760, "margin": 32},
    "fit-content": {"width": None, "height": None, "margin": 34},
    "auto": {"width": 960, "height": 540, "margin": 34},
}


def get_theme(name: str = "neurips", overrides: dict[str, Any] | None = None, page: str | None = None) -> dict[str, Any]:
    if name not in THEMES:
        raise KeyError(f"Unknown theme {name!r}; available: {', '.join(sorted(THEMES))}")
    result = deepcopy(THEMES[name])
    if page:
        result["page"] = deepcopy(PAGE_PRESETS[page])
        result["page_preset"] = page
    for key, value in (overrides or {}).items():
        if key == "category_colors":
            result[key].update(value)
        elif key == "page":
            result[key].update(value)
        else:
            result[key] = value
    return result


def register_theme(name: str, theme: dict[str, Any], *, replace: bool = False) -> None:
    if name in THEMES and not replace:
        raise ValueError(f"Theme {name!r} is already registered")
    merged = deepcopy(BASE)
    for key, value in theme.items():
        if key == "category_colors":
            merged[key].update(value)
        elif key == "page":
            merged[key].update(value)
        else:
            merged[key] = value
    THEMES[name] = merged
