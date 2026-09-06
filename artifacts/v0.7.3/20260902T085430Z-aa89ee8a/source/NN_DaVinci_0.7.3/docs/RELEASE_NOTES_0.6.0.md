# NN_DaVinci 0.6.0 Beta — Scientific Figure Studio

0.6.0 adds a dedicated scientific-figure authoring layer to the proven 0.5.2 model inspection baseline. Development occurs only in `NN_DaVinci_0.6.0_Dev`; the frozen 0.5.2 source, artifact, trial handoff and administrative pilot container are not migrated or modified.

## User-visible additions

- independent Figure IR 1.0 and project schema 1.3;
- true polygon-based Tensor Geometry for feature maps, sequences, matrices, vectors, scalars and unknown/symbolic shapes;
- Figure Studio with Layers, object tree, Groups, locks, physical guides, snapping, design tokens, annotations, proof and A–H Panels;
- Structure Lens for bounded traces/paths, architecture pathways, shape timelines, provenance/mismatch warnings, metric overlays, repeated structures and unknown explanations;
- seven editable offline architecture templates;
- versioned native SVG metadata round-trip;
- cross-format SVG/PDF/TikZ/editable-PPTX exports and an eight-file submission package.

## Scientific safeguards

- Graph IR, Semantic View and Figure IR remain separate.
- Geometry scale is visual metadata; labels are the authoritative shapes.
- Unknown dimensions stay `?` or symbolic.
- Author annotations are never presented as Graph IR provenance.
- Structure Lens returns `unknown`/`unsupported` when evidence is insufficient and never enumerates all simple paths on arbitrary graphs.
- Third-party SVG imports do not claim recovered model semantics.

## Compatibility

Project 1.2 and older compatible 1.x projects migrate to 1.3 with an empty Figure IR. No shape, semantics or provenance is invented. Existing 10k/50k lazy, summary and focus boundaries remain in place; large Figure entry uses a bounded semantic summary rather than full expansion.

## Automated acceptance surfaces

- all inherited Python tests plus Figure IR, Tensor Geometry, Layer/round-trip, Structure Lens and performance tests;
- dedicated Chrome Figure Studio workflow at 1440, 800 and 390 px;
- all seven templates checked for spatial proof and minimum 7 pt text;
- all 28 template/format combinations checked for SVG XML, embedded PDF fonts, standalone TikZ compilation and editable non-raster PPTX parity;
- 1,000-object Figure IR serialization/render/operation coverage;
- clean-snapshot packaging and v0.6.0 artifact inventory.

Exact final counts, durations, coverage and artifact identity are recorded in the fresh full-verification report, not estimated in this document.

## Human evidence

No human participant completed a 0.5.2 or 0.6.0 session. The stopped `pilot-DiKua23D` object is an administrative container with no consent, Trial Mode or human evidence. Automated tests are not participants. Therefore 0.6.0 makes no human-usability, learnability or completion-time claim.
