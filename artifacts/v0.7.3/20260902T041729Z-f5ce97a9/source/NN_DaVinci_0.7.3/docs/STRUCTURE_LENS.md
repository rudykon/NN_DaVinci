# Structure Lens

Structure Lens is NN_DaVinci 0.6.1's bounded, evidence-linked analysis surface for paper authors. Results point to Graph IR nodes, edges, ports, tensors and source locators. Missing evidence yields `unknown` or `unsupported`; a display name or keyword alone cannot create a positive architecture claim.

## Queries

- upstream or downstream trace from a selected node;
- bounded directed input-to-output paths;
- residual/skip, attention and MoE-routing evidence highlights;
- port-bound shape-transition timeline;
- potential shape-mismatch, ambiguous port-binding and incomplete-provenance warnings;
- parameter, FLOP and activation-memory overlays;
- exact repeated-structure signatures with `×N` and source-node expansion;
- explanation of unknown nodes and the evidence that is missing.

Each result contains stable node/edge IDs, evidence records, warnings and query metadata. Metric gaps remain null/unknown and are never coloured or summed as zero.

For residual, attention and MoE pathway queries, the HTTP route supplies both Graph IR and the project's validated Semantic View to `StructureLens`. Semantic entity evidence is evaluated before Graph-only fallback. Result metadata exposes `semantic_view_consulted`, `semantic_evidence_prioritized`, numeric `confidence`, a human-readable `reason`, and `positive_claim`. A keyword-only display name returns confidence `0.0` with `positive_claim=false`; it never becomes evidence by presentation alone.

## Status semantics

| Status | Meaning |
|---|---|
| `supported` | the bounded query completed and has evidence for its reported positive result |
| `partial` | cancellation or a declared budget stopped a valid partial traversal |
| `unknown` | the graph lacks sufficient evidence for a positive conclusion |
| `unsupported` | the requested rule/metric is absent, invalid for the selection, or no directed path exists |

Warnings are review candidates, not automatic proof that a model is wrong. A known rank or dimension difference is labelled a *potential* mismatch because an unrecorded transform may explain it.

Every positive pathway result names its exact supporting nodes/edges and recognition reasons. A low-confidence candidate remains a review candidate with its confidence and reason; negative/unknown results explicitly carry `positive_claim=false`. This field is the machine boundary that prevents a UI highlight or preview from being misreported as a proven structure.

## Port and tensor discipline

For an edge, Structure Lens resolves the exact `source_port` against the source node's outputs and the exact `target_port` against the target node's inputs. An edge tensor can provide the source-side transfer record. A missing port is inferred only when exactly one tensor-bearing candidate exists; multiple candidates produce an `ambiguous-port-binding` warning and no positive compatibility claim.

Shape timelines carry this binding record for each hop. Symbolic, dynamic or absent dimensions remain unknown. The warning output includes the precise edge and port IDs used for a potential mismatch.

Residual claims require an explicit skip/residual/shortcut edge record or a structurally evidenced multi-input addition. Attention requires a canonical operator type or explicit operator-family metadata. MoE routing requires explicit routing/dispatch/combine edge evidence. Substrings in model, class or display names are not evidence.

Repeated structures are grouped only by an exact evidence signature, not approximate labels. Each group records the signature, expansion source-node IDs and `count`/`×N`; nonmatching port/tensor/operator evidence splits the groups. Shared multi-input/multi-output nodes preserve parallel paths and the exact port binding on every returned hop.

## Budgets, cancellation and recovery

The default budget is:

| Resource | Default | API maximum |
|---|---:|---:|
| visits | 10,000 | 1,000,000 |
| depth | 64 | 1,000 |
| returned paths | 25 | 1,000 |
| queued states | 10,000 | 1,000,000 |
| generated states | 50,000 | 10,000,000 |
| estimated queued-state memory | 64 MiB | 8 GiB |
| wall time | 1 s | 60 s |

The memory limit is a conservative queued-state estimate, not a process-RSS measurement. Metadata reports visits, generated states, peak queue entries, peak estimated memory, configured bounds and `terminated_by`. Path search uses bounded breadth-first state and never enumerates all simple paths in an arbitrary graph.

The browser uses `AbortController`. A cancelled query never claims completion. A `partial` result recommends narrower endpoints, a coarser semantic level, focus or viewport recovery. For a large graph, the model-to-figure pipeline can start with a bounded semantic summary and then create a focused/viewport Figure without discarding the full source Graph IR.

## Figure preview boundary

A supported Lens result may include a source-linked Figure Panel preview. The preview is non-mutating. Only the explicit **Add preview as Figure Panel** action copies it into a fresh Page/Panel with new IDs and remapped references. Unsupported/unknown results do not silently create a positive-evidence Panel.

Highlighting maps returned Graph IR IDs only to Figure objects whose provenance carries the same IDs. Template archetypes remain templates and are not treated as inspected model instances.

## Key implementation paths

- `src/nn_davinci/structure_lens.py`
- `src/nn_davinci/model_figure.py`
- `/api/structure-lens/<operation>` in `src/nn_davinci/server.py`
- `tests/test_structure_lens.py`
- `tests/test_structure_lens_061.py`
- `tests/test_model_figure_061.py`

The 0.6.1 exact-evidence tests cover ambiguous ports with no positive compatibility claim, keyword-only residual/attention/MoE negatives, Semantic View priority, shared-node parallel paths, repeat signatures, visit/depth/path/queue/generated-state/memory/time termination, and fresh-ID Figure preview insertion.
