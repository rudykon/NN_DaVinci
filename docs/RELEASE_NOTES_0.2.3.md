# NN_DaVinci 0.2.3 Beta release notes

0.2.3 is a backward-compatible post-seal semantic-parity hotfix. It adds no
0.3 product features, frameworks, export formats or editor workflows.

## Fixed

- The independent post-seal verifier now executes every canonical row's real
  JSON Pointer, observed type and comparison in addition to its separately
  implemented semantic check. The Python gate enforces `passed >= 89`,
  `collected == passed == tests == collected-ID lines == unique IDs`, zero
  failed/error/skipped/deselected, and the anchored 73-ID subset.
- All four named graph corpora independently recheck three fixed-hash runs,
  structure and every time/RSS/SVG budget. The spatial gate now includes all
  three 10k zero-output adversaries, including `nested_x_y_filtered`.
- Replay source and Chrome runtime inventories require exact ordinary-file
  equality with their manifests. Extra files, missing files, symlinks and
  special files are release failures even after a valid reseal.
- The mutation report now covers all 34 canonical predicates plus 20 composite
  subconditions, including the independently reproduced 73/89, wide-DAG and
  nested-spatial false-passes.
- `verification.json` now names its internal decision `pre_seal_audit`. Only an
  external sibling `release-decision.json`, created after both copy and final
  attestations pass, may name the final `release_audit`.
- Verification-environment reconstruction permits an installed-distribution
  fallback only for explicitly allow-listed TorchCAM. Every other locked wheel
  must come from the configured index; all consumed wheel hashes remain in
  sealed evidence.

## Evidence policy

Authoritative full verification starts from a randomized allow-listed source
snapshot and never consumes old `artifacts/`, build trees or caches as pass
inputs. A successful run is atomically promoted under
`artifacts/v0.2.3/<run_id>/`; copy/final attestations, the release decision and
their outer checksum remain sibling files. Nightly remains an explicit full alias
and is not counted as additional coverage.

The project is still not a Git repository. No repository, commit, tag, upload,
remote or package publication was created by this hotfix.
