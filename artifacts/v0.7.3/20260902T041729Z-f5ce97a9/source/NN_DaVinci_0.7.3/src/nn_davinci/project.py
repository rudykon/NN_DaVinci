from __future__ import annotations

import json
import platform
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .errors import OptionalDependencyError, ValidationError
from .figure_ir import FigureIR
from .ir import GraphIR
from .scene_ir import Scene, empty_scene
from .semantic import SemanticView

PROJECT_VERSION = "1.4"
SEMANTIC_VIEW_ENVELOPE_VERSION = "1.0"
SEMANTIC_VIEW_DOCUMENT_KEY = "document"
SEMANTIC_VIEW_REQUIRED_FIELDS = frozenset({
    "name",
    "source_ir_version",
    "source_digest",
    "entities",
    "connections",
    "source_to_semantic",
    "semantic_to_source",
    "detections",
    "semantic_version",
})
SEMANTIC_VIEW_DOCUMENT_FIELDS = SEMANTIC_VIEW_REQUIRED_FIELDS | {"architecture_evidence"}


def _semantic_view_document(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Return the persisted Semantic View document from a project envelope.

    Project schema 1.x originally used ``semantic_view`` only for the current
    level/view controls.  Schema 1.3 keeps that compatible envelope and stores
    the evidence-bearing Semantic View under ``document``.  A short-lived
    0.6.1 prerelease wrote the same document fields flat beside the controls;
    accepting that shape lets those local files be loaded and canonicalized
    without weakening the evidence checks.
    """

    document = payload.get(SEMANTIC_VIEW_DOCUMENT_KEY)
    if document is not None:
        if not isinstance(document, dict):
            raise ValidationError(
                "Project Semantic View document must be an object",
                hint="Regenerate the Semantic View from the project's Graph IR.",
            )
        return dict(document)
    if "entities" not in payload:
        return None
    return {key: payload[key] for key in SEMANTIC_VIEW_DOCUMENT_FIELDS if key in payload}


def _validated_semantic_view(document: dict[str, Any], graph: GraphIR) -> SemanticView:
    missing = sorted(SEMANTIC_VIEW_REQUIRED_FIELDS - set(document))
    if missing:
        raise ValidationError(
            f"Project Semantic View document is missing required fields {missing!r}",
            hint="Persist the complete SemanticView.to_dict() result without filtering its evidence maps.",
        )
    try:
        return SemanticView.from_dict(document).validate(graph)
    except ValidationError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ValidationError(
            "Project Semantic View document is malformed",
            hint="Regenerate the Semantic View from the project's Graph IR.",
        ) from exc


@dataclass(slots=True)
class Project:
    name: str
    graph: GraphIR
    model_source: dict[str, Any] = field(default_factory=dict)
    sample_inputs: list[dict[str, Any]] = field(default_factory=list)
    dynamic_dimensions: dict[str, Any] = field(default_factory=dict)
    theme: str = "neurips"
    theme_overrides: dict[str, Any] = field(default_factory=dict)
    layout: dict[str, Any] = field(default_factory=dict)
    export: dict[str, Any] = field(default_factory=lambda: {"formats": ["svg"], "transparent": False})
    analysis_options: dict[str, Any] = field(default_factory=dict)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    comments: list[dict[str, Any]] = field(default_factory=list)
    collaboration: dict[str, Any] = field(default_factory=dict)
    presentation: dict[str, Any] = field(default_factory=lambda: {"teaching_animation": False, "perspective_mode": False})
    semantic_view: dict[str, Any] = field(default_factory=lambda: {"version": "1.0", "level": None, "view": "faithful"})
    canvas_state: dict[str, Any] = field(default_factory=lambda: {
        "search": "", "selection": [], "focus": [], "analysis_metric": "", "breadcrumbs": [],
        "viewports": {}, "view_box": None, "zoom": 1.0, "fixed_layout": False,
        "positions_by_view": {}, "routes_by_view": {},
    })
    import_configurations: list[dict[str, Any]] = field(default_factory=list)
    task_history: list[dict[str, Any]] = field(default_factory=list)
    paper_workflow: dict[str, Any] = field(default_factory=lambda: {"preset": "paper", "suggestions": [], "applied": None})
    figure_composer: dict[str, Any] = field(default_factory=dict)
    figure_ir: dict[str, Any] = field(default_factory=dict)
    scene_ir: dict[str, Any] = field(default_factory=dict)
    plugin_requirements: list[dict[str, str]] = field(default_factory=list)
    environment: dict[str, Any] = field(default_factory=dict)
    project_version: str = PROJECT_VERSION
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        # Read the 0.1 schema without continuing its misleading UI terminology.
        legacy_perspective = self.presentation.pop("three_dimensional", None)
        if "perspective_mode" not in self.presentation and legacy_perspective is not None:
            self.presentation["perspective_mode"] = bool(legacy_perspective)
        if not isinstance(self.semantic_view, dict):
            raise ValidationError("Project semantic_view must be an object")
        self.semantic_view.setdefault("version", SEMANTIC_VIEW_ENVELOPE_VERSION)
        self.semantic_view.setdefault("level", None)
        self.semantic_view.setdefault("view", "faithful")
        defaults: dict[str, Any] = {
            "search": "", "selection": [], "focus": [], "analysis_metric": "", "breadcrumbs": [],
            "viewports": {}, "view_box": None, "zoom": 1.0, "fixed_layout": False,
            "positions_by_view": {}, "routes_by_view": {},
        }
        for key, value in defaults.items():
            self.canvas_state.setdefault(key, value)
        figure: FigureIR | None = None
        if self.figure_ir:
            # Validate the independent visual document without translating any
            # of its contents back into Graph IR model facts.
            figure = FigureIR.from_dict(self.figure_ir)
            self.figure_ir = figure.to_dict()
        self._validate_persisted_semantic_provenance(figure)
        if isinstance(self.scene_ir, Scene):
            scene = self.scene_ir.validate()
        elif self.scene_ir:
            if not isinstance(self.scene_ir, dict):
                raise ValidationError("Project scene_ir must be a Scene IR object")
            scene = Scene.from_dict(self.scene_ir)
        else:
            # Direct Python construction remains convenient while Project 1.4
            # always serializes an explicit empty Scene.  No model geometry,
            # semantics, or provenance is inferred here.
            scene = empty_scene(f"{self.name} · 3D")
        self.scene_ir = scene.to_dict()
        self._validate_persisted_scene_provenance(scene, figure)

    def _validate_persisted_semantic_provenance(self, figure: FigureIR | None) -> None:
        """Validate the persisted Graph ↔ Semantic View ↔ Figure chain."""

        document = _semantic_view_document(self.semantic_view)
        uses_semantic_provenance = bool(
            figure
            and any(item.provenance.kind == "semantic_view" for item in figure.iter_objects())
        )
        uses_graph_provenance = bool(
            figure
            and any(item.provenance.kind == "graph_ir" for item in figure.iter_objects())
        )
        uses_evidence_provenance = uses_semantic_provenance or uses_graph_provenance
        if document is None:
            if uses_semantic_provenance:
                raise ValidationError(
                    "Model-derived Figure IR requires its persisted Semantic View document",
                    hint=(
                        "Save the exact SemanticView.to_dict() used to generate the Figure "
                        "under semantic_view.document."
                    ),
                )
            if uses_graph_provenance:
                from .model_figure import validate_model_figure_provenance

                assert figure is not None
                report = validate_model_figure_provenance(figure, self.graph)
                if not report.get("passed"):
                    raise ValidationError(
                        "Project Graph IR and Figure IR provenance disagree",
                        hint="Repair or regenerate the Figure's exact Graph IR provenance index.",
                        details={"provenance_validation": report},
                    )
            # Compatibility boundary: older 1.x Graph-only projects and
            # Figures without evidence claims may contain only level/view state.
            return

        semantic = _validated_semantic_view(document, self.graph)
        controls = {
            "version": str(self.semantic_view.get("version", SEMANTIC_VIEW_ENVELOPE_VERSION)),
            "level": self.semantic_view.get("level"),
            "view": self.semantic_view.get("view", "faithful"),
        }
        # Canonicalize both the supported nested representation and the
        # prerelease flat representation to one deterministic project shape.
        self.semantic_view = {
            **controls,
            SEMANTIC_VIEW_DOCUMENT_KEY: semantic.to_dict(),
        }
        if not uses_evidence_provenance:
            return

        # Imported locally to keep Project's core schema layer independent of
        # the model-to-Figure builder while reusing its single provenance gate.
        from .model_figure import validate_model_figure_provenance

        assert figure is not None
        report = validate_model_figure_provenance(figure, self.graph, semantic)
        if not report.get("passed"):
            raise ValidationError(
                "Project Graph IR, Semantic View, and Figure IR provenance disagree",
                hint="Regenerate the Figure from the persisted Graph IR and Semantic View.",
                details={"provenance_validation": report},
            )

    def persisted_semantic_view(self) -> SemanticView | None:
        """Return the validated evidence document, if this project stores one."""

        document = _semantic_view_document(self.semantic_view)
        if document is None:
            return None
        return _validated_semantic_view(document, self.graph)

    def persisted_scene(self) -> Scene:
        """Return the validated editable Scene IR document."""

        return Scene.from_dict(self.scene_ir)

    def _validate_persisted_scene_provenance(
        self,
        scene: Scene,
        figure: FigureIR | None,
    ) -> None:
        """Validate every evidence-bearing Scene object against the project."""

        evidence_objects = [
            item
            for item in scene.iter_objects()
            if item.provenance.kind in {"graph_ir", "semantic_view", "figure_ir"}
        ]
        if not evidence_objects:
            # Empty, template, author, external, and explicitly unknown scenes
            # make no model-evidence claim and therefore need no Graph bridge.
            return
        uses_semantic = any(item.provenance.kind == "semantic_view" for item in evidence_objects)
        uses_figure = any(
            item.provenance.kind == "figure_ir" or bool(item.provenance.figure_ir_ids)
            for item in evidence_objects
        )
        semantic = self.persisted_semantic_view()
        if uses_semantic and semantic is None:
            raise ValidationError(
                "Model-derived Scene IR requires its persisted Semantic View document",
                hint="Save the exact SemanticView.to_dict() used to generate the Scene under semantic_view.document.",
            )
        if uses_figure and figure is None:
            raise ValidationError(
                "Scene IR Figure provenance requires the referenced persisted Figure IR",
                hint="Persist the Figure IR used for 2D/3D selection and provenance synchronization.",
            )
        from .model_scene import validate_model_scene_provenance

        report = validate_model_scene_provenance(scene, self.graph, semantic, figure)
        if not report.get("passed"):
            raise ValidationError(
                "Project Graph IR, Semantic View, Figure IR, and Scene IR provenance disagree",
                hint="Regenerate the Scene from the exact persisted evidence documents.",
                details={"provenance_validation": report},
            )

    def stamp_environment(self) -> None:
        from . import __version__

        self.environment.update({
            "nn_davinci": __version__,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "graph_ir": self.graph.ir_version,
            "figure_ir": self.figure_ir.get("schema_version") if self.figure_ir else None,
            "scene_ir": self.scene_ir.get("schema_version") if self.scene_ir else None,
            "font": self.theme_overrides.get("font_family", "Inter, Arial, sans-serif"),
        })
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def record_artifacts(self, paths: Sequence[str | Path]) -> None:
        generated_at = datetime.now(timezone.utc).isoformat()
        for path in paths:
            target = Path(path)
            self.artifacts.append({
                "path": str(target), "format": target.suffix.lower().lstrip("."),
                "size_bytes": target.stat().st_size if target.exists() else None,
                "generated_at": generated_at,
            })
        self.updated_at = generated_at

    def add_comment(self, text: str, *, author: str = "local", target_ids: list[str] | None = None, resolved: bool = False) -> str:
        from .ir import stable_id

        comment_id = stable_id("comment", f"{author}:{text}:{len(self.comments)}")
        self.comments.append({
            "id": comment_id, "author": author, "text": text,
            "target_ids": target_ids or [], "resolved": resolved,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        return comment_id

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["graph"] = self.graph.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Project":
        payload = dict(data)
        if "graph" not in payload:
            raise ValidationError("Project is missing its Graph IR", hint="Expected a top-level 'graph' object.")
        version = str(payload.get("project_version", PROJECT_VERSION))
        major = version.split(".", 1)[0]
        if version != PROJECT_VERSION and major == PROJECT_VERSION.split(".", 1)[0]:
            environment = dict(payload.get("environment", {}))
            migrations = list(environment.get("project_schema_migrations", []))
            migrations.append({
                "from": version,
                "to": PROJECT_VERSION,
                "reason": (
                    "Project 1.4 added an explicit empty Scene IR; no 3D geometry was inferred; "
                    "no tensor shape, model semantics, or provenance was inferred"
                ),
            })
            environment["project_schema_migrations"] = migrations
            payload["environment"] = environment
            payload["project_version"] = PROJECT_VERSION
            payload.setdefault("figure_ir", {})
            payload["scene_ir"] = empty_scene(
                f"{str(payload.get('name', 'Migrated project'))} · 3D",
                migration_from=f"project-{version}",
            ).to_dict()
        elif major != PROJECT_VERSION.split(".", 1)[0]:
            raise ValidationError(
                f"Project major version {version!r} is incompatible with supported version {PROJECT_VERSION!r}",
                hint="Open the project with a compatible NN_DaVinci release or migrate its project schema.",
            )
        elif "scene_ir" not in payload:
            raise ValidationError(
                "Project 1.4 is missing its Scene IR document",
                hint="Use an empty Scene IR when the project contains no 3D authoring state.",
            )
        payload["graph"] = GraphIR.from_dict(payload["graph"])
        return cls(**payload)

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        self.stamp_environment()
        target.parent.mkdir(parents=True, exist_ok=True)
        data = self.to_dict()
        if target.suffix.lower() in {".yaml", ".yml"}:
            try:
                import yaml
            except ImportError as exc:
                raise OptionalDependencyError(
                    "Saving YAML projects requires PyYAML",
                    hint="Install nn-davinci[yaml] or save with a .json extension.",
                ) from exc
            target.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        else:
            target.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: str | Path) -> "Project":
        source = Path(path)
        if source.suffix.lower() in {".yaml", ".yml"}:
            try:
                import yaml
            except ImportError as exc:
                raise OptionalDependencyError(
                    "Loading YAML projects requires PyYAML",
                    hint="Install nn-davinci[yaml] or use a JSON project.",
                ) from exc
            data = yaml.safe_load(source.read_text(encoding="utf-8"))
        else:
            data = json.loads(source.read_text(encoding="utf-8"))
        return cls.from_dict(data)
