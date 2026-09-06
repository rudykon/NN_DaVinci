from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .errors import PluginError

PLUGIN_API_VERSION = "2.0"
CAPABILITY_VERSIONS = {
    "adapter": "2.0",
    "semantic-recognizer": "2.0",
    "layout": "2.0",
    "analyzer": "2.0",
    "theme": "2.0",
    "exporter": "2.0",
    "operator": "1.0",
}


@dataclass(slots=True)
class PluginContext:
    adapters: Any
    layout_engine: Any
    analyzers: dict[str, Any]
    themes: dict[str, Any]
    register_theme: Any
    exporters: dict[str, Any]
    register_exporter: Any
    operator_types: dict[str, Any]
    register_operator_type: Any
    semantic_recognizers: dict[str, Any]
    register_semantic_recognizer: Any


def create_context() -> PluginContext:
    from .adapters import registry
    from .analysis import ANALYZERS
    from .layout import LayoutEngine
    from .operators import OPERATOR_TYPES, register_operator_type
    from .render.export import CUSTOM_EXPORTERS, register_exporter
    from .themes import THEMES, register_theme
    from .semantic import SEMANTIC_RECOGNIZERS, register_semantic_recognizer

    return PluginContext(
        registry, LayoutEngine, ANALYZERS, THEMES, register_theme,
        CUSTOM_EXPORTERS, register_exporter, OPERATOR_TYPES, register_operator_type,
        SEMANTIC_RECOGNIZERS, register_semantic_recognizer,
    )


@dataclass(slots=True)
class PluginManifest:
    name: str
    version: str
    api_version: str = PLUGIN_API_VERSION
    capabilities: list[str] = field(default_factory=list)
    entry_point: str = ""
    description: str = ""
    source: str = ""
    capability_versions: dict[str, str] = field(default_factory=dict)
    security: dict[str, Any] = field(default_factory=lambda: {
        "executes_local_code": True,
        "process_isolation": False,
        "network_granted_by_nn_davinci": False,
    })

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, source: str = "") -> "PluginManifest":
        manifest = cls(source=source, **data)
        if manifest.api_version.split(".")[0] != PLUGIN_API_VERSION.split(".")[0]:
            migration = "Replace API 1 context assumptions with API 2 capability negotiation and declare capability_versions."
            raise PluginError(
                f"Plugin {manifest.name!r} requires incompatible API {manifest.api_version}",
                hint=f"NN_DaVinci supports plugin API {PLUGIN_API_VERSION}. {migration}",
                details={"migration": migration, "supported_capabilities": CAPABILITY_VERSIONS},
            )
        if not manifest.name or not manifest.version or not manifest.entry_point:
            raise PluginError("Plugin manifest requires name, version, and entry_point")
        unknown = sorted(set(manifest.capabilities) - set(CAPABILITY_VERSIONS))
        if unknown:
            raise PluginError(f"Plugin {manifest.name!r} declares unknown capabilities: {', '.join(unknown)}")
        manifest.capability_versions = {
            capability: manifest.capability_versions.get(capability, manifest.api_version)
            for capability in manifest.capabilities
        }
        return manifest


class PluginManager:
    GROUPS = {
        "nn_davinci.adapters": "adapter", "nn_davinci.layouts": "layout",
        "nn_davinci.analyzers": "analyzer", "nn_davinci.themes": "theme",
        "nn_davinci.exporters": "exporter",
        "nn_davinci.operators": "operator",
        "nn_davinci.semantic_recognizers": "semantic-recognizer",
    }

    def __init__(self) -> None:
        self.manifests: dict[str, PluginManifest] = {}
        self.loaded: dict[str, Any] = {}
        self.failures: dict[str, dict[str, Any]] = {}

    def discover(self, paths: list[str | Path] | None = None) -> list[PluginManifest]:
        discovered: list[PluginManifest] = []
        for group, capability in self.GROUPS.items():
            for entry in importlib.metadata.entry_points(group=group):
                manifest = PluginManifest(entry.name, _distribution_version(entry), capabilities=[capability], entry_point=entry.value, source=f"entrypoint:{group}", capability_versions={capability: CAPABILITY_VERSIONS[capability]})
                self.manifests[manifest.name] = manifest
                discovered.append(manifest)
        for root in paths or []:
            directory = Path(root)
            if not directory.exists():
                continue
            for path in sorted(directory.glob("*/nn-davinci-plugin.json")):
                data = json.loads(path.read_text(encoding="utf-8"))
                manifest = PluginManifest.from_dict(data, source=str(path))
                self.manifests[manifest.name] = manifest
                discovered.append(manifest)
        return discovered

    def negotiate(self, name: str, requested: list[str] | None = None) -> dict[str, Any]:
        if name not in self.manifests:
            raise PluginError(f"Unknown plugin {name!r}")
        manifest = self.manifests[name]
        requested_set = set(requested or manifest.capabilities)
        missing = sorted(requested_set - set(manifest.capabilities))
        incompatible = sorted(
            capability for capability in requested_set & set(manifest.capabilities)
            if manifest.capability_versions.get(capability, "0").split(".")[0] != CAPABILITY_VERSIONS[capability].split(".")[0]
        )
        return {
            "plugin": name,
            "api_version": manifest.api_version,
            "accepted": not missing and not incompatible,
            "capabilities": {capability: CAPABILITY_VERSIONS[capability] for capability in sorted(requested_set - set(missing) - set(incompatible))},
            "missing": missing,
            "incompatible": incompatible,
            "security": manifest.security,
        }

    def load(self, name: str, context: Any = None, *, allow_local_code: bool = False) -> Any:
        if name not in self.manifests:
            raise PluginError(f"Unknown plugin {name!r}")
        manifest = self.manifests[name]
        negotiation = self.negotiate(name)
        if not negotiation["accepted"]:
            raise PluginError(f"Plugin {name!r} failed capability negotiation", details=negotiation)
        if manifest.source and not manifest.source.startswith("entrypoint:") and not allow_local_code:
            raise PluginError(
                f"Local plugin {name!r} can execute arbitrary code and requires explicit confirmation",
                hint="Review its source, then call load(..., allow_local_code=True). Unknown plugins are never auto-executed.",
                details={"security": manifest.security, "source": manifest.source},
            )
        try:
            module_name, separator, symbol = manifest.entry_point.partition(":")
            module = self._import_module(module_name, manifest)
            entry = getattr(module, symbol) if separator else module
            active_context = context or create_context()
            instance = entry(active_context) if callable(entry) else entry
        except Exception as exc:
            self.failures[name] = {"exception": type(exc).__name__, "message": str(exc), "editor_survived": True}
            raise PluginError(
                f"Plugin {name!r} failed to load: {exc}",
                details={"entry_point": manifest.entry_point, "exception": type(exc).__name__},
            ) from exc
        self.loaded[name] = instance
        try:
            self._integrate(instance, manifest, active_context)
        except Exception as exc:
            self.loaded.pop(name, None)
            self.failures[name] = {"exception": type(exc).__name__, "message": str(exc), "editor_survived": True}
            raise PluginError(f"Plugin {name!r} failed during capability integration: {exc}", details=self.failures[name]) from exc
        self.failures.pop(name, None)
        return instance

    def load_safely(self, name: str, context: Any = None, *, allow_local_code: bool = False) -> dict[str, Any]:
        try:
            self.load(name, context, allow_local_code=allow_local_code)
            return {"name": name, "loaded": True, "failure": None, "editor_survived": True}
        except PluginError as exc:
            return {"name": name, "loaded": False, "failure": exc.to_dict(), "editor_survived": True}

    @staticmethod
    def _import_module(module_name: str, manifest: PluginManifest) -> Any:
        if manifest.source and not manifest.source.startswith("entrypoint:"):
            relative = Path(*module_name.removesuffix(".py").split("."))
            candidate = Path(manifest.source).parent / relative.with_suffix(".py")
            if candidate.exists():
                safe_name = "".join(character if character.isalnum() else "_" for character in manifest.name)
                spec = importlib.util.spec_from_file_location(f"nn_davinci_plugin_{safe_name}", candidate)
                if spec is None or spec.loader is None:
                    raise PluginError(f"Cannot import local plugin file {candidate}")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module
        return importlib.import_module(module_name)

    @staticmethod
    def _integrate(instance: Any, manifest: PluginManifest, context: PluginContext) -> None:
        capabilities = set(manifest.capabilities)
        callable_capabilities = {"layout", "analyzer", "exporter", "semantic-recognizer"}
        invalid_callable = sorted(capability for capability in capabilities & callable_capabilities if not callable(instance))
        if invalid_callable:
            raise TypeError(f"Capabilities require a callable plugin instance: {', '.join(invalid_callable)}")
        if "adapter" in capabilities and not (hasattr(instance, "load") and hasattr(instance, "name")):
            raise TypeError("Adapter capability requires name and load")
        if capabilities & {"theme", "operator"} and not isinstance(instance, dict):
            raise TypeError("Theme/operator capability requires a dictionary instance")
        if "adapter" in capabilities and hasattr(instance, "load") and hasattr(instance, "name"):
            context.adapters.register(instance)
        if "layout" in capabilities and callable(instance):
            context.layout_engine.register(manifest.name, instance)
        if "analyzer" in capabilities and callable(instance):
            context.analyzers[manifest.name] = instance
        if "theme" in capabilities and isinstance(instance, dict):
            context.register_theme(manifest.name, instance)
        if "exporter" in capabilities and callable(instance):
            context.register_exporter(manifest.name, instance)
        if "operator" in capabilities and isinstance(instance, dict):
            for op_type, specification in instance.items():
                context.register_operator_type(op_type, specification)
        if "semantic-recognizer" in capabilities and callable(instance):
            context.register_semantic_recognizer(manifest.name, instance)

    def describe(self) -> list[dict[str, Any]]:
        return [
            asdict(self.manifests[key])
            | {
                "loaded": key in self.loaded,
                "failure": self.failures.get(key),
                "negotiation": self.negotiate(key),
                "security_boundary": "Local plugins execute in the editor process only after explicit confirmation; they are not sandboxed.",
            }
            for key in sorted(self.manifests)
        ]


def _distribution_version(entry: Any) -> str:
    try:
        return entry.dist.version
    except Exception:
        return "unknown"


manager = PluginManager()
