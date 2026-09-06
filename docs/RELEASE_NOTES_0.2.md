# NN_DaVinci 0.2.0 Beta release notes

## Quality changes

- Added paper-aware content cropping, explicit page selection, stage/rank wrapping, repeated-block
  `×N` aggregation, semantic critical-edge routing, measurable occupancy and a 7 pt readability
  guard. Locked placements and manual routes survive final page adaptation.
- Added non-pixel geometry acceptance for ResNet, Transformer, U-Net, RNN, MoE, multimodal and
  diffusion diagrams: clipping, overlap, text bounds, font size, occupancy, semantic edges and
  deterministic layout are asserted.
- Added a real Playwright-core test using local Chrome. It exercises the core editor round trip,
  project import/export, seven downloads and DOM-XSS resistance while recording console errors.
- Added request/upload limits, extension and export allowlists, malformed/deep input handling,
  security headers and preservation of HTTP 4xx responses. `/favicon.ico` now returns an ordinary
  404 and a real SVG favicon is available at `/favicon.svg`.
- Expanded the local framework corpus and made state-dict, sampled JAXPR and lightweight-MLIR
  limitations explicit. See `COMPATIBILITY.md`.
- Static and runtime analysis now reports coverage, labels and limitations. MAC/FLOP convention is
  explicit; unknown work is not silently added as zero; latency uses warm-up and a distribution.
- Added Ruff, mypy, ESLint, Prettier and branch coverage checks. Web assets are formatted rather
  than stored as long compressed lines.
- Added fresh wheel/sdist build and isolated-venv smoke tests, including CLI and package-data checks.
- Renamed the former "3D" control to "perspective presentation" because it remains a 2D CSS effect.
- Added `verify-quick.sh` and `verify-full.sh`; full verification treats required skips as failures
  and never reads the retained `artifacts/` directory.

## Compatibility notes

Project files written with the legacy `presentation.three_dimensional` key are migrated to
`presentation.perspective_mode` when loaded. New projects only write the new name. Graph IR stays
at version 1.0 and the project envelope stays at version 1.0; no topology migration is required.

## Evidence

The retained visual sample set is `artifacts/v0.2/2026-08-25-beta3/`: seven architectures, each
newly rendered as SVG, PDF and PNG, plus numeric geometry evidence and a source/environment hash
manifest. These samples are for inspection only; full verification generates a separate temporary
seven-format set from an empty directory on every run.
