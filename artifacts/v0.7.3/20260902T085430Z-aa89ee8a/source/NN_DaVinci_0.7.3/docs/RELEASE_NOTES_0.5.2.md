# NN_DaVinci 0.5.2 Beta — Responsive Workspace & Pilot UX Hotfix

0.5.2 is an interaction and release-evidence hotfix. It preserves the 0.5.1 toolbar actions,
history, Composer recovery, drawing algorithms, semantic recognition, project schema 1.2 and frozen
Trial event schema while making the full research workflow operable and discoverable at desktop,
tablet, phone and short-landscape sizes.

## Responsive workspace

- The desktop editor remains the canonical three-column workspace. At widths ≤800 px, its existing
  component/library, structure, analysis and Inspector surfaces become left/right off-canvas drawers
  reached through compact canvas navigation. No duplicate graph/editor state was introduced.
- A selected node leaves an obvious Inspector entry and context badge at narrow widths. Closing a
  drawer preserves selection and tab state.
- Toolbar menus, responsive drawers, workflow drawers and dialogs now share mutual exclusion,
  backdrop ownership, Escape/outside-close behavior, forward/reverse focus trapping, opener-focus
  restoration and breakpoint cleanup.
- Workflow dialogs keep their title and actions visible around an independently scrolling body.
  Dynamic viewport bounds, 40–42 px controls, reduced-motion and forced-colors handling cover the
  phone and 568×320 short-landscape boundary without horizontal overflow.

## Composer and pilot workflow clarity

- The Paper menu names the action `Figure Composer（多 Panel）` and opens its dialog immediately.
  Source Graph, Semantic View, level, Panel count, readiness and retry/empty guidance are visible
  before or while preview work completes.
- A new universally applicable composition contains exactly Panel A `Semantic blocks` at
  block/paper and Panel B `Operation evidence` at operation/paper. Existing valid Composer state is
  restored instead; repeated entry does not append or rebuild panels.
- Import, analysis, layout, paper optimization, Composer preview/export, save and export now expose
  pending/busy, succeeded, warning, failed, cancelled and retry feedback. Browser-native text prompts
  were replaced with an application dialog, and async handlers surface failures without unhandled
  promise rejections.

## Browser acceptance

`npm run e2e:responsive` covers exactly seven real-Chrome viewports: 1440×900, 1024×768,
800×720, 768×720, 568×320, 390×780 and 320×568. It blocks on document/toolbar/canvas
geometry, all menu paths, left/right drawer access, selection-to-Inspector access, surface layering,
keyboard navigation and focus return, breakpoint cleanup, short-dialog usability, exact Composer
A/B initialization and zero console/page errors. The narrowest run completes this saved/exported
loop: import model → block view → Paper View → Composer A/B → save project → export SVG.

The responsive JSON report is consumed by full verification and summarized in `verification.json`;
it is additive to the ten inherited Editor scenarios, Semantic workflow, Product workflow, Trial
workflow and the unchanged 34-row executable acceptance matrix.

## Regression baseline and evidence boundary

The completed development quick baseline is 149/149 Python tests with zero failures, errors, skips
or deselections. Coverage is old core line `2268/2481 = 91.41%`, branch
`722/864 = 83.56%`, combined `2990/3345 = 89.39%`; expanded core line
`2470/2696 = 91.62%`, branch `792/944 = 83.90%`, combined `3262/3640 = 89.62%`;
all package line `7963/9108 = 87.43%`, branch `2368/3040 = 77.89%`, combined
`10331/12148 = 85.04%`.

A successful fresh full verification writes only to `artifacts/v0.5.2/<run_id>/`. Its external
sibling attestation and `release-decision.json` establish the authoritative result; source text does
not pre-claim that result. Older artifacts remain historical and are never overwritten or accepted
as a 0.5.2 run.

No human participant was available during implementation. Existing 0.5.0/0.5.1 sessions are not
rewritten as 0.5.2 evidence, `awaiting_participants` remains honest, and a formal pilot must begin on
one frozen, authoritatively verified 0.5.2 build. No Git repository was initialized by this release.
