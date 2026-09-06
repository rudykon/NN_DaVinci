# UX Design System 0.7.1

NN_DaVinci 0.7 uses one application design system for Start Center, Graph Explore, Figure Studio, Scene Studio, Proof, Export, dialogs, drawers, menus, and task/status surfaces. Application-chrome themes do not change the scientific meaning or evidence carried by Graph/Figure/Scene palettes.

## Foundations

`web/design-system.css` defines the normative chrome tokens:

- 4 px base spacing and an 8 px primary rhythm;
- shared control height, sidebar width, foreground/background/surface/border/accent/focus tokens;
- consistent focus rings, disabled state, radius, shadow, and status colors;
- local system, CJK, and mathematical fallback fonts only, with no online font request;
- a visually separate canvas background so paper/scene content is not confused with application chrome.

The four themes are `light`, `dark`, `high-contrast`, and `paper`. High Contrast raises boundary/focus visibility and retains forced-colors-compatible borders. Paper reduces chrome color while keeping focus, warning, success, and error states distinguishable. Scientific content retains its separately selected accessible palette.

## Density

Application density is exactly `comfortable`, `balanced`, or `compact`, with Balanced as the default. It changes chrome spacing and row/control height without changing the saved scientific content. A migrated prerelease preference named `spacious` maps to Comfortable.

Graph, Figure and Scene expose `compact`, `paper`, or `detailed` content density. Scene projection combines that choice with semantic level/view and bounded summary/focus materialization. Paper is the publication default; it prioritizes the visual argument while retaining full text and provenance outside the visible label. Unknown values remain explicit rather than being replaced with zero or an inferred value.

## Shell and command distribution

Permanent shell controls are organized as no more than seven primary groups: Project/File, Undo/Redo, workspace, canvas/selection core tools, Proof, Export, and More. Task-specific actions live under Project, Import, Analyze, Compose, 3D, View, Export, and Help surfaces. Selection-only actions appear in a contextual toolbar and do not reserve empty space when nothing is selected.

Ctrl/Cmd+K opens a shared command registry. Each command has one ID and execution handler, label/category, optional shortcut, search terms, workspace availability, and a disabled reason. The palette supports Graph/Scene object search, arrow/Home/End navigation, Enter execution, Escape dismissal, and focus restoration. Inapplicable commands remain explained instead of acting as silent grey controls.

## Surface and workspace state

The inherited surface manager plus the 0.7 workspace state machine enforce one transient interaction owner at a time. Menus, popovers, responsive drawers, workflow drawers, and dialogs coordinate backdrop/inert state, z-index, Escape, outside click, focus trapping/restoration, viewport clamping, keyboard navigation, and ARIA state. Browser-native `prompt()`, `alert()`, and `confirm()` are not part of the new Scene workflow.

Graph, Figure, and Scene are explicit workspace states rather than overlapping Boolean modes. Each owns local selection/view context while cross-workspace highlighting uses stable evidence IDs. Save state is `clean`, `dirty`, `saving`, `saved`, `error`, or `conflict`; action state is `idle`, `busy`, `success`, `warning`, or `error`, with retry callbacks for failures.

## Responsive layout

- `>=1280 px`: both bounded, resizable sidebars can remain visible.
- `801–1279 px`: compact controls and constrained sidebar widths preserve canvas priority; both desktop sidebars can remain present until the 800 px drawer breakpoint.
- `<=800 px`: canonical left/right sidebars become focus-managed drawers and the canvas is the only grid column.
- `<=440 px`: preferences collapse to one column and the workspace switcher keeps touch-sized controls.

Sidebar widths are local UI preferences with pointer and keyboard resize controls, bounded to 200–420 px (left) and 220–460 px (right). They persist in `nndv-ui-preferences-0.7`. The Inspector properties panel has a persisted whole-panel pin/unpin control; individual property rows do not have independent pins.

Required release sizes are 1920×1080, 1440×900, 1280×720, 1024×768, 800×600, 568×320, and 390×844. The responsive harness measures the Scene canvas against the full viewport and records 0.691117, 0.625341, 0.614173, and 0.617669 at the four desktop widths plus 0.900000, 0.812500, and 0.928910 at the three narrow widths with both drawers closed. Those values satisfy the >=60% desktop and >=70% narrow targets without changing the denominator. The release screenshot contract contains at least 44 captures spanning all four themes, every exact viewport, seven real-architecture 2D/3D pairs, and all seven editable 3D Scene templates. The full driver binds the manifest and an independent visual report; only its artifact `verification.json` declares the run outcome.

## Status and progressive disclosure

The application surfaces project/workspace/save state, selection counts, zoom/camera context, and active task/action status without requiring the user to infer a click result. Empty Scene and Inspector states tell the author what to do next. Errors retain details and recovery actions.

Figure and Scene Inspectors put selection-relevant transform/style/semantic/evidence/export information ahead of advanced state. The Scene Inspector changes between no selection, one object, and multiple objects and has exactly six groups: Transform, Geometry, Appearance, Layout, Semantics and Provenance. Scene property rows can be pinned independently. The Scene tree has its own search/filter, visibility, locking and group-collapse controls; the command palette also searches objects and commands.

## Measurable gates and evidence authority

- no more than seven visible primary top-level groups;
- no critical workflow deeper than three menu levels;
- no-selection Inspector does not expose irrelevant object transform fields;
- responsive canvas area, overflow, focus, contrast, touch target, surface bounds, and toolbar wrapping must be measured in real Chrome before release;
- 10k/50k Graphs remain summary/focus bounded rather than becoming full 3D DOM/mesh expansions;
- retained 2D Figure performance may regress by no more than 20% from the pinned 0.7.0 baseline.

Local three-run preflight records a +3.762% 2D median regression (146.424 ms versus 141.115 ms), within the 20% limit. `/tmp` results are diagnostic; the release result uses the performance/environment report bound inside the new artifact. Automated E2E, metrics, and screenshots are machine evidence, not human usability research; participant counts and human outcomes remain zero/null.

The browser contract separates targeted runtime assertions from independent evidence checks. Body foreground/background contrast, WebGL depth capability, CPU SVG strokes, projected Scene-label overlap/clipping, real route geometry, PNG identity/dimensions/hashes, themes, states, viewports, and architecture/template coverage are recorded distinctly. This is still not a per-component WCAG audit, and automation remains machine evidence rather than a human usability result.
