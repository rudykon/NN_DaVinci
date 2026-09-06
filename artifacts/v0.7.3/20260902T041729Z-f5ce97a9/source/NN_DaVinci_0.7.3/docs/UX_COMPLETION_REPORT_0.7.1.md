# NN_DaVinci 0.7.1 UX completion report

This report maps the confirmed 0.7.0 gaps to shipped 0.7.1 behavior and executable evidence. Human participants remain zero; every result here is automated or developer inspection evidence.

## Navigation and information density

The Start Center is task-first: New, Import, Real Models, 2D Templates, 3D Templates, and Recent Projects. Search and category filters work across the catalog while progressive disclosure keeps the initial surface bounded. Blank 2D, Blank 3D, Graph→Scene, and template Scene are separate entry types. Explanatory UI copy is consistently Chinese; architecture and format proper names remain English.

The top shell exposes project/workspace, current tool, save state and action feedback without duplicating command ownership. Context controls progressively move into a labelled overflow menu. At 568×320 a compact landscape rule gives vertical space back to the canvas; at 390×844 long projection/camera labels are reachable and untruncated.

## Scene authoring closure

- Canvas gizmo: translate, rotate, scale, X/Y/Z constraints, local/world coordinates, snapping, keyboard nudge, undo/redo and autosave.
- Layout: X/Y/Z align and distribute, Group/Ungroup, collapse/explode, hide/show/isolate/focus.
- Camera: Frame Scene, Frame Selection, default camera and named views.
- Tree: search, filter, group collapse, visibility, locking and synchronized selection.
- Inspector: exact Transform, Geometry, Appearance, Layout, Semantics and Provenance groups; no/single/multi-selection states; per-property pins.
- Content density: Compact, Paper and Detailed; Paper is the default for paper projection.
- Command registry: every new Scene action has category, shortcut where applicable, availability and a disabled reason.
- Batch export: any subset of SVG/PDF/TikZ/PPTX/PNG/EPS/HTML/Scene JSON/glTF/GLB, live progress, isolated failures and cancellation of remaining work.

## Themes

Light, Dark, High Contrast and Paper share semantic tokens but are independently checked. Paper changes the WebGL clear color, grid, projected labels, selection, panels and proof preview to a light paper environment. A theme toggle is not accepted if only application chrome changes.

## Evidence

The Scene E2E suite covers the inherited seven workflows plus the 0.7.1 gizmo, six-group Inspector, per-property pin, tree collapse/filter, full XYZ layout controls, responsive overflow, Start Center hierarchy, three density modes, Paper WebGL clear color and batch dialog. The responsive suite covers all seven exact viewports. Browser console, page and unexpected request errors must be zero.

Static/product tests ensure the required controls are present and routed through the command registry. A deterministic Node harness proves batch success, per-format failure isolation and AbortSignal cancellation. Toolbar truth fixtures prove that a clipped local control is rejected even when the page itself has no overflow.

Raw release results live in `reports/e2e/`, `reports/visual/`, and the screenshot manifests inside the fresh artifact. Only the sealed artifact may declare the final pass.

## Remaining boundaries

This is a local single-user authoring application, not a real-time collaborative editor. Autosave revision resolution is not a multi-user merge. The gizmo edits Scene objects, not arbitrary mesh vertices or skeletal rigs. Automated contrast/geometry checks are not a complete manual WCAG or assistive-technology audit. No human ease, time-to-figure, or task-success claim is made.
