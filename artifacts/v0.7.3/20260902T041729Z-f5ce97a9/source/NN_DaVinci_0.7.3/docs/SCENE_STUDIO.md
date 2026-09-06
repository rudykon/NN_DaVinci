# Scene Studio

Scene Studio is NN_DaVinci 0.7.2's explicit three-dimensional authoring workspace for Scene IR 1.0. It is separate from Graph Explore and 2D Figure Studio, uses real XYZ geometry and cameras, and shares evidence-centered selection without conflating the three document types. Initial open frames the actual visible world bounds; it changes only the active camera and records the automatic frame, leaving object geometry untouched.

## Entry points and workflow

The Start Center has six progressive-disclosure sections: New, Import, Real Models, 2D Templates, 3D Templates, and Recent Projects. Search and category filters operate without flattening every entry onto the first screen. Blank 2D, Blank 3D, Graph→Scene, and the exact seven editable 3D template paths are visually distinct. Each template card opens a real non-empty Scene IR document with template-only provenance. A normal model workflow is:

1. Import.
2. Explore & Analyze.
3. Compose 2D or 3D.
4. Proof & Export.

The header/workspace switcher identifies the current project and Graph/Figure/Scene mode; the status surfaces show save/action state. Switching workspaces snapshots local context. Canonical Project 1.4 state carries Scene IR, selected Scene IDs, active camera, and workspace contexts. The browser-local autosave draft also carries UI preferences; those preferences are local recovery state, not a portable Project 1.4 field. Scene changes participate in the inherited undo/redo snapshot mechanism.

## True 3D renderer and fallback

`scene-renderer.js` consumes Scene IR world transforms, composes model/view/projection matrices, builds procedural solid geometry and authored route segments, and renders through WebGL2 with `DEPTH_TEST`. Routes follow their endpoints/control points rather than producing an origin-centred placeholder square. A projected DOM layer anchors readable Scene labels and rejects overlapping or clipped placements. Perspective and orthographic cameras are mathematically distinct. Camera orbit changes view/projection coordinates and depth while object world transforms remain unchanged. This is not the legacy CSS perspective preview.

If WebGL2 creation or context restoration fails, Scene Studio calls `/api/scene/project` for the current camera and presents the deterministic CPU-projected SVG. A visible status names the fallback. If the API request also fails, a deterministic local SVG projection remains visible rather than leaving a dead canvas. The fallback is an interactive authoring view; publication exports still use the server CPU exporter and are never produced by capturing the WebGL canvas.

## Navigation and selection

The wired browser controls include:

- orbit by tool drag, Alt-drag, or secondary-button drag;
- pan by tool drag or middle-button drag;
- wheel zoom;
- Front, Back, Left, Right, Top, Bottom, and Isometric presets;
- orthographic/perspective toggle, Frame/Focus Selection, and camera lock;
- local ray-to-oriented-bounds picking with nearest-depth selection;
- Shift/Ctrl/Cmd additive selection and projected-bounds marquee selection;
- keyboard tools `V` (select), `O` (orbit), `H` (pan), `F` (frame), and Escape (clear selection).

The CPU SVG fallback retains `data-scene-object-id` identity so projected objects remain selectable. Selecting an Object3D resolves its Graph/Semantic/Figure provenance IDs; matching Graph/Figure content can highlight from those stable evidence IDs. Returning to another workspace restores that workspace's own local selection while retaining shared evidence focus.

## Editing

The Scene tree, camera list, responsive contextual selection toolbar, on-canvas transform gizmo, transform fields, material opacity, snapping controls, and unified Inspector are live. Authors can insert Box, Sphere, Cylinder, or Tensor author objects; generated tensor/model objects remain editable.

Unlocked selections support numeric or gizmo-driven X/Y/Z position, rotation (degrees), and scale; local/world coordinates; axis constraints; grid snapping; keyboard nudge; complete X/Y/Z alignment and distribution; Group/Ungroup; object/camera locking; hide/show/isolate/focus; opacity; depth spacing; and selection-based collapse/explode. Gizmo operations participate in undo/redo and autosave. The searchable/filterable tree and canvas selection remain synchronized; group rows expose collapse, visibility, and lock state.

The Inspector has exactly six collapsible groups in order: Transform, Geometry, Appearance, Layout, Semantics, and Provenance. It distinguishes no selection, one selection, and multiple selections, and each property row can be pinned independently. Scene content density is Compact, Paper, or Detailed; Paper is the publication default. The remaining interaction boundary is explicit: this is object-level neural-network diagram authoring, not arbitrary mesh-component or CAD constraint editing.

## Save, conflicts, and command feedback

The shared UI state machine exposes `clean`, `dirty`, `saving`, `saved`, `error`, and `conflict` save states. Autosave compares the last persisted project revision and does not silently treat a mismatch as saved. Its application dialog shows current and stored revision summaries, lets the author load the stored copy or explicitly overwrite it, rechecks the stored revision before overwrite, and leaves data untouched if resolution fails.

The command registry provides Ctrl/Cmd+K search, categories, shortcuts, workspace-dependent availability, disabled reasons, Graph/Scene object search, arrow/Home/End keyboard navigation, and focus restoration. Scene generation/export operations use visible busy/success/warning/error feedback and retry hooks. Batch export runs any subset of the ten Scene formats, reports per-format progress, isolates failures, and can cancel remaining work through an abort signal. Long inherited jobs remain available through the Task Center with queued/running/succeeded/failed/cancelled records.

## Seven architecture grammars

Bundled editable Scenes and evidence-backed model conversion cover CNN, ResNet, U-Net, Transformer, MoE, Multimodal Fusion, and Diffusion U-Net:

- ResNet uses a separate 3D route for evidenced residual skips.
- U-Net separates encoder, bottleneck, decoder, and evidenced cross-level skips.
- Transformer represents tokens, attention, FFN operations, heads/ribbons, and Q/K/V branches when evidenced.
- MoE represents router, expert branches, and merge; top-k is shown only when supplied as evidence/author state.
- Multimodal streams remain separate until an evidenced fusion point.
- Diffusion timestep conditioning uses a distinct route/material from the main flow.

Templates have `template` provenance only. Model conversion cannot infer a family or special role from a display/class/module name: missing evidence remains `unknown`. Symbolic and dynamic tensor dimensions remain symbols or `?`, and visual volume extent is explicitly not a literal tensor measurement.

## Proof and export

Scene Studio exports CPU-projected SVG, PDF, TikZ, editable PPTX, PNG, EPS, and offline HTML, plus canonical Scene JSON and glTF/GLB. The physical projector defaults to a 180 × 120 mm page with 8 mm margins, automatic non-decorative fit-to-content, Paper label budgeting, screen-space collision resolution, depth sorting, back-face/hidden-edge policy, 0.75 pt strokes, and labels of at least 7 pt. PNG is the intentional 300-DPI raster proof; SVG/PDF/TikZ/EPS remain native vector, and PPTX retains editable shapes without flattened slide media.

glTF/GLB retain non-zero XYZ geometry, cameras, materials, Scene object IDs, and provenance in `extras`; glTF embeds its binary buffer rather than referencing a network asset. Offline HTML embeds the CPU SVG projection and local interaction code under a restrictive CSP with no runtime network request.

The release browser contract exercises real-model→Semantic→Figure/Lens→Scene, actual reload, all ten formats, return-to-2D provenance, error/cancel/retry, Inspector pin persistence, side-by-side revision resolution, and WebGL→CPU SVG fallback. Its manifest contains at least 44 screenshots covering four themes, all seven exact viewports, paired 2D/3D captures for every real architecture, and one genuine editable 3D capture for each Start Center Scene template; the seven-architecture checks require non-helper model objects and visible projected labels. Full-viewport focused canvas ratios are 0.691117/0.625341/0.614173/0.617669 at desktop widths and 0.900000/0.812500/0.928910 at narrow widths with drawers closed, meeting the 60%/70% gates.

The clean full driver binds that manifest, all 140 corpus exports, 28 landed scientific documents, seven independent Graph/Semantic/Figure/Scene parity reports, fourteen individual Chrome SVG verdicts, independent embedded-font PDF/compiled-TikZ verdicts, performance, inherited regression, and landed screenshots. Format validity, true-3D validity, scientific fidelity, and publication validity are separate fields. This page defines the contract and deliberately does not state a current run result; only `artifacts/v0.7.2/<run_id>/verification.json` may declare one.

Chrome and automated proof are machine evidence only. NN_DaVinci 0.7.2 has zero human participants and zero completed human sessions; no automation establishes human ease of use.
