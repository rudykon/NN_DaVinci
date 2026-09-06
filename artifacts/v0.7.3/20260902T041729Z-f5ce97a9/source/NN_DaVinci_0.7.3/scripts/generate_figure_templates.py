#!/usr/bin/env python3
"""Regenerate the two auditable copies of bundled Figure Studio templates."""

from __future__ import annotations

import json
from pathlib import Path

from nn_davinci.figure_export import figure_proof
from nn_davinci.figure_templates import TEMPLATE_SPECS, instantiate_template, materialize_templates


ROOT = Path(__file__).parents[1]


def main() -> None:
    outputs = materialize_templates(
        ROOT / "templates" / "figure_studio",
        ROOT / "src" / "nn_davinci" / "figure_templates",
    )
    proofs = {}
    for spec in TEMPLATE_SPECS:
        _, figure = instantiate_template(spec.slug)
        proofs[spec.slug] = figure_proof(figure)
    print(json.dumps({"templates": len(TEMPLATE_SPECS), "files": len(outputs), "proofs": proofs}, sort_keys=True))


if __name__ == "__main__":
    main()
