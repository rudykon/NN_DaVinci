# Scientific Figure Studio

Scientific Figure Studio is NN_DaVinci 0.7.1's dedicated two-dimensional paper-figure workspace. Open it from the workspace switcher or Compose/Paper surface. It edits Figure IR 1.0 while preserving Graph IR and Semantic View evidence; true 3D authoring lives in the separate Scene Studio rather than a hidden Figure presentation mode.

## Workspace and responsive ownership

On desktop, Templates/Symbols/Layers/Pages share the canonical left panel, the Figure Canvas stays in the centre, and Properties/Provenance/Proof share the canonical Inspector on the right. The 0.7 application shell limits permanent top-level groups and moves task-specific actions into Project, Import, Analyze, Compose, 3D, View, Export, Help and the searchable command palette. A contextual toolbar keeps high-frequency Page, selection, Tensor, annotation, alignment, lock, Structure Lens and proof actions near the canvas only when relevant.

At 800 px and below, the same left and right panels become focusable drawers. The app does not construct a second canvas, object tree, Page model or Inspector state. Figure, Graph, and Scene keep distinct workspace contexts under one state machine; returning to Figure restores its Page/selection/view context while evidence selection can remain synchronized.

## Page-first workflow

The Page tree is the owner of multi-page state. Authors can activate, add, duplicate, rename, delete and reorder Pages; choose single-column, double-column, A4 portrait, A4 landscape or custom physical dimensions; and move/reorder unlocked Panels within or across adjacent Pages. Page rename is the Page title field followed by the settings action, not a cosmetic browser-only label. Each Page can have a distinct size and orientation. The browser authoring guard permits at most 64 Pages, while each Page retains the Figure IR A–H/eight-Panel limit.

Deleting or resizing a Page that contains locked Panels, Layers or objects is rejected. At least one Page and one Panel per Page are retained. Page duplication creates fresh Page/Panel/Layer/Group/Object IDs and rewrites constraint/group/edge endpoint references to those fresh IDs. Page order is persisted and is the canonical export order.

## Layers, object tree and locks

Each Panel exposes Model data, Semantic annotation, Author annotation and Legend/Caption Layers. Authors can create, rename, reorder, hide or lock a Layer. Objects can move between unlocked Layers in the same Panel without changing provenance.

The object tree follows Page/Panel/Layer/Group/Object hierarchy. Canvas and tree selection are bidirectional. Multi-selection supports grouping, ungrouping, alignment and equal spacing. Locked objects, populated locked Layers and locked Panels are protected from automatic relocation. New Panels select `schematic`, `tensor-geometry` or `mixed` independently; grid, horizontal, vertical and free arrangements retain locked geometry.

## Guides, style and deterministic text

The View menu toggles millimetre page margins, columns and a point baseline grid. Object dragging snaps to a 0.5 mm grid and records a `snap-baseline` constraint. Alignment actions record their scope, including cross-Panel constraints.

Figure-level design tokens cover font family/size/weight, physical line width, corner radius, arrow size, colours and opacity. NeurIPS, ICML, IEEE, ACM, colour-blind and grayscale presets update tokens; object overrides remain local.

Text is laid out in explicit millimetre lanes with deterministic wrapping. Manual newlines, Unicode, CJK and math characters are retained; requested and fallback font stacks are recorded. No exporter may use horizontal glyph compression or silently shrink required text. If wrapping, an explicit abbreviated visible label/full-name record, or authorized geometry changes cannot keep authoring text at least 7 pt, export fails with a remediation message. Chrome permits a 0.01 pt final-measurement tolerance solely for numeric round-off. The exact conversion and CTM rules are in [UNIT_SYSTEM](UNIT_SYSTEM.md).

## Annotations, formulas and provenance

Text, equation, arrows, callouts, brackets/regions, legends and other author objects carry `author_annotation` provenance. Annotation edges use dash, colour and metadata distinct from model-data edges. Proximity to a model glyph never turns an annotation into Graph IR evidence.

Equation objects preserve their source and normalize a documented, non-executing safe subset into editable Unicode text. The subset includes Greek letters, common operators, simple scripts, fractions, roots and bounded rectangular matrices. Unsupported or malformed input remains visible as an explicit invalid-formula fallback with its error record; no TeX command is executed. SVG/TikZ/PPTX/HTML keep the normalized text editable and retain the original source metadata.

The Provenance tab shows selected-object source IDs, Graph IR IDs, source locator and author flag. A model-derived Figure additionally records Graph→Semantic→Figure mappings, port/tensor evidence and its summary/focus/viewport generation policy. Structure Lens highlights only Figure objects linked to the returned evidence. Adding a Lens preview is an explicit author action; a preview alone does not mutate the Figure.

## Save and native round trip

Saving writes Project 1.4 `.nndv.json` and local recovery state, including `figure_active_page`, hierarchy, selection, guides, locks and routes plus an explicit Scene IR document (empty when unused). For a model-derived Figure it also saves the exact evidence document under `semantic_view.document`; project loading validates that document against the saved Graph digest and validates all Figure forward/reverse provenance indexes before accepting the project. Graph-only Lens evidence receives and validates the same exact index without fabricating a Semantic View claim. The browser debounces autosave for 350 ms and stores the same project payload shape used for recovery, including Semantic/Figure/Scene documents and workspace context; idle scheduling may delay the storage write but does not change its content. Refresh restoration activates the persisted Page ID when it still exists, otherwise the first valid Page. A Graph model-fact edit invalidates cached Semantic evidence, marks a dependent Figure for regeneration, and omits that stale Figure/evidence document from autosave until the evidence chain is rebuilt; the prior Figure remains available only as reconciliation input.

CLI Scene-Project creation follows the same persistence rule: `nnviz project --workspace scene` stores the exact Semantic View document used by the generated Scene and passes focused create→validate→reproduce checks. It does not save an evidence-bearing Scene against a summary-only Semantic envelope.

Undo/redo holds at most 100 in-memory snapshots of Graph/Figure workspace state, including Graph store identity, the persisted Semantic document, project envelope and Figure-regeneration state. It is deliberately session-only: history and future stacks are not serialized into project, autosave, SVG metadata or exports, so refresh starts a new edit history. This prevents stale commands from referring to IDs that were regenerated by Page duplication or import.

Native NN_DaVinci SVG embeds digest-checked Figure IR metadata. Foreign SVG becomes a marked external-vector group and does not recover model semantics.

## Seven export formats

| Format | Fidelity and Page policy |
|---|---|
| SVG | source-linked vector DOM; one numbered file per Page for multi-page Figures |
| PDF | one container, one physical PDF page per Figure Page; heterogeneous sizes preserved |
| TikZ | standalone editable source; one numbered source per Page |
| PPTX | one editable slide per Page; text, panels, tensor faces and connectors stay editable |
| PNG | one 300-DPI RGBA file per Page with Page/source metadata |
| EPS | one vector EPSF Level 3 file per Page; no raster fallback |
| HTML | one dependency-free offline viewer with Page navigation, basic SVG text/position editing, downloads and canonical source |

PowerPoint uses one presentation-wide slide size. A heterogeneous Figure therefore uses the maximum Page width and height as its presentation canvas and centres every Page at 1:1 scale without cropping. SVG/TikZ/PNG/EPS multi-page downloads are returned as ordered numbered files (or a browser ZIP); one-Page filenames remain backward compatible.

The one-Page submission-package baseline contains 12 files:

```text
figure.svg        figure.pdf       figure.tex       figure.pptx
figure.png        figure.eps       figure.html      figure.nndv.json
caption.md        provenance.json  proof.json       export-policy.json
```

For multi-page documents, SVG/TikZ/PNG/EPS add numbered Page files, so the total grows with Page count. `export-policy.json` retains source Page IDs/order and heterogeneous-page decisions; provenance and proof separately retain evidence and geometry diagnostics.

## Templates and model-derived figures

Seven bundled offline archetypes cover CNN, ResNet, U-Net, Transformer, MoE, multimodal fusion and diffusion U-Net. Every template includes schematic and Tensor Geometry content plus explicit template provenance; symbolic/unknown shapes remain symbolic/unknown, and no template claims a checkpoint, accuracy or paper result.

Start Center also exposes a separate exact set of seven editable 3D Scene template cards for those families. They open non-empty Scene IR documents with template-only provenance and are not aliases for these Figure templates or for the seven real-model examples.

Seven deterministic offline executable models cover ResNet50, Vision Transformer, BERT-like encoder, multiscale U-Net, diffusion U-Net, top-k MoE and image–text fusion. Each uses fixed seeds, CPU sample inputs, random/local weights and no downloads. Release examples must pass through the real `Graph IR → Semantic View → Figure IR` path rather than substituting their similarly named templates. Their Start Center operation Graphs use a compact, evidence-complete Block/Paper projection (at most six visible lanes); release module Graphs use the corresponding Stage projection. Bundling changes only visual density: every original node, edge and port remains reachable through the saved forward/reverse provenance index.

## Proof and acceptance boundary

The Inspector's Python `figure_proof()` report is fast, deterministic and provisional. It is not eligible to block or authorize a release and reports no fabricated final CTM scale.

The strict release oracle opens the landed SVG in Chrome and independently measures the final DOM: effective font size (≥7 pt), effective stroke width (≥0.1 pt), CTM anisotropy/singularity, text conflicts/overflow, Page/Panel clipping, complete edge/object collisions, all edge crossings, marker clipping and zero/transparent objects. Adversarial transformed SVG fixtures must fail for the intended reason. PDF/TikZ/PPTX/PNG/EPS/HTML receive separate format checks.

Chrome automation is machine evidence only. It does not count as a human participant or support a human usability, ease-of-use or completion-time claim. The inherited Figure contract remains release-blocking in 0.7.1: all 328 authoritative 0.7.0 test IDs and retained coverage floors must remain intact, and the clean full driver must re-run Figure E2E/oracles rather than cite the parent artifact as a current result. Only the resulting `verification.json` owns the run outcome.

The Figure Studio Chrome contract exercises a real model-derived mixed Figure, a Structure Lens evidence Panel, tensor shape/style editing, a long-label final-SVG bbox check, adding a second Page, six Panels, save→refresh→active-Page recovery, native SVG metadata round trip, all seven exports, the submission package, 1440/800/390 px layouts and zero console/page/request errors. Page/Panel source operations and Python validators separately cover duplicate fresh IDs, rename/settings, reorder/delete, per-Page A–H bounds and lock rejection.
