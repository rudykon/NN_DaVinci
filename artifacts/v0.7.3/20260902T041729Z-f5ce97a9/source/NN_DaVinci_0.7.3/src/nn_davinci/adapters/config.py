from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from ..errors import AdapterError
from ..ir import GraphIR
from .base import Adapter, Capability
from .manual import ManualAdapter


class PythonConfigAdapter(Adapter):
    """Safely read a literal GRAPH/MODEL_CONFIG assignment without executing Python."""

    name = "python-config"
    extensions = (".py",)
    priority = 9
    capabilities = (Capability("literal-python-config"), Capability("no-code-execution"))
    variable_names = ("GRAPH", "MODEL_CONFIG", "NETWORK", "NN_DAVINCI_GRAPH")

    def accepts(self, source: Any) -> bool:
        if not isinstance(source, (str, Path)) or Path(str(source).split(":", 1)[0]).suffix.lower() != ".py":
            return False
        path = Path(str(source).split(":", 1)[0])
        if not path.exists():
            return False
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            return any(isinstance(item, (ast.Assign, ast.AnnAssign)) and self._assignment_name(item) in self.variable_names for item in tree.body)
        except (OSError, SyntaxError):
            return False

    def load(self, source: Any, **options: Any) -> GraphIR:
        path = Path(str(source).split(":", 1)[0])
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        requested = str(source).split(":", 1)[1] if ":" in str(source) else None
        names = (requested,) if requested else self.variable_names
        for statement in tree.body:
            name = self._assignment_name(statement)
            if name not in names:
                continue
            value_node = statement.value
            try:
                value = ast.literal_eval(value_node)
            except (ValueError, TypeError) as exc:
                raise AdapterError(
                    f"Python config variable {name} is not a literal",
                    hint="Use only dict/list/string/number literals, or import a trusted model with the PyTorch adapter and --allow-code.",
                ) from exc
            if not isinstance(value, dict):
                raise AdapterError(f"Python config variable {name} must be a dictionary")
            graph = ManualAdapter().load(value)
            graph.metadata.update({"source_format": "python_config", "source_file": str(path), "source_variable": name, "executed_code": False})
            return graph
        raise AdapterError(
            "No literal neural-network config assignment was found",
            hint=f"Define one of: {', '.join(self.variable_names)}.",
        )

    @staticmethod
    def _assignment_name(statement: Any) -> str | None:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
            return statement.targets[0].id
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            return statement.target.id
        return None

