# NN_DaVinci 0.6.0 Researcher Trial Protocol

## Purpose and status

This protocol evaluates whether an ML researcher can inspect an unfamiliar model and produce an
editable paper-figure draft with NN_DaVinci. It evaluates workflow usability and semantic trust; it
is not a benchmark of the participant or their research. No 0.6.0 human study is currently scheduled
or authorized. Human conclusions remain unavailable until a separately governed study recruits and
records consented, non-developer ML researchers.

Protocol version 1.0 and the `0.5.0-trial-events-1` privacy schema are intentionally unchanged by
0.6.0. Those identifiers describe protocol compatibility, not the product build. No 0.5.0, 0.5.1 or
0.5.2 session is converted into 0.6.0 evidence; any future session must identify a separately frozen
0.6.0 build in a newly governed ledger.

## Participants and roles

- Recruit 3–5 researchers who build, inspect or publish ML models and were not involved in this
  implementation. Record no names, employers, model paths or free-form feedback in Trial Mode.
- A facilitator provides the build and the participant guide, answers only recovery questions, and
  records qualitative feedback in a separately controlled anonymous notes form.
- A reviewer checks semantic issues against Graph IR/source provenance before classifying severity.
  Automation and developer self-tests are regression evidence only and are never counted as people.

## Environment

Use one local workstation, a loopback Web server and an offline example or a participant-owned model
whose execution safety has been decided by the participant. Record the build version, OS, browser,
CPU and RAM in the study log outside Trial Mode. Do not copy model paths into the exported event JSON.

## Procedure

1. Give the participant `CONSENT.md` and `PARTICIPANT_GUIDE.md`. Do not enable Trial Mode for them.
2. After explicit consent, the participant enables Trial Mode and selects one task case.
3. The participant follows `TASKS.md` without CLI documentation. The facilitator does not lead the
   clicks, but may point to the visible recovery action after an error.
4. The participant downloads the local event JSON and may inspect or delete it before handing it to
   the facilitator.
5. The facilitator records task outcome, anonymous issue category and verbatim feedback only with
   the separate consent described in `CONSENT.md`.
6. A scientific reviewer verifies any alleged semantic error using node/edge source-path provenance.

## Measures and thresholds

The event schema derives first interactive view time, first paper-ready time, semantic/node/edge/label
edit counts, export outcomes, errors and recovery actions. The release targets are:

- median first interactive view/first figure no more than 5 minutes;
- median paper-ready figure no more than 15 minutes;
- core task success at least 80%;
- zero serious semantic errors.

A core task succeeds only after import, paper-ready proof and successful SVG, PDF, TikZ and PPTX
exports. “Serious semantic error” means a wrong data-flow direction, missing or invented residual/skip/
merge path, false repeated count, wrong input/output role, or unsupported numerical claim that could
mislead a paper reader. An explicit `unknown` backed by provenance is not an error.

## Analysis rules

Report every completed and abandoned task. Use median times and exact numerator/denominator for task
success. Separate usability, compatibility, recoverability, terminology and scientific-fidelity
issues. Do not infer population-level usability from fewer than three participants. Do not replace
missing human observations with E2E measurements. Automated click counts and first-figure timings must
be labelled `automated`.

## Data handling

Trial Mode is opt-in and local-only. Its strict allowlist excludes model bytes, filenames, paths,
node/edge IDs, labels, search text, comments, user identity and free text. Files are mode 0600 in a
mode 0700 local directory. Nothing is uploaded. A participant can revoke consent, inspect/download the
JSON, or delete the local trial directory. Qualitative notes require separate handling and must use a
random participant code not stored in Trial Mode.

## Stop conditions

Stop a task if the participant withdraws, the model contains data they do not want processed, trusted
code execution is unclear, or the tool enters an unrecoverable state. Mark the session `consent_revoked`
or `abandoned`; never rewrite it as success.
