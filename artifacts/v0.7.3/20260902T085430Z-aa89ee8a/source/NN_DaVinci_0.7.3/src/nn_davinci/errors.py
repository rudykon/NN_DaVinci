from __future__ import annotations


class NNDaVinciError(Exception):
    """Base exception with a user-actionable message."""

    code = "nn_davinci_error"
    status_code = 400

    def __init__(self, message: str, *, hint: str | None = None, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.details = details or {}

    def to_dict(self) -> dict:
        payload = {"error": self.code, "message": self.message}
        if self.hint:
            payload["hint"] = self.hint
        if self.details:
            payload["details"] = self.details
        return payload


class ValidationError(NNDaVinciError):
    code = "validation_error"


class AdapterError(NNDaVinciError):
    code = "adapter_error"


class OptionalDependencyError(NNDaVinciError):
    code = "optional_dependency_missing"


class ExportError(NNDaVinciError):
    code = "export_error"


class PluginError(NNDaVinciError):
    code = "plugin_error"


class GraphTooLargeError(NNDaVinciError):
    """A synchronous full-graph render was rejected before layout."""

    code = "graph_too_large"
    status_code = 422
