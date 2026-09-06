# Project schema 1.3

NN_DaVinci 0.6.1 continues to write `.nndv.json` projects with `project_version: "1.3"`, introduced in 0.6.0. Schema 1.3 adds an independent optional `figure_ir` document and Figure workspace recovery fields. Graph IR remains the source of model facts.

## New state

- `figure_ir`: empty object or a validated Figure IR 1.0 document;
- `semantic_view.version/level/view`: compatible selection controls; `framework`/`module` are author aliases for persisted `model`/`layer` levels;
- `semantic_view.document`: the complete canonical `SemanticView.to_dict()` evidence document. It is required when `figure_ir` contains model-derived `semantic_view` provenance, and optional for legacy Graph-only, template-only or author-only Figures;
- `canvas_state.workspace_mode`: `graph` or `figure`;
- `canvas_state.figure_selection`: selected Figure object IDs;
- `canvas_state.figure_active_page`: the Page ID restored as active after save/autosave and refresh;
- `canvas_state.figure_active_layer`: the active Layer ID;
- `canvas_state.figure_include_guides`: physical-guide visibility;
- `figure_ir.pages`: one or more independently sized Pages, canonically ordered by `(order, id)`; every Page retains its title, physical dimensions, margins, columns/gap, point baseline grid and one to eight A–H Panels;
- each Panel retains mode, lock, physical geometry, ordered Layers/Groups/Objects and constraints/routes; Page titles support rename without changing IDs;
- Figure Composer state accepts one to eight A–H Panels and retains each Panel's mode, lock and tensor geometry settings.

Duplicating a Page creates fresh Page, Panel, Layer, Group and Object IDs, then remaps group membership, constraint targets and edge endpoint references to those fresh IDs. Global ID uniqueness and the per-Page eight-Panel limit are runtime validation requirements, not optional UI conventions.

Portable schemas are stored in:

- `schemas/project-1.3.schema.json`
- `schemas/figure-ir-1.0.schema.json`

The Python runtime validators remain authoritative because they also enforce global ID uniqueness, constraint targets, semantic provenance rules and deterministic ordering. `Project` validates `semantic_view.document` against the saved Graph IR digest and bidirectional Semantic indexes, then validates Figure↔Semantic↔Graph forward/reverse mappings. Graph-only evidence objects are validated directly against Graph node/edge/port IDs and the Figure index; they do not require a fabricated Semantic document. A model-derived Figure with a missing required document, orphan entity/Graph ID, changed tensor/port binding or tampered reverse index is rejected. Legacy prerelease files that placed a complete Semantic View flat in `semantic_view` are accepted and canonicalized into `document`; no evidence is inferred for older config-only projects.

## Migration from 1.2

`Project.from_dict()` accepts project 1.2 and earlier compatible 1.x documents, preserves their Graph IR and existing presentation state, sets `figure_ir` to `{}`, and records a migration entry in `environment.project_schema_migrations`.

The migration does not:

- infer or fabricate a tensor shape;
- invent a semantic label or provenance record;
- convert CSS perspective into Tensor Geometry;
- create author annotations;
- claim that old visual layout represented Figure IR.

After opening an old project, the user may explicitly build a Figure draft from the preserved Graph IR. Unknown/symbolic shapes remain unknown/symbolic.

## Compatibility

Schema 1.3 keeps the 1.x major line. NN_DaVinci rejects incompatible project major versions with a migration hint. Older applications that do not understand `figure_ir` should not overwrite a 1.3 project because they cannot preserve its Figure document.

Native SVG metadata is a separate round-trip format (`nndv-figure-svg-metadata-1`) and carries Figure IR 1.0 plus its digest; it is not a replacement for the full project file.

## Deterministic save

Figure IR serialization is canonical and digestible. The outer project retains timestamps and environment data, so two separately saved full project files need not have identical bytes. Compare Figure content using `FigureIR.digest()` rather than hashing the complete project wrapper.

The browser's 350 ms debounced autosave serializes the same project/`canvas_state` payload used by explicit recovery, including `figure_active_page` and, when present, the exact `semantic_view.document`. Undo/redo `history` and `future` stacks are session-only implementation state and are intentionally absent from schema 1.3, autosave, downloaded projects and native SVG metadata. A restored project therefore recovers document/evidence state but starts with empty undo/redo history.

## Tests

- `tests/test_figure_ir.py` verifies migration and native SVG round-trip.
- `tests/test_project_semantic_provenance_061.py` verifies required Semantic View persistence plus orphan/digest/reverse-index rejection.
- `tests/test_web_security.py` verifies legacy presentation compatibility.
- `tests/e2e/figure-studio.e2e.mjs` verifies save, refresh, active-Page recovery and multi-page export behavior; Figure IR/unit tests cover fresh duplicate IDs, reorder/delete/rename settings, locks and per-Page bounds.
