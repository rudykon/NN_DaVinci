# NN_DaVinci 0.7.0 Beta release notes

**Theme:** 3D Neural Figure & UX Completion  
**Development date:** 2026-08-31  
**Graph IR:** 1.0  
**Semantic View:** 1.0  
**Figure IR:** 1.0  
**Scene IR:** 1.0  
**Project schema:** 1.4

NN_DaVinci 0.7.0 adds an evidence-preserving true-3D authoring and publication path without replacing the 0.6.1 Figure workflow. Graph IR remains the fact layer, Semantic View remains an evidence-backed derived index, and Figure/Scene IR remain independent author-expression documents.

The frozen parent is authoritative 0.6.1 run `20260830T122225Z-0f6f36c2`: 294 allow-listed source files, tree digest `26469ab2eb7fd2d10a4d058ec7061017f8de005d714ca2760e2412a414d7ad7f`, 246/246 Python test IDs, and 14/14 landed production SVG passes. The 0.7 tree does not modify the parent or its artifacts and never uses old evidence as a current 0.7 result.

## Scene IR 1.0 and Project 1.4

Scene IR adds versioned `Scene`, `Camera`, `Light`, `Layer3D`, `Group3D`, and `Object3D` records with deterministic identity/digest, visibility/lock/selection, materials, author state, local XYZ transform, composed world matrices/bounds, and optional camera-bound projection records. Euler rotation is stored in **degrees** consistently across Python, JSON, and browser controls.

Scene provenance distinguishes Graph IR, Semantic View, Figure IR, template, author annotation, external 3D, and unknown sources. Materialized model-derived objects keep their Graph node/edge IDs, available port-binding/shape/dtype evidence, Semantic IDs/reasons, optional Figure IDs, and forward/reverse indexes. Summary-first conversion above 10,000 source nodes explicitly uses digests and bounded representative IDs; it does not claim a complete unbounded per-object ID list. Orphaned or tampered stored evidence fails contextual Project validation.

Project 1.4 requires an explicit Scene IR document. Compatible 1.3 migration creates a valid empty Scene and writes project/scene migration records stating that no geometry, tensor fact, architecture, or provenance was inferred. The legacy CSS `presentation.perspective_mode` remains a 2D preference and is not converted into a camera or mesh.

`nnviz project --workspace scene` writes the exact persisted `semantic_view.document` used by Scene generation, then applies the same contextual validation as Project loading. Focused CLI checks cover create→validate→reproduce; trusted Python factories and pickle inputs remain explicit opt-ins.

## Genuine three-dimensional behavior

The browser renderer builds procedural world-space meshes and route segments, composes model/view/projection matrices, and uses WebGL2 depth testing. Routes follow endpoints/control points instead of producing an origin-centred placeholder square. A projected DOM overlay anchors Scene labels and deterministically avoids overlap/clipping. Orthographic and perspective cameras are mathematically distinct. Orbit changes the camera/projection result rather than applying a CSS transform to an SVG.

Focused tests establish the non-visual proof boundary:

- camera rotation changes projected coordinates while world coordinates remain unchanged;
- orthographic and perspective depth behavior differs;
- face/edge ordering and hidden-line decisions respond to projected depth;
- ray picking returns different-depth hits nearest first;
- GLB contains real non-zero XYZ buffers, meshes/nodes, cameras, materials, Scene IDs, and provenance.

If WebGL2 is unavailable or loses context, the UI explicitly requests and displays the deterministic CPU SVG projection; if that request fails, a labelled local SVG remains visible. The fallback is never presented as WebGL.

## Scientific primitives and seven grammars

The Scene vocabulary covers tensor/cuboid/stack volumes, layer planes, operation/convolution/pooling/down/up blocks, residual and U-Net skips, attention heads/ribbons and Q/K/V branches, token sequences, MoE router/expert/merge, multimodal streams/fusion, diffusion timestep conditioning, group frames, annotations/legends, and arrow/tube/polyline/bezier routes.

Bundled editable templates and model conversion cover CNN, ResNet, U-Net, Transformer, MoE, Multimodal Fusion, and Diffusion U-Net. Start Center exposes exactly one real non-empty editable 3D template card for each family. Templates have template-only provenance. Model conversion uses explicit Graph/Semantic evidence; a display name or requested layout cannot create architecture semantics. Symbolic/dynamic/unknown dimensions remain symbols or `?`, and visual depth/thickness never overwrites tensor facts.

Large conversion defaults to 250 objects and uses summary/focus materialization. Local preflight bounds both 10k- and 50k-node sources to 249 Scene objects rather than producing full DOM/mesh scenes.

## Independent CPU projection and exports

`scene_projection.py` computes physical vector primitives from the selected camera with depth sorting, back-face policy, basic polygon occlusion, sampled hidden-line removal, vector routes/arrows, uniform physical strokes, billboard labels, deterministic label avoidance, and a 7 pt label minimum.

The export surface is:

| Output | 0.7.0 contract |
|---|---|
| SVG | native vector polygons/paths/polylines/text; no image or foreign object |
| PDF | native vector/text operators; no Image XObject |
| TikZ | editable vector source; no screenshot/includegraphics |
| PPTX | editable shapes/text; no flattened slide media |
| PNG | intentional CPU-projected 300-DPI raster proof |
| EPS | EPSF Level 3 vector operations; no raster operator |
| HTML | restrictive-CSP, dependency-free interactive CPU SVG view |
| Scene JSON | canonical reloadable Scene IR 1.0 |
| glTF/GLB | embedded/binary glTF 2.0 world geometry, cameras, materials, IDs, provenance |

None of the paper-vector formats captures the WebGL canvas. Producer metadata does not authorize final quality; landed outputs still require independent format/oracle inspection.

## Scene Studio interaction

Scene Studio is a distinct Graph/Figure/Scene workspace with:

- orbit, pan, wheel zoom, perspective/orthographic switching, Front/Back/Left/Right/Top/Bottom/Isometric views, Frame Selection, and camera lock;
- nearest-depth ray selection, Shift/Ctrl/Cmd additive selection, marquee selection, and fallback-SVG object selection;
- numeric XYZ position/rotation/scale, snapping, X/Y/Z alignment, controller distribution, grouping, object lock, hide/show/isolate/focus, selection collapse/explode, opacity, and depth spacing;
- Scene tree/camera list, selection-aware transform/provenance Inspector, author Box/Sphere/Cylinder/Tensor insertion, and cross-workspace evidence highlighting;
- Scene-aware undo/redo plus Project 1.4 persistence of Scene, active camera, selection, and workspace context; browser-local autosave separately retains UI preferences.

Known interaction limits are explicit: there is no on-canvas XYZ gizmo; only X distribution is exposed in the current contextual toolbar; collapse/explode is selection-based rather than a group-tree widget; and individual Inspector property rows cannot be pinned separately.

## Design system, state, and responsive shell

The new application chrome centralizes 4/8 px spacing, control/surface/border/focus/status tokens, local-only font fallbacks, and Light/Dark/High Contrast/Paper themes. Application density is Comfortable/Balanced/Compact with Balanced default. Graph/Figure label density remains Compact/Paper/Detailed; Scene uses semantic level/view and bounded summary/focus rather than that three-value toggle.

Permanent shell groups are limited by the Project/File, history, workspace, selection/canvas, Proof, Export, and More model. Task commands live under Project/Import/Analyze/Compose/3D/View/Export/Help. Ctrl/Cmd+K uses a shared contextual command registry with shortcuts, disabled reasons, Graph/Scene search, keyboard navigation, and focus restoration.

One surface manager/state machine owns menus, popovers, drawers, dialogs, workspace context, save state, and async action feedback. Autosave exposes clean/dirty/saving/saved/error/conflict, compares current and stored revision summaries before an explicit load/overwrite choice, and rechecks the stored revision before overwriting. Whole-Inspector pin state and pointer/keyboard sidebar widths persist.

The browser evidence contract exercises WebGL depth, authoring/selection, actual routes and projected labels, camera navigation, command-palette focus, four themes, sidebar/Inspector persistence, side-by-side revision resolution, seven real-model imports, Semantic/Figure/Lens→Scene generation, actual reload, all Scene formats, return-to-2D provenance, error/cancel/retry, WebGL→CPU fallback, and the exact seven Start Center 3D templates. It produces at least 44 landed screenshots, seven real-architecture 2D/3D pairs, seven 3D template captures, all seven exact viewport captures, and ten non-empty downloads. An independent validator checks the screenshot manifest and PNG files instead of trusting producer booleans.

Using the full viewport denominator, focused Scene canvas ratios are 0.691117/0.625341/0.614173/0.617669 at 1920/1440/1280/1024 and 0.900000/0.812500/0.928910 at 800/568/390 with both drawers closed. They satisfy the documented >=60% desktop and >=70% narrow gates. Targeted runtime checks remain distinct from a per-component WCAG audit.

## Candidate corpus and local preflight evidence

The fresh candidate corpus at `/tmp/nndv-070-scene-corpus-release-corpus-1` contains seven templates and seven real models. Each has `scene.nndv.json` plus `scene.svg`, `.pdf`, `.tex`, `.pptx`, `.png`, `.eps`, `.html`, `.scene.json`, `.gltf`, and `.glb`; each real model also has `comparison.svg` and `comparison.png`.

- generation report: `/tmp/nndv-070-scene-corpus-generation-report-1.json`, 14/14, 140 exports, 14 Projects, 14 comparison files, 0 failures;
- corpus: 168 files, 74,993,641 bytes, tree digest `ec674f5bca0455436d05b2a9164c1915a3ee668fe87d41c1092e2b8695623814`;
- independent validator: `/tmp/nndv-070-scene-corpus-validation-report-2.json`, 14/14 PASS, SHA-256 `55a6beb4354fa763e7edf76a155145eb38d6d8a02c2e89f5bcf9d61768b28858`.

The current three-run local performance preflight records:

| Gate | Local result | Limit |
|---|---:|---:|
| 250-object first interactive, max | 151.959 ms | <=500 ms |
| 1000-object first interactive, max | 662.209 ms | <=1500 ms |
| 500-object orbit interaction frame, p95 | 17.578 ms | <=50 ms |
| selection/Inspector, median (30 samples) | 0.204 ms | <=100 ms |
| CPU publication projection, 250/1000 median | 334.060 / 1462.243 ms | reported diagnostic |
| retained 2D Figure median | 146.424 ms, +3.762% vs 141.115 ms | <=+20% |

The performance JSON currently lives at `/tmp/nndv-070-scene-performance.json`. These are real local measurements and the candidate corpus is fresh. Release authority nevertheless belongs only to the full driver's regenerated/copied reports with environment metadata and manifest binding in the new artifact.

## Regression and release-evidence contract

The inherited contract is exact: all 246 authoritative 0.6.1 test IDs must still be collected and pass; none may be removed, renamed, skipped, or weakened, and all retained coverage floors remain unchanged. New Scene tests are additive.

The clean driver also requires the corrected Scene CLI workflow, the full-viewport canvas-area gates above, exactly seven UI template families, genuine WebGL route/label evidence, all four themes, every target viewport, every real-architecture 2D/3D pair, every template 3D capture, ten landed formats, and the independent visual report. It binds at least 44 screenshots and all reports to hashes and command logs.

This source document intentionally does not declare a 0.7.0 run outcome. Only a completed fresh `artifacts/v0.7.0/<run_id>/verification.json` may do that; an old artifact, `/tmp` report, producer boolean, or failed run cannot be relabelled.

## Commands

```bash
# Local server
PYTHONPATH=src ../envs/python-tools/bin/python \
  -m nn_davinci serve --host 127.0.0.1 --port 8765 --no-browser

# Scene generation/export
PYTHONPATH=src ../envs/python-tools/bin/python -m nn_davinci scene \
  examples/resnet.json --architecture resnet \
  --format svg,pdf,tikz,pptx,png,eps,html,json,gltf,glb \
  --output outputs/resnet-3d

# Project validation/replay
PYTHONPATH=src ../envs/python-tools/bin/python \
  -m nn_davinci validate outputs/resnet.scene.nndv.json
PYTHONPATH=src ../envs/python-tools/bin/python \
  -m nn_davinci reproduce outputs/resnet.scene.nndv.json --output outputs/replayed

# Verification
./scripts/verify-quick-0.7.0.sh
./scripts/verify-full-0.7.0.sh
```

## Human, safety, and publication boundary

| Human measure | 0.7.0 result |
|---|---:|
| Participants | 0 |
| Completed human sessions | 0 |
| First-figure median | null / N/A |
| Paper-ready median | null / N/A |
| Core task success | null / N/A |
| Ease/learnability | null / N/A |
| Serious semantic errors | null / N/A |

Automation does not count as a participant. The Flask service remains loopback-only and unauthenticated; local plugins are not a sandbox; Python/pickle are trusted-code opt-ins; HTML and packaged UI make no runtime network request. This work does not initialize or operate Git and performs no commit, tag, push, upload, or publication.
