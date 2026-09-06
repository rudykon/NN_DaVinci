"""Small, deterministic, editable scientific-formula normalization.

This is intentionally not a TeX executor.  It accepts a documented safe
subset and converts it to Unicode text that remains editable in SVG, TikZ,
PPTX, HTML and project sources.  Unsupported or malformed input is retained
verbatim with an explicit invalid-formula record.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any


FORMULA_SYNTAX_VERSION = "nndv-formula-1"
MAXIMUM_FORMULA_CHARACTERS = 4_096
MAXIMUM_GROUP_DEPTH = 16
MAXIMUM_MATRIX_CELLS = 256


GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "varepsilon": "ϵ", "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "ϑ",
    "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ",
    "pi": "π", "varpi": "ϖ", "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ",
    "phi": "φ", "varphi": "ϕ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ",
    "Pi": "Π", "Sigma": "Σ", "Upsilon": "Υ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
}

OPERATORS = {
    "times": "×", "cdot": "·", "pm": "±", "mp": "∓", "le": "≤", "leq": "≤",
    "ge": "≥", "geq": "≥", "ne": "≠", "neq": "≠", "approx": "≈", "sim": "∼",
    "to": "→", "rightarrow": "→", "leftarrow": "←", "leftrightarrow": "↔",
    "infty": "∞", "sum": "∑", "prod": "∏", "int": "∫", "partial": "∂", "nabla": "∇",
    "in": "∈", "notin": "∉", "subset": "⊂", "subseteq": "⊆", "cup": "∪", "cap": "∩",
    "forall": "∀", "exists": "∃", "neg": "¬", "land": "∧", "lor": "∨",
    "ell": "ℓ", "Re": "ℜ", "Im": "ℑ", "mathbb{R}": "ℝ", "mathbb{N}": "ℕ",
}

SUPERSCRIPT = str.maketrans("0123456789+-=()nijkT", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾nⁱʲᵏᵀ")
SUBSCRIPT = str.maketrans("0123456789+-=()aeoxhklmnpstijr", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₒₓₕₖₗₘₙₚₛₜᵢⱼᵣ")


class FormulaSyntaxError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FormulaResult:
    source: str
    text: str
    lines: tuple[str, ...]
    valid: bool
    fallback: bool
    error: str = ""
    syntax_version: str = FORMULA_SYNTAX_VERSION
    features: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _balanced(value: str) -> None:
    depth = 0
    escaped = False
    for character in value:
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if character == "{":
            depth += 1
            if depth > MAXIMUM_GROUP_DEPTH:
                raise FormulaSyntaxError(f"formula group depth exceeds {MAXIMUM_GROUP_DEPTH}")
        elif character == "}":
            depth -= 1
            if depth < 0:
                raise FormulaSyntaxError("formula contains an unmatched closing brace")
    if depth:
        raise FormulaSyntaxError("formula contains an unmatched opening brace")


def _extract_group(value: str, start: int) -> tuple[str, int]:
    if start >= len(value):
        raise FormulaSyntaxError("formula script or command is missing an argument")
    if value[start] != "{":
        if value[start] == "\\":
            match = re.match(r"\\[A-Za-z]+", value[start:])
            if not match:
                return value[start], start + 1
            return match.group(0), start + len(match.group(0))
        return value[start], start + 1
    depth = 1
    index = start + 1
    while index < len(value) and depth:
        if value[index] == "{":
            depth += 1
        elif value[index] == "}":
            depth -= 1
        index += 1
    if depth:
        raise FormulaSyntaxError("formula command has an unterminated group")
    return value[start + 1 : index - 1], index


def _matrix(match: re.Match[str], features: set[str]) -> str:
    environment = match.group(1)
    body = match.group(2)
    rows = [row.strip() for row in re.split(r"\\\\", body)]
    cells = [[cell.strip() for cell in row.split("&")] for row in rows]
    if not cells or any(not row for row in cells):
        raise FormulaSyntaxError("matrix must contain at least one cell per row")
    columns = len(cells[0])
    if any(len(row) != columns for row in cells):
        raise FormulaSyntaxError("matrix rows must contain the same number of cells")
    if len(cells) * columns > MAXIMUM_MATRIX_CELLS:
        raise FormulaSyntaxError(f"matrix exceeds {MAXIMUM_MATRIX_CELLS} cells")
    features.add("matrix")
    rendered = [[_normalize(cell, features) for cell in row] for row in cells]
    widths = [max(len(row[index]) for row in rendered) for index in range(columns)]
    inner = ["  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)) for row in rendered]
    if environment in {"pmatrix", "matrix"}:
        left, right = "(", ")"
    elif environment == "vmatrix":
        left = right = "|"
    else:
        left, right = "[", "]"
    return "\n".join(f"{left}{row}{right}" for row in inner)


def _normalize(value: str, features: set[str]) -> str:
    matrix_pattern = re.compile(r"\\begin\{(matrix|bmatrix|pmatrix|vmatrix)\}(.*?)\\end\{\1\}", re.DOTALL)
    while matrix_pattern.search(value):
        value = matrix_pattern.sub(lambda match: _matrix(match, features), value, count=1)

    fraction = re.compile(r"\\frac\{([^{}]*)\}\{([^{}]*)\}")
    while fraction.search(value):
        features.add("fraction")
        value = fraction.sub(lambda match: f"({_normalize(match.group(1), features)})/({_normalize(match.group(2), features)})", value)
    if "\\frac" in value:
        raise FormulaSyntaxError("nested or malformed fraction is outside the safe formula subset")

    square_root = re.compile(r"\\sqrt\{([^{}]*)\}")
    while square_root.search(value):
        features.add("root")
        value = square_root.sub(lambda match: f"√({_normalize(match.group(1), features)})", value)
    if "\\sqrt" in value:
        raise FormulaSyntaxError("nested or malformed root is outside the safe formula subset")

    def replace_command(match: re.Match[str]) -> str:
        command = match.group(1)
        if command in GREEK:
            features.add("greek")
            return GREEK[command]
        if command in OPERATORS:
            features.add("operator")
            return OPERATORS[command]
        if command in {",", ";", "quad", "qquad"}:
            return " " if command in {",", ";"} else ("  " if command == "quad" else "    ")
        if command in {"mathrm", "mathbf", "mathit", "text"}:
            return ""  # braces remain and are removed below; styling stays editable plain text.
        raise FormulaSyntaxError(f"unsupported formula command \\{command}")

    value = re.sub(r"\\([A-Za-z]+|[,;])", replace_command, value)
    output: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character not in "_^":
            output.append(character)
            index += 1
            continue
        argument, index = _extract_group(value, index + 1)
        argument = _normalize(argument, features)
        table = SUBSCRIPT if character == "_" else SUPERSCRIPT
        converted = argument.translate(table)
        if any(symbol == original for symbol, original in zip(converted, argument) if original.isalnum()):
            # Keep an explicit readable script when Unicode has no safe glyph.
            converted = f"{'_' if character == '_' else '^'}({argument})"
        else:
            features.add("subscript" if character == "_" else "superscript")
        output.append(converted)
    normalized = "".join(output).replace("{", "").replace("}", "")
    return re.sub(r"[ \t]+", " ", normalized).strip()


def normalize_formula(source: str) -> FormulaResult:
    """Normalize the safe formula subset, retaining invalid input verbatim."""

    raw = str(source)
    try:
        if len(raw) > MAXIMUM_FORMULA_CHARACTERS:
            raise FormulaSyntaxError(f"formula exceeds {MAXIMUM_FORMULA_CHARACTERS} characters")
        if not raw.strip():
            raise FormulaSyntaxError("formula is empty")
        if any(character in raw for character in ("\x00", "\u2028", "\u2029")):
            raise FormulaSyntaxError("formula contains an unsupported control character")
        _balanced(raw)
        features: set[str] = set()
        normalized = _normalize(raw, features)
        if not normalized:
            raise FormulaSyntaxError("formula produced no visible editable text")
        return FormulaResult(raw, normalized, tuple(normalized.splitlines()), True, False, features=tuple(sorted(features)))
    except FormulaSyntaxError as exc:
        fallback = f"Invalid formula: {raw}"
        return FormulaResult(raw, fallback, tuple(fallback.splitlines()), False, True, str(exc), features=("invalid-fallback",))


__all__ = [
    "FORMULA_SYNTAX_VERSION",
    "FormulaResult",
    "FormulaSyntaxError",
    "normalize_formula",
]
