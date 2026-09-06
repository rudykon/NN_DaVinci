# Architecture (0.7.2)

## Architecture Evidence and landed parity

Architecture Evidence 1.0 sits between source-bound Semantic View detections and both publication documents. Recognition examines Graph topology, explicit operation/module identity, ports and tensor shapes, and detections whose provenance IDs exist in the source Graph. It deliberately ignores display names, corpus keys, Python class names, filenames and requested layout families.

Each evidence record is sealed to the Semantic source digest and contains exact supporting node/edge/port IDs, detected roles, repeat counts, protected critical routes, confidence/reasons, alternatives and explicit uncertain claims. Figure and Scene builders consume the same record but materialize separate documents. `architecture_parity.py` validates the landed Figure IR and Scene IR without calling either builder, then compares both against Graph IR and Semantic View. A removed route, substituted provenance ID, changed repeat count or relabelled role is therefore observable after serialization.

## Invariants

1. `GraphIR` owns model semantics and stable traceable IDs, never pixel geometry.
2. Analysis writes namespaced records to graph/node analysis maps, never theme values.
3. `LayoutResult` owns geometry. Locked positions are promoted to project constraints.
4. Renderers consume Graph IR + geometry + theme and never parse a model.
5. Framework, analyzer, layout, theme and exporter extensions cross a versioned plugin boundary.
6. `SemanticView` is a versioned derived index: it never rewrites source `GraphIR`, and every
   summary entity/connection traces in both directions to source node/edge IDs.
7. Faithful View may group only evidenced structure; Paper View may additionally aggregate and
   conceptualize. Low-confidence matches remain explicit `unknown` entities.
8. `FigureIR` owns editable publication presentation. Every model-derived object retains
   Graph/Semantic evidence; author annotations never become model facts.
9. Figure geometry is millimetres and physical style is points under one centralized exact unit
   system. A backend cannot reinterpret a point as an SVG user unit.
10. Compiled Figure proof is provisional. Only an independent measurement of the serialized final
    SVG DOM/CTM is eligible to block or authorize the final-SVG geometry gate.
11. `Scene` owns editable three-dimensional authoring state. Local transforms use XYZ position,
    Euler degrees and positive XYZ scale; composed world records and camera projections are derived.
12. WebGL2 is an interactive Scene renderer only. Every paper format consumes the independent CPU
    `ProjectedScene`; a WebGL screenshot can never satisfy a vector export contract.
13. Project 1.4 stores an explicit Scene IR 1.0 document. Compatible 1.3 migration creates an empty
    Scene plus an explicit no-inference record and never interprets legacy CSS perspective as 3D.
14. Scene family/primitive semantics require Graph/Semantic evidence. A requested layout or display
    name cannot manufacture residual, attention, expert, fusion, diffusion, or tensor facts.

These boundaries make model import expensive only once, allow deterministic relayout, and keep
manual edits reproducible.

## 0.6.1 model-to-figure pipeline

`model_figure_from_graph()` is the canonical evidence-preserving entry:

```text
GraphIR → derive/materialize SemanticView → bounded layout → FigureIR
```

Graph node/edge IDs, ports, tensor records, Semantic View IDs, source locators, confidence and
recognition reasons flow into Figure provenance and metadata. A deterministic mapping index supports
Graph↔Semantic↔Figure lookup. Regeneration reconciles stable object identities with existing
locked geometry, visibility, local style and author-created manual routes.

An unfocused operation-level request above the authoring threshold starts at a coarser Semantic View
and records `requested_level`, `selected_level` and `summary_first`. Focus IDs/hops and viewport
slices provide bounded detail recovery. This changes the visible authoring projection, not the
underlying Graph IR.

## 0.7.0 model-to-scene pipeline

`model_scene_from_graph()` is the canonical evidence-preserving 3D entry:

```text
GraphIR → persisted SemanticView → bounded family layout → Scene IR 1.0
                                                          ├─→ WebGL2 interaction
                                                          ├─→ CPU ProjectedScene
                                                          └─→ Scene JSON/glTF/GLB
```

The builder accepts the exact Graph, optional persisted Semantic View and Figure IR, explicit
architecture/layout request, semantic level/view, focus IDs/hops, maximum-object budget, and an
existing Scene for reconciliation. Explicit Graph metadata can evidence one of seven families;
otherwise the evidenced family stays `unknown` even if a requested family controls layout.
Materialized model-derived objects record their Graph node/edge IDs, available port bindings and
shape/dtype evidence, Semantic IDs/reasons when used, optional Figure IDs, and Scene-level forward/
reverse indexes. Source locators remain authoritative in Graph IR and are reached through those IDs;
the Scene does not duplicate a locator or source digest into every object. When a Semantic View is
supplied, the Scene-level Semantic record retains its source digest.

The default 250-object budget is summary-first for large inputs. Through 10,000 source nodes,
summary provenance retains the exact covered IDs. Above that threshold it records an explicit
digest-and-bounded-representatives mode, source counts/digests, and bounded representative IDs
rather than embedding an unbounded ID list in every visible summary object. A focused request
materializes a bounded neighborhood with exact source IDs. Stable object identity lets regeneration
restore visibility/material, selected state, locked transforms/locks, and the active camera; other
author objects, groups, routes, and unlocked transforms are not promised automatic reconciliation.

`scene_ir.py` owns the schema/runtime model and dependency-free world/camera/ray behavior;
`scene_math.py` owns vector/matrix composition, inversion, projection and intersection;
`scene_projection.py` produces an immutable physical `ProjectedScene`; `scene_export.py` emits paper
formats; and `scene_gltf.py` emits canonical Scene JSON plus embedded glTF/GLB world geometry.

## Project 1.4 persistence and migration

Project 1.4 requires `scene_ir` alongside Graph, Semantic, and Figure records. `Project.__post_init__`
canonicalizes direct Python construction with no Scene to an explicit empty Scene. Loading a compatible
1.x predecessor records the source/target versions in both the Project environment and Scene migration
history, then creates a default authoring camera/light with no model objects or provenance. Incompatible
major versions and 1.4 documents missing `scene_ir` are rejected.

Evidence-bearing Scene objects trigger contextual validation against the exact persisted Graph,
Semantic document, and Figure document. Template/author/external/unknown Scenes make no such model
claim. `render_project()` dispatches by the explicit `export.workspace`; a Scene Project cannot fall
through to the Graph renderer merely because both documents exist.

## Scene rendering and export authority

The browser renderer builds procedural meshes and world-space route segments from Scene objects and
composes local/world, view and perspective/orthographic projection matrices in WebGL2 with a depth
buffer. Route endpoints and authored control points are projected as lines/tubes; no generic object
mesh is placed at the origin as a connector substitute. A DOM overlay anchors Scene labels to projected
object positions and deterministically rejects overlapping or clipped placements. Camera and object
caches serve interaction only. Local ray picking transforms the screen ray into object space and
returns the nearest positive hit. WebGL failure emits an explicit state transition and requests the
server CPU SVG; the last-resort browser SVG remains visibly labelled as a fallback.

The CPU projector independently constructs vector faces, visible/hidden edge chunks, arrow/routes and
labels in millimetres with physical point styles. It depth-sorts faces, applies back-face and sampled
occlusion policy, then avoids label rectangles deterministically. SVG, PDF, TikZ and EPS contain
native vector/text operations; PPTX contains editable shapes; PNG is the intentional 300-DPI raster;
offline HTML embeds the CPU SVG and source data under a restrictive CSP. Scene JSON round-trips Scene
IR, while glTF/GLB retain real XYZ buffers, camera/material nodes, IDs, and provenance extras.

## Physical text and proof authority

`units.py` centralizes the exact `72 pt = 25.4 mm` and CSS 96-DPI conversions plus CTM scale and
effective font/stroke helpers. Figure SVG uses a millimetre `viewBox`, converts point-valued style to
millimetre user units and avoids non-scaling strokes for its own physical line contract.

`text_layout.py` produces deterministic physical lanes and line records for manual newlines,
Unicode/CJK/math scripts and explicit fallback stacks. No Figure backend uses `textLength`,
anisotropic glyph compression or silent font shrinkage. A placement that cannot meet the 7 pt
minimum fails with an actionable remedy.

`figure_proof()` is a conservative compiled-primitive estimate and declares itself non-final. The
independent Chrome oracle instead opens the landed SVG and measures `getBBox()`,
`getBoundingClientRect()` and complete CTMs. It covers effective units, text-text/text-graphic
conflicts, Page/Panel clipping, complete edge/object collisions and crossings, marker clipping and
adversarial transforms. Format-specific gates remain separate.

## Page and export model

Figure IR owns one or more independently sized Pages, each with one to eight Panels. The browser
supports Page add/duplicate/delete/reorder/resize/navigation and unlocked Panel movement within or
across Pages. Locks prevent destructive Page operations. Orientation is derived from Page width and
height; canonical order is `(order, id)`.

The Figure exporter has one explicit policy for all seven formats. SVG/TikZ/PNG/EPS emit numbered
per-Page files for multi-page documents; PDF preserves heterogeneous media boxes; editable PPTX
centres every Page at 1:1 on a presentation-wide maximum Page canvas; HTML embeds every Page and the
canonical source in one dependency-free viewer. PNG is fixed at 300 DPI RGBA. EPS accepts only the
vector SVG→PDF→Poppler path. Each output retains Page/source identity appropriate to its format.

`formula.py` normalizes a small non-executing formula subset into editable Unicode while retaining
the original source. Unsupported input is visible and explicitly marked invalid rather than
executed, discarded or silently mis-rendered.

## Responsive workspace and surface ownership

The desktop shell remains one grid with the canonical left workspace, canvas and Inspector. At
widths ≤800 px those same side elements become off-canvas drawers; compact canvas navigation calls
the canonical tab and Inspector controls, so no duplicate graph or editor state exists. Selection
updates the narrow Inspector entry and its context badge without opening a second inspector.

Menus, responsive drawers, workflow drawers and dialogs share one browser surface manager. Opening
one closes the previous surface, synchronizes `aria-expanded`/`aria-hidden` and inert state, owns the
backdrop, traps Tab within modal surfaces and returns focus to the opener on Escape, outside click or
explicit close. Breakpoint changes close stale narrow surfaces before restoring desktop columns.
Workflow dialogs keep title and actions outside an independently scrolling body; `dvh` bounds,
minimum touch targets, reduced-motion and forced-colors rules cover the tested narrow/short cases.

The 0.7 `WorkspaceStateMachine` replaces overlapping Graph/Figure/Scene mode booleans with one
active workspace and one saved context per workspace. It separately owns visible save state
(`clean/dirty/saving/saved/error/conflict`) and registered action state
(`idle/busy/success/warning/error`). Autosave compares the expected persisted revision before write;
a mismatch opens an application dialog showing current/stored summaries and requires an explicit
load-or-overwrite choice.

`CommandRegistry` is the shared command authority for toolbar/menu/palette invocation. Commands
carry category, shortcut, workspace availability, disabled reason and one execution handler; the
palette adds Graph/Scene object search and returns focus to its opener. Browser-local design-system
preferences persist four chrome themes, Comfortable/Balanced/Compact density, bounded sidebar widths
and the whole-Inspector pinned state; they are not portable Project 1.4 fields. Scientific content
density and palette remain document/editor choices, not application-chrome state.

## Package map

```text
nn_davinci
├── adapters       manual/config, ONNX, PyTorch FX/runtime, TensorFlow, Keras, JAXPR and MLIR
├── analysis       static metrics, runtime records, explainability and graph diff
├── layout         deterministic layered/domain layouts and collapsed graph views
├── render         grouped SVG, PDF/PNG/EPS conversion, TikZ and editable PPTX
├── web            dependency-free browser editor
├── ir.py          framework-neutral, versioned model semantics
├── semantic.py    five-level derived semantics, confidence, reasons and provenance
├── figure_ir.py   deterministic Page/Panel/Layer/object publication document
├── model_figure.py evidence-preserving Graph→Semantic→Figure pipeline
├── figure_export.py seven-format, multi-page rendering and provisional proof
├── scene_ir.py    deterministic Scene/Camera/Light/Layer3D/Group3D/Object3D document
├── scene_math.py  dependency-free world/camera matrices, projection, rays and intersection
├── model_scene.py evidence-preserving bounded seven-family Graph→Semantic→Scene pipeline
├── scene_projection.py deterministic physical CPU projection, occlusion and labels
├── scene_export.py native paper-vector/editable/raster/offline Scene outputs
├── scene_gltf.py  canonical Scene JSON plus embedded glTF 2.0 and binary GLB
├── units.py       exact point/millimetre/CSS-pixel and CTM conversions
├── text_layout.py deterministic Unicode wrapping and fallback records
├── formula.py     non-executing editable formula subset and invalid fallback
├── structure_lens.py bounded evidence, port/tensor and metric queries
├── viewport.py    bounded lazy slices and stable boundary proxies
├── tasks.py       persistent local jobs, cancellation, retry and result IDs
├── import_wizard.py non-executing format/safety/scale recommendations
├── optimizer.py   reviewable paper-layout metrics, diffs and proofs
├── real_models.py deterministic seven-model offline corpus and three-view evidence
├── composer.py    independent A/B/C/D panel state, proof geometry and figure export
├── paper_production.py evidence-based templates, candidates, captions and examples
├── diff_corpus.py fixed real-model ablation pairs and export evidence
├── trial.py       explicit-consent, privacy-allowlisted local JSON recorder
├── trial_models.py six independent offline workflow cases and compatibility report
├── trial_cases   framework-only model constructors with no recognizer hints
├── project.py     Project 1.4 envelope, contextual provenance and compatible 1.x migration
├── editor.py      command history for Python/headless editing
├── plugins.py     API-versioned discovery and error isolation
├── operators.py   extensible operator semantic registry
├── server.py      loopback-only Flask API
└── cli.py         automation and CI entry point
```

## Researcher Trial boundary

`TrialRecorder` is disabled by default and does not create its root until explicit protocol consent.
The server accepts only an exact event-specific field allowlist; unexpected model names, paths,
labels, identifiers or free text are rejected before persistence. Events are atomic mode-0600 JSON
inside a mode-0700 local directory. The browser can restore an active session after refresh, but no
upload or remote endpoint exists. Trial summaries deliberately leave serious semantic error review
unset because it requires a human comparison against source provenance.

The external trial corpus lives outside recognizer implementation: its PyTorch/ONNX constructors
import framework packages only and carry no NN_DaVinci tags. `trial_models.py` imports them through
the public adapters, builds Semantic View and paper candidates, composes block+operation Panels,
exports editable formats and performs a project round trip. The six-case Chrome workflow proves kit
readiness, never human usability.

For 0.7.1 the human-evidence state remains participants `0`, completed sessions `0`, and every
human time/success/ease/semantic-review metric `null`/N/A. Automated Chrome is a rendering and
workflow oracle, not a human participant.

## Import safety

Data formats are parsed without execution. Python model factories and pickle checkpoints are
explicit opt-ins. Runtime capture is initiated only by Python/CLI calls, not by a browser upload.
Adapters wrap errors with format, dependency and remediation context.

The import wizard performs a byte/name inspection before an adapter is invoked. It recognizes
PyTorch factories, TorchScript, state dictionaries, ONNX, Keras, TensorFlow, JAX, MLIR,
JSON/YAML and projects, then reports safety, sample-input requirements, an estimated scale and a
recommended framework/semantic/page view. Python and pickle are never executed by inspection;
trusted execution needs explicit confirmation. A state dictionary is reported as weight grouping
only because it cannot reconstruct topology.

## Semantic view

`derive_semantic_view()` indexes the source graph at `model`, `stage`, `block`, `layer` and
`operation`. Residual, attention, encoder/decoder, U-Net skip, repeated block, MoE router/expert,
timestep conditioning, modality fusion and diffusion-loop/component detectors emit confidence,
human-readable reasons and source provenance. A
detector that lacks sufficient evidence emits `unknown`; it does not infer a paper concept from a
name alone. `source_to_semantic` and `semantic_to_source` provide the reverse mappings used by
search, selection, comments, focus, analysis overlays, locked positions and manual routes during
level switches. Python, CLI, HTTP and Project 1.4 all carry `level` and `view`.

## Layout

The generic layout computes deterministic ranks, repeatedly applies barycentric ordering to
reduce crossings, respects direction, routes forward edges orthogonally and routes residual or
cyclic edges around the main path. Domain detectors add stable ordering for CNN, ResNet, U-Net,
Transformer, RNN, MoE, multimodal and diffusion graphs. Position/alignment/distribution/panel
constraints are applied after automatic placement; locked positions and user-dragged edge
waypoints are restored in final canvas coordinates. RNN cells can be expanded into editable time
steps. Collapsed groups become
aggregate proxy nodes while preserving external ports and cross-group connectivity.

Paper adaptation runs after semantic layout and before final rendering. It measures the natural
content box, chooses explicitly among single-column, double-column, widescreen and fit-content,
wraps oversized ranks into deterministic serpentine segments, and records scale, final body size,
occupancy and warnings. Residual, U-Net skip, attention, MoE routing, diffusion-loop and recurrent
edges receive semantic routes. Locked placements and manual edge waypoints are restored last and
the metrics are recomputed, so an impossible constraint produces an actionable warning instead of
being silently moved.

The 0.4.1 publication path, retained by 0.4.2, budgets the final physical page before panel layout. Composer viewBox
geometry and declared millimetres share one aspect ratio, so SVG/PDF text is never anisotropically
scaled. Pillow measures local DejaVu glyph advances for wrapping; nodes expand and row gaps are
redistributed without compressing glyphs. Sparse semantic summaries use balanced row spacing,
while dense operation panels must switch to a representative provenance-backed block or fail the
paper-ready proof. The landed SVG is then re-measured in Chrome and the landed PDF is independently
rasterized at 300 DPI; neither check consumes the generator's in-memory geometry as its authority.

The 0.3 optimizer evaluates node overlap, edge-node collision, crossing, bend count, path length,
symmetry, whitespace balance, label overflow, minimum font and critical-edge salience. It returns
at most three candidate layouts with before/after metrics and a geometry diff. Applying a candidate
is a separate action with an undo snapshot; locked placements, comments, annotations and manual
route interiors are protected. Proof previews use actual single-column, double-column,
wide-two-column and multi-panel dimensions. A readability request that cannot reach 7 pt reports
the blocking constraints.

## Real-model production and Figure Composer

`real_models.py` exposes seven deterministic CPU factories with fixed seeds and sample inputs:
torchvision ResNet50, a local Vision Transformer, BERT-like encoder, multiscale U-Net,
diffusion U-Net, top-k MoE and image–text fusion model. Factories never request pretrained weights.
Every entry is exercised as framework/module/operation Graph IR and then passed through the same
semantic recognizers used for imported user models; model display names are not recognition inputs.

The 0.6.1 completion corpus sends all seven entries through `model_figure_from_graph()` and records
the Graph/Semantic/Figure mapping, tensor/port provenance and bounded generation policy. Its Figure
artifacts are distinct from the seven bundled archetype templates even when their architecture names
match. Summary-first, focused and viewport generations exercise the same public pipeline.

`paper_production.py` chooses among eight evidence-based templates and returns no more than three
candidate layouts. A candidate records readability, geometry, critical-structure coverage,
aggregation and unknown semantics, but remains unapplied until the user accepts it. Caption text is
assembled only from Graph IR inputs, stages, evidenced connections and declared abbreviations.

The three built-in production examples materialize a stage-level Paper View plus a focused
operation detail selected from a high-confidence block. In 0.4.2, a module path locates only the
candidate boundary; directed boundary/path closure then retains selectors, every residual merge,
all merge inputs and the actual block output. Every paper edge records one or more ordered source
node/edge paths and a forward direction. Repetition signatures compare directed topology,
input/output shapes, operation types, parameter counts, scalar attributes, merge indegree and
optional projection branches. Unknown content stays `unknown`.

The U-Net overview uses the same closure rule at stage scale. Framework path evidence identifies
encoder/decoder scale regions, while unowned pool/interpolate/concat operations remain inside the
source path between aggregates. The resulting decoder aggregates have two evidenced inputs and
the three encoder–decoder skip edges remain distinct from sequential data flow. Graph IR inputs
keep their placeholder names; output names are assigned independently, and caption generation
states received inputs and produced outputs separately.

`verification/fixtures/scientific-fidelity/` contains executable golden graphs for ResNet50, ViT
and multiscale U-Net. `validate_scientific_fidelity.py` reads the landed `.nndv.json` projects,
replays each edge-ID chain against Graph IR, and blocks release on missing roles, key edges, merge
indegree, source-path provenance, repeat counts or caption facts. This `SCIENTIFIC-FIDELITY`
acceptance is additive to the 0.4.1 publication-quality acceptance.

`FigureComposer` owns shared figure settings and one to four independent `FigurePanel` records.
Each panel carries its own source graph, semantic level/view, layout, locks, manual routes and
annotations. Composition transforms already-laid-out panels into a common page; a single-panel edit
reuses other panel digests instead of performing a global relayout. Cross-panel arrows use the
`semantic-connection` kind plus `not_model_data_edge=true`, so they cannot be confused with tensor
flow. Project 1.4 serializes this inherited Composer state alongside Figure and Scene documents. Whole-figure SVG/PDF/TikZ/PNG/EPS/PPTX and optional
per-panel TikZ are produced from the composed Graph IR and layout.

The 0.5.1 recovery path treats a composed canvas as fixed physical geometry only when three records
agree: the serialized `FigureComposer` Panel IDs, Graph IR `figure_composer.panel_count`, and the
layout's per-Panel digests/transforms. Valid state is hydrated through one browser path for startup,
recent-project recovery and `.nndv.json` import, so it is rendered without a generic Graph relayout.
Project canvas state additionally carries the viewBox, zoom and fixed-layout flag. Empty legacy
`figure_composer` objects are rejected as inactive and safely fall back to a new default Composer.
Composer control edits, Panel changes, node locks and manual routes schedule the same local autosave;
undo/redo snapshots carry the Composer and fixed-layout state as one unit.
The active Trial session has a separate, session-ID-scoped local runtime record for semantic/node/
edge/label edit counters and one-shot milestones. It contains no model name, path or free text and is
discarded when the server reports that the session ended. This prevents a refresh between T4 and T5
from replacing the final edit summary with zeros while leaving the frozen Trial event schema unchanged.

The 0.5.2 Composer entry is deliberately explicit: `Figure Composer（多 Panel）` opens before
preview work starts and presents source Graph, Semantic View, level, Panel count and readiness. A
new universally valid composition starts with Panel A `Semantic blocks` at block/paper and Panel B
`Operation evidence` at operation/paper. Existing valid Composer state wins over these defaults, and
one initialization marker prevents repeated clicks from appending another A/B pair. Preview/export
operations expose busy, success, warning, failure and retry states while keeping the dialog usable.

The enhanced comparison path performs stable exact/probable matching, reports confidence and
unmatched nodes, and retains both models' operation IDs for aggregated matches. It offers
side-by-side, overlay, change-only and summary views. A weight-only state dictionary remains
explicitly outside the structural-comparison claim.

## Rendering

Graph rendering and Figure rendering remain distinct. In Figure Studio, `compile_figure()` creates
one deterministic set of physical primitives from Figure IR. Corrected per-Page SVG is the
canonical final geometry for SVG/PDF/PNG/EPS/HTML. TikZ and editable PowerPoint consume the same
compiled Figure primitives, including the same line breaks, point sizes, source IDs and Page order.
Every Figure object is a named source-linked group or editable shape rather than a full-page raster.

PDF and EPS are vector conversions of corrected Page SVG; PNG is the intentional 300-DPI raster
format. TikZ preserves explicit point fonts/lines. PPTX preserves editable text, panels, tensor
faces and connectors. HTML embeds Page SVG plus canonical Figure source and rejects non-embedded
external assets to keep its no-network promise.

The legacy Web `presentation.perspective_mode` remains a CSS transform of the 2D SVG and intentionally
is not called a 3D network view. Scene Studio is a separate renderer/document: it has world-space
meshes/routes, cameras, projection matrices, depth testing, CPU projection and Scene provenance.

The browser runtime deliberately keeps a no-build architecture: `app.js`, `scene-renderer.js`,
`scene-interactions.js`, `commands.js`, `state-machine.js`, `styles.css`, `design-system.css`, and
`scene-studio.css` are served as package data, so an installed wheel needs no Node runtime or CDN.
Prettier normalizes the source and ESLint checks the editor/modules/E2E in the development/release
workspace.

## Large graphs

Synchronous full rendering remains rejected above 2,000 nodes or 12,000 edges. Separately, the
server stores the source graph and exposes summary, semantic-level, viewport-slice, neighborhood
and search APIs. A viewport slice contains at most 500 real/proxy nodes and estimates at most
2,000 SVG DOM objects. Cross-viewport connections terminate at stable proxy IDs and stubs. The
browser therefore constructs only visible nodes, related edges and required boundary proxies;
pan/zoom replaces the bounded slice, not the full graph. Search and selection resolve against the
server-side source graph, and per-level viewport state restores the previous location after drill.
For very large inputs the first summary defers the complete semantic index, uses only explicit stage
boundaries or an honest unknown model proxy, and preserves the 500-node/2,000-object limits. This is
the path used by the 50k product gate; operation detail remains available through bounded slices.

## Local task center

Import, analyze, layout, runtime and export use one local task record with
`queued/running/succeeded/failed/cancelled` states, stage, progress, elapsed time, input scale and
resource budget. Cooperative work checks cancellation between phases; task/result IDs and JSON
records survive browser refresh and loopback-server restart. Failures include recovery actions.
Export artifacts and records are retained under a UID-scoped temporary task root and cleaned by a
bounded retention policy. This is a single-user loopback service, not an account or permission
boundary.

## First-use and plugin boundary

The Start Center is a view over existing local APIs: new/import/open, seven offline examples,
the exact seven editable 3D Scene templates (CNN, ResNet, U-Net, Transformer, MoE, Multimodal Fusion,
and Diffusion U-Net), recent recovery and a short tutorial. Each Scene card opens a real non-empty
template-only Scene rather than a blank placeholder. Command palette, global search,
context help and issue navigation all dispatch the same editor actions. Autosave is debounced and
scheduled with `requestIdleCallback` when available; recovery restores project and Composer state
without making a network request. Browser workflow metrics are explicitly automation-only.

The release driver owns evidence binding: it records at least 44 browser screenshots, all ten Scene
format downloads, and an independent visual report alongside exact inherited regression, corpus,
migration and performance reports. Source documentation describes this contract but does not infer a
run result; only the new artifact's `verification.json` may declare one.

Plugin API 2.0 versions adapter, semantic-recognizer, layout, analyzer, theme and exporter
capabilities and negotiates them before loading. A plugin exception is converted to an isolated
failure record (or an explicit unknown semantic detection) rather than terminating the editor.
Loading a local plugin is an explicit `allow_local_code` operation: it executes unsandboxed Python
in the local server process. There is no remote installer, online store or automatic unknown-code
execution.

## Web and import boundary

The loopback Flask service caps requests at 16 MiB and in-memory form data at 2 MiB, applies an
upload extension allowlist, rejects malformed/deep JSON and malformed ONNX with 4xx responses,
and preserves Werkzeug HTTP status codes. Standalone HTML uses a restrictive CSP and creates the
inspector with `textContent`/`replaceChildren`; external image references are removed unless they
are embedded image data URLs. Python factory and pickle loading remain explicit trusted-input
opt-ins outside the browser's implicit import path.
