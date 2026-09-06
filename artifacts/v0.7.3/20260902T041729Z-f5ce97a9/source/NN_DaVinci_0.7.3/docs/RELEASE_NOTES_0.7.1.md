# NN_DaVinci 0.7.1 release notes

**3D Publication Quality & UX Completion**

NN_DaVinci 0.7.1 turns the true-3D foundation from 0.7.0 into a paper-oriented authoring workflow. It fixes the fixed fourteen-case Scene corpus at the projection/layout layer, adds independent landed-output gates for every case, and closes the confirmed Scene UI and small-window gaps. Graph IR, Semantic View, Figure IR, Scene IR, Project 1.4, and the existing 2D workflow retain their evidence boundaries.

The frozen parent is authoritative 0.7.0 run `20260831T044446Z-9e6cd3cf`: 356 allow-listed source files, source digest `16aa60c611c4cf8c327fe4174314091dcb8dae840dc22ce85f73dae9926fb00d`, and 328 exact Python test IDs. That source tree and artifact are read-only.

## Publication projection

- Automatic framing excludes decorative world/group frames and targets stable page occupancy with fixed physical margins.
- Compact, Paper, and Detailed density modes use semantic label priority, aggregation, abbreviation with retained full text, and explicit budgets. Paper is the publication default.
- Labels are assigned to screen-space lanes and collision-resolved against other labels, projected objects, page bounds, and routed geometry. Leaders use bounded detours instead of a shared center starburst.
- Hidden-line clipping retains arrow direction on the last visible route segment. Architecture routes preserve semantic color, including clearly distinguished ResNet residual skips.
- Model-derived scenes aggregate repeated blocks and cap connectors without removing evidence-bearing semantics. Decorative frames no longer dominate the content bounding box.
- SVG, PDF, TikZ, PPTX, PNG, EPS, and offline HTML share one `ProjectedScene`; Scene JSON, glTF, and GLB retain real XYZ, cameras, materials, stable object IDs, and provenance.

## Landed-output verification

The release driver regenerates all seven templates and seven real-model cases in ten formats. Validation has three separate verdicts:

1. format validity;
2. true-3D/source consistency;
3. publication visual quality.

Every final SVG is opened independently in Chrome and measured using actual glyph geometry, `getBBox()`, `getScreenCTM()`, page clipping, label/object/edge intersections, leader crossings, arrowheads, font size and horizontal/vertical text scale. PDF and compiled TikZ PDF are checked with independent PDF tools for physical page size, embedded fonts, extractable text, word geometry, boundary ink, and corresponding object positions. Positive, negative, and mutation fixtures cover label stacks, label/object collision, clipping, starburst leaders, huge decorative frames, non-uniform text scale, toolbar truncation, and a constant-true validator.

The artifact also contains fourteen explicit 0.7.0→0.7.1 proofs. For every case it preserves the parent and current `scene.png` at original pixel resolution, plus a side-by-side proof. Parent images are historical inputs only and are never treated as current output.

## Scene Studio UX

- The contextual toolbar progressively folds into an explicit overflow menu. The 390×844 and 568×320 browser gates measure control scroll/client geometry, including Orthographic and Camera lock.
- Start Center is organized as New, Import, Real Models, 2D Templates, 3D Templates, and Recent Projects with search, category filters, consistent Chinese explanatory text, and progressive disclosure.
- A canvas XYZ gizmo supports translate, rotate, and scale, local/world coordinates, axis constraints, snapping, keyboard nudge, undo/redo, and autosave.
- X/Y/Z alignment and distribution, Group/Ungroup, hide/isolate/focus/explode, Frame Scene, Frame Selection, and default-camera recovery are visible commands.
- The Scene tree supports group collapse, search/filter, visibility, lock state, and synchronized selection.
- The Scene Inspector is exactly six collapsible groups—Transform, Geometry, Appearance, Layout, Semantics, Provenance—with per-property pinning and clear no/single/multi-selection states.
- Light, Dark, High Contrast, and Paper themes cover the Scene canvas, grid, labels, selection and proof preview. Paper is a genuinely light publication workspace.
- Batch export supports all ten formats, per-format progress, failure isolation, and cancellation.

## Compatibility and limits

The exact 328 inherited tests and retained coverage floors remain release-blocking. The seven browser suites, project migration, 10k/50k bounded summary/focus behavior, packaging, isolated wheel/sdist install, CLI/schema/project roundtrip, and 2D performance are replayed from a clean snapshot.

The retained 2D timing gate uses three recorded paired runs. Each run counterbalances four current/parent observations after one warm-up per version, and first verifies that the pinned 0.7.0 Figure renderer and Figure IR sources are byte-identical to the retained 0.7.1 implementation. The historical artifact timing remains in the report as context; the blocking regression percentage uses the same-load paired comparison so CPU-frequency drift is not mislabeled as a product change.

The 500-object orbit gate composes the view-projection matrix once per frame and batch-projects all visible world-space centres, matching the matrix reuse of the interactive renderer. A direct equivalence assertion locks the batch result to the single-point projection API; the blocking p95 remains 20 ms and is not relaxed.

This release does not claim arbitrary third-party GLB reconstruction, CAD-grade mesh editing, universal framework/model support, or inferred semantics from names. Dynamic or missing evidence remains symbolic or `unknown`. See `KNOWN_LIMITATIONS.md`.

## Reproduce

```bash
./scripts/verify-quick-0.7.1.sh
./scripts/verify-full-0.7.1.sh
```

Only a newly sealed `artifacts/v0.7.1/<run_id>/verification.json` can declare the full release result. Temporary reports, source prose, and the parent artifact cannot substitute for it. Human participants and completed human sessions remain zero; all usability/time metrics remain null.
