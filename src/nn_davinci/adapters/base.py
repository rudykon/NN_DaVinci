from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..errors import AdapterError
from ..ir import GraphIR


@dataclass(frozen=True, slots=True)
class Capability:
    name: str
    version: str = "1.0"
    description: str = ""


class Adapter(ABC):
    name = "adapter"
    version = "1.0"
    extensions: tuple[str, ...] = ()
    capabilities: tuple[Capability, ...] = ()
    priority = 0

    def accepts(self, source: Any) -> bool:
        if isinstance(source, (str, Path)):
            return Path(str(source).split(":", 1)[0]).suffix.lower() in self.extensions
        return False

    @abstractmethod
    def load(self, source: Any, **options: Any) -> GraphIR:
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "extensions": list(self.extensions),
            "capabilities": [asdict(item) for item in self.capabilities],
        }


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, Adapter] = {}

    def register(self, adapter: Adapter, *, replace: bool = False) -> None:
        if adapter.name in self._adapters and not replace:
            raise AdapterError(f"Adapter {adapter.name!r} is already registered")
        self._adapters[adapter.name] = adapter

    def get(self, name: str) -> Adapter:
        try:
            return self._adapters[name]
        except KeyError as exc:
            raise AdapterError(
                f"Unknown model adapter {name!r}",
                hint=f"Available adapters: {', '.join(sorted(self._adapters))}",
            ) from exc

    def detect(self, source: Any) -> Adapter:
        matches = [item for item in self._adapters.values() if item.accepts(source)]
        if not matches:
            suffix = Path(source).suffix if isinstance(source, (str, Path)) else type(source).__name__
            raise AdapterError(
                f"No adapter recognized model source {suffix!r}",
                hint="Pass adapter='manual', 'onnx', 'pytorch', 'keras', 'jax', or 'mlir' explicitly.",
            )
        return max(matches, key=lambda item: item.priority)

    def load(self, source: Any, *, adapter: str | None = None, **options: Any) -> GraphIR:
        selected = self.get(adapter) if adapter else self.detect(source)
        try:
            graph = selected.load(source, **options)
            graph.metadata.setdefault("adapter", selected.describe())
            return graph.validate()
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(
                f"{selected.name} adapter could not import the model: {exc}",
                hint="Check the model format, sample input, and optional framework dependency.",
                details={"adapter": selected.name, "exception": type(exc).__name__},
            ) from exc

    def describe(self) -> list[dict[str, Any]]:
        return [self._adapters[key].describe() for key in sorted(self._adapters)]


registry = AdapterRegistry()

