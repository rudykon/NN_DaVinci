# NN_DaVinci 0.5.1 Beta — Composer State Recovery Hotfix

0.5.1 is a narrow workflow hotfix. It does not add a drawing algorithm, importer, framework,
analyzer, cloud surface or trial event field.

## Fixed

0.5.0 serialized both the composed Graph IR and its physical layout, but browser startup and project
import restored them through the ordinary Graph layout path. The canvas could therefore still contain
nodes after refresh while losing the exact Panel geometry that the participant had reviewed. Existing
Chrome acceptance checked only node presence and did not expose that state mismatch.

0.5.1 uses one hydration path for startup autosave, Start Center recovery and `.nndv.json` import.
A canvas is restored as a fixed composition only when its Composer Panel IDs, composed Graph metadata,
Panel layout digests and Panel transforms agree. The preserved state includes:

- shared title, page preset and arrangement;
- Panel order, titles, semantic levels/views and independent cached layouts;
- locked node positions, manual edge routes and annotations;
- composed physical layout, viewBox and zoom;
- Composer/fixed-layout undo and redo snapshots.

Composer control and Panel changes now schedule the same local autosave as canvas edits. An empty or
malformed legacy `figure_composer` object is treated as inactive and falls back safely instead of
opening a broken dialog. Project schema remains 1.2; the added canvas keys are backward-compatible
defaults.

## Regression evidence

The real-Chrome product workflow follows the participant-facing path: create three Panels, change
shared controls and Panel semantics, preview, drag a node, reroute an edge, export the editable bundle,
save the project, refresh, reopen Composer and reopen the downloaded project. It now compares exact
Panel layout digests and lock/route counts before and after both recovery paths. The focused workflow
passes 31 assertions; the Python Composer suite adds a project round-trip for physical canvas state.
The six external trial-model paths now perform the same deliberate node drag and edge reroute before
autosave, refresh and project reopen. All 65 Chrome assertions must pass, and the session-ID-scoped
local runtime record preserves anonymous semantic/node/edge/label counters across refresh so the final
`edit_summary` cannot silently revert to zero. The Trial event schema is unchanged.

This is automated product evidence, not a researcher participant. The human trial remains
`awaiting_participants`; stopped 0.5.0 sessions are not promoted into 0.5.1 evidence. A formal pilot
must start again from one frozen, authoritatively verified 0.5.1 build.

Fresh verification also gives every quick run an isolated task-runtime directory. The existing task
regression now exercises expired-file cleanup explicitly, so coverage no longer depends on stale
records left in the user's shared temporary task directory.

## Verification and artifact status

Development uses the focused Composer Python/Chrome checks and `verify-quick.sh`. A successful fresh
full verification, when explicitly run, writes a new authority under `artifacts/v0.5.1/<run_id>/`.
The 0.5.0 artifact is historical comparison evidence only and cannot pass a 0.5.1 run.

The completed development quick baseline is 149/149 Python tests. Coverage is: old core line
`2268/2481 = 91.41%`, branch `722/864 = 83.56%`, combined `2990/3345 = 89.39%`;
expanded core line `2470/2696 = 91.62%`, branch `792/944 = 83.90%`, combined
`3262/3640 = 89.62%`; all package line `7963/9108 = 87.43%`, branch
`2368/3040 = 77.89%`, combined `10331/12148 = 85.04%`.
