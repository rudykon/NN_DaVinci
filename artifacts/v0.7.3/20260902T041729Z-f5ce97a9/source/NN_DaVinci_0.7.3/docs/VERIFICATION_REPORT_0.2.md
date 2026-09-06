# NN_DaVinci 0.2.3 verification report

Verification time authority: sealed `verification.json` `started_utc` and
`ended_utc`; this source document deliberately does not hard-code a run-local
calendar date.  
Release command: `./scripts/verify-full.sh`  
Repository state: no Git repository was initialized or committed.

## Trust and baseline

The external anchor is `docs/TRUST_ANCHOR_0.2.2.json`, mode `0444`, expected
SHA-256 `10979b1d7112b7639207405dffe23f534762a02fb047b61540c5e04c955a3224`.
The verifier checks that literal before reading the anchor. The frozen 73-ID
file remains mode `0444`, SHA-256
`bd53e5272703b7d79399830ee146db8362c1e5f1e58798ecb95a731c695af838`.
All current Python tests must additionally collect and pass with zero failure,
error, skip and deselection.

The old 0.2.1 core ratios remain independent non-regression gates: line
`1893/2076 = 91.18497110%`, branch `648/778 = 83.29048843%`. Expanded core
adds `labels.py`, `scaling.py` and `verification.py`, with line ≥88.5% and true
branch ≥80%. All-package line and branch may not fall below
`3926/4716 = 83.24851569%` and `1264/1690 = 74.79289941%`. Denominator changes
are emitted per file. The 0.2.1 per-file inventory used to explain those
changes is marked non-authoritative and is never used to decide pass/fail;
the exact anchored total ratios remain the gate. Exclusions remain empty.
Against that inventory, the old-core statement denominator is unchanged at
2076 and only `layout/engine.py` changes the branch denominator, from 502 to
498; the retained 0.2.0 comparison remains a separately named historical field.
Historical 0.2.0 values were
line `1736/1952 = 88.93%`, branch `573/734 = 78.07%`, combined
`2309/2686 = 85.96%`.

The most recent sealed run records the exact current numerators below; the
document checker derives or verifies these strings from fresh coverage JSON:

```text
old_core line        1894/2076 = 91.23%
old_core branch       645/774 = 83.33%
old_core combined    2539/2850 = 89.09%
expanded_core line   2036/2238 = 90.97%
expanded_core branch  691/830 = 83.25%
expanded_core combined 2727/3068 = 88.89%
all_package line     4064/4875 = 83.36%
all_package branch   1307/1742 = 75.03%
all_package combined 5371/6617 = 81.17%
```

These strings are checked from current coverage JSON; displayed rounding is
never used for the gate.

## Closure changes

- 34 non-duplicate executable typed predicates replace the former 67-row
  over-count. All 48 legacy IDs map explicitly to canonical blockers without
  increasing the count. Each result records UTC start, duration,
  observed/expected value, evidence digest and failure reason.
- Every one of the 34 canonical predicates has a resealed matrix/post-seal
  parity mutation. Twenty composite cases separately mutate the 89-test floor,
  test-ID inventory, wide-DAG time/RSS/SVG, nested spatial completeness/time,
  replay-source/runtime extras, wheel hashes, sealed logs and validator code.
- `full.log` and `finalize.log` are closed before the versioned JSON
  `SHA256SUMS`. Only the root checksum file is excluded; nested identical,
  whitespace, backslash and newline-bearing names remain unambiguous entries.
  Copied and final paths are independently hash-checked and semantically
  replayed from raw evidence without importing the finalizer/matrix evaluator.
  The clean controller directory is deleted before either replay, and both
  sibling attestations record that its path is absent.
- The authority runs from a randomized clean snapshot. `source/snapshot.json`
  and `source/consumed-inputs.json` retain source/input lineage and reject old
  artifact/build/cache paths.

## Adversarial geometry and scale

The spatial implementation indexes both dimensions with an AVL interval tree,
whose height is deterministically logarithmic rather than priority-dependent,
preserves deterministic pair ordering, and exposes complete/truncated/lower
bound semantics with a default 1,000,000-pair budget. Full runs execute three
measurements of both 10k zero-output axis adversaries, twenty seeded distribution
differentials, 100 SCC differentials and real full/focus layouts for deep chain,
wide DAG, SCC, sparse skip and locally dense corpora. Raw wall/CPU/RSS/pair/SVG
records and structure invariants live in sealed `stress/results.json`.

The independent Chrome oracle now checks CTM anisotropy and singular values,
natural glyph advance, CSS/SVG stretch, annotation/legend/label/node geometry,
marker bodies, de Casteljau/control-hull flattened cubic/quadratic curves,
strict publication roles and input-side metadata identity. Twenty-six
hand-written positive/negative fixtures, including S curves, loops and
multi-turn curves,
include all nine required adversarial failures. The seven authority manifests
retain their fixed input SHA, node/edge IDs, critical edges, empty crossing
exception lists and RNN/MoE provenance.

## Environment and durable result

Full executes clean `npm ci` from `package-lock.json`, builds wheel and sdist,
installs each without `--no-deps` in separate fresh environments, rebuilds an
additional independent environment from the platform verification lock, hashes
every available/reconstructed wheel, runs `pip check`, CLI rendering and
package-data checks, and retains a platform-only 102-package dependency closure.
The closure expands Torch's `cuda-toolkit[...]` extras explicitly instead of
mistaking a successful `pip check` for proof that optional-extra libraries such
as `libcudart.so.13` are present.
It also regenerates seven formats,
compiles TikZ, checks PDF fonts/PPTX editability, runs the ten real Chrome E2E
scenarios and all compatibility/security tests.

The only authoritative numbers are those in the newest sealed
`artifacts/v0.2.3/<run_id>/verification.json`. It reports only the pre-seal
audit. Sibling copy/final attestations report independent replay, and the
external `release-decision.json` declares `release_audit` only after both pass.
The sealed bundle includes
`source/replay-source` and the isolated Node oracle runtime, so deletion of the
controller temporary directory does not break replay. `SHA256SUMS` covers every
retained regular file except the root manifest itself. This report is validated against current-run raw
coverage and policy evidence before sealing; it does not treat SHA inventories
as Git history.
