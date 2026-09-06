# Participant Guide

You will use a local diagram editor to inspect an ML model and create an editable paper-figure draft.
This is a test of the tool, not of you. You do not need to read CLI documentation.

## Before starting

1. Start the supplied local build and open the displayed loopback address in Chrome.
2. Open **Trial Mode**. Read the privacy summary and `CONSENT.md`.
3. If you agree, tick the consent box yourself and choose **Enable local recording**. Until then, no
   trial directory or event file is created.
4. Choose the assigned model case. The included cases use random local weights or ONNX initializers and
   need no network. For your own Python/pickle model, do not approve execution unless you trust it.

## What the interface records

Only event categories, elapsed milliseconds, graph/visible-object counts, edit counts, export formats,
error categories and recovery actions. It does not record the model, filename, path, node names,
labels, searches, comments or your identity. It does not upload anything.

## During the task

- Treat **unknown** as “not enough structural evidence”, not as a broken node. Inspect its reason and
  source provenance. Change the semantic only if the evidence supports your change.
- Paper View may aggregate repeated structure. Switch to Faithful View or drill to Operation to verify
  the represented path.
- A figure is paper-ready only when the Composer proof says so. The tool must not obtain this result by
  reducing the final font below 7 pt.
- If an action fails, follow the visible recovery hint, then continue. Please say aloud what was
  confusing if the facilitator is collecting separately consented notes.

## Finishing and withdrawal

Complete the four required editable exports, save the project, refresh/recover it, then choose
**Complete current task**. Download the local JSON if you want to inspect or share it. You may choose
**Revoke consent** at any time; this ends the active task and prevents further recording. You can ask
the facilitator to delete the local JSON without penalty.

