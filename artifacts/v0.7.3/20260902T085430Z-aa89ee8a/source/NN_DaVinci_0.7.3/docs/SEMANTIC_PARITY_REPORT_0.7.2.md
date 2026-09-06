# NN_DaVinci 0.7.2 semantic parity report

## Result boundary

Semantic parity in 0.7.2 means that the same source-backed architecture claim survives four independently landed surfaces: Graph IR, Semantic View, Figure IR and Scene IR. A family name alone is not evidence. The release gate requires all seven real-model cases to have non-`unknown` Architecture Evidence 1.0, matching evidence provenance digests on the three derived surfaces, and no omitted protected critical route.

Only a fresh `artifacts/v0.7.2/<run_id>/verification.json` may declare the release gate passed. This source document defines the expected result and how to reproduce it; it does not substitute for the artifact report.

## Seven-model contract

| Real model | Evidence family | Expected roles | Protected routes | Scientific interpretation | Explicit uncertainty |
|---|---:|---:|---:|---|---|
| ResNet50 | `resnet` | 6 | 4 | input stem, four bottleneck stages with repeats `[3,4,6,3]`, output head; four residual skips | none |
| Vision Transformer | `transformer` | 5 | 1 | image/class-token input, repeated attention, FFN and residual/norm roles, output | class token is asserted only when the rank-4 input and importer path support it |
| BERT encoder | `transformer` | 5 | 1 | token/position input, repeated attention, FFN and residual/norm roles, output | image class token is explicitly not applicable |
| Multiscale U-Net | `unet` | 9 | 3 | three encoder levels, bottleneck, three decoder levels, output and forward skips | none |
| Diffusion U-Net | `diffusion-unet` | 6 | 5 | input, conditioning, down path, bottleneck, up path and output; conditioning routes retained | external sampling loop remains `unknown` without a source-backed cycle |
| Top-k MoE | `moe` | 5 | 5 | router, four experts, expert branches, weighted combine and output | none |
| Image/text fusion | `multimodal-fusion` | 4 | 2 | separate image and text lanes, fusion and output | none |

For every row, the expected, Figure and Scene role counts must be identical; the expected, Figure and Scene protected-route counts must also be identical. The independent corpus validator additionally requires seven parity reports, 28 landed scientific documents and `zero_critical_omission_real_models = 7`.

## Independent oracle

The parity oracle reads these files from each `exports/scene-corpus/real-models/<case>/` directory:

- `graph.graph.json`
- `semantic.semantic.json`
- `figure.figure.json`
- `scene.scene.json`
- `semantic-parity.json`

It does not invoke the production Figure or Scene projection builders. It recomputes source-ID membership, tensor-contract validity, role/repeat agreement, route endpoints and source edges, evidence digest equality, and critical omissions from the serialized documents. A parity report passes only when `passed` is true and `failures` is empty.

Negative controls delete residual, U-Net, MoE or multimodal routes; change repeat counts or roles; substitute source IDs; and tamper with the evidence digest. Each mutation must be rejected. Display names, corpus keys, Python class names, filenames and requested layout are separately tested as forbidden recognition inputs.

## Reader verification

A reader can answer the release questions directly from the fresh artifact:

1. Inspect `verification.json.scientific_fidelity` for seven non-unknown models, seven parity reports, 28 landed documents and seven zero-omission models.
2. Inspect each real model's `semantic-parity.json` for its family, role counts, route counts, provenance digest, uncertainty and empty failure list.
3. Resolve every `landed_documents` digest to the adjacent Graph, Semantic, Figure and Scene file.
4. Inspect `reports/exports/scene-artifacts-validation.json` for independent validation, exact counts and no failures.

The claim stops at the fixed seven-model corpus. Unknown or insufficiently supported architectures remain `unknown`; 0.7.2 does not claim universal architecture recognition.
