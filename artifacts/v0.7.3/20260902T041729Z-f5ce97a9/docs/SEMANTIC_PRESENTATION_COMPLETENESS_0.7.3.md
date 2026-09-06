# Semantic presentation completeness in 0.7.3

## Contract

Architecture Evidence is the scientific authority. A generic role graph binds
each role and critical route to current Graph IR node/edge/port provenance.
Figure IR and Scene IR are projections of that role graph; coordinates and
names are presentation inputs, never architecture evidence.

For up to twelve roles, every role must have a direct reader-visible label.
Larger diagrams may use an explicit numbered legend or aggregation only when
role IDs remain one-to-one traceable and no scientific meaning is lost. A
failed fit is reported as a blocker; the renderer may increase page use,
change camera framing, route a leader, or rearrange content, but may not hide a
required label.

Each critical route must have a landed vector primitive, bound endpoints, and
direction evidence. Repetition must be visible as `×N` where appropriate.

## Independent landed-output evidence

The release pipeline uses independent readers rather than trusting Figure or
Scene in-memory metadata:

- SVG is decoded in Chromium. DOM visibility, computed transforms, role IDs,
  page bounds, font size, scale, collisions, clipping, and route arrows are
  measured from the landed document.
- PDF text is extracted independently and compared with normalized canonical
  role labels. Fonts must be embedded, Unicode-extractable, and not Base-14.
- TikZ source bindings are inspected, then seven isolated PDFs are compiled
  and their extracted text is checked independently.
- PPTX must contain editable text/shapes with role and route bindings; a
  flattened whole-slide image is rejected.
- The seven-model matrix requires exact equality for visible roles and landed
  critical routes in every model.

The geometric publication gate retains a 7 pt minimum with the existing 0.01
pt numeric conversion tolerance. Clipping, label-label overlap,
label-object collision, edge-node collision, unexplained crossings, and
non-uniform text scale must remain zero.

## Mutation sensitivity

The semantic presentation oracle is exercised against eight negative classes:
deleted role label; metadata-only/hidden label; off-page label; wrong role-ID
binding; deleted or reversed critical route; changed repeat count;
name/corpus/layout-only false positive; and stale Architecture Evidence digest.
Each mutation must trigger its corresponding blocker. A check that merely finds
one visible label cannot satisfy the 0.7.3 contract.

The machine-readable results are stored in the sealed artifact under
`reports/semantic/`, including the matrix, browser DOM report, cross-format
presentation report, and negative-mutation report.
