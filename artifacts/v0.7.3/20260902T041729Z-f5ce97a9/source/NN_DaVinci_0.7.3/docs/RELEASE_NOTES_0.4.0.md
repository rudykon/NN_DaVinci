# NN_DaVinci 0.4.0 — Real Models & Paper Production

0.4.0 turns the 0.3 semantic canvas into a repeatable model-to-paper workflow. From the Web Start
Center, a researcher can open an offline real model, inspect evidence-backed semantic levels,
choose and compare paper-layout candidates, compose overview/detail or comparison panels, make
local edits, recover the project after refresh and export an editable submission figure.

## Real models, not model-name diagrams

The release contains seven deterministic CPU constructors: torchvision ResNet50, Vision
Transformer, BERT-like encoder, multiscale U-Net, diffusion U-Net, top-k MoE and an image–text
fusion model. Each has a fixed seed and sample input and never requests pretrained weights.
Compatibility evidence fixes parameters, input/output shapes, framework/module/operation views,
shared parameters and expected residual/attention/encoder/decoder/skip/router-expert/timestep/fusion
semantics. Recognition uses Graph IR paths, operators, boundaries and connectivity. Every accepted
detection has confidence, reasons and source-node/edge provenance in both directions; uncertainty
stays explicit `unknown`.

The report records local framework warm-up separately, followed by three measured construction,
import, semantic, first-screen and paper-layout runs per model, with peak RSS and hardware context.

## Figure Composer and one-click production

Figure Composer supports A/B/C/D panels. A panel may reference a different model or another
semantic level of the same model and keeps independent locks, manual routes and annotations.
Shared title, legend, color semantics, font and numeric format sit above panel state. Grid,
horizontal, vertical and overview-detail arrangements support equal size, gap and baseline
alignment. Cross-panel semantic arrows are dashed and carry `not_model_data_edge=true`.

Proof preview reports physical millimetres/inches, minimum font and line width, occupancy and the
reason when 7 pt cannot be reached. One action exports the whole composition as SVG, PDF, TikZ,
PNG, EPS and editable PPTX; TikZ can additionally be split per panel. Project schema 1.2 stores the
Composer and migrates schema 1.0/1.1 projects.

The paper generator selects among CNN/ResNet stage, Transformer block, Encoder–Decoder/U-Net,
MoE routing, multimodal fusion, diffusion pipeline, model comparison and overview-detail templates.
It offers at most three unapplied candidates with font, crossing/collision, whitespace, symmetry,
critical coverage, aggregation and unknown-semantic evidence. Apply and undo preserve user locks
and manual routes. Caption drafts only use facts present in Graph IR or analysis.

## Three production examples

Full verification regenerates three original examples from executable models:

- ResNet50 overview plus bottleneck detail;
- Vision Transformer attention overview/detail;
- multiscale U-Net encoder–decoder overview/detail.

Each example includes `.nndv.json`, SVG/PDF/TikZ/PPTX, proof preview, caption draft, full Semantic
View provenance, geometry-quality report and production notes that identify remaining human
judgment. XML/PDF/TikZ/PPTX compatibility parsers and `pdflatex` validate that the files remain
editable/compilable; this is not a claim of pixel identity in every application release.

## Diff, first use and local plugins

Model comparison now reports exact/probable/unmatched matches with confidence and both models'
operation IDs. It exposes added, removed, modified, moved, shared, shape, parameter, FLOPs and
runtime differences in side-by-side, overlay, change-only and summary views. Fixed evidence covers
ResNet18→ResNet50, Transformer→MoE Transformer and U-Net→attention U-Net. Weight-only
`state_dict` inputs remain explicitly non-structural.

Start Center provides new/import/open/Composer, seven real examples, architecture templates, recent
recovery and tutorial entries. `Ctrl+K` opens the command palette; global search, shortcut/context
help and an issue list route to existing editor operations. Debounced idle autosave restores graph
and Composer state after refresh. Product E2E reports automated clicks, steps, recoveries,
first-figure, autosave, 50k and cancellation timings; no human usability study is claimed.

Plugin API 2.0 versions adapter, semantic recognizer, layout, analyzer, theme and exporter
capabilities, negotiates versions and isolates failures. Local plugins require explicit code trust
and run unsandboxed in the local process. There is no remote store or automatic unknown-code path.

## Scale and verification

The 2,000-node synchronous full-render rejection remains. 10k operations use bounded lazy
viewports; 50k opens through a deferred semantic summary. Both enforce at most 500 visible nodes,
2,000 estimated SVG objects and 200 ms viewport updates. The browser gates first interaction at
2 seconds and cooperative task cancellation at 1 second. A panel-only edit must preserve every
other panel's layout digest. Hardware, input sizes and three backend runs are stored in
`product/performance/three-runs.json`.

The complete Python suite contains the inherited 130 tests plus 13 product tests. Full verification
also runs lint, mypy, coverage, ten inherited Chrome scenarios, the 27-assertion semantic workflow,
the new product workflow, seven-format controls, three real paper examples and all inherited 34
release blockers. The older checksum, attestation, mutation and matrix logic is mechanically
retained; 0.4 product evidence is added as a separate acceptance report.

A successful fresh run is written only to `artifacts/v0.4.0/<run_id>`. The authoritative result is
the run whose `verification.json`, two external attestations and sibling `release-decision.json`
all pass. Previous artifacts may be inspected by a person but are not current verification inputs.

Current raw coverage arithmetic is recorded without rounded-threshold decisions: old-core line
`2205/2418 = 91.19%`, branch `717/860 = 83.37%`, combined `2922/3278 = 89.14%`;
expanded-core line `2358/2580 = 91.40%`, branch `767/916 = 83.73%`, combined
`3125/3496 = 89.39%`; all-package line `6651/7813 = 85.13%`, branch
`1963/2586 = 75.91%`, combined `8614/10399 = 82.83%`. Gates continue to compare the unrounded
fractions in machine evidence.

## Boundaries

There is still no cloud service, multi-user editing, online plugin market, arbitrary 3D tensor
renderer or cross-platform release matrix. Model weights are not downloaded. Researcher review is
still required for terminology, evidence emphasis and the final scientific message.
