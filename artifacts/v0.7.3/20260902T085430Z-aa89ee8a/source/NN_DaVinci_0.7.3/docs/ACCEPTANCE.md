# NN_DaVinci 0.2.3 acceptance

`./scripts/verify-full.sh` is the release gate. It first verifies the externally
supplied read-only trust anchor using the expected SHA-256 literal passed on the
command line, copies an explicit source allowlist to a randomized clean path,
and runs every input-dependent check there. Old `artifacts/`, build trees,
caches and `node_modules` are excluded and rejected by consumed-input lineage.

The executable mapping is
`verification/acceptance-matrix-0.2.3.json`. Its 34 rows are distinct semantic
blockers. All 48 legacy IDs have an explicit mapping to a canonical blocker;
aliases are retained for traceability but are not counted as extra checks.
Every row names an allow-listed semantic validator, real command provenance,
an evidence file, RFC 6901 JSON Pointer, observed type and predicate. Matrix row
count is not a test count; `release_blocker_checks` counts only rows that ran and
saved an independent result.

## Blocking groups

| Group | Blocking command/oracle | Required evidence |
|---|---|---|
| Anchor and Python IDs | `verify_trust_anchor.py`, `run_tests.py` | trust SHA/mode, frozen 73/73, all collected/passed, zero failed/error/skipped/deselected |
| Coverage | `summarize_coverage.py` | old-core anchored ratio, expanded-core line ≥88.5%/branch ≥80%, all-package anchored ratio; raw numerators/denominators |
| Matrix fail-closed | `validate_acceptance_matrix.py`, `run_matrix_mutations.py` | all 34 typed predicates are mutated and rejected by both evaluators; 20 composite cases separately cover count, graph budgets, nested spatial, inventory, wheel hashes, seal and validator code |
| Seal | `seal_evidence.py`, independent `verify_sealed_bundle.py` | versioned JSON inventory covers every regular file except the root `SHA256SUMS` itself, including nested files named `SHA256SUMS`; copied and final path raw semantic replay both clean |
| Large graphs | `benchmark_large_graph.py`, `capture_*_large_graph_evidence.py` | iterative SCC; real wide/SCC/skip/dense layouts; 100/1k/10k budgets; 10k zero-output spatial adversaries ≤2 s each run; explicit pair budget |
| Final SVG | separate Chrome `svg_quality_oracle.mjs` | strict roles/metadata, CTM/glyph scale, marker/object geometry, de Casteljau control-hull curve flattening and 26 hand-authored truth fixtures |
| Seven authorities | `verify_visual_fixtures.py`, strict oracle | fixed input SHA and IR/provenance, empty crossing exceptions, zero clipping/overlap/collision/crossing, ≥7 pt and scale ratios ≥0.85 |
| Publication | `validate_publication_exports.py` | SVG/PDF/PNG/TikZ/EPS/PPTX exclude `⊞`/resize/selection controls; MoE `Expert ×4` retained |
| Browser | ten stable IDs in `tests/e2e/editor.e2e.mjs` | isolated project state, direct coordinate/route/state assertions, console errors and skips zero |
| Formats/packages | fresh generation plus font/TikZ/PPTX/package validators | seven formats, embedded fonts, independently compiled TikZ, editable PPTX, safe HTML, wheel+sdist dependency install and `pip check` |
| Environment | clean `npm ci`, platform lock, environment/source manifests | exact Linux CPython 3.13 dependency closure, Node lock install, root configs, no Git initialization |

## Atomic evidence lifecycle

The authoritative sequence is:

```text
clean snapshot workload → close full.log → pre_seal_audit → close finalize.log
→ SHA256SUMS → copy → independent hash/semantic replay
→ atomic local rename → independent final-path replay
→ external release-decision.json referencing both attestation hashes
```

The final short terminal summary is not appended to sealed logs. The bundle
contains its clean source snapshot, verifier, Chrome oracle and Playwright
runtime, so replay does not require the deleted controller directory. Post-seal
attestations are sibling files with their own checksum. Success evidence lives
at `artifacts/v0.2.3/<run_id>/`; failed staging is explicitly
non-authoritative. `SHA256SUMS` is not Git history, and the project remains
without a Git repository.

## Stable browser scenarios

`load-console-security`, `node-drag-coordinates`,
`connect-route-constraint`, `align-distribute-lock-hide-geometry`,
`undo-redo-state`, `group-collapse-focus`,
`annotation-presentation-persistence`, `project-round-trip`,
`seven-format-downloads`, and `dom-xss` are the ten release metrics. Assertion
count is diagnostic only.

## Historical coverage correction

The 0.2.0 `percent_covered=85.96%` value was combined coverage, not branch
coverage. The historical values were line `1736/1952 = 88.93%`, branch
`573/734 = 78.07%`, combined `2309/2686 = 85.96%`. All 0.2.3 thresholds compare
unrounded fractions.

## Additive 0.5.0 Beta trial-kit blocker

`trial/acceptance.json` adds five product checks without changing the inherited 34-row matrix:
runtime/landed privacy schema identity, all six external Web model workflows, NeurIPS/ICML/IEEE
PDF+TikZ proof, complete participant documents, and an honest `awaiting_participants` human status.
The Chrome trial workflow imports all six cases, audits Faithful/Paper views, produces a paper-ready
block+operation composition, exports an editable bundle and project, refreshes, recovers and completes
the local session. Its clicks and timings are explicitly automated and cannot satisfy human targets.

## Additive 0.5.1 Composer recovery hotfix

The inherited product Chrome workflow now blocks on exact recovery rather than node presence. It
records a participant-like Composer edit sequence, then requires unchanged Panel layout digests,
shared controls, Panel semantics, locked-node count and manual-route count after autosave refresh and
after reopening the downloaded project. The project round-trip test separately preserves viewBox,
zoom and the fixed-layout flag. These checks do not alter or satisfy the human-trial denominator.
The six-case Trial Chrome workflow repeats the node drag, edge reroute, autosave refresh and project
reopen for every external case. Its 65 assertions are blocking only when all per-case layout digests,
locks, routes and the final nonzero node/edge edit summaries survive; it remains automation-only.

## Additive 0.5.2 responsive workspace hotfix

`e2e/responsive-workspace.json` is a separate pre-seal product gate. Real Chrome must pass all seven
fixed viewports (1440×900, 1024×768, 800×720, 768×720, 568×320, 390×780 and 320×568),
canonical left/Inspector drawer access, mutually exclusive surfaces, keyboard focus trap/return,
breakpoint cleanup and bounded workflow dialogs with zero console/page errors. At 320 px the same run
must import a real example, select block and Paper View, produce exactly the universal Composer A/B
defaults, save `.nndv.json` and export SVG. Reopening Composer may not add duplicate panels.

This report is additive to the inherited ten Editor scenarios, Semantic workflow, Product workflow,
Trial workflow and 34-row matrix. It does not change the frozen Trial schema or turn automated timing
into a human usability claim.
