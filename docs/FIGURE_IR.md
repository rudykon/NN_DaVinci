# Figure IR 1.0

Figure IR remains NN_DaVinci 0.7.1's deterministic two-dimensional publication-document model. It is separate from the model graph, inferred semantic views, and the three-dimensional Scene IR.

| Representation | Owns | Must not claim |
|---|---|---|
| Graph IR | model nodes, ports, tensors, edges, hierarchy and source locators | paper layout or author intent |
| Semantic View | evidence-backed structural recognition and two-way source mappings | facts that the source cannot prove |
| Figure IR | Pages, Panels, Layers, glyphs, styles, locks, routes and annotations | that an author annotation came from a model |
| Scene IR | world geometry, cameras, lights, 3D routes, materials and Scene author state | that visual depth or thickness is a model/tensor fact |

The model-to-figure path is `Graph IR → Semantic View → Figure IR`. Figure and Scene may both reference the same evidence IDs, and a Scene object may explicitly reference a Figure object, but neither visual document is derived by interpreting the other's pixels or apparent geometry. The author-facing hierarchy is `framework/stage/block/module/operation`; project/schema 1.x keeps `model` and `layer` as the persisted equivalents of `framework` and `module`. Alias normalization selects the same entities and never manufactures a second evidence graph. A Figure object links to Graph IR/Semantic View evidence, identifies a bundled template, records an external vector, carries explicit `author_annotation` provenance, or explains why its provenance is `unknown`. Changing a paper figure never rewrites model evidence.

## Document hierarchy and pages

```text
Figure
└─ Page (one or more, canonical order = order then ID)
   └─ Panel A–H (one to eight per Page)
      └─ Layer
         ├─ Group
         └─ Object
```

Every Panel starts with four semantic Layer roles: `model-data`, `semantic-annotation`, `author-annotation` and `legend-caption`. Objects include node, tensor and operator glyphs; data/annotation edges; text, equation, title, caption and legend objects; images, callouts, brackets, regions, insets and guides. Each Panel independently selects `schematic`, `tensor-geometry` or `mixed` mode.

A Page stores its own width, height, margins, columns, column gap and baseline grid. Orientation is derived from width versus height rather than stored as a second source of truth. Pages may have heterogeneous sizes and orientations. Page order, IDs and physical dimensions are included in the export policy and round-trip source.

## Physical design and text state

Page, Panel and object geometry uses millimetres. Typography, line widths, radii, arrows and the baseline grid use PostScript points under the exact `72 pt = 25.4 mm` contract; browser measurements use the normative `96 CSS px = 25.4 mm` conversion. See [UNIT_SYSTEM](UNIT_SYSTEM.md).

Figure-level tokens define font family, size/weight/minimum, line widths, radii, arrows, colours, opacity and guide colours. Object styles reference tokens and may apply local overrides. Text objects compile into explicit physical lanes and deterministic lines. The layout preserves manual newlines and records Unicode scripts plus ordered font fallbacks. It never uses `textLength`, horizontal glyph compression or silent font shrinkage. Required authoring text below 7 pt, or text that cannot fit at 7 pt or above, fails with an actionable error. The landed-SVG oracle has a 0.01 pt numeric measurement tolerance for pixel/CTM round-off; it does not relax the 7 pt authoring minimum.

Position locks, manual routes and alignment/equal-spacing/snap/pin constraints are first-class data. Reordering unlocked content does not rewrite locked Pages, Panels, Layers, objects or author routes.

Tensor objects retain authoritative model shape text in `tensor_shape`/`shape_label` and in their tensor provenance. Visual scaling is recorded separately and never changes a tensor specification. Editing the displayed shape on an evidence-backed object creates an explicit `author_shape_override`; it never overwrites the source tensor fields, and output marks that label as an author override rather than `data-real-shape`. Equation objects retain their original source plus normalized editable text, safe-subset version, feature list and explicit validity/fallback record.

## Provenance rules

- `graph_ir` and `semantic_view` provenance require evidence IDs.
- Evidence-backed model Figures retain Graph IR node/edge IDs, Semantic View IDs, exact source/target port bindings, tensor records, structural recognition reasons and source locators when available.
- Every Figure `semantic_view` ID must name an entity in the persisted Semantic View saved with that project/export. Conversely, each Semantic View entity records its source Graph IR IDs, and the Figure's reverse mapping must agree. Graph-only evidence objects, including added Structure Lens panels, are checked directly against the saved Graph and require the same exact forward/reverse index even when no Semantic View document is needed. Orphans, substituted IDs, tensor/port-binding changes and tampered reverse mappings are validation failures.
- `author_annotation=true` is valid only with `kind=author_annotation` and a reason.
- `unknown` and `external_vector` require an explicit reason.
- Template objects claim only the bundled archetype, never a model instance, checkpoint, result or accuracy.
- Moving an evidence-backed object to another visual Layer does not change its provenance kind.
- Importing native NN_DaVinci SVG restores Figure IR only after metadata digest validation. Foreign SVG becomes `external-vector-group`; visual proximity is not reconstructed as model evidence.

`FigureIR.validate()` enforces the Figure document's intrinsic IDs, hierarchy and provenance shape. Cross-representation truth requires more context: Project 1.4 construction/loading parses `semantic_view.document`, validates its source digest and bidirectional indexes against the saved Graph IR, then runs `validate_model_figure_provenance()` against the Figure and, when present, the independent Scene provenance validator. A standalone Figure IR cannot prove that an external Graph/Semantic/Scene ID exists, so it is never described as sufficient for that cross-check.

The CLI Project path uses this same boundary. `nnviz project --workspace scene` persists the exact Semantic View document used by Scene generation before Project validation; focused create→validate→reproduce checks guard against emitting an evidence-bearing Scene with only a Semantic summary and no `semantic_view.document`.

## Summary, focus and viewport generation

`model_figure_from_graph()` validates the source Graph IR, derives or accepts one persisted Semantic View, materializes the requested level/view from that same entity set, lays it out and creates source-linked Figure objects. A corpus-specific compact layout projection may bundle visible objects, but its provenance resolves back to real entities in that persisted Semantic View and to the original Graph IR; it is never saved as a substitute evidence graph. The fixed-corpus Start Center's operation Graph therefore keeps the author's Block/Paper selection while producing at most six publication lanes, and the release-reviewed module Graph uses its Stage projection; both retain every source node, edge and port in the bidirectional index. When an unfocused operation view exceeds the bounded authoring threshold, generation starts from a coarser semantic summary of the original Graph and records both requested and selected levels. Callers can provide focus IDs/hops or a viewport request to recover bounded operation detail. Existing locked geometry, visibility, styles and author manual routes are reconciled onto regenerated objects with stable identities.

Structure Lens consumes the source Graph IR and this same Semantic View. Positive residual, attention and MoE panels require explicit structural/operator/semantic evidence and expose confidence plus reasons; ambiguous or missing evidence yields `positive_claim=false`, `unknown` or `unsupported`. A Lens preview copied into a Figure receives fresh Page/Panel/Layer/Object IDs and uses exact `graph_ir` provenance for its raw evidence objects, including original source/target ports. It carries no orphan Semantic identity, materialized Semantic port or derived semantic-confidence claim; the bounded query response separately retains its Semantic View reasoning.

This policy is a bounded authoring workflow, not deletion of source evidence: the full Graph IR remains available to summary, search, focus and viewport APIs.

## Determinism and validation

`FigureIR.canonical_json()` sorts Pages, Panels, Layers, Groups, objects and design-token keys using stable order/ID rules. `FigureIR.digest()` is SHA-256 over that canonical UTF-8 JSON. Identical content therefore has an identical digest.

The runtime validator is `src/nn_davinci/figure_ir.py`; the portable schema is `schemas/figure-ir-1.0.schema.json`. Figure IR 1.x readers reject incompatible major versions and never translate Figure objects back into model facts or synthesize Scene geometry. Figure IR remains version 1.0 in NN_DaVinci 0.7.1.

## SVG round trip and proof

Native SVG contains `nndv-figure-svg-metadata-1` metadata with product/Figure IR versions, canonical digest, complete document source, provenance/tensor state, styles, locks, constraints and routes. A per-page SVG additionally records its source Figure digest, Page ID/index and total Page count.

`figure_proof()` is intentionally provisional: it estimates compiled Figure primitives and cannot certify the landed renderer result. Release acceptance uses an independent Chrome DOM oracle over the serialized final SVG and its complete CTMs. The oracle measures effective font/stroke sizes, text/graphic bounds, clipping, collisions, crossings, markers and adversarial transforms. Generator-side metadata cannot declare a measured failure safe.

The 0.7 full driver additionally binds the Figure evidence to the Scene/browser evidence set, including at least 44 browser screenshots, ten Scene-format downloads, seven real-architecture 2D/3D pairs, and an independent visual report. The artifact's `verification.json`, rather than this IR specification, owns the run outcome.

## Multi-page export policy

| Format | Page policy |
|---|---|
| SVG | one source-linked `.page-NNN.svg` per Page; a one-Page Figure keeps `<stem>.svg` |
| PDF | one PDF page per Figure Page, preserving heterogeneous physical sizes |
| TikZ | one standalone `.page-NNN.tex` per Page; a one-Page Figure keeps `<stem>.tex` |
| PPTX | one editable slide per Page; heterogeneous pages are centered at 1:1 on the maximum-size presentation canvas |
| PNG | one 300-DPI metadata-bearing RGBA file per Page |
| EPS | one vector EPSF Level 3 file per Page; raster fallback is rejected |
| HTML | one offline viewer containing all Pages, per-page SVG DOM and canonical Figure IR source |

## Key implementation paths

- `src/nn_davinci/figure_ir.py`
- `src/nn_davinci/model_figure.py`
- `src/nn_davinci/figure_export.py`
- `src/nn_davinci/units.py`
- `src/nn_davinci/text_layout.py`
- `src/nn_davinci/formula.py`
- `schemas/figure-ir-1.0.schema.json`
