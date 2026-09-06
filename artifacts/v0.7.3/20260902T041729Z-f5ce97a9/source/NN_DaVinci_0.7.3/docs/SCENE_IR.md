# Scene IR 1.0

Scene IR is NN_DaVinci 0.7.2's deterministic, editable three-dimensional visual-document model. It is deliberately independent of Graph IR, Semantic View, and Figure IR. When a Scene is model-derived, its metadata may carry sealed Architecture Evidence 1.0 and its objects may carry protected architecture role/route IDs; those fields remain source-bound claims rather than geometry inference.

| Representation | Owns | Must not claim |
|---|---|---|
| Graph IR | imported model facts, ports, tensors, hierarchy, source locators | author geometry, paper layout, camera choice |
| Semantic View | evidence-backed structural aggregation and source mappings | structure not supported by source evidence |
| Figure IR | 2D Page/Panel/Layer/object authoring | 3D world geometry or camera projection |
| Scene IR | world geometry, cameras, lights, materials, 3D routes and author state | that visual depth/thickness is a tensor fact |

The model path is `Graph IR → Semantic View → Scene IR`. Scene objects can link to Graph/Semantic/Figure evidence, identify a bundled template, carry explicit author annotation provenance, or remain `unknown`. Editing Scene geometry never mutates model evidence.

## Version and hierarchy

```text
Scene IR 1.0
└─ Scene
   ├─ Camera (one or more; one active)
   ├─ Light
   └─ Layer3D
      ├─ Group3D
      └─ Object3D
```

The portable schema is `schemas/scene-ir-1.0.schema.json`; the runtime model is `src/nn_davinci/scene_ir.py`. The 0.7 reader accepts exactly Scene IR 1.0. Other minor versions and incompatible major versions are rejected until an explicit Scene migration exists; compatible Project migration is a separate Project 1.x operation.

Every identity is stable and globally unique within a scene. Model object IDs derive deterministically from their source-record key, connector IDs from their ordered source-edge identities, and template/author helpers from explicit family/role identity strings. The validator rejects collisions across the Scene; array position is never used as an implicit identity. Scene IR 1.0 does not promise that every generated ID encodes a semantic level or every display attribute.

## Coordinate and transform contract

- NN_DaVinci uses a right-handed world coordinate system.
- An Object3D stores local `position [x,y,z]`, Euler `rotation [rx,ry,rz]` in **degrees**, and positive `scale [sx,sy,sz]`. Matrices convert degrees exactly once at composition; browser numeric rotation controls and Python transforms use the same unit.
- Nested Group transforms compose with Object transforms. Layer3D scopes objects/groups, visibility, lock, metadata, and order but has no transform in Scene IR 1.0. The resulting object world matrix is derived; local Object/Group transforms remain the editable source.
- Camera projection never writes back to local or world transforms.
- Local transforms are the editable authority. Composed `world` coordinates/matrices are deterministic Scene records refreshed from the nested Group/Object transform chain; Layer3D contributes visibility, lock, metadata, and order but no transform. `projections` are optional camera/viewport-bound derived records. Neither derived record becomes a model fact, and camera changes never write back to local or world geometry.
- All finite numeric fields reject NaN and infinity. Singular object scale, singular camera basis, an invalid near/far interval, and cyclic parent references are invalid.

`scene_math.py` supplies dependency-free vector, matrix, look-at, perspective, orthographic, inverse-transform, ray, and intersection functions. A camera change must alter projected coordinates while leaving world coordinates unchanged.

## Cameras and lights

A camera records:

- `projection`: `orthographic` or `perspective`;
- position, target, up vector, and an optional Euler rotation in degrees;
- perspective field of view or orthographic scale;
- near/far clipping planes and aspect ratio;
- lock state, stable identity, name, and bounded metadata.

Front, Back, Left, Right, Top, Bottom, and Isometric are Scene Studio camera presets that write those numeric camera fields; Scene IR 1.0 does not encode them as a closed `view` enum.

Lights are authoring/interactive-render records: ambient, directional, or point, with color, intensity, position/direction, visibility, and lock state. The deterministic paper projector uses a fixed face-tone policy derived from material colors and face normals; it does not depend on GPU-specific shading.

## Materials and scientific primitives

A material records a base color, optional per-face colors, edge color, authoring stroke width, opacity, metallic/roughness hints, and an unlit flag. The CPU publication projector applies its own physical stroke policy to the projected primitives, so a material stroke value is not an exemption from release measurements. Remote textures, executable shaders, and external URIs are not part of Scene IR 1.0.

The validated Object3D vocabulary includes:

- tensor volume: cuboid/box geometry, thin sheet, tensor/sequence stack, and feature-map stack;
- layer plane and operation block;
- convolution kernel/window and pooling/downsample/upsample transition;
- residual arc and U-Net cross-level skip;
- attention head/ribbon and Q/K/V branch;
- token sequence;
- MoE router, expert branch, and merge;
- multimodal stream and fusion;
- diffusion timestep conditioning;
- group frame, annotation, legend, billboard label;
- arrow, tube, polyline, and cubic bezier route.

The browser WebGL implementation distinguishes route primitives from solid glyphs: it renders route endpoints/control points as projected segments and never replaces a connector with an origin-centred square. Scene labels are a projected DOM overlay with deterministic overlap/clipping avoidance. These are interactive-view behaviors; the CPU `ProjectedScene` below remains the paper-export authority.

Symbolic, dynamic, or unknown dimensions remain their original symbols or `?`. Generated objects keep `tensor_shape`/`shape_label` separately from `visual_geometry_mapping` and `visual_geometry_is_literal_tensor_size=false` metadata. If depth or thickness is illustrative, the Scene legend and provenance state that it is a visual mapping rather than a measured tensor dimension.

## Authoring state

Layers, groups, and objects carry visibility and lock state; cameras carry lock state. Groups and objects also carry selection flags for round-trip recovery. First-class Scene fields record the active camera, selected object/group IDs, metadata, and migration history. Object/group metadata may record authoring display state such as an exploded position, while the resulting edited transforms remain the geometry authority.

Project 1.4 separately persists portable browser recovery context in `canvas_state`, including the Scene selection, active camera, and workspace contexts. The browser's local autosave draft additionally carries `ui_preferences` such as panel state, density, theme, and sidebar widths; that local extension is not a first-class Scene IR field or a portable Project 1.4 guarantee. Active layer, focus/isolation, depth-spacing controls, and snap preferences are likewise not first-class Scene IR 1.0 fields. Unless a client explicitly records such a value in bounded metadata or supported Project UI state, it must not be presented as portable Scene author state.

Routes retain their editable world-space control points. Axis movement, snapping, alignment, and distribution mutate unlocked objects' editable local transforms; derived world records are then refreshed from the Group/Object chain. A locked item is not moved to make an export or layout pass.

## Provenance

Each non-compacted materialized model-derived Object3D records:

- Graph IR node/edge IDs and available port-binding/shape/dtype evidence;
- Semantic View entity/connection IDs and recognition reasons when used;
- optional Figure IR object IDs for explicit 2D/3D author links;
- a forward mapping from evidence to Scene IDs and a reverse mapping from Scene IDs to evidence.

Source locators remain authoritative in Graph IR and are resolved through the stored Graph IDs; when generation uses a Semantic View, the Scene-level Semantic record stores its source digest. A summary-first conversion above 10,000 source nodes deliberately switches to a digest-and-bounded-representatives provenance mode with counts/digests and representative IDs. It does not claim that each visible summary object embeds the complete unbounded source-ID set. Focused materialization returns to exact source IDs.

Template objects use `template` provenance. Author objects use `author_annotation`. If a caller represents third-party 3D content, it uses `external_3d` and does not acquire model semantics; 0.7.1 does not claim a general mesh-import/reconstruction workflow. `external_vector` belongs to Figure IR, not Scene IR. Missing evidence uses `unknown` with a human-readable reason. A display name or architecture keyword cannot create residual, attention, MoE, diffusion, or tensor-shape evidence.

## Project 1.4 migration

Project schema 1.4 requires a `scene_ir` field and stores Scene workspace recovery state. Direct Python construction canonicalizes an omitted value to an explicit empty Scene. Migrating a compatible 1.3 project adds only that empty Scene plus explicit project/scene migration records. The old `presentation.perspective_mode` CSS preview is retained only as a legacy 2D presentation preference; it is never converted into Scene objects, a camera, a tensor volume, or provenance.

Loading a non-empty scene validates it independently and then validates every Graph/Semantic/Figure reference against the exact documents stored in the project. An invalid or orphan reference is rejected rather than silently downgraded.

## Determinism and safety budgets

Canonical serialization uses stable order/ID ordering for cameras, lights, layers, groups, and objects and sorted keys for semantic maps. Route control-point arrays and migration history retain authored sequence. Material fields are emitted deterministically with their owning object. The digest is SHA-256 over canonical UTF-8 JSON.

Intrinsic validation applies bounded route-point, string, metadata-JSON, and total-scene limits. The runtime limits include 10,000 objects, 128 Layers, 4,096 Groups, 32 cameras, 64 lights, 4,096 points per route, metadata JSON depth 32, and 200,000 metadata items. It rejects parent cycles, duplicate IDs, missing references, malformed matrices, non-finite transforms, invalid material values, unsupported fields, and unsafe prototype-style keys. The separate Scene export asset validator rejects dangerous/external asset URIs and malformed embedded image data; glTF is emitted with an embedded buffer, and the HTML validator rejects runtime network/executable dependencies. These parser ceilings are not rendering targets: model conversion defaults to 250 Scene objects and switches to evidence-indexed summary/focus materialization instead of creating 10k/50k meshes synchronously.

## Export boundary

`scene_projection.py` derives an immutable physical `ProjectedScene` through the selected CPU camera. It implements view/projection matrices, depth ordering, back-face policy, sampled hidden-line removal, vector faces/edges/routes, physical strokes, billboard labels, and deterministic post-projection label avoidance. `scene_export.py` consumes only those primitives for SVG, PDF, TikZ, editable PPTX, 300-DPI PNG, vector EPS, and offline HTML. `scene_gltf.py` separately emits canonical Scene JSON and embedded glTF/GLB world geometry with cameras, materials, IDs, and provenance.

WebGL is an interactive view, not an export authority. No vector export is constructed from a WebGL screenshot. If WebGL2 is unavailable or loses its context, the browser requests `/api/scene/project` and displays its CPU SVG with an explicit fallback notice; a deterministic local SVG is the last-resort view if that request also fails. Final SVG acceptance reopens the landed file and measures it independently; producer metadata cannot waive a measured failure. The clean full driver binds the required unit/integration, corpus, migration, performance, E2E, at-least-44-screenshot, ten-download, and independent visual reports into one new artifact. Only that artifact's `verification.json` declares the run outcome.
