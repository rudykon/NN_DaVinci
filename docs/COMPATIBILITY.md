# Compatibility matrix for 0.7.2

This is an evidence boundary, not a claim that every model from a named framework or architecture is supported. "Inherited tested" means the invariant belongs to the frozen 0.7.1 acceptance and must pass again under the exact 342-ID regression gate. "Focused tested" means new 0.7.2 behavior has direct developer test evidence but is not release-authoritative until the fresh full artifact records it. "Experimental" means a path exists but the fixed corpus does not establish a broad guarantee. "Unsupported" means an input is deliberately rejected or cannot be reconstructed from the supplied information.

## 0.7.1 Scene and Project compatibility

| Surface | Implemented/focused contract | Release status |
|---|---|---|
| Scene IR | deterministic 1.0 JSON; stable IDs; nested Group/Object transforms; Layer visibility/lock/order scope; cameras/lights/materials; visibility/lock/selection; strict parser and budgets | focused Python checks; release outcome is artifact-owned |
| Rotation | Object/Group/Camera Euler rotation is stored in degrees across Python, JSON, and browser fields | focused world/matrix tests pass |
| Project | schema 1.4 requires explicit Scene IR; 1.3 migration creates an empty Scene and records that no geometry/semantics/provenance was inferred | focused round-trip/migration checks; full driver binds the migration report |
| Model→Scene | bounded Graph→Semantic→Scene conversion with bidirectional indexes for materialized evidence and optional Figure references; >10k summary mode uses explicit digests/bounded representatives | focused seven-family/provenance tests pass |
| Scene templates | CNN, ResNet, U-Net, Transformer, MoE, multimodal fusion, diffusion U-Net; exact seven Start Center cards; editable, non-empty, and template-only | focused template/API/UI checks; full driver requires seven landed 3D captures |
| Browser renderer | local WebGL2, world/model/view/projection matrices, depth buffer, procedural meshes, true route segments, projected collision-avoiding labels, perspective/orthographic cameras | focused renderer/E2E checks; full driver binds the browser and independent visual reports |
| Static fallback | server CPU SVG for current camera, then deterministic local SVG if the request fails; visible fallback state | wired and E2E exercised; fallback remains driver/browser dependent |
| Interaction | orbit/pan/wheel zoom, named views, camera lock, ray pick, additive/marquee selection, numeric and gizmo XYZ transform/snap, local/world axes, full align/distribute, Group/Ungroup, tree collapse/filter, lock/hide/isolate/focus/explode, opacity/depth spacing | focused browser, Node and Python tests; object-level primitives, not mesh-component CAD |
| CPU projection | camera matrices, depth sort, basic occlusion, back-face/hidden-edge policy, vector faces/edges/routes, billboard/avoided labels, >=7 pt, physical stroke | focused projection tests pass |
| Paper formats | native SVG/PDF/TikZ/EPS, editable PPTX, 300-DPI PNG, offline HTML | focused export/corpus checks; full driver binds landed format oracles |
| World formats | canonical reloadable Scene JSON, embedded glTF 2.0, binary GLB with real XYZ mesh data, cameras/materials/IDs/provenance | focused format/parser/corpus checks; full driver binds landed hashes |
| Python/API/CLI | `scene_from_graph`, `render_scene`, Scene template/generate/project/pick/transform/export HTTP routes, `nnviz scene`, and Project create/reproduce/validate | focused direct Scene/API checks and `project --workspace scene` create→validate→reproduce pass; the CLI persists the exact `semantic_view.document` |

The paper-vector exporters consume only the deterministic CPU `ProjectedScene`; none captures WebGL. SVG rejects images/foreign objects/external resources, PDF rejects Image XObjects, TikZ rejects `includegraphics`, PPTX rejects flattened media, and EPS rejects raster image operators. PNG is intentionally raster.

glTF uses an embedded binary data URI and GLB contains its binary chunk. External/network asset URIs, executable URIs, malformed embedded data, unsafe prototype-style keys, unsupported Scene fields, non-finite transforms, duplicate/dangling IDs, cycles, and incompatible major versions are rejected. Third-party 3D geometry does not acquire model semantics merely because it is spatially near a model object.

## 0.7.1 browser/environment boundary

The Web editor requires a modern browser with ES2020-class JavaScript, SVG, `dialog`, Pointer Events, and local storage. WebGL2 is optional because the explicit CPU SVG fallback remains usable. The installed package carries JavaScript/CSS locally and requests no CDN/runtime network dependency.

The required responsive sizes are 1920×1080, 1440×900, 1280×720, 1024×768, 800×600, 568×320, and 390×844. Full-viewport focused canvas ratios are 0.691117/0.625341/0.614173/0.617669 on desktop and 0.900000/0.812500/0.928910 on narrow screens with drawers closed, so every 60%/70% area gate is met. The full browser contract produces at least 44 screenshots covering four themes, all seven viewports, seven real-model 2D/3D pairs, all seven editable 3D templates, and workflow/fallback/error states, plus ten non-empty downloads and an independent visual report. Release status is read only from the artifact's `verification.json`.

## Inherited 0.6.1 Scientific Figure Studio formats

The 0.6.1 gate instantiates all seven bundled templates and all seven seeded offline real models,
passes model examples through Graph IR → Semantic View → Figure IR, and independently validates
all seven export formats. This is a bounded format/evidence contract, not a promise of pixel
identity in every external editor or support for every model from a named architecture family.

| Surface | Tested 0.6.1 contract |
|---|---|
| Figure IR | deterministic 1.0 JSON, global ID/constraint validation, explicit provenance, heterogeneous Pages and A–H Panels per Page |
| Project | schema 1.3 round-trip; compatible 1.x migration adds an empty Figure IR without inferred facts |
| Tensor Geometry | NCHW/NHWC, BTD, matrix/vector/scalar, symbolic/dynamic/unknown and multi-I/O vector glyphs |
| Units/text | exact 72 pt = 25.4 mm and CSS 96 DPI conversion; deterministic Unicode/manual wrapping/fallback records; no compression or text below 7 pt |
| Native SVG | valid XML plus digest-checked `nndv-figure-svg-metadata-1` round-trip; final DOM/CTM geometry re-measured by an independent Chrome oracle |
| Third-party SVG | imported only as an external vector group; no model semantics are claimed |
| PDF | one page per Figure Page, including heterogeneous sizes; embedded fonts and extractable text are checked independently |
| TikZ | one standalone source per Figure Page, compiled with `pdflatex` |
| PPTX | one editable slide per Figure Page; heterogeneous Pages are centred 1:1 on a maximum-size slide canvas; no full-page raster picture |
| PNG | one 300-DPI RGBA image per Figure Page with Page/source metadata and explicit alpha policy |
| EPS | one EPSF Level 3 vector file per Figure Page with font resources; raster fallback is rejected |
| HTML | one dependency-free offline multi-page viewer retaining canonical Figure IR and per-page SVG DOM |
| Formula | safe non-executing editable subset plus explicit invalid-formula fallback; original source retained |
| Chrome | Page and Figure workflows at 1440/800/390 px; strict landed-SVG oracle has no console/page/request errors |

Seven template archetypes cover CNN, ResNet, U-Net, Transformer, MoE, multimodal fusion and
diffusion U-Net. They contain symbolic/template evidence, not pretrained model facts, accuracy or
paper conclusions. The separately generated seven real-model Figures use fixed-seed offline CPU
constructors and carry Graph/Semantic/Figure provenance; similarly named templates are not accepted
as substitutes for those model-derived artifacts.

Multi-page file policy is deterministic: SVG/TikZ/PNG/EPS emit numbered files, PDF preserves each
Page's physical media box, PPTX uses one presentation-wide maximum canvas and centres heterogeneous
Pages at 1:1, and HTML embeds every Page in one offline source-preserving viewer. See
`FIGURE_IR.md` and `UNIT_SYSTEM.md` for the normative contracts.

## 0.4 offline real-model production corpus

These are locally constructed executable PyTorch models, not hand-authored diagrams. All use a
fixed seed and sample input, run on CPU, request no pretrained weights and are checked in
framework/module/operation views. The machine report records exact nodes/edges, trainable/shared
parameters, tensor dtypes/shapes, semantic detections with confidence/reason/two-way provenance,
peak RSS and three measured construction/import/semantic/first-screen/paper-layout runs. A local
framework-import warm-up is timed separately and excluded from the three model runs.

| Corpus key | Fixed parameters | Input → output | Required evidenced semantics |
|---|---:|---|---|
| `resnet50` (torchvision) | 25,557,032 | `[1,3,64,64]` → `[1,1000]` | residual block |
| `vision_transformer` | 327,274 | `[1,3,64,64]` → `[1,10]` | attention, encoder |
| `bert_encoder` | 516,576 | `[1,16]` → `[1,96]` | attention, encoder |
| `multiscale_unet` | 488,756 | `[1,3,64,64]` → `[1,4,64,64]` | encoder, decoder, skip |
| `diffusion_unet` | 147,236 | `[1,4,32,32]`, timestep `[1]` → `[1,4,32,32]` | encoder, decoder, timestep conditioning |
| `topk_moe` | 132,228 | `[1,12]` → `[1,12,64]` | router/expert routing |
| `image_text` | 181,576 | image `[1,3,64,64]`, tokens `[1,12]` → `[1,8]` | attention, modality fusion |

The fixed diff corpus constructs torchvision ResNet18→ResNet50, BERT-like encoder→MoE
Transformer and multiscale U-Net→attention U-Net. Matching is `exact`/`probable`/`unmatched`
with confidence and operation provenance. These pairs bound the claim; they are not a universal
checkpoint matcher. The three paper examples use ResNet50, Vision Transformer and multiscale
U-Net and validate editable SVG/PDF/TikZ/PPTX plus project/proof/caption/provenance/quality files.
For 0.4.2, every SVG/PDF is physically 178 × 118 mm, every PDF is independently rendered to a
2103 × 1394 PNG at 300 DPI, and a real-Chrome blocker requires ≥7 pt text, 1.0 text transforms
and zero overflow/overlap/collision/clipping/unexplained crossing. Before images are visual baselines,
not acceptance inputs.

The additional `SCIENTIFIC-FIDELITY` corpus fixes executable semantic goldens for these three
examples. ResNet50 expects bottleneck body/projection/identity counts 16/4/12; its displayed
`layer1.1` identity block has a two-input residual merge and two exactly equivalent Layer 1
instances. Vision Transformer expects attention and FFN residual merges, each with indegree two,
and three shape/topology-equivalent encoder blocks. Multiscale U-Net expects three encoder scales,
three decoder scales, a bottleneck and three forward encoder–decoder skip paths. Every aggregate
edge is replayed as an ordered source Graph IR edge chain. These fixed constructors bound the
claim; uncertain custom structures remain `unknown`.

## 0.5 external-style researcher-trial corpus

These cases are conventional PyTorch/ONNX constructors in a standalone package that never imports
NN_DaVinci and contains no semantic tags. They use fixed seeds, random local weights/initializers and
no network. Each machine run verifies inputs/outputs, explicit unknowns, confidence/reason/provenance,
three paper candidates, a paper-ready block+operation composition, project recovery and four editable
exports.

| Case | Boundary exercised | Required invariant |
|---|---|---|
| `dynamic_pytorch` | data-dependent branch, runtime fallback | input is `image`, output is separate, sampled-path boundary is explicit |
| `onnx_multi_io` | dynamic dimensions, two inputs/outputs, shared initializer | `tokens`/`mask` and `scores`/`features` remain distinct |
| `shared_siamese` | module called twice, shared parameters | two inputs/outputs and shared-weight evidence are retained |
| `transformer_residual` | pre-norm attention + FFN | two residual merge nodes each retain both incoming paths |
| `unet_skip` | two encoder/decoder scales | skip detections carry source-edge provenance |
| `custom_unknown` | unfamiliar spectral gate | no named architecture is guessed from the class/module name |

These six compact cases are compatibility probes, not human participants and not a claim about every
third-party checkpoint. Actual participant-owned models remain subject to the adapter boundaries below.

## Inherited framework adapter matrix

| Input | Status | Reproduced invariant |
|---|---|---|
| PyTorch module / FX | Tested | torchvision ResNet18 imports with shapes, hierarchy, more than 20 edges and exactly 11,689,512 parameters |
| PyTorch runtime fallback | Tested | Data-dependent Python control flow falls back to the sampled execution; a reused `Linear` is marked shared and its 20 parameters are counted once |
| PyTorch nested output | Tested | A dict containing a tensor and tuple becomes three output tensors |
| TorchScript file | Tested | A newly traced and saved `.torchscript` graph is loaded through `torch.jit.load` and translated without pickle |
| PyTorch `state_dict` | Tested, weights only | Produces `ParameterGroup` nodes, no topology edges, `structure_available: false`, `representation: weight-groups-only` and a limitation message |
| ONNX | Tested subset | Symbolic `batch` dimension, initializer counts, two inputs/two outputs, If/Loop subgraphs, control edges and external tensor data are retained |
| Keras Functional | Tested subset | Branch/residual graph, two calls to a shared layer, nested `Model` hierarchy and parameter invariants are retained |
| TensorFlow GraphDef | Tested subset | Unknown batch dimension and `^control` dependency become a shaped port and a control edge |
| TensorFlow SavedModel | Tested subset | Two signatures are enumerated and each can be selected and imported independently |
| JAX | Tested interface | The accepted interface is exactly `callable + sample_input -> JAXPR`; dict pytree input and two outputs are represented |
| textual MLIR | Tested lightweight subset | Single-result textual SSA operations, quoted/bare operation names, SSA operands and `tensor<...>` result shapes are parsed; a block label is rejected with its line |
| Graph IR / manual JSON and YAML | Tested | Versioned round trips, stable IDs, explicit edges, sequential `layers`, constraints and safe literal Python configuration |

The test environment was Python 3.13.5 with PyTorch 2.13.0+cu130, torchvision 0.28.0+cu130,
ONNX 1.22.0, TensorFlow 2.21.0, Keras 3.15.1, JAX 0.11.1, NumPy 2.5.2,
TorchLens 2.34.1 and TorchCAM 0.5.0.dev0. Tests force CPU execution; a CUDA build being present
does not mean a GPU was used. Exact environment, source hashes and the current real-model report
are written into each successful inherited verification report. Fresh 0.6.1 evidence and its clean
source inventory are written into `artifacts/v0.6.1/<run_id>/`; an older artifact is never
accepted as a current run input.

## Experimental scope

| Surface | What is experimental |
|---|---|
| PyTorch FX/runtime | Models with custom C++/CUDA ops, distributed wrappers, `torch.export`, arbitrary Python containers or control flow unlike the tested sampled path |
| TorchScript | The PyTorch 2.13 runtime emits deprecation notices in favor of `torch.export`; only a traced sequential corpus item is currently pinned |
| ONNX | Operator semantic coverage and shape inference outside the tested opset-18 MatMul/If/Loop corpus; external data must be available beside the model path |
| Keras | Subclassed models without Functional connectivity, custom serialization objects and backend-specific layers |
| TensorFlow | Resource/control-flow functions, variables/assets and composite outputs beyond the tested GraphDef and two-signature SavedModel |
| JAX | Only the sampled JAXPR path is visible; Flax/Haiku checkpoints are not topology inputs by themselves |
| textual MLIR | The parser is a lightweight SSA extractor, not an official MLIR parser and not dialect-semantic validation |
| Real-model recognition | Custom modules may remain `unknown`; corpus success proves only the seven fixed constructors and their evidenced patterns, never an inference from a class/display name |
| Model diff | Probable matching is heuristic and reports confidence; a reviewer must confirm whether a moved/renamed node is conceptually identical |
| Paper compatibility | Built-in parsers and LaTeX compilation check editability/compilation, but cannot guarantee appearance in every Inkscape, LibreOffice or PowerPoint release |
| Figure Studio equations | The documented safe subset normalizes to editable Unicode and retains the source; it is not a complete TeX math-layout engine, and unsupported syntax uses an explicit invalid-formula fallback |
| Font portability | Fallback candidates and final renderer metrics are recorded and checked, but an untested external editor can substitute fonts and shift glyph placement |
| Heterogeneous PPTX pages | PowerPoint has one slide size per presentation; Pages are centred at 1:1 on the maximum Page canvas rather than receiving independent slide sizes |
| Scene family recognition | Only explicit Graph/Semantic architecture evidence selects a family role; custom networks and name-only hints remain unknown or use a requested layout without acquiring semantics |
| Scene occlusion | CPU projection implements deterministic depth ordering, face tests and sampled hidden-line removal; it is not a general exact constructive-solid-geometry renderer for every intersecting/non-manifold mesh |
| WebGL portability | WebGL2 capability/driver behavior varies; the explicit CPU SVG fallback is the supported degraded mode |
| Scene interaction | Numeric/controller XYZ editing is implemented; an on-canvas transform gizmo and dedicated group-collapse tree widget are not present |
| Scene labels | Billboard/post-projection labels use deterministic bounding-box avoidance; crowded custom scenes can still require author repositioning, hiding, or a different camera |
| App recovery | Autosave compares current/stored revision summaries before explicit load/overwrite; whole-Inspector pin persists, but individual property rows are not independently pinnable |

## Deliberately unsupported or rejected

- A `state_dict` cannot recover forward topology, branch structure or module calls. NN_DaVinci does
  not draw a guessed network for it.
- Pickle and Python factory inputs are rejected unless the caller explicitly enables trusted code.
- MLIR block labels/arguments, multi-block region syntax, nested regions, symbol tables, aliases,
  custom attributes/types that do not match the documented subset, and dialect verification are
  rejected rather than partially accepted under a claim of general MLIR support.
- Importing an arbitrary JAX/Flax checkpoint without a callable and representative sample input is
  unsupported.
- Dynamic execution tests describe the sampled path. They do not establish all possible branches.
- Scene architecture roles are never inferred from display/class/module names alone. A requested
  layout family may arrange unknown content, but it does not create residual/attention/MoE/fusion/
  diffusion provenance.
- Scene IR 1.0 has no shader, texture or external-buffer fields; its export asset validator rejects
  dangerous/external asset URIs and malformed embedded images, and offline HTML rejects runtime
  network dependencies. Imported third-party GLB is not reverse-engineered into
  model topology or Semantic View evidence.
- `presentation.perspective_mode` is retained as a legacy 2D preference only. Project 1.3→1.4
  migration never interprets it as a camera or 3D geometry.

Run the matrix alone with:

```bash
JAX_PLATFORMS=cpu CUDA_VISIBLE_DEVICES='' \
  ../envs/python-tools/bin/python -m unittest -v tests.test_compatibility_matrix
```

It is inherited by the 0.7.2 gate. Run the current release drivers with `./scripts/verify-quick-0.7.2.sh` and `./scripts/verify-full-0.7.2.sh`; only a completed fresh 0.7.2 artifact records authoritative skip counts, dependency inventory, coverage, Chrome/visual results, corpus paths, scientific parity, and performance.

## Human evidence

The compatibility matrix is automated evidence only. NN_DaVinci 0.7.2 has 0 human participants
and 0 completed human sessions. Human usability, ease/learnability, first-figure time,
paper-ready time, task success and serious-semantic-error results are all null/N/A. Chrome and
other automation do not count as participants.
