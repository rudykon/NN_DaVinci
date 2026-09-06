# NN_DaVinci 0.7.2 scientific fidelity report

## Claim boundary

0.7.2 treats architecture recognition as an evidence claim, not a drawing style. The detector accepts Graph topology, importer-declared operation/module identities, ports and tensor shapes, and Semantic detections that resolve to real source IDs. It does not inspect a graph display name, corpus key, Python class name, filename or requested layout to select a family. If supported evidence is insufficient, the result is `unknown` with an explicit reason.

Architecture Evidence 1.0 records family/confidence/reasons, exact supporting node/edge/port IDs, roles, repeat counts, protected critical routes, alternatives, uncertainty, the Semantic source digest and a sealed provenance digest. Validation rejects stale digests and missing source IDs.

## Four-surface parity

For every fixed real model, the corpus serializes Graph IR, Semantic View, Figure IR and Scene IR. The parity oracle reads those landed documents and does not call either production projection builder. It checks:

- the evidence digest is identical across Semantic, Figure and Scene;
- every expected role and critical route appears exactly once in Figure and Scene;
- repeat counts and scientific labels agree;
- protected routes retain their exact source edges and endpoints;
- tensor shape/dtype claims occur in the source Graph contract;
- no critical structure was omitted by either paper projection.

Mutation tests delete residual/U-Net/MoE/multimodal routes, change repeat counts, relabel roles and tamper with evidence. Each mutation must fail independently.

## Fixed corpus expectations

| Model | Required landed structure |
|---|---|
| ResNet50 | four bottleneck stages, repeat counts `[3,4,6,3]`, four residual-skip routes |
| Vision Transformer | class-token input plus three repeated attention, FFN and residual/norm roles |
| BERT encoder | token/position input plus three repeated attention, FFN and residual/norm roles |
| Multiscale U-Net | three encoder levels, bottleneck, three decoder levels and three forward skip routes |
| Diffusion U-Net | input, conditioning, down path, bottleneck, up path and output; three conditioning routes; external sampling loop unknown |
| Top-k MoE | router, four experts, output, four expert branches and one weighted-combine route |
| Image/text fusion | separate image and text lanes, fusion and output, with two multimodal stream routes |

The release corpus must contain seven non-unknown real models, seven independent parity reports, 28 landed scientific documents, and seven real models with zero critical omission. These counts are checked separately from the 14 Scene cases and 140 format exports.

## Publication and camera hotfixes

All fourteen Scene PDFs must contain embedded packaged TrueType fonts, Type0/CID font dictionaries and ToUnicode maps, with no Base-14 fallback. All fourteen TikZ sources must compile offline. Every landed Scene SVG is remeasured in Chrome for labels, clipping, collisions, route crossings and physical constraints.

Initial browser framing uses actual visible Scene world bounds and camera projection. Tests rotate cameras, compare orthographic and perspective behavior, exercise very wide/tall/deep Scenes, and confirm that fitting changes camera state rather than object geometry.

## Evidence status

Focused and quick checks are machine evidence. The source documentation does not declare the final release result; only a fresh sealed `artifacts/v0.7.2/<run_id>/verification.json` may do so. There are zero human participants and zero completed human sessions, and no Git or publication operation is performed.
