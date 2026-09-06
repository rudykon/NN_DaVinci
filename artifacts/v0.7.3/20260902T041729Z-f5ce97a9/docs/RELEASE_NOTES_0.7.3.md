# NN_DaVinci 0.7.3 release notes

## Reader-Visible Scientific Completeness & Generalization Hotfix

0.7.3 closes a specific gap in 0.7.2: Architecture Evidence could contain a
correct role while the final paper projection omitted its label. The current
production path builds a generic role graph from `detected_roles`,
`repeat_count`, `critical_routes`, and their Graph IR provenance, then derives
Figure and Scene publication projections from that graph. For figures with at
most twelve roles every role is directly labelled; label budgeting and
collision handling cannot silently delete a scientific role.

The seven fixed real-model results now expose the complete reader-visible set:

| Model | Visible roles | Landed critical routes |
|---|---:|---:|
| ResNet50 | 6 | 4 |
| Vision Transformer | 5 | 1 |
| BERT encoder | 5 | 1 |
| Multi-scale U-Net | 9 | 3 |
| Diffusion U-Net | 6 | 3 |
| Top-k MoE | 5 | 5 |
| Image-text fusion | 4 | 2 |

This restores ResNet stage 1, ViT/BERT embeddings, U-Net decoder level 2,
diffusion conditioning/up path, and the MoE input/embedding. Repeated roles use
`×N`; every protected route retains a landed path, endpoint binding, and arrow
direction. SVG and browser DOM/CTM checks prove that labels are visible and
inside the page. Independent PDF text extraction, TikZ source and compiled-PDF
extraction, and editable PPTX inspection prove the same normalized role set.

## Generalization and negative evidence

Recognition does not use corpus keys, graph/model display names, filenames,
Python class names, requested layout families, or existing 2D/3D positions.
The fixed-corpus projection remains only as an inherited compatibility fallback;
stage/paper production uses the Architecture Evidence role graph first.

Seven deterministic metamorphisms rename graph and module vocabulary, replace
sample metadata keys, reorder nodes/edges/input branches, and inject unrelated
coordinates while preserving typed operations, topology, ports, shapes, and
hierarchy. Family, role/repeat signatures, critical-route types, and rebound
source provenance remain stable. Ten depth/width variants cover alternate
ResNet repeats, Transformer depth, U-Net levels, MoE expert/top-k settings, and
both multimodal branch orders. Removing decisive edges must produce unknown,
lower confidence, or explicit evidence loss.

Eight landed-output mutations prove that the oracle is not a producer-side
boolean: deleted, hidden, off-page, wrongly bound, repeat-drifted, stale-digest,
and missing/reversed-route cases are rejected, as is a name/corpus/layout-only
false positive.

## Service and evidence hygiene

`/api/health` returns product version, PID, uptime, bound host/port,
source/build identities, and readiness. The start/status/stop/restart scripts
validate PID identity and process start time, refuse unrelated listeners,
verify readiness after the launcher exits, and confirm port release. Loopback
is still the default. Binding to `0.0.0.0` emits an explicit warning because
the service has no authentication.

Package, CLI, Web health, current reports, and current schemas identify 0.7.3.
Historical E2E schemas remain labelled inherited inputs in the current aggregate
report. The release audit contains an explicit stale-current-version blocker.

The frozen parent is authoritative 0.7.2 run
`20260901T142604Z-010606e8`: 410 allow-listed source files, source digest
`6d4591e41fd423604fe3537aba200bcdd57e4254c0684dc6bd5b3672fd9c169e`,
and 353 exact Python test IDs. The parent tree and artifact remain read-only.
No Git operation, upload, publication, or human study is part of this release.

Only a fresh sealed `artifacts/v0.7.3/<run_id>/verification.json` is the
authoritative verdict. Source-tree and `/tmp` reports are diagnostic inputs,
not a release declaration.
