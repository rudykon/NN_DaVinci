# NN_DaVinci 0.7.1 publication visual report

This document defines what is inspected and where the machine measurements land. It does not predeclare a full-run verdict. The fresh artifact's `verification.json` and referenced raw reports are authoritative.

## Case-by-case scope

| Kind | Case | 0.7.0 issue reproduced | 0.7.1 acceptance |
|---|---|---|---|
| Template | CNN | Decorative framing and central annotation competition | Main content occupancy 55–90%, zero measured collision/clipping |
| Template | ResNet | Residual skip resembled a dominant empty frame | Colored directional skip arches, arrowheads retained, no edge-node collision |
| Template | U-Net | Skip leaders and center labels competed with decoder geometry | Semantic skip routes and external label lanes remain separated |
| Template | Transformer | Center text competed with repeated blocks/routes | Paper label budget and aggregation retain only argument-bearing labels |
| Template | MoE | Expert branches encouraged radial leader concentration | Router/expert/merge structure remains legible without starburst |
| Template | Multimodal Fusion | Modal labels and fusion routes crowded the middle | Separate streams, evidenced fusion, bounded leaders |
| Template | Diffusion U-Net | Conditioning route and U-Net skips competed | Conditioning material/route stays distinct with collision-free text |
| Real model | ResNet-50 | Large label stack and long edge prose | Repeated blocks aggregate; residual semantics remain traceable |
| Real model | Vision Transformer | Repeated attention labels and connector density | Bounded summary with prioritized token/attention/FFN labels |
| Real model | BERT encoder | Dense repeated encoder text | Aggregated encoder blocks with full text retained in metadata |
| Real model | Multiscale U-Net | Cross-scale skips, object overlap and long leaders | Stable camera, grouped levels and routed skip semantics |
| Real model | Diffusion U-Net | Conditioning/skip congestion and clipping risk | Independent conditioning route, external labels and page-safe bounds |
| Real model | Top-k MoE | Router/expert fan-out produced radial density | Connector cap, expert aggregation and non-starburst labeling |
| Real model | Image-text | Two-stream labels collided near fusion | Separate modal lanes and evidenced fusion point |

## Hard gates

For every final SVG, Chrome measures rendered DOM geometry using `getBBox()` and `getScreenCTM()`. The per-case verdict requires minimum text ≥7 pt, horizontal/vertical scale 1, no clipping/overflow, no label-label or label-object overlap, no edge-node collision, no leader-object or label-edge crossing, arrowhead correspondence, no unexplained starburst, and non-decorative occupancy within the publication band.

The independent cross-format oracle verifies ten signatures and semantics, true XYZ/camera/material/object/provenance payloads in Scene JSON/glTF/GLB, PDF and compiled-TikZ page size, fonts, extractable text, word boxes, page boundary ink, and cross-format label/object correspondence. Its result contains distinct format, true-3D, and publication statuses.

## Oracle truth

The positive fixture must pass. Mutations must fail for label stacking, label/object collision, clipped text, starburst leaders, huge decorative frame occupancy, and non-uniform text scale. A truncated toolbar fixture must fail at 390×844 and 568×320. The validator source is also mutated to a constant-true implementation and must be rejected.

## Persisted evidence

- `reports/visual/scene-svg-oracle.json`: fourteen individual landed-SVG results and geometry metrics.
- `reports/visual/scene-publication-oracle.json`: PDF, compiled TikZ PDF, ten-format and true-3D results.
- `reports/visual/oracle-fixtures.json`: positive/negative/mutation truth classifications.
- `reports/visual/scene-before-after.json`: fourteen hash-bound version comparisons.
- `evidence/publication-before-after/<kind>/<case>/before-0.7.0.png`: unchanged parent PNG.
- `evidence/publication-before-after/<kind>/<case>/after-0.7.1.png`: fresh current PNG.
- `evidence/publication-before-after/<kind>/<case>/before-after.png`: original-pixel side-by-side proof.
- `exports/scene-corpus/<kind>/<case>/scene.{svg,pdf,tex,pptx,png,eps,html,scene.json,gltf,glb}`: fresh final outputs.

Original-resolution PNGs and SVGs must still be visually inspected after the full run. Machine geometry is release-blocking evidence, not a substitute for scientific/domain review or human usability research.
