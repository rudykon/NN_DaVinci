# NN_DaVinci 0.2.1 Beta release notes

0.2.1 is a credibility and stability correction, not a framework/export
expansion.

- Corrected release statistics: line, true branch and combined coverage use
  their own raw numerators/denominators and unrounded gates. The 0.2.0
  `85.96% branch` statement was wrong: it was combined coverage; true branch
  was `573/734 = 78.07%`.
- Froze all 73 pre-0.2.1 Python test IDs and made missing IDs/deselection fatal.
- Replaced recursive Tarjan DFS with iterative deterministic Kosaraju SCC
  ranking. Added 100/1k/10k deterministic graph corpora, bounded focus/summary
  behavior, HTTP 422 full-render refusal and a sweep-line overlap index.
- Added a separate Chrome final-SVG oracle with fixed tolerances and 12 manual
  positive/negative geometry fixtures. It independently measures transforms,
  clipping, overlap, text, fonts, occupancy, edge-node collisions, unrelated
  crossings and metadata drift from files on disk.
- Re-routed the fixed Transformer, U-Net and Diffusion examples without
  deleting/hiding edges or adding bridge markers. Seven authority inputs now
  pass with zero collisions/crossings and exact IR/provenance hashes.
- Removed `textLength/lengthAdjust` glyph crushing. Added deterministic
  `compact`, `paper` and `detailed` labels; paper wraps required shape,
  parameters and FLOPs. Chrome reports horizontal scale 1.0 for the authority
  set, and SVG/PDF/TikZ required text is cross-checked.
- Split browser acceptance into ten isolated stable scenarios with direct
  coordinate, route, alignment/distribution, lock/hide, history and persistence
  assertions. Straight edges now gain editable orthogonal control points on
  first route drag.
- Moved coverage, lint/type caches, summaries and downloads into run-local
  directories. Each successful full run retains logs, raw JSON, hashes,
  environment and current artifacts under `artifacts/v0.2.1/`.
- Added exact verification constraints while retaining library extras as
  compatible ranges. Wheel/sdist and seven-format gates remain mandatory.

Deferred to 0.3: full five-level browsing, lazy canvas, asynchronous task and
cancel UI, a complete import wizard, and advanced interactive layout
optimization.
