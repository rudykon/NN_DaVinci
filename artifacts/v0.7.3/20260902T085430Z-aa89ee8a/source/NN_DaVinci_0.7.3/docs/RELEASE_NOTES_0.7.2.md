# NN_DaVinci 0.7.2 release notes

## Scientific Fidelity & Semantic Scene Hotfix

0.7.2 preserves the 0.7.1 Scene/Figure publication workflow and changes how model architecture claims are established. Architecture Evidence 1.0 is now derived from Graph topology, explicit imported operation/module identity, ports and tensor shapes, and source-ID-backed Semantic detections. Display names, corpus keys, Python class names, filenames and requested layouts do not participate in family recognition. Unsupported or insufficiently evidenced inputs remain `unknown` with a reason.

The seven fixed real models now land architecture-specific roles, repeat counts and protected routes in both Figure IR and Scene IR:

- ResNet50: bottleneck stages with `[3,4,6,3]` repeats and residual skips.
- Vision Transformer and BERT encoder: attention, feed-forward and residual/norm roles.
- Multiscale U-Net: encoder/decoder levels and forward skip routes.
- Diffusion U-Net: input, conditioning, down/up path, bottleneck and output roles; the external sampling loop remains explicitly unknown.
- Top-k MoE: router, four experts, expert branches and weighted combine.
- Image/text model: separate image and text lanes, fusion and output roles.

An independent parity oracle reads the landed Graph IR, Semantic View, Figure IR and Scene IR documents. It rejects missing routes, role or repeat drift, tensor-contract disagreement, invalid source IDs and substituted provenance. The 14-case corpus includes 28 landed scientific documents and seven parity reports in addition to 140 Scene exports and fourteen 2D/3D comparisons.

Scene PDF export now uses packaged embedded TrueType fonts through Type0/CID fonts and ToUnicode maps. Base-14 fallback is forbidden. TikZ replaces the supported Unicode multiplication and centered-dot characters with portable LaTeX forms and compiles with a writable offline TeX cache.

Scene Studio now auto-frames visible world bounds when a Scene first opens. The camera fit is committed as camera state and does not mutate Scene object geometry.

## Compatibility and evidence boundary

The frozen parent is 0.7.1 run `20260831T154536Z-d8ec62b7`, with 383 source files, digest `d28a979c588dc998c0816e8757d70bca266d252b9c6f0098d56edd8e3021b2a9`, and 342 exact parent test IDs. The 0.7.2 quick gate requires those IDs, zero failures/errors/skips/deselections, and no regression from all four parent coverage floors. The full gate regenerates all evidence, runs seven Chrome suites, performs three-repeat performance checks, builds and installs wheel/sdist, and verifies the artifact independently.

This document does not predeclare a release PASS. Only a completed fresh `artifacts/v0.7.2/<run_id>/verification.json` is authoritative. No Git, upload, publication or human study is part of this work.
