# Reference-project design ledger

NN_DaVinci uses original code and a new Graph IR; it does not vendor the reference
projects. The following ideas were deliberately retained after inspecting the local
copies listed in `../../downloaded-open-source-projects.md`.

| Reference | Adopted design idea |
|---|---|
| draw_convnet | Feature-map depth cues and omission markers for large channels |
| NN-SVG | Parameter-driven SVG whose text and objects remain independently editable |
| PlotNeuralNet | Semantic layer shapes and TikZ as a first-class publication target |
| Netron | Broad adapter boundary, tensor ports, attributes and source-format metadata |
| DotNets / Graphviz | Stable ranks, configurable direction and routing separated from styling |
| ENNUI | Drag/drop authoring, browser persistence and code/config export |
| NNet / NeuralNetTools | Analysis overlays separated from base structure |
| Neataptic | Manual graph construction down to neuron/edge granularity |
| TensorSpace | Selecting a layer links structure to its intermediate features |
| Netscope | Fast search plus graph/inspector split for large imported models |
| Moniel | Command-based editing, undo history and computation-graph IDE workflow |
| Texample | Publication presets and composable multi-panel figures |
| Quiver | Layer-to-activation gallery, input browsing and disposable analysis artifacts |
| Net2Vis | Automatic abstraction followed by manual cleanup; consistent visual grammar |
| Model Explorer | Hierarchical namespaces, folding, adapter capabilities and lazy large graphs |
| torchview | One-call Python API, shape propagation, meta-device capture and roll/unroll |
| TorchLens | Runtime graph distinct from declared modules, trace IDs and rich per-op records |
| TorchCAM | Unified explainability method interface and explicit target-layer selection |
| Neural Network Diagram Generator | Optional weight/bias detail, sign styling and parameter indices |

The architecture makes four strict separations: model semantics (`GraphIR`), analysis
records, layout geometry, and visual theme. This is the key invariant that permits a
project to change theme, rerun analysis, or relayout without destroying manual edits.
