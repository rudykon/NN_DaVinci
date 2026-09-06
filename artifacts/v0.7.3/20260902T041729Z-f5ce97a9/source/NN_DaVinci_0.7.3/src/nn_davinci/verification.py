"""Release-verification arithmetic shared by scripts and regression tests.

This module deliberately treats line, branch, and combined coverage as three
different fractions.  coverage.py's ``percent_covered`` is the combined value;
it is never accepted as a branch-coverage measurement here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from fractions import Fraction
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class CoverageFraction:
    covered: int
    total: int

    @property
    def fraction(self) -> Fraction:
        return Fraction(self.covered, self.total) if self.total else Fraction(1, 1)

    @property
    def percent(self) -> float:
        return float(self.fraction * 100)

    def to_dict(self) -> dict[str, int | float]:
        return {**asdict(self), "fraction": float(self.fraction), "percent": self.percent}


@dataclass(frozen=True, slots=True)
class CoverageSummary:
    line: CoverageFraction
    branch: CoverageFraction
    combined: CoverageFraction

    def to_dict(self) -> dict[str, dict[str, int | float]]:
        return {
            "line": self.line.to_dict(),
            "branch": self.branch.to_dict(),
            "combined": self.combined.to_dict(),
        }


def summarize_coverage_totals(totals: Mapping[str, Any]) -> CoverageSummary:
    """Build exact fractions from a coverage.py JSON ``totals`` mapping."""
    covered_lines = int(totals["covered_lines"])
    statements = int(totals["num_statements"])
    covered_branches = int(totals.get("covered_branches", 0))
    branches = int(totals.get("num_branches", 0))
    return CoverageSummary(
        line=CoverageFraction(covered_lines, statements),
        branch=CoverageFraction(covered_branches, branches),
        combined=CoverageFraction(covered_lines + covered_branches, statements + branches),
    )


def meets_coverage_thresholds(
    summary: CoverageSummary,
    *,
    minimum_line: Fraction,
    minimum_branch: Fraction,
) -> bool:
    """Compare exact, unrounded fractions against release thresholds."""
    return summary.line.fraction >= minimum_line and summary.branch.fraction >= minimum_branch


def format_coverage(name: str, summary: CoverageSummary) -> str:
    """Return an unambiguous human-readable coverage record."""
    return " ".join(
        [
            name,
            f"line={summary.line.covered}/{summary.line.total}={summary.line.percent:.2f}%",
            f"branch={summary.branch.covered}/{summary.branch.total}={summary.branch.percent:.2f}%",
            f"combined={summary.combined.covered}/{summary.combined.total}={summary.combined.percent:.2f}%",
        ]
    )


__all__ = [
    "CoverageFraction",
    "CoverageSummary",
    "format_coverage",
    "meets_coverage_thresholds",
    "summarize_coverage_totals",
]
