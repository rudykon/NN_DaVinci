# NN_DaVinci 0.2.2 Beta release notes

> Superseded by 0.2.3: independent audit found deterministic post-seal
> false-passes for the 89-test floor, named-graph budgets and the nested spatial
> adversary. The 0.2.2 product fixes remain valid, but its verification closure
> claim must be read with that qualification.

0.2.2 is a backward-compatible verification-closure and adversarial-geometry
fix. It does not add five-level browsing, a lazy canvas, asynchronous task UI,
new frameworks or new export formats.

## Fixed

- Collapsed the former 67-row over-count into 34 independently replayable
  semantic blockers. All 48 legacy IDs map explicitly to canonical blockers.
- Added fail-closed evidence/code mutation tests and an immutable external trust
  anchor check for the frozen 73 Python test IDs and historical thresholds.
- Closed all retained logs before a versioned, unambiguous JSON `SHA256SUMS`;
  fixed nested-name/newline/backslash ambiguity and bundled the clean source,
  verifier and Node oracle runtime for replay after controller cleanup.
- Replaced the recursive priority treap with a deterministic-height AVL
  interval index and
  explicit million-pair truncation semantics; added zero-output and distribution
  adversaries plus SCC differential/large graph structure gates.
- Corrected the final SVG oracle's transform/text compression measurement and
  added strict roles, input-side metadata, annotation/legend, marker-body and
  de Casteljau/control-hull screen-space curve geometry checks with 26
  known-truth fixtures, including S curves, loops and multi-turn paths.
- Added copyable CLI `--focus`, `--focus-hops` and `--summary` recovery paths
  shared with API/Web scale policy.
- Split publication rendering from editor controls. `Expert ×4` provenance is
  retained while `⊞`, resize handles and selection affordances are absent from
  publication exports.
- Added old/expanded/all coverage gates, a Linux CPython 3.13 transitive
  verification lock, an independent lock-driven environment rebuild with
  102 exact packages (including expanded Torch CUDA extras), available wheel
  hashes, clean `npm ci` with an empty run-local cache, dependency-aware
  wheel/sdist installs and `pip check`.
- Added a per-file 0.2.1→0.2.2 all-package denominator diff. Its historical
  inventory is explicitly diagnostic-only; exact release ratios and thresholds
  still come only from the immutable external trust anchor and current raw
  coverage JSON.

## Evidence policy

Authoritative full verification always starts from a randomized clean source
snapshot and never consumes old artifacts. Successful evidence is atomically
promoted only under `artifacts/v0.2.2/<run_id>/`; post-seal attestations remain
sibling files. Nightly is intentionally a full alias and adds no separately
counted workload because full already contains mutation/property/adversarial
and clean dependency rebuild gates.

The project still has no Git repository. No commit, upload, remote or package
publication was created by this release work.
