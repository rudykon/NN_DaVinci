# Design requirement coverage (0.7.2)

This matrix preserves the inherited FR-01–FR-42 contract and adds the 0.7.2 scientific-fidelity hotfix requirements below. Framework-backed rows run only when their optional dependency is installed; their verified scope is bounded by `COMPATIBILITY.md`. An implementation path is not by itself a release PASS: the feature-completion matrix and fresh artifact own acceptance status.

## 0.7.2 scientific-fidelity requirements

| ID | Requirement | Release evidence |
|---|---|---|
| FR-43 | Architecture recognition is derived from Graph topology, importer-declared operation/module identity, ports/tensors and source-ID-backed Semantic detections; names, keys, filenames, class names and layout requests are excluded | exact positive and negative Python cases plus landed corpus records |
| FR-44 | Evidence records family/confidence/reasons, exact source IDs, roles, repetition, critical routes, uncertainty, source digest and provenance digest | seven real-model Architecture Evidence documents |
| FR-45 | Graph IR, Semantic View, Figure IR and Scene IR remain independently serializable and agree on every protected role, route, repeat count, tensor contract and provenance ID | independent landed parity reports; producer builders are not called by the oracle |
| FR-46 | ResNet, Transformer/BERT, U-Net, diffusion U-Net, top-k MoE and multimodal fusion retain their architecture-specific critical routes with zero omission | seven non-unknown real models and seven zero-critical-omission reports |
| FR-47 | Scene PDF uses packaged embedded fonts, Unicode maps and no Base-14 fallback; TikZ compiles in a writable offline TeX cache | all fourteen PDF/TikZ publication-oracle cases |
| FR-48 | Initial Scene open frames real world bounds and commits camera state without mutating object geometry | camera Python tests and retained Chrome Scene workflow |
| FR-49 | Fresh release validation preserves every exact 0.7.1 test ID and all four parent coverage floors, regenerates 14×10 exports, and verifies the pinned parent source/artifact read-only | quick/full report and sealed artifact |

| Requirement | Implementation evidence |
|---|---|
| FR-01 imports | `adapters/`: PyTorch/model factory/state dict, ONNX, TensorFlow GraphDef/SavedModel, Keras, JAXPR, MLIR, safe Python config, JSON/YAML and manual authoring; dynamic/input semantic/hide/expand options |
| FR-02 Graph IR | `ir.py`: ports, tensors, nodes, edges, hierarchy, source IDs, sharing, analysis, tags and constraints |
| FR-03 hierarchy | Independent Semantic View 1.0 derives model/stage/block/layer/operation levels with confidence, reasons, source node/edge provenance, explicit unknowns, Faithful/Paper modes and bidirectional traceability; Web breadcrumb/tree/drill/up/restore controls preserve source selection and per-level canvas state |
| FR-04 layout | Stable layered/radial plus CNN, ResNet, U-Net, Transformer, RNN time-unroll, MoE, multimodal and diffusion strategies; paper-aware wrapping/segmentation, `×N` aggregation, 7 pt guard, locked constraints, bounded neighborhood focus and lazy viewport views |
| FR-05 themes | NeurIPS, IEEE, ACM, grayscale, colorblind, dark and teaching; page/font/weight/color/opacity/spacing/arrow/dash/shape/parameter/FLOPs overrides |
| FR-06 vector export | Independent-group SVG, vector PDF, TikZ; also PNG, EPS and editable PPTX |
| FR-07 editing | Web and `GraphEditor`: node and edge-waypoint drag/grid snap, edge rerouting/style, connect, align, distribute, multi-select, copy, lock, hide, group, icons/images, zoom/arrow/region/formula/panel annotations and history |
| FR-08 static analysis | Parameters, trainable parameters, FLOPs/MACs, shapes/dtypes, activation bytes, depth, receptive field and bottlenecks |
| FR-09 runtime | PyTorch leaf execution order plus TorchLens operation graph, actual tensors/gradients, timing, peak GPU memory/location, dynamic/unexecuted paths, NaN/Inf and graph linkage; public API and CLI |
| FR-10 explainability | Unified TorchCAM methods, input gradients, feature/channel and attention capture linked by module path |
| FR-11 comparison | Stable exact/probable/unmatched matching with confidence; added/removed/modified/moved/share/shape/parameter/FLOPs differences; side-by-side/overlay/change-only/summary views and operation provenance |
| FR-12 entry points | Local Web UI; `draw()`/`semantic_view()`/runtime/explain plus `scene_from_graph()`/`render_scene()` Python APIs; level/view CLI; render/analyze/runtime/explain/compare/project/scene/reproduce/validate/batch/report workflows |
| FR-13 reproducibility | Project schema 1.4 contains model/input/Graph/Semantic/Figure/Scene/theme/layout/analysis/plugin/environment/artifact and UI state; compatible 1.x documents migrate explicitly, with 1.3→1.4 adding only an empty Scene and no inferred facts |
| FR-14 plugins | Plugin API 2.0 capability negotiation and failure isolation for adapter/semantic-recognizer/layout/analyzer/theme/exporter, explicit local-code trust, migration errors and runnable template |
| FR-15 semantic recognition | Residual, attention, encoder/decoder, U-Net skip, repeated block, MoE router/expert, timestep conditioning, modality fusion and diffusion loop/component detectors; uncertain structure stays `unknown` and every result records source node/edge evidence |
| FR-16 lazy canvas | Server summary/semantic/viewport/neighborhood/search APIs; stable cross-viewport proxies; at most 500 visible nodes and 2,000 estimated DOM objects; synchronous full-render rejection remains active |
| FR-17 task center | Persistent queued/running/succeeded/failed/cancelled jobs for import/analyze/layout/runtime/export with stages, progress, elapsed time, scale, budget, cooperative cancellation, retry, recovery guidance and artifact IDs |
| FR-18 import wizard | Non-executing format detection, explicit Python/pickle trust, sample/multi-input/shape/dtype/dynamic-axis guidance, scale estimates, semantic/page/label recommendations, diagnostics and reproducible configurations |
| FR-19 paper optimizer | At most three opt-in geometry diffs with ten before/after metrics, undo, protected manual constraints, six presets, four real paper proof sizes and explained 7 pt failures |
| FR-20 real-model corpus | Seven deterministic offline CPU factories with fixed sample input/seed/parameters/shapes, framework/module/operation views, semantic provenance and three-run time/RSS compatibility report |
| FR-21 Figure Composer | Independent A/B/C/D panels, shared figure semantics, alignment/equal-size/gap controls, distinct cross-panel semantic arrows, physical proof and whole/split export |
| FR-22 one-click paper figure | Evidence-based level/page/template/density/theme recommendation, up to three reviewable candidates, eight architecture/task templates and a non-fabricating caption draft |
| FR-23 production exports | A composed Figure exports SVG/PDF/TikZ/PNG/EPS/editable PPTX/HTML; Scene adds independent CPU projections in the same paper formats plus Scene JSON/glTF/GLB; `.nndv.json` remains the Project envelope |
| FR-24 first-use workflow | Start Center, exact seven editable 3D Scene templates, explicit Graph/Figure/Scene switcher, command registry/palette, global object search, shortcuts/help/issues, visible autosave state, network-free examples and in-browser end-to-end paths |
| FR-25 product scale | Three-run 10k/50k evidence with hardware/input sizes; Graph and Scene open through summary/focus, visible Scene target ≤250 by default (≤500 release bound), DOM ≤2,000, isolated updates, and no synchronous full-mesh expansion |
| FR-26 paper examples and diff corpus | Three original real-model paper projects with vector/editable artifacts, proof/caption/provenance/quality/steps plus three fixed real-model comparison pairs and machine-readable reports |
| FR-27 scientific fidelity | Paper details use directed boundary/path closure; every paper edge has ordered source-path provenance; merge indegree, input/output ports and shapes are retained; repetition compares topology/shapes/attributes/optional branches; ResNet/ViT/U-Net executable golden graphs and caption facts are release-blocking |
| FR-28 consented Trial Mode | Recording is disabled by default; explicit protocol consent gates a strict event allowlist stored as local JSON with no model/path/label/identity/free text and no upload; revoke/export/refresh recovery are supported |
| FR-29 external trial corpus | Six framework-only offline cases cover dynamic PyTorch, dynamic ONNX multi-I/O, shared modules, Transformer residuals, U-Net skips and explicit custom unknown; each completes Web semantics, Paper View, Composer, project recovery and editable exports |
| FR-30 venue proof | An NN_DaVinci PDF and editable TikZ figure compile under official NeurIPS 2026 and ICML 2026 styles plus local IEEEtran, and each compiled PDF is independently rendered at 300 DPI |
| FR-31 honest human evidence | Chrome/AI/developer runs are labelled automated and never count as participants; unavailable human observations remain null and the Beta report pauses human conclusions until 3–5 real ML researchers complete consented tasks |

## 0.7.0 true-3D and UX requirements retained by 0.7.1

These requirements are additive. They do not replace or weaken FR-01–FR-42, the exact 328 inherited 0.7.0 Python test IDs, retained coverage floors, 7 pt publication minimum, landed-output oracles, or scientific-fidelity gates.

| Requirement | Normative implementation | Acceptance boundary |
|---|---|---|
| FR-32 Scene IR 1.0 | `Scene`, `Camera`, `Light`, `Layer3D`, `Group3D`, `Object3D`; deterministic IDs/digest; local XYZ position/Euler **degrees**/scale; composed world records; camera-bound projection records; material, visibility, lock, selection, author state and migration history | strict schema/runtime round-trip, non-finite/cycle/dangling/unsafe/oversize rejection, world unchanged by camera motion |
| FR-33 Project 1.4 | required explicit `scene_ir`; contextual Graph↔Semantic↔Figure↔Scene provenance validation; workspace-aware replay | 1.3 migration creates only an empty Scene and records no inferred geometry, shape, semantic role or provenance |
| FR-34 scientific 3D primitives | tensor volumes/stacks, planes, operation/conv/pool/scale blocks, residual/U-Net/attention/QKV/MoE/multimodal/diffusion structures, frames/labels, arrow/tube/polyline/bezier routes | symbolic/dynamic/unknown dimensions remain symbols/`?`; visual extent never overwrites tensor facts |
| FR-35 seven Scene grammars | CNN, ResNet, U-Net, Transformer, MoE, Multimodal Fusion and Diffusion U-Net templates plus model conversion | templates use template-only provenance; model-derived special roles require exact Graph/Semantic evidence; name-only inference fails closed |
| FR-36 true-3D interaction | WebGL2 model/view/projection matrices and depth buffer; procedural meshes and authored route segments; projected, collision-avoiding Scene labels; orbit/pan/zoom/views/projection; ray and marquee selection; XYZ edit/snap/align/distribute; group/lock/hide/isolate/focus/explode/material/depth state; cross-workspace evidence selection | camera rotation changes projection but not world coordinates; routes are drawn from endpoints/control points rather than origin placeholders; different-depth picking is ordered; save/refresh/undo restore Scene context; known UI omissions remain documented |
| FR-37 independent projection/export | CPU `ProjectedScene` with camera matrices, depth ordering, basic occlusion/hidden lines, vector faces/routes, physical strokes, billboard labels/avoidance and >=7 pt text; SVG/PDF/TikZ/editable PPTX/PNG/EPS/offline HTML plus Scene JSON/glTF/GLB | vector formats contain native primitives rather than WebGL screenshots; PNG is 300 DPI; GLB has non-zero XYZ mesh/node data; landed outputs require independent validation |
| FR-38 WebGL fallback/offline safety | local packaged browser code, no CDN; WebGL failure requests CPU SVG and shows explicit state; unsafe/external assets rejected | fallback selection/save/export remains operable; HTML performs no runtime network request; failure is never silent |
| FR-39 design system and commands | 4/8 px tokens; Light/Dark/High Contrast/Paper; local fallback fonts; Comfortable/Balanced/Compact; <=7 shell groups; contextual toolbar; shared Ctrl/Cmd+K registry and surface state | command availability/disabled reason, keyboard navigation, focus restoration, ARIA, busy/success/warning/error/retry; no browser prompt/alert/confirm in new workflow |
| FR-40 responsive/information density | resizable persisted sidebars; <=800 px canonical drawers; Graph/Figure/Scene contexts; Graph/Figure compact/paper/detailed labels; Scene semantic level/view and bounded summary/focus; evidence detail in Inspector/Lens | exact 1920×1080, 1440×900, 1280×720, 1024×768, 800×600, 568×320 and 390×844 Chrome matrix; no horizontal overflow/surface escape/toolbar overlap; desktop canvas >=60%, narrow closed-drawer canvas >=70% |
| FR-41 performance/regression | three-run Scene interactive/projection/interaction/selection metrics; 10k/50k summary/focus bounds; retained Figure benchmark | <=250 interactive <=500 ms; 1000 <=1500 ms; 500-object orbit p95 <=20 ms; selection median <=100 ms; retained 2D median regression <=20% |
| FR-42 release evidence | seven templates plus seven real-model Scenes, each with Project and ten Scene outputs; comparisons for real models; migration, interaction, visual, performance and verification reports | one fresh artifact only; no old artifact as current input; failed full remains failed until a separate fresh replacement passes |
| FR-43 honest Beta boundary | machine evidence and human evidence remain separate; local server/plugin/trusted-code limits are visible | participants=0, completed sessions=0, all human outcome metrics null/N/A; no Git/upload/publication claim |

### Acceptance contract

Implementation and focused checks cover FR-32–FR-40. In particular, `nnviz project --workspace scene` now persists its exact Semantic View document and passes focused create→validate→reproduce checks. The responsive harness measures the FR-40 canvas area against the full viewport: 0.691117/0.625341/0.614173/0.617669 at 1920/1440/1280/1024 and 0.900000/0.812500/0.928910 at 800/568/390 with both responsive drawers closed, satisfying the 60%/70% thresholds. WebGL renders actual routes and projected Scene labels, and Start Center exposes exactly the seven required editable Scene template families.

FR-42 is evaluated only by the clean release driver. That driver binds the exact inherited-ID and coverage reports, corpus/performance/migration evidence, at least 44 browser screenshots, ten non-empty Scene format downloads, and an independent visual report. The screenshot manifest covers all four themes, all seven exact viewports, seven real-architecture 2D/3D pairs, and all seven editable 3D template families. Producer booleans are insufficient. The 0.7.2 driver additionally blocks on landed scientific parity, fourteen SVG Chrome results, embedded-font PDF/compiled-TikZ results, truth fixtures, and fourteen parent/current before/after proofs. The outcome and run ID belong exclusively to `artifacts/v0.7.2/<run_id>/verification.json`.

## 0.7.1 publication and interaction completion

| ID | Requirement | Executable acceptance |
|---|---|---|
| FR-43 | All fourteen fixed Scenes must be paper-readable with semantic label budgets, automatic framing and decorative-frame exclusion | 14 individual Chrome SVG verdicts; minimum 7 pt; occupancy 55–90%; zero collision/clipping/crossing classes |
| FR-44 | PDF and compiled TikZ PDF must independently preserve page, text, font and major-object geometry | Separate cross-format oracle with format/true-3D/publication statuses |
| FR-45 | The visual gate must have known-truth positives, negatives and mutations and reject a constant-true validator | Fixture report covers label stack/object, clipping, starburst, frame, text scale and toolbar truncation |
| FR-46 | Scene authoring must expose XYZ gizmo, local/world, full XYZ layout, Ungroup, tree collapse/filter and six-group Inspector with per-property pins | Product tests and browser assertions over visible, live controls |
| FR-47 | Compact/Paper/Detailed density and four complete themes must affect the Scene canvas and proof | Monotonic projection tests, theme screenshots and WebGL clear-color assertion |
| FR-48 | Scene batch must isolate failures and cancel remaining work | Deterministic success/failure/cancel test plus browser dialog assertions |

## 0.5.0 Researcher Trial Kit

The release-blocking portion of 0.5.0 is kit readiness: privacy schema, six model workflows, venue
compilation, participant-facing documents and honest status reporting. Human target evaluation
(first figure median ≤5 minutes, paper-ready ≤15 minutes, task success ≥80%, serious semantic
errors 0) becomes authoritative only after real participants exist. An automated E2E may verify that
the workflow is operable, but cannot pass or populate those human measures.

## 0.5.1 Composer state recovery hotfix

The hotfix is limited to the participant's existing save/recovery path. A composed project must
restore shared Composer controls, Panel order/title/semantic level/view, cached independent layouts,
locked nodes, manual edge routes, annotations, physical page geometry, viewBox and zoom after both a
browser refresh and reopening the downloaded `.nndv.json`. Recovery must reuse the stored physical
layout only when Composer, Graph IR and layout metadata agree; malformed or empty legacy Composer
state must fall back safely. A real-Chrome regression reproduces the participant sequence of compose,
drag, reroute, save, refresh, reopen Composer and reopen the project, and compares Panel layout
digests and manual edit counts before/after. This automated regression is product evidence only and
does not count as a trial participant.
The active consented Trial session must also retain its anonymous semantic/node/edge/label counters
across that refresh, so the final `edit_summary` describes the performed edits instead of a new empty
browser state. This local runtime state is keyed by the stable session ID, contains no model/path/free
text and is cleared when the session ends; the 0.5.0 event schema is unchanged.

## 0.5.2 Responsive Workspace & Pilot UX Hotfix

This is an additive interaction contract and does not renumber the frozen FR-01–FR-31 mapping.
Desktop widths keep the canonical three-column editor. At ≤800 px, the same component/library,
structure, analysis and Inspector DOM surfaces become focus-managed drawers reachable from compact
canvas navigation; a selected item must leave an obvious Inspector entry and context indicator.

Toolbar menus, responsive drawers, workflow drawers and dialogs are mutually exclusive. Escape,
outside click, backdrop and explicit close must synchronize ARIA state and restore opener focus;
modal surfaces trap forward and reverse Tab. A resize across the 800 px boundary must remove stale
backdrops, inert state and open-surface classes. Workflow dialogs have fixed title/action regions and
an independently scrolling body, fit short landscape and phone viewports without horizontal overflow,
and respect reduced motion, forced colors and touch-size controls.

`Figure Composer（多 Panel）` is a visible Paper-production action. Opening it must immediately
show the current Graph, Semantic View, level, Panel count and readiness or an actionable empty state.
A new graph gets exactly Panel A `Semantic blocks` / block / paper and Panel B
`Operation evidence` / operation / paper; a saved valid composition is restored instead, and repeated
open actions cannot duplicate initialization. Preview, import, analysis, layout, save and export must
distinguish pending/busy, success, warning, failure, cancellation and retry without browser-native
prompt dialogs or unhandled promise failures.

Real-Chrome acceptance covers exactly 1440×900, 1024×768, 800×720, 768×720, 568×320,
390×780 and 320×568. It gates geometry, overflow, keyboard/focus behavior, surface layering,
breakpoint cleanup, bounded dialogs, zero browser errors and the narrowest operable loop:
import model → block view → Paper View → default Composer A/B → save project → export SVG.

P2 evidence: TensorFlow/Keras/JAX adapters; editable PPTX/EPS; portable collaboration metadata,
authors and resolvable comments; concurrent batch generation; deterministic captions/reports; data
flow teaching animation and an optional 2D perspective presentation mode.

0.3.0 browser acceptance adds a real Chrome workflow that imports a model, drills from model to
block and operation, searches and inspects analysis provenance, switches to Paper View, compares
and applies an optimizer diff, manually moves a node and edge route, saves/reloads the project and
exports SVG, PDF, TikZ and editable PPTX. The scale workflow imports a real 10,000-operation JSON
graph and gates first interaction, visible-node and SVG DOM bounds. The previous 10 browser
scenarios remain unchanged and passing.

0.4.0 adds a second real Chrome product workflow. It starts at Start Center, opens an offline real
model, drills and searches, inspects analysis evidence, compares/applies a paper candidate, builds
and edits a multi-panel figure, exports the Composer bundle/project, refreshes autosave recovery,
opens a 50,000-operation semantic summary and cancels a local task. The report records automated
click/step/recovery/first-figure metrics and explicitly does not claim a human usability study.
Full acceptance also constructs all seven real models, emits the three paper examples and three
diff pairs, and records three runs for every performance gate. The inherited 130 Python tests and
both older Chrome suites remain separate regression inputs rather than being replaced by new test
counts.

## 0.4.1 publication-quality hotfix

The release is blocked unless all three real paper examples are regenerated from local executable
models and independently pass at the final 178 × 118 mm double-column size. Each example must use
a stage/block semantic overview and a bounded representative detail with `×N` aggregation and
bidirectional node/edge provenance; a complete operation graph may not be fitted into half a panel.

The landed SVG/PDF acceptance requires minimum font ≥ 7 pt; zero label overflow, node overlap,
edge-node collision, clipping and unexplained crossing; horizontal and transform text scale exactly
1.0; no title/legend/group-label collision; and balanced page/panel occupancy. The PDF page points
must equal the proof millimetres and a fresh `pdftoppm` rendering must be 300 DPI with matching pixel
dimensions. Before/after PNGs are comparison outputs only and are never a passing input.

If these predicates cannot be met, Composer must choose a coarser semantic level, a representative
block, balanced panel ratios or another panel. It must not reduce the font below 7 pt or label the
result paper-ready. The publication acceptance is a product release blocker in addition to, not a
replacement for, the inherited 143 Python tests and Chrome workflows.

## 0.4.2 scientific-fidelity hotfix

0.4.2 keeps every 0.4.1 physical and Chrome predicate, and adds a separate
`SCIENTIFIC-FIDELITY` release blocker. ResNet50 must distinguish 16 bottleneck bodies, four
projection transitions and 12 identity bottlenecks; the selected Layer 1 identity detail has two
exact shape/topology equivalents. The ViT detail must contain both attention and FFN residual
merges with indegree two. The U-Net overview must contain three encoder scales, a bottleneck,
three decoder scales, three directed skip edges and decoder merge indegree two.

The independent validator consumes the landed project, not an in-memory generator claim. It
replays every ordered source edge ID against Graph IR, checks aggregate endpoints and direction,
compares executable golden roles/key edges/repeat counts, rejects an input named `output_0`, and
requires captions to distinguish received inputs from produced outputs. Missing or uncertain
evidence is reported as unknown rather than replaced with a model-name inference.

The matrix describes implemented surfaces, not universal framework compatibility. Tested and
experimental boundaries are recorded in `COMPATIBILITY.md`. Optional framework imports fail with
actionable errors. Static analysis, JSON diagrams, SVG and TikZ run without a GPU.
