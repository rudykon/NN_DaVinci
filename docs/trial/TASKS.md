# Researcher Trial Tasks

Complete the assigned case entirely in the Web interface. The facilitator records pass/fail and does
not count a partial automated substitute as human completion.

## T1 — Import and orient

Open Trial Mode, select the assigned case, and wait for the first interactive Paper View. State the
model inputs and outputs using the labels shown. For participant-owned input, use the import wizard and
review format, execution safety, sample input and view recommendation before import.

Success: a navigable model opens; inputs are not named as outputs; any dynamic sampling boundary or
topology limitation is visible.

## T2 — Audit semantics

Use the structure tree, breadcrumbs and double-click drill-down to inspect Stage/Block/Operation. Find
one detected structure and inspect confidence, reason and source node/edge provenance. Inspect an
`unknown` if present and explain why it was not guessed. Switch between Faithful and Paper View.

Success: the participant can trace a paper node/edge back to source evidence and can distinguish
unknown from an asserted architecture pattern.

## T3 — Generate a paper draft

Choose **Generate paper figure**, compare the candidates, and apply one. Open Figure Composer; use one
semantic block Panel and one operation-evidence Panel. Generate the proof.

Success: Composer reports paper-ready with final minimum font at least 7 pt and the participant can
identify what Paper View aggregated.

## T4 — Make a deliberate edit

Change at least one node position or label and one edge route. Do not change scientific meaning merely
to satisfy the task. Save an `.nndv.json` project.

Success: the edit remains editable and locked/manual constraints are not silently overwritten.

## T5 — Recover and export

Refresh the page, recover the autosaved/recent project, and verify the Panels and manual edits. Export
SVG, PDF, TikZ and PPTX (the Composer bundle is acceptable). Open the PDF and inspect its final size.

Success: the recovered project retains the composition and all four editable/publication formats are
non-empty.

## T6 — Finish and report

Return to Trial Mode, complete the task and download the local JSON. Tell the facilitator separately:
the first confusing point, any semantic claim you distrusted, and the one change that most reduced work.

Case assignment must cover the corpus across participants: dynamic PyTorch, ONNX multi-I/O, shared
module, Transformer residual, U-Net skip and custom unknown. A participant may complete more than one
case, but participant count and session count must be reported separately.

