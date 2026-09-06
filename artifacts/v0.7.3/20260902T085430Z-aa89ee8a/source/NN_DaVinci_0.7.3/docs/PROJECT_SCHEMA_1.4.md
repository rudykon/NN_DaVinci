# Project Schema 1.4

Project 1.4 adds one required top-level field, `scene_ir`, containing a Scene
IR 1.0 document. Graph IR remains the model-evidence record, Semantic View
remains an evidence-backed interpretation, and Figure IR/Scene IR remain
editable authoring documents.

## Persistence boundary

- `Project.scene_ir` is stored as canonical Scene IR JSON.
- `Project.persisted_scene()` returns a validated `Scene` object.
- `Project.save()` records the Scene schema version in
  `environment.scene_ir`.
- Scene objects with Graph, Semantic, or Figure provenance are checked against
  the exact project documents and their bidirectional indexes before load or
  save succeeds.
- Template, author annotation, external 3D, and unknown provenance do not
  become model facts.

The normative schemas are `schemas/project-1.4.schema.json` and
`schemas/scene-ir-1.0.schema.json`.

## 1.3 to 1.4 migration

Loading a compatible Project 1.3 file creates a valid empty Scene IR with a
default authoring camera and light but no layers, groups, objects, tensor
shapes, model semantics, or provenance. Both
`environment.project_schema_migrations` and `scene_ir.migrations` state this
explicitly. Existing Graph IR, Semantic View, Figure IR, and UI state are
preserved.

This migration never derives an architecture from project, node, module, or
operator names. A later model-to-scene action must use Graph/Semantic evidence
or retain unknown architecture semantics.

## Safety and limits

The Python parser rejects unsupported fields, non-finite numbers, duplicate or
dangling IDs, cyclic groups, invalid camera planes, inconsistent selection,
unsafe prototype-style metadata keys, excessive nesting, and oversized
collections. Scene generation defaults to 250 visible objects and switches to
an evidence-indexed summary when the source graph would exceed that budget;
focus generation remains bounded by the same limit.
