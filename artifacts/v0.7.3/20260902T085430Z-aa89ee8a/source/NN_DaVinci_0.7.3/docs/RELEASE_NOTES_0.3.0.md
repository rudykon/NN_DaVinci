# NN_DaVinci 0.3.0 — Semantic Canvas & Paper Workflow

0.3.0 turns NN_DaVinci from a full-graph renderer with editing tools into a local research
workflow: inspect an import, understand its structure at the useful semantic scale, refine a
reviewable paper layout and export the same editable project to publication formats.

## Research workflow

- The import wizard recognizes PyTorch factory, TorchScript, `state_dict`, ONNX, Keras,
  TensorFlow, JAX, MLIR, JSON/YAML and project inputs without executing them. It exposes the
  trust boundary, sample/multiple-input requirements, estimated graph scale and recommended view,
  semantic level, page and label density. Python factories and pickle remain explicit opt-ins;
  `state_dict` is correctly described as weights without recoverable topology.
- The independent Semantic View 1.0 derives `model → stage → block → layer → operation`
  from Graph IR. Residual, attention, encoder/decoder, U-Net skip, repeated block, MoE router/
  expert and diffusion-loop matches include confidence, reasons and source node/edge provenance.
  Unknown structure stays `unknown`. Faithful View and Paper View are separate and every summary
  item can be traced in both directions.
- The Web editor adds breadcrumbs, a structure tree, double-click drill, parent navigation and
  full-graph restore. Search, source selection, focus, analysis overlay, comments, locked
  positions and manual routes survive semantic-level switches.
- Project schema 1.1 persists semantic, canvas, import, task and paper-workflow state and migrates
  0.2.x schema 1.0 projects. Python API, CLI and project rendering accept `level` and `view`.

## Lazy canvas and task center

The loopback server now provides graph summary, semantic materialization, viewport slice,
neighborhood, search and provenance endpoints. The browser creates only the current slice and
stable cross-boundary proxy/stub objects. Synchronous full rendering still rejects more than
2,000 nodes or 12,000 edges, so lazy browsing is not implemented by disabling a safety bound.

The release Chrome workflow opens a real 10,000-operation graph at a semantic first view in
approximately 1.70 seconds on the acceptance host. It gates at most 500 visible nodes, at most
2,000 SVG graphic objects, first interaction at no more than 2 seconds and viewport refresh at no
more than 200 ms. The direct server viewport benchmark is about 5 ms on that host; these are
measured release-environment results rather than universal hardware guarantees.

Import, analyze, layout, runtime and export share local persistent task records with queued,
running, succeeded, failed and cancelled states. Records show phase, progress, elapsed time,
input scale and resource budget, support cooperative cancellation/retry, survive refresh and
identify stable results or artifacts. Failures provide recovery suggestions such as supplying a
sample input, selecting module/summary view, reducing focus or changing page.

## Paper optimizer

The optimizer returns at most three candidates and never changes the diagram before the user
selects one. Each candidate shows before/after node overlap, edge-node collision, crossings,
bends, path length, symmetry, whitespace balance, label overflow, minimum font and critical-edge
salience. Applying a diff creates an undo point and protects locked nodes, manual route interiors,
comments and annotations. Proof preview uses single-column, double-column, wide-two-column and
multi-panel dimensions. Compact, paper, detailed, teaching, grayscale and colorblind presets are
available; an impossible 7 pt readability request reports the responsible constraint.

## Compatibility and acceptance

The existing importers, analysis, seven-format export, plugins, editor functions and all ten
0.2.3 Chrome scenarios remain present. Semantic corpus includes the existing seven architecture
families, weight-free torchvision ResNet18 and a local lightweight Transformer factory. A new
real-Chrome workflow covers import, semantic drill, search/provenance, Paper View, candidate
comparison/application, node and edge edits, project refresh recovery and SVG/PDF/TikZ/editable
PPTX export.

The 0.3.0 verification controller writes only successful final evidence beneath
`artifacts/v0.3.0/<run_id>`. The 0.2.3 release-proof machinery is mechanically inherited rather
than redesigned: the source of release gates remains `acceptance-matrix-0.2.3.json`, and the
bundle still includes `SHA256SUMS`, `consumed-inputs.json`, `pre_seal_audit`, independent replay
attestations and sibling `release-decision.json`. The nightly script remains a `full alias`.
The workspace has no Git repository and this release does not initialize one.

The final development quick report ran 130/130 Python tests. Its raw coverage fractions are:

| Scope | Line | Branch | Combined |
|---|---:|---:|---:|
| old core | `2178/2365 = 92.09%` | `713/852 = 83.69%` | `2891/3217 = 89.87%` |
| expanded core | `2331/2527 = 92.24%` | `763/908 = 84.03%` | `3094/3435 = 90.07%` |
| all package | `5525/6477 = 85.30%` | `1762/2298 = 76.68%` | `7287/8775 = 83.04%` |

Historical correction retained by the inherited documentation gate: old 0.2.0 line
`1736/1952 = 88.93%`, branch `573/734 = 78.07%`, combined `2309/2686 = 85.96%`.

## Remaining boundaries

The service remains loopback-only, single-user and unauthenticated. There is no cloud service,
multi-user collaboration, account system, true 3D tensor renderer, cross-platform release matrix
or plugin marketplace. Dynamic framework execution still represents sampled paths, and optional
export/framework dependencies remain required for their respective formats.
