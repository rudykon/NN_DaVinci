# Responsive Workspace and Toolbar (0.7.1)

NN_DaVinci 0.7 preserves one canonical Graph/Figure/Scene state while distributing controls by user task. Responsive proxies invoke the same commands and DOM-owned side panels; they do not create a second model, Scene, Page tree, canvas, or Inspector.

## Command ownership

The persistent shell is limited to Project/File, Undo/Redo, workspace, canvas/selection essentials, Proof, Export, and More. Import, Analyze, Compose, 3D, View, and Help actions live in task menus/drawers or Ctrl/Cmd+K. Selection actions appear in a contextual toolbar only when they are valid.

Every command has one meaning and one handler regardless of whether it is invoked from a toolbar, menu, contextual bar, responsive proxy, or palette. Availability returns either enabled or an explicit disabled reason. Busy/success/warning/error state is announced through the shared action-status region; errors retain retry when the operation supports it.

## Layout contract

| Width | Workspace behavior |
|---|---|
| `>=1280 px` | Graph/Figure/Scene canvas with both bounded, resizable sidebars available |
| `801–1279 px` | compact chrome and constrained desktop sidebars preserve the central canvas; both can remain present until the drawer breakpoint |
| `<=800 px` | one canvas grid column; the canonical left and right panels become focus-managed drawers |
| `<=440 px` | labels/preferences compress to touch-safe single-column controls and the workspace switcher remains reachable |

The left width is bounded to 200–420 px and the right to 220–460 px. Pointer drag and keyboard arrows resize them; values persist as local UI preferences. At narrow widths resize handles disappear rather than sitting over the canvas.

The normative release matrix is 1920×1080, 1440×900, 1280×720, 1024×768, 800×600, 568×320, and 390×844. The harness asserts matching viewport/document dimensions, bounded toolbar/menu/dialog geometry, no page overflow, no topbar/canvas overlap, and the canvas-area threshold itself. Calculated against full viewport area, the focused ratios are 0.691117, 0.625341, 0.614173, and 0.617669 at 1920/1440/1280/1024, satisfying the >=60% desktop gate. With both canonical drawers closed they are 0.900000, 0.812500, and 0.928910 at 800/568/390, satisfying the >=70% narrow gate. The denominator remains the full viewport.

In 0.7.1 the contextual toolbar progressively moves lower-priority commands into an explicit overflow menu. Browser geometry checks measure each visible control's scroll/client bounds, including the known `Orthographic` and `Camera lock` labels. At 568×320 the compact landscape rule reduces vertical chrome instead of hiding controls with clipping; at 390×844 the same commands remain reachable through overflow with full accessible names.

## One transient surface

The inherited surface manager owns menus, popovers, responsive drawers, workflow drawers, and dialogs. Opening one closes or transfers ownership from the previous surface. It synchronizes `aria-expanded`/`aria-hidden`, backdrop/inert state, z-index, Escape/outside-click behavior, modal Tab/Shift+Tab containment, and opener focus restoration. Crossing the 800 px breakpoint closes stale narrow surfaces before desktop columns return.

Menus are measured after opening and clamped to the visual viewport. Workflow dialogs keep title/actions outside an independently scrolling body and use dynamic viewport bounds. `prefers-reduced-motion`, forced colors, focus-visible outlines, and touch-sized narrow controls remain part of the inherited accessibility contract.

## Workspace-specific controls

- Graph keeps import, semantic level/view, analysis, layout, search/focus, and evidence inspection.
- Figure keeps Page/Panel/Layer/object authoring, paper proof, and publication export.
- Scene keeps select/orbit/pan, camera projection/view/lock, Frame Scene/Selection/default camera, selection context actions, XYZ gizmo and numeric fields, local/world axes, snap, full XYZ alignment/distribution, Group/Ungroup, visibility/isolation, material opacity, depth spacing, density, and provenance.

The workspace switcher snapshots local context before transition. Canonical Project 1.4 canvas state restores Scene IR/active camera/selection, Figure active Page, and Graph/Semantic context. The browser-local autosave preference extension restores density/theme and sidebar widths; those preferences are not portable Scene IR fields. Evidence IDs synchronize cross-workspace highlighting; local canvas selection is not overwritten merely because another workspace becomes active.

## Command palette and keyboard

Ctrl/Cmd+K searches registered commands and Graph/Scene objects. Results show category/description, shortcut, and disabled explanation. Arrow keys, Home, End, Enter, and Escape operate the palette; focus returns to the opener after execution/dismissal. Scene keyboard tools are V/select, O/orbit, H/pan, F/frame, and Escape/clear.

## Inherited 0.5.2 contract

The 0.5.2 responsive hotfix remains a regression requirement: canonical side panels, mutual exclusion, ARIA/focus cleanup, bounded workflow dialogs, Figure Composer A/B initialization, and the historical narrow import→Paper→save→SVG workflow are not removed by the 0.7 redesign. Its historical E2E viewports and reports remain historical evidence; 0.7 must re-run current Chrome checks instead of relabelling them.

## Honest acceptance state

`tests/e2e/scene-studio.e2e.mjs` defines the browser evidence contract for Blank 2D/3D, exact seven Start Center 3D templates, real-model/Semantic/Structure-Lens→Scene, reload, return-to-2D provenance, error/cancel/retry, projected labels, actual routes, all ten formats, and all seven architectures. Its screenshot manifest contains at least 44 PNGs: four themes, seven exact responsive sizes, seven real-model 2D/3D pairs, seven editable 3D template captures, and the required workflow/error/fallback states. The clean full driver binds that manifest, ten non-empty downloads, JavaScript/CSS checks, inherited responsive evidence, and the independent visual report. Automated Chrome behavior is machine evidence only and does not populate human usability metrics; the artifact `verification.json` alone states the run outcome.
