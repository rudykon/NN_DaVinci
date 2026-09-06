#!/usr/bin/env python3
"""Compile one NN_DaVinci PDF and TikZ figure in official venue styles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

from nn_davinci.composer import FigureComposer, FigurePanel
from nn_davinci.trial_models import import_external_model


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "verification" / "fixtures" / "venue-templates"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str], cwd: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, env=environment, text=True, capture_output=True, check=False)


def _tikz_body(source: Path) -> str:
    text = source.read_text(encoding="utf-8")
    start = text.index("\\definecolor")
    end = text.index("\\end{tikzpicture}") + len("\\end{tikzpicture}")
    return text[start:end] + "\n"


def _document(venue: str) -> str:
    common = r"""
\usepackage{graphicx}
\usepackage{xcolor}
\usepackage{tikz}
\usetikzlibrary{arrows.meta,positioning,fit,backgrounds}
"""
    figures = r"""
\begin{figure*}[t]
\centering
\includegraphics[width=88mm]{model-figure.pdf}
\caption{PDF export inserted at its final 88 mm publication width.}
\end{figure*}
\begin{figure*}[t]
\centering
\resizebox{88mm}{!}{\input{model-figure-body.tex}}
\caption{Editable TikZ export compiled by the venue template.}
\end{figure*}
\end{document}
"""
    if venue == "neurips2026":
        return (
            r"\documentclass{article}" + "\n" + r"\usepackage[main,final,nonatbib]{neurips_2026}" + common
            + r"\title{NN\_DaVinci Venue Proof}" + "\n" + r"\author{Anonymous local verification}" + "\n"
            + r"\begin{document}\maketitle\section{Editable figure proof}" + figures
        )
    if venue == "icml2026":
        return (
            r"\documentclass{article}" + "\n" + r"\usepackage[accepted]{icml2026}" + common
            + r"\icmltitlerunning{NN\_DaVinci Venue Proof}" + "\n" + r"\begin{document}" + "\n"
            + r"\twocolumn[\icmltitle{NN\_DaVinci Venue Proof}\begin{icmlauthorlist}\icmlauthor{Anonymous}{local}\end{icmlauthorlist}\icmlaffiliation{local}{Local verification}\vskip 0.3in]"
            + "\n" + r"\printAffiliationsAndNotice{}\section{Editable figure proof}" + figures
        )
    return (
        r"\documentclass[conference]{IEEEtran}" + common
        + r"\title{NN\_DaVinci Venue Proof}" + "\n" + r"\author{\IEEEauthorblockN{Anonymous local verification}}" + "\n"
        + r"\begin{document}\maketitle\section{Editable figure proof}" + figures
    )


def generate(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    source_root = output / "source-figure"
    source_root.mkdir(exist_ok=True)
    graph, _ = import_external_model("transformer_residual")
    composer = FigureComposer(
        title="Transformer residual evidence",
        panels=[FigurePanel("A", "Block and source paths", graph, semantic_level="block", semantic_view="paper")],
        arrangement="horizontal",
        page_preset="single-column",
        paper_ready_required=True,
    )
    _, _, proof = composer.compose()
    exports = composer.export(source_root / "model-figure.svg", formats=("pdf", "tikz"))
    pdf_source = next(path for path in exports if path.suffix == ".pdf")
    tikz_source = next(path for path in exports if path.suffix == ".tex")
    source_manifest = json.loads((TEMPLATES / "sources.json").read_text(encoding="utf-8"))
    report: dict[str, Any] = {
        "schema_version": "0.5.0-venue-proof-1",
        "measurement_source": "compiled-local-templates",
        "source_figure": {
            "case": "transformer_residual",
            "pdf_sha256": _sha256(pdf_source),
            "tikz_sha256": _sha256(tikz_source),
            "proof": proof,
        },
        "template_sources": source_manifest,
        "venues": {},
        "failures": [],
    }
    environment = dict(os.environ)
    environment["TEXMFVAR"] = str(output / "texmf-var")
    for venue in ("neurips2026", "icml2026", "ieee"):
        venue_root = output / venue
        venue_root.mkdir(exist_ok=True)
        shutil.copy2(pdf_source, venue_root / "model-figure.pdf")
        (venue_root / "model-figure-body.tex").write_text(_tikz_body(tikz_source), encoding="utf-8")
        if venue == "neurips2026":
            shutil.copy2(TEMPLATES / "neurips_2026.sty", venue_root / "neurips_2026.sty")
        elif venue == "icml2026":
            shutil.copy2(TEMPLATES / "icml2026.sty", venue_root / "icml2026.sty")
        tex = venue_root / "venue-proof.tex"
        tex.write_text(_document(venue), encoding="utf-8")
        first = _run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex.name], venue_root, environment)
        second = _run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex.name], venue_root, environment) if first.returncode == 0 else first
        pdf = venue_root / "venue-proof.pdf"
        info = _run(["pdfinfo", pdf.name], venue_root, environment) if pdf.is_file() else None
        fonts = _run(["pdffonts", pdf.name], venue_root, environment) if pdf.is_file() else None
        render = _run(["pdftoppm", "-png", "-r", "300", pdf.name, "venue-proof-300dpi"], venue_root, environment) if pdf.is_file() else None
        pngs = sorted(venue_root.glob("venue-proof-300dpi-*.png"))
        checks = {
            "latex_first_pass": first.returncode == 0,
            "latex_second_pass": second.returncode == 0,
            "compiled_pdf": pdf.is_file() and pdf.stat().st_size > 0,
            "pdf_export_inserted": "\\includegraphics[width=88mm]{model-figure.pdf}" in tex.read_text(encoding="utf-8"),
            "tikz_export_inserted": "\\input{model-figure-body.tex}" in tex.read_text(encoding="utf-8"),
            "pdfinfo_valid": bool(info and info.returncode == 0 and "Pages:" in info.stdout),
            "fonts_inspectable": bool(fonts and fonts.returncode == 0 and "Type 3" not in fonts.stdout),
            "proof_300dpi": bool(render and render.returncode == 0 and pngs and all(path.stat().st_size > 0 for path in pngs)),
        }
        if not all(checks.values()):
            report["failures"].append({"venue": venue, "checks": [key for key, value in checks.items() if not value], "latex_tail": second.stdout[-2000:]})
        report["venues"][venue] = {
            "checks": checks,
            "passed": all(checks.values()),
            "pdf": str(pdf.relative_to(output)) if pdf.is_file() else None,
            "proof_pngs": [str(path.relative_to(output)) for path in pngs],
            "pdf_sha256": _sha256(pdf) if pdf.is_file() else None,
        }
    report["passed"] = not report["failures"] and len(report["venues"]) == 3
    (output / "venue-proof-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = generate(args.output)
    print(json.dumps({"passed": report["passed"], "venues": {key: value["passed"] for key, value in report["venues"].items()}}, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
