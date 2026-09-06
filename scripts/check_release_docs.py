#!/usr/bin/env python3
"""Validate release documents against current machine-readable evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def fraction_text(item: dict) -> str:
    return f"{item['covered']}/{item['total']} = {item['percent']:.2f}%"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).parents[1]
    paths = [
        root / "README.md",
        root / "docs/ARCHITECTURE.md",
        root / "docs/REQUIREMENTS.md",
        root / "docs/COMPATIBILITY.md",
        root / "docs/ACCEPTANCE.md",
        root / "docs/VERIFICATION_REPORT_0.2.md",
        root / "docs/KNOWN_LIMITATIONS.md",
        root / "docs/RELEASE_NOTES_0.3.0.md",
        root / "docs/RELEASE_NOTES_0.4.0.md",
        root / "docs/RELEASE_NOTES_0.4.1.md",
        root / "docs/RELEASE_NOTES_0.4.2.md",
        root / "docs/RELEASE_NOTES_0.5.0.md",
        root / "docs/RELEASE_NOTES_0.5.1.md",
        root / "docs/RELEASE_NOTES_0.5.2.md",
        root / "docs/RESPONSIVE_TOOLBAR.md",
    ]
    documents = {str(path.relative_to(root)): path.read_text(encoding="utf-8") for path in paths}
    joined = "\n".join(documents.values())
    coverage = json.loads(args.coverage.read_text(encoding="utf-8"))
    failures = []
    current_release_docs = {
        "README.md",
        "docs/ARCHITECTURE.md",
        "docs/REQUIREMENTS.md",
        "docs/COMPATIBILITY.md",
        "docs/KNOWN_LIMITATIONS.md",
        "docs/RELEASE_NOTES_0.5.2.md",
        "docs/RESPONSIVE_TOOLBAR.md",
    }
    for name in current_release_docs:
        if "0.5.2" not in documents[name]:
            failures.append(f"{name}: missing release version")
    for scope in ("old_core", "expanded_core", "all_package"):
        for metric in ("line", "branch", "combined"):
            expected = fraction_text(coverage[scope][metric])
            if expected not in joined:
                failures.append(f"documentation missing current {scope} {metric}: {expected}")
    for expected in ("1736/1952 = 88.93%", "573/734 = 78.07%", "2309/2686 = 85.96%"):
        if expected not in joined:
            failures.append(f"historical correction missing: {expected}")
    readme = documents["README.md"]
    verification_report = documents["docs/VERIFICATION_REPORT_0.2.md"]
    if "--format svg,tikz" not in readme or ".[export]" not in readme or "envs/python-tools" not in readme:
        failures.append("README zero-install SVG/TikZ and explicit PDF dependency example incomplete")
    if "3D 视图" in joined or "3D view" in joined:
        failures.append("deprecated 3D product naming remains")
    if "Verification date:" in verification_report:
        failures.append("verification report hard-codes a run-local calendar date")
    if "sealed `verification.json` `started_utc`" not in verification_report or "`ended_utc`" not in verification_report:
        failures.append("verification report does not name sealed UTC timestamps as its time authority")
    for phrase in (
        "acceptance-matrix-0.2.3.json",
        "SHA256SUMS",
        "consumed-inputs.json",
        "--focus",
        "--summary",
        "full alias",
        "no Git repository",
        "pre_seal_audit",
        "release-decision.json",
        "Figure Composer",
        "50,000",
        "Plugin API 2.0",
        "schema 1.2",
        "artifacts/v0.5.2/<run_id>",
        "178 × 118 mm",
        "publication-quality",
        "SCIENTIFIC-FIDELITY",
        "130",
        "Trial Mode",
        "awaiting_participants",
        "NeurIPS/ICML/IEEE",
        "149",
        "Responsive Workspace",
        "Figure Composer（多 Panel）",
        "568×320",
        "320×568",
    ):
        if phrase not in joined:
            failures.append(f"release closure documentation missing phrase: {phrase}")
    report = {"documents": sorted(documents), "checks": 40, "failures": failures, "passed": not failures}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if failures:
        raise SystemExit("\n".join(failures))
    print(json.dumps({"documents": len(documents), "passed": True}, sort_keys=True))


if __name__ == "__main__":
    main()
