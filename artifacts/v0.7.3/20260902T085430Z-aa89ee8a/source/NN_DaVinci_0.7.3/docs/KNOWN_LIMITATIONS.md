# Known limitations in 0.7.3

## 0.7.3 hotfix boundary

- The generalization evidence is deliberately bounded to seven real-model metamorphisms and ten depth/width/branch-order variants. Structurally ambiguous or unsupported graphs remain `unknown`; passing this corpus is not a universal architecture-recognition proof.
- Models with at most twelve detected roles are proven with direct labels. Larger custom diagrams may use a numbered legend or explicit aggregation, but must retain one-to-one role-ID traceability; a difficult fit can still require author-selected page, density, or camera changes.
- Cross-format semantics are proven for native NN_DaVinci SVG, PDF, TikZ, compiled TikZ PDF, and editable PPTX. Editing those files in another program can remove bindings or substitute fonts, so externally modified documents must be revalidated.
- Direct original-resolution review in this release is AI-assisted and covers the seven final real-model PNGs plus seven before/after composites. Human participants remain 0; no usability, learnability, scientific-correctness, accessibility, or domain-expert approval claim is made.
- The lifecycle scripts are local process-management helpers, not a service manager for public deployment. There is no authentication, authorization, TLS, multi-user isolation, or hardened LAN exposure. Loopback remains the safe default; `0.0.0.0` is explicitly warned.
- Service identity validation uses Linux `/proc` process metadata and the recorded listening endpoint. Equivalent guarantees on non-Linux hosts are not claimed by this release evidence.

The detailed 0.7.2 boundaries below remain inherited unless superseded above.

## Evidence status and human boundary

- NN_DaVinci 0.7.2 has 0 human participants and 0 completed human sessions. Human usability, ease/learnability, first-figure time, paper-ready time, task success, and serious-semantic-error results are null/N/A. Python, Chrome, export automation, screenshots, AI-assisted inspection, and developer self-tests are not participants.
- Source-tree focused results are development evidence, not a release verdict. The clean full driver regenerates and binds inherited coverage/IDs, corpus, migration, performance, E2E, at least 44 browser screenshots, ten non-empty Scene downloads, and an independent visual report. Only the new artifact's `verification.json` is authoritative; `/tmp`, parent, and prose claims cannot substitute for it.
- The strict landed-output oracles test documented SVG accessibility, physical, and geometric invariants; they are not a full application or per-component WCAG audit and do not determine whether an author's scientific narrative is correct. Captions, emphasis, causal claims, terminology, and model interpretation still require domain-expert review.

## Scene IR and true-3D boundaries

- Scene geometry is an authoring representation. Tensor shape labels and evidence are authoritative; volume thickness, spacing, colors, and exploded offsets can be visual mappings and must not be read as measured tensor dimensions. Symbolic/dynamic/unknown values remain symbolic or `?`.
- Scene IR 1.0 composes Object and nested Group transforms. Layer3D is a visibility/lock/order/metadata scope and does not carry its own transform.
- The seven architecture grammars are bounded to CNN, ResNet, U-Net, Transformer, MoE, multimodal fusion, and diffusion U-Net. Architecture Evidence 1.0 proves only supplied Graph/Semantic topology, operation/module identity, port/tensor evidence, and source-ID-backed detections. Custom architectures can remain `unknown`; model keys, filenames, class/module/display names, and requested layouts never create residual, attention, expert, fusion, or diffusion semantics.
- The seven editable Scene templates are archetypes with template-only provenance. They are not pretrained checkpoints and make no accuracy, paper-result, or universal-architecture claim. The seven real-model examples use fixed seeds, CPU, random/local weights, and no downloads; their success does not generalize to every implementation in those families.
- Project 1.3→1.4 migration creates an empty Scene plus migration records. It never derives geometry, a camera, tensor facts, architecture, or provenance from the legacy CSS `presentation.perspective_mode` flag.
- Scene IR parser ceilings (including 10,000 objects) are defensive limits, not interactive performance promises. Normal model-to-Scene conversion defaults to 250 objects and uses summary/focus materialization. Above 10,000 source nodes, summary provenance intentionally stores counts/digests and bounded representatives instead of a complete per-object source-ID list; focused neighborhoods retain exact IDs. A last-resort browser-local Graph fallback is also bounded, but its simplified layout is not equivalent to the evidence-aware server generator.
- CPU projection provides deterministic camera transforms, fit-to-content, face depth ordering, back-face policy, basic polygon occlusion, and sampled hidden-line removal. It is not an exact constructive-solid-geometry solver for arbitrary intersecting, concave, transparent, or non-manifold third-party meshes. Adversarial imported scenes outside the fixed corpus may still require another camera or author cleanup.
- Projected labels use semantic budgets, deterministic abbreviation, external lanes, glyph-aware collision checks, and routed leaders. Labels are never silently reduced below 7 pt. A custom scene that cannot satisfy the physical page contract can therefore require author-selected density/camera/page changes or fail explicitly instead of emitting unreadable text.
- Ray picking uses world-space bounds/triangles supported by Scene primitives. Selection of exotic third-party geometry not represented by those primitives is outside the proven scope.
- WebGL2 behavior depends on browser/driver capability. Context loss or unavailability intentionally drops to a visibly labelled CPU SVG view. The fallback preserves selection/save/export, but it does not reproduce GPU shading or frame rate.
- The on-canvas gizmo supports translate/rotate/scale, local/world coordinates, axis constraints, snapping, keyboard nudge, undo/redo, and autosave for current Scene primitives. It does not claim CAD-grade arbitrary pivot editing, skeletal rigs, constraint solvers, or mesh-component editing.
- Scene IR 1.0 directly persists the active camera and selection, but has no first-class active-layer, focus/isolation, depth-spacing-control, or snap-preference fields. Project UI state covers the implemented browser recovery context; portable consumers must not infer unstored controls from Scene geometry.
- Third-party GLB/3D assets do not automatically acquire model semantics. Scene IR 1.0 has no texture/shader/buffer fields, and the Scene export asset validator rejects dangerous or external asset URIs and malformed embedded images. A general third-party GLB import/reconstruction workflow is not claimed.

## Scene export boundaries

- WebGL is never the paper-export authority. SVG, PDF, TikZ, PPTX, PNG, EPS, and HTML use the independent CPU projection. This also means GPU shading is not reproduced in publication output; face tones follow the deterministic material/projection policy.
- PNG is intentionally raster at 300 DPI. SVG/PDF/TikZ/EPS are native vectors, and PPTX uses editable shapes, but external programs can substitute fonts or introduce small positioning differences.
- Scene PDF/TikZ are publication outputs rather than semantic round-trip formats. Canonical Scene JSON is the editable source; glTF/GLB preserve 3D geometry and provenance extras but are not Project 1.4 envelopes.
- Passing producer-side Scene validation or export metadata does not prove final publication quality. The 0.7.2 release separately reports format validity, true-3D validity, scientific parity, and publication validity; Chrome SVG plus embedded-font PDF/compiled-TikZ oracles can block a producer PASS.

## UX and responsive boundaries

- The browser evidence contract covers the real-model→Semantic→Figure/Lens→Scene→reload→all-ten-exports→return-2D chain, error/cancel/retry, four themes, all exact viewports, all seven real-architecture 2D/3D pairs, and all seven editable 3D template families. Its independent visual validator checks the landed screenshot manifest and PNG files rather than accepting producer booleans. This remains automated evidence, not a domain-expert judgment of a scientific narrative.
- Autosave detects revision mismatch and opens a side-by-side current/stored summary before loading or overwriting; this is local single-user revision recovery, not multi-user merge/conflict resolution.
- Sidebar widths are pointer/keyboard resizable and persisted on desktop. Scene property rows can be pinned independently; this pin model applies to the Scene Inspector and is not retroactively claimed for every inherited Graph/Figure control.
- The Scene Inspector has exactly six collapsible groups and the Scene tree has search, filtering, visibility, locking, and group collapse. Cross-workspace selection remains evidence-linked but each workspace keeps its own authoring state.
- Busy/success/warning/error and retry are shared for registered async actions, but inherited legacy controls are not all migrated to the same registry. The Task Center remains the authority for long inherited jobs.
- The responsive area check uses the full viewport denominator. Focused desktop ratios are 0.691117/0.625341/0.614173/0.617669 and narrow closed-drawer ratios are 0.900000/0.812500/0.928910, meeting the 60%/70% gates. Contrast and automated pixel/geometry checks still do not constitute a complete per-component WCAG audit; domain-expert and assistive-technology review remain outside the machine evidence.

## Inherited 2D/scientific boundaries

- `figure_proof()` is a compiled-IR estimate and cannot substitute for independent Chrome measurement of the landed SVG DOM and complete CTMs. The known 0.6.0 historical proof defect remains documented in the frozen 0.6.1 release notes and artifacts.
- Figure text is never compressed or silently reduced below 7 pt. Content that cannot fit must wrap, use an explicit abbreviation/full-name record, move to a legend, receive more space, or fail.
- Formula support is a bounded, non-executing editable Unicode subset, not TeX. Unsupported or malformed input remains visible as an `Invalid formula` fallback.
- Figure PPTX has one presentation-wide slide size, so heterogeneous Pages are centered at 1:1 on the maximum canvas. SVG/TikZ/PNG/EPS use numbered Page files; multi-page PDF requires the offline `pdfunite` utility.
- Figure PNG is an intentional 300-DPI raster. Figure EPS uses a vector SVG→PDF→Poppler path and rejects raster fallback. External assets must be embedded for offline HTML.
- Tensor Geometry remains a 2D/isometric encoding and is distinct from Scene IR volumes. Its linear/sqrt/log/normalized/manual extents are visual mappings.
- Locks can deliberately leave unused space or a proof failure. The system does not move locked Figure/Scene content or overwrite manual routes merely to pass an oracle.
- Native Figure SVG restores Figure IR only when versioned metadata and its digest validate. Foreign SVG remains an external-vector group; its paths are not reverse-engineered into model facts.
- Structure Lens is evidence- and budget-bounded. Missing/ambiguous port, shape, FLOPs, memory, residual, attention, or MoE evidence remains unknown; warnings are candidates rather than proof that a model is wrong.
- Semantic aliases change author vocabulary, not identity. Missing Graph/Semantic/Figure/Scene provenance references are validation failures rather than silently downgraded claims.
- Synchronous full Graph rendering remains rejected above 2,000 nodes or 12,000 edges. The 10k/50k contract is summary/focus/viewport, not full DOM or full-mesh expansion.
- Framework coverage is the tested subset in `COMPATIBILITY.md`. A PyTorch dynamic trace is a sampled path; `state_dict` cannot recover topology; JAX requires a callable and sample input; textual MLIR is a lightweight subset.
- FLOPs/MACs, activation memory, receptive field, runtime timings, and GPU statistics retain coverage/environment boundaries and are not portable guarantees.

## Runtime, safety, and repository boundaries

- Direct `nnviz scene` and `nnviz project --workspace scene` are covered by focused command checks. Scene-Project creation persists the evidence-bearing `semantic_view.document`, and the produced Project passes contextual validate/reproduce. Python factory and pickle inputs still execute trusted local code only after explicit opt-in.
- Optional formats require their documented local dependencies (for example Pillow and python-pptx; inherited Figure paths also use CairoSVG/Poppler/TeX tooling). Missing dependencies produce actionable failures rather than silent degradation.
- The Flask service defaults to loopback, has no authentication, and is not a public or multi-user collaboration service.
- Plugin API 2.0 isolates ordinary failures but is not a security sandbox. Explicitly enabled local plugins run with the server process's permissions; there is no remote store/installer or automatic execution of unknown plugins.
- Python factories and pickle checkpoints may execute arbitrary code and remain explicit trusted-input opt-ins. Safe inspection, Graph/Scene JSON, ONNX, and ordinary Project loading do not grant that trust.
- The 0.7.3 development tree is not turned into a Git repository. This work performs no commit, tag, push, upload, or publication and does not modify the frozen 0.7.2 tree/artifact.
- Clean ancestry is content evidence: the parent is authoritative 0.7.2 run `20260901T142604Z-010606e8`, with 410-file digest `6d4591e41fd423604fe3537aba200bcdd57e4254c0684dc6bd5b3672fd9c169e`. All exact 353 parent test IDs and all four retained coverage floors remain mandatory.
