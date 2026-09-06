# NN_DaVinci 0.6.1 Beta release notes

**Theme:** Publication Fidelity & Model-to-Figure Completion  
**Release date:** 2026-08-30  
**Figure IR:** 1.0  
**Project schema:** 1.3

NN_DaVinci 0.6.1 closes the publication-fidelity gaps found after 0.6.0. It keeps Graph IR, Semantic View and Figure IR separate while making the entire `Graph IR → Semantic View → Figure IR → final export` chain measurable, multi-page and evidence-preserving.

Historical 0.6.0 release notes and frozen 0.5.2/0.6.0 source/artifacts remain unchanged. A 0.6.1 run writes only to a fresh `artifacts/v0.6.1/<run_id>/` directory.

The clean-replay parent is authoritative 0.6.0 run `20260829T183558Z-09a7930b`, pinned by MANIFEST SHA-256 `797d5b38403154b1317d00e8a9e03c48373a2c046e10e4a43229f828769e3cc4` and its 259-file source digest `f3f5922944756355f9b79b3a18cd3cebc80db5f5d6de2e35cfb1d05b60697bd8`. All 259 parent paths remain present in the 0.6.1 tree. This is verifiable content ancestry; the release does not invent a separate audit record for the historical directory-copy event.

## Physical units and text fidelity

- Centralized exact conversions: `72 pt = 25.4 mm`, `96 CSS px = 25.4 mm`, and `1 pt = 4/3 CSS px`.
- Figure geometry remains millimetres; typography, lines, radii, arrows and baseline grids remain point-based public values.
- SVG serializes physical point styles into the millimetre user coordinate system; TikZ uses explicit point fonts/lines; PPTX retains editable point text.
- Effective final font and stroke size is measured from the complete SVG CTM, including anisotropic and singular transforms.
- Deterministic text layout preserves manual newlines and handles Unicode/CJK/math scripts with explicit requested/fallback font records.
- Required text is never forced with `textLength`, horizontal glyph compression or silent font reduction. The authoring value must fit at 7 pt or above through wrapping, explicit abbreviation/full-name retention, layout changes, or an actionable failure; the independent final measurement allows 0.01 pt only for numeric CTM/pixel round-off.

The normative details are in [UNIT_SYSTEM](UNIT_SYSTEM.md).

## Final-output proof authority

The Python `figure_proof()` report remains useful for fast compiled-IR feedback but is now explicit about its authority: `final_output_verified=false`, `release_blocker_eligible=false`, and no fabricated final text-scale value.

This distinction repairs a known 0.6.0 proof defect. The old Figure Studio `figure_proof()` PASS values cannot authorize publication output. Independent Chrome replay of the seven persisted SVGs in the pinned 0.6.0 artifact produces 0/7 passes, 7/7 failures and 341 geometry issues in the pinned environment. The fresh 0.6.1 full driver re-runs that exact negative control, binds every input hash to the old manifest and stores the raw report alongside before/after images. Old files remain read-only, and the negative control never substitutes for the 14 fresh 0.6.1 SVG passes.

A separate Chrome oracle opens the landed serialized SVG and independently measures the DOM with `getBBox()`, `getBoundingClientRect()` and complete CTMs. It checks effective physical metrics, text-text/text-graphic conflicts, overflow, Page/Panel clipping, full-segment edge/object collisions, all crossings, marker clipping, transparent/zero-size objects and adversarial transforms. Generator-side proof cannot waive a measured failure.

PDF font/text checks, TikZ compilation, PPTX editability, PNG DPI/alpha semantics, EPS vector/font resources and HTML offline/source preservation are separate acceptance gates.

## Model-to-Figure completion

- Added one evidence-preserving model-to-Figure entry that validates Graph IR, derives/materializes Semantic View, lays out a bounded projection and creates editable Figure IR.
- Fixed-corpus operation Graphs now honor the author-selected Block/Paper view while using at most six compact publication lanes; module release Graphs retain the Stage projection. Both pathways index every original node, edge and port and pass the same strict provenance validator.
- Figure objects retain Graph IR node/edge IDs, Semantic View IDs, source locators, port/tensor evidence, recognition reasons and explicit provenance.
- Stable mapping metadata supports Graph↔Semantic↔Figure selection and Structure Lens highlights.
- Large/unfocused operation requests use a recorded semantic summary first; focus IDs/hops and viewport slices recover bounded detail.
- Regeneration preserves matching locked geometry, visibility, local style and author manual routes.
- Structure Lens binds both source and target tensor ports, reports ambiguity as unknown, and requires structural/tag evidence instead of architecture-name keywords.
- Path budgets now cover visits, depth, returned paths, queue entries, generated states, estimated queued-state memory and wall time.

## Multi-page Figure workflow

- Page navigation plus add, duplicate, delete, reorder and physical resize/orientation workflows.
- Fresh IDs and remapped constraints/groups/edge endpoints on Page duplication.
- Lock-aware deletion/resizing and unlocked Panel reorder/movement within or across Pages.
- Heterogeneous Page sizes and orientations with one canonical `(order, id)` export sequence.
- Active Page state persists with the Figure workspace.

## Seven Figure export formats

| Format | 0.6.1 policy |
|---|---|
| SVG | one source-linked numbered file per Page; one-Page filename compatibility retained |
| PDF | one container with one physical PDF page per Figure Page; heterogeneous sizes retained |
| TikZ | one standalone editable source per Page |
| PPTX | one editable slide per Page; heterogeneous Pages centred at 1:1 on the maximum-size canvas |
| PNG | one 300-DPI RGBA file per Page with physical/Page metadata |
| EPS | one vector EPSF Level 3 file per Page with no raster fallback |
| HTML | one dependency-free multi-page viewer with editable SVG text/position, downloads and canonical Figure source |

The one-Page submission-package baseline now contains all seven exports plus project, caption, provenance, proof and `export-policy.json` (12 files). Multi-page SVG/TikZ/PNG/EPS add numbered files; Page IDs/order and heterogeneous-size decisions remain explicit.

## Editable formula subset

Equation objects keep their original source and normalize a small, non-executing safe subset into editable Unicode text. Supported features include Greek letters, common operators, simple superscripts/subscripts, fractions, roots and bounded rectangular matrices. Length, nesting depth and matrix cell count are bounded. Malformed or unsupported input stays visible as an explicit invalid-formula fallback with an error record; it is never executed as TeX.

## Offline templates and real models

The seven bundled archetypes remain CNN, ResNet, U-Net, Transformer, MoE, multimodal fusion and diffusion U-Net. Their environment record is 0.6.1, while template schema/version and provenance remain stable. They do not claim a checkpoint, accuracy or paper result.

A distinct seven-item fixed-seed offline CPU corpus covers ResNet50, Vision Transformer, BERT-like encoder, multiscale U-Net, diffusion U-Net, top-k MoE and image–text fusion. No constructor requests pretrained weights or downloads. Release artifacts for this corpus must be generated through the actual Graph→Semantic→Figure pipeline; a similarly named template is not an acceptable replacement.

## Compatibility and migration

- Figure IR remains 1.0 and project schema remains 1.3.
- Compatible 1.x projects add only missing Figure state and never infer model facts.
- Native SVG round trip continues to require valid versioned metadata and digest.
- Foreign SVG remains an external vector group.
- The 0.6.0 release drivers and evidence remain available for historical replay; 0.6.1 uses separate release drivers and artifact roots.
- Dependency-specific export failures remain actionable and never trigger silent format degradation.

## Verification and release evidence

The release entry points are:

```bash
./scripts/verify-quick-0.6.1.sh
./scripts/verify-full-0.6.1.sh
```

Only the fresh full artifact is authoritative for exact test counts, assertion counts, timings, coverage, skips, export inventories and checksums. This release-note source deliberately does not predeclare those measurements. A run is acceptable only when the artifact records the required Python, Chrome, final-SVG oracle, cross-format, model-to-Figure, package and source-provenance gates without a blocker.

Compatibility is an explicit gate, not an assumption: all 171 authoritative 0.6.0 Python test IDs must still be collected and pass, with zero baseline IDs missing. The retained old-core, expanded-core and all-package coverage manifests/floors are unchanged and each must pass. New 0.6.1 tests are additive. The full run also requires seven authoritative before/after comparisons, the old seven-SVG negative control, the 14-Figure×7-format fresh corpus, exact final-SVG hashes and the cross-format ≤1 mm position contract.

## Human evidence

| Human measure | 0.6.1 result |
|---|---:|
| Participants | 0 |
| Completed human sessions | 0 |
| First-figure median | null / N/A |
| Paper-ready median | null / N/A |
| Core task success | null / N/A |
| Ease/learnability | null / N/A |
| Serious semantic errors | null / N/A |

Automated Chrome, Python/export checks, AI runs and developer self-tests are machine evidence only. They do not count as participants and do not support a human usability, ease-of-use or completion-time conclusion.

## Known boundaries

Formula support is not full TeX; external editors can substitute fonts; PPTX has one slide size per presentation; PNG is intentionally raster; large model authoring remains summary/focus/viewport bounded; Structure Lens remains evidence- and budget-bounded; framework coverage remains the tested subset. See [KNOWN_LIMITATIONS](KNOWN_LIMITATIONS.md) and [COMPATIBILITY](COMPATIBILITY.md).
