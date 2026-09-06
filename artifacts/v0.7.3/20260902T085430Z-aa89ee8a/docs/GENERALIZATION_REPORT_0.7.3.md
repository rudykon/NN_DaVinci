# Generalization report for 0.7.3

## Recognition boundary

The architecture detector derives claims from topology, typed operations,
ports, tensor shapes, and bounded module hierarchy evidence. Graph/model names,
corpus or sample keys, filenames, Python class names, requested layout,
existing coordinates, and isolated lexical fragments do not establish an
architecture. When structural evidence is insufficient, the result remains
`unknown` with an explicit reason.

The role graph consumes only validated Architecture Evidence and current Graph
IR IDs. Every emitted role and route carries provenance that must resolve in
that graph. A metamorphic copy must therefore rebind provenance rather than
retain stale IDs.

## Deterministic corpus

The fixed seed is 7300. For each of the seven real models, the corpus performs
all of the following while retaining structural evidence:

1. Replace graph name, sample metadata keys, node display names, and lexical
   fragments in module paths.
2. Shuffle node arrays, edge arrays, and input-branch order.
3. Inject unrelated pre-layout coordinates.
4. Re-derive Architecture Evidence and compare canonical family, role types,
   repeat counts, and critical-route types.
5. Confirm that provenance resolves only to the transformed Graph IR.
6. Remove decisive topology/route evidence and require degradation to unknown,
   lower confidence, or an explicit missing claim.

Ten additional variants cover ResNet repeats `[2,2,2,2]` and `[3,3,3,3]`;
Transformer depths 2 and 5; U-Net depths 2 and 4; MoE configurations with
three/top-1 and six/top-2 experts; and image-first/text-first multimodal branch
orders at different widths.

The run is offline, initializes local random weights only, and downloads
nothing. The sealed JSON report records all original/transformed signatures,
removed evidence, degradation results, rebound provenance, variant attributes,
seed, and failures. Passing this bounded corpus is evidence of resistance to
the enumerated shortcuts; it is not a universal proof for every neural-network
implementation.
