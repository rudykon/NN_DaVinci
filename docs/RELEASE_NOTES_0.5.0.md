# NN_DaVinci 0.5.0 Beta — Researcher Trial & Workflow Hardening

0.5.0 freezes the 0.4.2 drawing and semantic algorithms and packages the existing model-to-paper
workflow for external researcher trials. It is a Beta because the complete kit has been exercised by
tests and real Chrome, but no external human participant was available; human usability conclusions
remain paused.

## Trial Mode

The Web editor now exposes an opt-in Trial Mode. It creates no storage before explicit consent. Its
event-specific allowlist records import outcome, first interactive/paper-ready elapsed time, edit
counts, export formats, broad errors and recovery actions in local JSON. It rejects extra fields and
never records or uploads model data, filenames, paths, node/edge IDs, label contents, searches,
comments or identity. Consent can be revoked; active sessions and stable IDs recover after refresh.

The trial kit contains protocol, participant guide, consent text, six tasks, machine JSON schema,
anonymous aggregation tool and a human report template. The current human status is honestly
`awaiting_participants`: 0 participants and no populated human metric.

## Independent model cases

Six framework-only constructors carry no recognizer hints and download no weights: sampled dynamic
PyTorch, dynamic-dimension ONNX with two inputs/outputs and a shared initializer, shared-weight
Siamese, Transformer with attention and FFN residual additions, two-scale U-Net with skip merges, and
a custom spectral gate that remains explicit unknown. Each compatibility run performs import,
provenance-bearing semantics, three paper candidates, paper-ready block+operation Composer, project
round trip and SVG/PDF/TikZ/PPTX export. The machine report records three timing runs per phase.

## Paper-template proof

A final-size 88 mm Transformer semantic figure is exported independently as PDF and editable TikZ,
inserted through both paths into official NeurIPS 2026 and ICML 2026 styles and local IEEEtran,
compiled twice, font-inspected and rendered to 300 DPI PNG. Template sources and hashes are recorded.

## Workflow hardening

PyTorch runtime fallback now creates explicit, correctly named graph inputs from the `forward`
signature and separate output nodes, so an input is never named `output_0`. Sampled dynamic boundaries
are stated in metadata. Unknown semantics explain the evidence boundary in the inspector. Task
failures expose actionable sample-input/module/summary/focus/page recovery buttons, and Trial Mode
records only the recovery category. Small external cases use balanced block+operation Panels instead
of a nearly empty one-node Stage overview.

## Acceptance and compatibility

The inherited 130 tests, 13 0.4 product tests, ten legacy Chrome scenarios, semantic workflow,
0.4 product workflow, Publication Quality 3/3 and Scientific Fidelity 3/3 remain release-blocking.
Five new Python tests and a 45-assertion six-case Chrome workflow exercise the trial kit. The additive
five-check `trial/acceptance.json` requires the six-case report, three venue proofs, privacy schema,
documents and honest human status. Existing Graph IR 1.0 and Project 1.2 compatibility is unchanged.

The final development quick baseline is 148/148 Python tests. Coverage is: old core line
`2267/2480 = 91.41%`, branch `722/864 = 83.56%`, combined `2989/3344 = 89.38%`;
expanded core line `2469/2695 = 91.61%`, branch `792/944 = 83.90%`, combined
`3261/3639 = 89.61%`; all package line `7945/9107 = 87.24%`, branch
`2363/3040 = 77.73%`, combined `10308/12147 = 84.86%`.

A successful fresh full run is written to `artifacts/v0.5.0/<run_id>/`. This work does not initialize
Git, commit, upload, publish, add cloud services or redesign the inherited attestation/mutation system.
