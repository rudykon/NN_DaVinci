#!/usr/bin/env python3
"""Create and inspect a fresh seven-format 0.6.1 submission package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from nn_davinci.figure_export import export_submission_package
from nn_davinci.figure_templates import instantiate_template
from nn_davinci.project import Project


RELEASE = "0.6.1 Beta — Publication Fidelity & Model-to-Figure Completion"
FORMAT_SUFFIXES = {".svg", ".pdf", ".tex", ".png", ".eps", ".pptx", ".html"}
SUPPORT_FILES = {
    "figure.nndv.json",
    "caption.md",
    "provenance.json",
    "proof.json",
    "export-policy.json",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    destination = args.output_dir.resolve()
    if destination.exists() and any(destination.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty submission package directory: {destination}")
    destination.mkdir(parents=True, exist_ok=True)

    graph, figure = instantiate_template("transformer-attention-ffn")
    project = Project(
        name=figure.name,
        graph=graph,
        model_source={"kind": "bundled-template", "key": "transformer-attention-ffn"},
        export={"formats": ["svg", "pdf", "tikz", "png", "eps", "pptx", "html"]},
        figure_ir=figure.to_dict(),
    ).to_dict()
    outputs = export_submission_package(
        figure,
        destination,
        project=project,
        caption="Editable Transformer attention and feed-forward architecture template.",
    )
    failures: list[str] = []
    names = {path.name for path in outputs}
    formats = {path.suffix.lower() for path in outputs if path.suffix.lower() in FORMAT_SUFFIXES}
    missing_support = sorted(SUPPORT_FILES - names)
    if formats != FORMAT_SUFFIXES:
        failures.append(f"submission formats are {sorted(formats)}, expected {sorted(FORMAT_SUFFIXES)}")
    if missing_support:
        failures.append(f"submission support files are missing: {missing_support}")
    for path in outputs:
        if not path.is_file() or path.stat().st_size == 0:
            failures.append(f"submission output is missing or empty: {path.name}")
    try:
        ET.parse(destination / "figure.svg")
    except (OSError, ET.ParseError) as exc:
        failures.append(f"submission SVG is invalid XML: {exc}")
    if not (destination / "figure.pdf").read_bytes().startswith(b"%PDF"):
        failures.append("submission PDF signature is invalid")
    if not (destination / "figure.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
        failures.append("submission PNG signature is invalid")
    if not (destination / "figure.eps").read_bytes().startswith(b"%!PS-Adobe-3.0 EPSF-3.0"):
        failures.append("submission EPS signature is invalid")
    try:
        with zipfile.ZipFile(destination / "figure.pptx") as archive:
            slide_xml = b"".join(
                archive.read(name)
                for name in archive.namelist()
                if name.startswith("ppt/slides/slide") and name.endswith(".xml")
            )
        if b"NNDV editable" not in slide_xml or b"<p:pic>" in slide_xml:
            failures.append("submission PPTX is not an editable vector document")
    except (OSError, zipfile.BadZipFile) as exc:
        failures.append(f"submission PPTX is invalid: {exc}")
    try:
        restored = Project.load(destination / "figure.nndv.json")
        if restored.graph.to_dict() != graph.to_dict() or restored.figure_ir != figure.to_dict():
            failures.append("submission .nndv.json does not round-trip its Graph/Figure evidence")
    except Exception as exc:
        failures.append(f"submission project cannot be restored: {type(exc).__name__}: {exc}")
    proof = json.loads((destination / "proof.json").read_text(encoding="utf-8"))
    if proof.get("final_output_verified") is not False or proof.get("release_blocker_eligible") is not False:
        failures.append("submission provisional proof is not explicitly separated from final-output verification")

    report = {
        "schema_version": "nndv-0.6.1-submission-package-validation-1",
        "release": RELEASE,
        "status": "PASS" if not failures else "FAIL",
        "formats": len(formats),
        "format_suffixes": sorted(formats),
        "support_files": len(SUPPORT_FILES & names),
        "output_files": len(outputs),
        "python_figure_proof_is_release_blocker": False,
        "strict_svg_oracle_required": True,
        "files": sorted(names),
        "failures": failures,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("NNDV_061_SUBMISSION=" + json.dumps({"status": report["status"], "formats": report["formats"], "files": report["output_files"]}, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
