from __future__ import annotations

from typing import Any


OPERATOR_TYPES: dict[str, dict[str, Any]] = {}


def register_operator_type(op_type: str, specification: dict[str, Any], *, replace: bool = False) -> None:
    """Register semantic defaults for a framework or domain-specific operator."""
    key = op_type.lower()
    if key in OPERATOR_TYPES and not replace:
        raise ValueError(f"Operator type {op_type!r} is already registered")
    if "category" not in specification:
        raise ValueError("Operator specification requires a semantic 'category'")
    OPERATOR_TYPES[key] = {"op_type": op_type, **specification}


def operator_specification(op_type: str) -> dict[str, Any] | None:
    return OPERATOR_TYPES.get(op_type.lower())


__all__ = ["OPERATOR_TYPES", "operator_specification", "register_operator_type"]
