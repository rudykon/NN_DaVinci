# NN_DaVinci 0.4.2 — Scientific Fidelity Hotfix

0.4.2 preserves the 0.4.1 final-size publication quality and fixes scientific topology in the
three shipped real-model paper examples.

## Model-to-paper corrections

- ResNet50 now displays the first identity bottleneck (`layer1.1`) rather than presenting the
  projection transition `layer1.0` as a generic repeated block. Machine evidence records 16
  bottleneck bodies, four projection transitions, 12 identity bottlenecks and two exact Layer 1
  identity repeats.
- Vision Transformer detail is a directed boundary/path closure containing the attention and FFN
  residual merges. Both merges retain their bypass and transformed input, indegree two, output
  path, tensor shapes and source edge IDs.
- Multiscale U-Net overview now contains input, three encoder scales, bottleneck, three decoder
  scales and output. Three forward encoder–decoder skip paths remain visible and each decoder
  aggregate has two evidenced inputs.
- PyTorch FX placeholder tensors keep their source input names instead of being called
  `output_0`. Caption drafts name received inputs and produced outputs separately.

Every paper edge stores ordered source node/edge paths with forward direction. Repetition
signatures compare directed topology, shapes, operation type, parameters, scalar attributes,
merge indegree and optional projection branches. Uncertain semantics remain `unknown`.

## Release acceptance

Executable semantic goldens live in `verification/fixtures/scientific-fidelity/`. The independent
`SCIENTIFIC-FIDELITY` release blocker reads the landed `.nndv.json`, replays every source path
against Graph IR, and verifies required roles, key edges, merge indegree, repeat counts and caption
facts. It is additive to the retained publication-quality gate: all three SVG/PDF figures remain
178 × 118 mm, at least 7 pt, 300 DPI proof-rendered, and zero-overflow/overlap/collision/
clipping/unexplained-crossing with 1.0 text transforms.

The inherited suite remains 143/143 tests. Current coverage is:

- old core: line `2224/2437 = 91.26%`, branch `722/864 = 83.56%`, combined `2946/3301 = 89.25%`;
- expanded core: line `2426/2652 = 91.48%`, branch `792/944 = 83.90%`, combined `3218/3596 = 89.49%`;
- all package: line `7430/8573 = 86.67%`, branch `2275/2940 = 77.38%`, combined `9705/11513 = 84.30%`.

A successful fresh full run is written to `artifacts/v0.4.2/<run_id>`. The 34 inherited matrix
blockers and existing Chrome workflows are mechanically retained; 0.4.2 does not redesign their
attestation or mutation machinery.
