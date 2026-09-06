"""Consent-gated, local-only researcher trial event recording."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import statistics
import tempfile
import threading
from typing import Any
from uuid import uuid4

from .errors import ValidationError

TRIAL_SCHEMA_VERSION = "0.5.0-trial-events-1"
TRIAL_PROTOCOL_VERSION = "1.0"
TRIAL_EVENT_TYPES = (
    "session_started",
    "import_started",
    "import_succeeded",
    "import_failed",
    "first_interactive_view",
    "paper_ready",
    "edit_summary",
    "export",
    "recovery",
    "session_completed",
)
TRIAL_CASE_KEYS = (
    "participant_model",
    "dynamic_pytorch",
    "onnx_multi_io",
    "shared_siamese",
    "transformer_residual",
    "unet_skip",
    "custom_unknown",
)
EXPORT_FORMATS = ("svg", "pdf", "tikz", "pptx", "png", "eps", "html", "project", "bundle")
ERROR_CODES = (
    "none",
    "validation",
    "optional_dependency",
    "unsafe_source",
    "unsupported_format",
    "paper_not_ready",
    "task_failed",
    "unknown",
)
RECOVERY_ACTIONS = (
    "retry",
    "sample_input",
    "module_view",
    "semantic_summary",
    "reduce_focus",
    "switch_page",
    "project_refresh",
    "autosave_restore",
    "open_issue",
)

_ENUMS: dict[tuple[str, str], tuple[str, ...]] = {
    ("session_started", "case_key"): TRIAL_CASE_KEYS,
    ("session_started", "workflow"): ("guided-web", "participant-owned"),
    ("import_started", "format"): (
        "pytorch", "torchscript", "state_dict", "onnx", "keras", "tensorflow", "jax", "mlir", "json", "yaml", "project", "unknown"
    ),
    ("import_started", "safety_level"): ("safe-data", "trusted-code", "restricted-pickle", "local-fixture", "unknown"),
    ("import_succeeded", "format"): (
        "pytorch", "torchscript", "state_dict", "onnx", "keras", "tensorflow", "jax", "mlir", "json", "yaml", "project", "unknown"
    ),
    ("import_failed", "format"): (
        "pytorch", "torchscript", "state_dict", "onnx", "keras", "tensorflow", "jax", "mlir", "json", "yaml", "project", "unknown"
    ),
    ("import_failed", "error_code"): ERROR_CODES,
    ("first_interactive_view", "semantic_level"): ("raw", "model", "stage", "block", "layer", "operation"),
    ("export", "format"): EXPORT_FORMATS,
    ("export", "error_code"): ERROR_CODES,
    ("recovery", "action"): RECOVERY_ACTIONS,
    ("session_completed", "status"): ("completed", "abandoned", "consent_revoked"),
}

_FIELDS: dict[str, dict[str, type]] = {
    "session_started": {"case_key": str, "workflow": str},
    "import_started": {"format": str, "safety_level": str},
    "import_succeeded": {"format": str, "node_count": int, "edge_count": int, "unknown_count": int},
    "import_failed": {"format": str, "error_code": str},
    "first_interactive_view": {"elapsed_ms": int, "visible_nodes": int, "dom_objects": int, "semantic_level": str},
    "paper_ready": {"elapsed_ms": int, "minimum_font_pt": float, "panel_count": int},
    "edit_summary": {"semantic_changes": int, "node_changes": int, "edge_changes": int, "label_changes": int},
    "export": {"format": str, "succeeded": bool, "error_code": str},
    "recovery": {"action": str, "succeeded": bool},
    "session_completed": {"status": str},
}


def trial_event_schema() -> dict[str, Any]:
    """Return the machine contract used by both server and trial package."""
    event_variants = []
    for event_type in TRIAL_EVENT_TYPES:
        properties: dict[str, Any] = {
            "event_id": {"type": "string", "pattern": "^event_[0-9]{4,}$"},
            "recorded_at": {"type": "string", "format": "date-time"},
            "event_type": {"const": event_type},
        }
        required = ["event_id", "recorded_at", "event_type"]
        for name, kind in _FIELDS[event_type].items():
            required.append(name)
            if kind is str:
                schema: dict[str, Any] = {"type": "string"}
            elif kind is bool:
                schema = {"type": "boolean"}
            elif kind is float:
                schema = {"type": "number", "minimum": 0}
            else:
                schema = {"type": "integer", "minimum": 0}
            enum = _ENUMS.get((event_type, name))
            if enum:
                schema["enum"] = list(enum)
            properties[name] = schema
        event_variants.append({
            "type": "object",
            "additionalProperties": False,
            "required": required,
            "properties": properties,
        })
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://local.nn-davinci.invalid/schemas/trial-events-0.5.0.json",
        "title": "NN_DaVinci local researcher trial export",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "protocol_version", "privacy", "sessions", "aggregate", "human_study_claim"],
        "properties": {
            "schema_version": {"const": TRIAL_SCHEMA_VERSION},
            "protocol_version": {"const": TRIAL_PROTOCOL_VERSION},
            "privacy": {
                "type": "object",
                "additionalProperties": False,
                "required": ["local_only", "uploaded", "contains_model_data", "contains_paths", "contains_user_identity"],
                "properties": {
                    "local_only": {"const": True},
                    "uploaded": {"const": False},
                    "contains_model_data": {"const": False},
                    "contains_paths": {"const": False},
                    "contains_user_identity": {"const": False},
                },
            },
            "sessions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "schema_version", "protocol_version", "session_id", "status",
                        "started_at", "finished_at", "privacy", "events",
                    ],
                    "properties": {
                        "schema_version": {"const": TRIAL_SCHEMA_VERSION},
                        "protocol_version": {"const": TRIAL_PROTOCOL_VERSION},
                        "session_id": {"type": "string", "pattern": "^trial_[a-f0-9]{32}$"},
                        "status": {"enum": ["active", "completed", "abandoned", "consent_revoked"]},
                        "started_at": {"type": "string", "format": "date-time"},
                        "finished_at": {
                            "oneOf": [
                                {"type": "null"},
                                {"type": "string", "format": "date-time"},
                            ],
                        },
                        "privacy": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "local_only", "uploaded", "contains_model_data",
                                "contains_paths", "contains_user_identity",
                            ],
                            "properties": {
                                "local_only": {"const": True},
                                "uploaded": {"const": False},
                                "contains_model_data": {"const": False},
                                "contains_paths": {"const": False},
                                "contains_user_identity": {"const": False},
                            },
                        },
                        "events": {"type": "array", "items": {"oneOf": event_variants}},
                    },
                },
            },
            "aggregate": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "completed_sessions", "first_figure_median_ms", "paper_ready_median_ms",
                    "core_task_success_rate", "target_evaluation", "human_conclusion_ready",
                ],
                "properties": {
                    "completed_sessions": {"type": "integer", "minimum": 0},
                    "first_figure_median_ms": {"type": ["number", "null"], "minimum": 0},
                    "paper_ready_median_ms": {"type": ["number", "null"], "minimum": 0},
                    "core_task_success_rate": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
                    "target_evaluation": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "first_figure_le_5_minutes", "paper_ready_le_15_minutes",
                            "core_task_success_ge_80_percent", "serious_semantic_errors_zero",
                        ],
                        "properties": {
                            "first_figure_le_5_minutes": {"type": "boolean"},
                            "paper_ready_le_15_minutes": {"type": "boolean"},
                            "core_task_success_ge_80_percent": {"type": "boolean"},
                            "serious_semantic_errors_zero": {"type": ["boolean", "null"]},
                        },
                    },
                    "human_conclusion_ready": {"type": "boolean"},
                },
            },
            "human_study_claim": {
                "const": "No human conclusions are valid until consented participant exports are reviewed under TRIAL_PROTOCOL.md."
            },
        },
    }


class TrialRecorder:
    """Persist strictly allow-listed events only after explicit consent."""

    def __init__(self, root: str | Path | None = None) -> None:
        uid = getattr(os, "getuid", lambda: 0)()
        configured = os.environ.get("NNDV_TRIAL_ROOT")
        self.root = Path(root or configured or (Path(tempfile.gettempdir()) / f"nn-davinci-trials-{uid}"))
        self.consent_path = self.root / "consent.json"
        self.sessions_root = self.root / "sessions"
        self.state_path = self.root / "state.json"
        self.lock = threading.RLock()
        self.consent: dict[str, Any] = {"accepted": False, "protocol_version": TRIAL_PROTOCOL_VERSION}
        self.active_session_id: str | None = None
        self._restore()

    def status(self) -> dict[str, Any]:
        with self.lock:
            sessions = self._session_paths()
            active_elapsed_ms = None
            if self.active_session_id:
                active = self._read_session(self.active_session_id)
                started = datetime.fromisoformat(str(active["started_at"]))
                active_elapsed_ms = max(0, int((datetime.now(timezone.utc) - started).total_seconds() * 1000))
            return {
                "schema_version": TRIAL_SCHEMA_VERSION,
                "protocol_version": TRIAL_PROTOCOL_VERSION,
                "enabled": self.consent.get("accepted") is True,
                "active_session_id": self.active_session_id,
                "active_elapsed_ms": active_elapsed_ms,
                "session_count": len(sessions),
                "storage": "local-json",
                "privacy": _privacy(),
                "event_types": list(TRIAL_EVENT_TYPES),
            }

    def set_consent(self, accepted: bool, *, protocol_version: str, explicit_confirmation: bool) -> dict[str, Any]:
        if protocol_version != TRIAL_PROTOCOL_VERSION:
            raise ValidationError(
                f"Trial protocol {protocol_version!r} is not supported",
                hint=f"Review and accept protocol {TRIAL_PROTOCOL_VERSION} before enabling Trial Mode.",
            )
        if accepted and not explicit_confirmation:
            raise ValidationError("Trial Mode requires an explicit consent confirmation")
        with self.lock:
            self._ensure_root()
            if not accepted and self.active_session_id:
                self._finish_locked("consent_revoked")
            self.consent = {
                "schema_version": TRIAL_SCHEMA_VERSION,
                "protocol_version": TRIAL_PROTOCOL_VERSION,
                "accepted": bool(accepted),
                "accepted_at": _now() if accepted else None,
                "revoked_at": None if accepted else _now(),
                "privacy": _privacy(),
            }
            self._atomic_write(self.consent_path, self.consent)
            self._persist_state()
            return self.status()

    def start_session(self, *, case_key: str = "participant_model", workflow: str = "guided-web") -> dict[str, Any]:
        with self.lock:
            self._require_consent()
            if self.active_session_id:
                raise ValidationError(
                    "A researcher trial session is already active",
                    hint="Finish or abandon the current session before starting another case.",
                )
            _validate_payload("session_started", {"case_key": case_key, "workflow": workflow})
            session_id = f"trial_{uuid4().hex}"
            self.active_session_id = session_id
            session: dict[str, Any] = {
                "schema_version": TRIAL_SCHEMA_VERSION,
                "protocol_version": TRIAL_PROTOCOL_VERSION,
                "session_id": session_id,
                "status": "active",
                "started_at": _now(),
                "finished_at": None,
                "privacy": _privacy(),
                "events": [],
            }
            self._write_session(session)
            self._persist_state()
            return self.record("session_started", {"case_key": case_key, "workflow": workflow})

    def record(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            self._require_consent()
            if not self.active_session_id:
                raise ValidationError("No researcher trial session is active", hint="Start a session after consent before recording events.")
            values = _validate_payload(event_type, payload)
            session = self._read_session(self.active_session_id)
            if session.get("status") != "active":
                raise ValidationError("The researcher trial session is no longer active")
            event = {
                "event_id": f"event_{len(session['events']) + 1:04d}",
                "recorded_at": _now(),
                "event_type": event_type,
                **values,
            }
            session["events"].append(event)
            self._write_session(session)
            return event

    def finish_session(self, status: str = "completed") -> dict[str, Any]:
        with self.lock:
            self._require_consent()
            return self._finish_locked(status)

    def export(self) -> dict[str, Any]:
        with self.lock:
            sessions = [self._read_path(path) for path in self._session_paths()]
            return {
                "schema_version": TRIAL_SCHEMA_VERSION,
                "protocol_version": TRIAL_PROTOCOL_VERSION,
                "privacy": _privacy(),
                "sessions": sessions,
                "aggregate": aggregate_trial_sessions(sessions),
                "human_study_claim": "No human conclusions are valid until consented participant exports are reviewed under TRIAL_PROTOCOL.md.",
            }

    def _finish_locked(self, status: str) -> dict[str, Any]:
        if not self.active_session_id:
            raise ValidationError("No researcher trial session is active")
        _validate_payload("session_completed", {"status": status})
        session_id = self.active_session_id
        event = self.record("session_completed", {"status": status})
        session = self._read_session(session_id)
        session["status"] = status
        session["finished_at"] = _now()
        self._write_session(session)
        self.active_session_id = None
        self._persist_state()
        return {"session": session, "summary": summarize_trial_session(session), "completion_event": event}

    def _require_consent(self) -> None:
        if self.consent.get("accepted") is not True:
            raise ValidationError(
                "Trial Mode is disabled because consent has not been recorded",
                hint="Review CONSENT.md and explicitly enable local-only recording first.",
            )

    def _restore(self) -> None:
        if self.consent_path.is_file():
            try:
                self.consent = self._read_path(self.consent_path)
            except (OSError, ValueError, json.JSONDecodeError):
                self.consent = {"accepted": False, "protocol_version": TRIAL_PROTOCOL_VERSION}
        if self.state_path.is_file():
            try:
                state = self._read_path(self.state_path)
                candidate = state.get("active_session_id")
                if isinstance(candidate, str) and re.fullmatch(r"trial_[a-f0-9]{32}", candidate):
                    session = self._read_session(candidate)
                    if session.get("status") == "active" and self.consent.get("accepted") is True:
                        self.active_session_id = candidate
            except (OSError, ValueError, json.JSONDecodeError, ValidationError):
                self.active_session_id = None

    def _ensure_root(self) -> None:
        self.sessions_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.root.chmod(0o700)
            self.sessions_root.chmod(0o700)
        except OSError:
            pass

    def _persist_state(self) -> None:
        self._atomic_write(self.state_path, {
            "schema_version": TRIAL_SCHEMA_VERSION,
            "active_session_id": self.active_session_id,
        })

    def _write_session(self, session: dict[str, Any]) -> None:
        self._ensure_root()
        self._atomic_write(self.sessions_root / f"{session['session_id']}.json", session)

    def _read_session(self, session_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"trial_[a-f0-9]{32}", session_id):
            raise ValidationError("Malformed local trial session ID")
        path = self.sessions_root / f"{session_id}.json"
        if not path.is_file():
            raise ValidationError(f"Unknown local trial session {session_id!r}")
        return self._read_path(path)

    def _session_paths(self) -> list[Path]:
        return sorted(self.sessions_root.glob("trial_*.json")) if self.sessions_root.is_dir() else []

    @staticmethod
    def _read_path(path: Path) -> dict[str, Any]:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValidationError("Local trial JSON must contain an object")
        return value

    @staticmethod
    def _atomic_write(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)
        try:
            path.chmod(0o600)
        except OSError:
            pass


def summarize_trial_session(session: dict[str, Any]) -> dict[str, Any]:
    events = session.get("events", [])
    first_view = [event["elapsed_ms"] for event in events if event.get("event_type") == "first_interactive_view"]
    paper_ready = [event["elapsed_ms"] for event in events if event.get("event_type") == "paper_ready"]
    edits = [event for event in events if event.get("event_type") == "edit_summary"]
    exports = [event for event in events if event.get("event_type") == "export"]
    imported = any(event.get("event_type") == "import_succeeded" for event in events)
    required_exports = {"svg", "pdf", "tikz", "pptx"}
    successful_exports = {event.get("format") for event in exports if event.get("succeeded")}
    return {
        "session_id": session.get("session_id"),
        "status": session.get("status"),
        "first_interactive_view_ms": min(first_view) if first_view else None,
        "paper_ready_ms": min(paper_ready) if paper_ready else None,
        "edits": {
            key: sum(int(event.get(key, 0)) for event in edits)
            for key in ("semantic_changes", "node_changes", "edge_changes", "label_changes")
        },
        "successful_exports": sorted(successful_exports),
        "errors": sum(event.get("event_type") in {"import_failed"} or (event.get("event_type") == "export" and not event.get("succeeded")) for event in events),
        "recoveries": sum(event.get("event_type") == "recovery" for event in events),
        "core_task_success": imported and paper_ready != [] and required_exports.issubset(successful_exports),
    }


def aggregate_trial_sessions(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    summaries = [summarize_trial_session(session) for session in sessions if session.get("status") == "completed"]
    first = [item["first_interactive_view_ms"] for item in summaries if item["first_interactive_view_ms"] is not None]
    paper = [item["paper_ready_ms"] for item in summaries if item["paper_ready_ms"] is not None]
    success = sum(bool(item["core_task_success"]) for item in summaries)
    return {
        "completed_sessions": len(summaries),
        "first_figure_median_ms": statistics.median(first) if first else None,
        "paper_ready_median_ms": statistics.median(paper) if paper else None,
        "core_task_success_rate": success / len(summaries) if summaries else None,
        "target_evaluation": {
            "first_figure_le_5_minutes": bool(first) and statistics.median(first) <= 300_000,
            "paper_ready_le_15_minutes": bool(paper) and statistics.median(paper) <= 900_000,
            "core_task_success_ge_80_percent": bool(summaries) and success / len(summaries) >= 0.8,
            "serious_semantic_errors_zero": None,
        },
        # Session files deliberately do not contain identity or researcher-role
        # data.  Consequently automation and consented human sessions cannot be
        # distinguished safely from the event stream alone.  Only the manual
        # protocol review may promote a trial to a human-study conclusion.
        "human_conclusion_ready": False,
    }


def _validate_payload(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if event_type not in TRIAL_EVENT_TYPES:
        raise ValidationError(f"Trial event type {event_type!r} is not allow-listed")
    if not isinstance(payload, dict):
        raise ValidationError("Trial event payload must be an object")
    expected = _FIELDS[event_type]
    if set(payload) != set(expected):
        raise ValidationError(
            f"Trial event {event_type!r} fields do not match the privacy allowlist",
            hint=f"Required fields: {', '.join(expected)}. Model names, paths, labels, text and user identifiers are forbidden.",
            details={"required": sorted(expected), "received": sorted(str(key) for key in payload)},
        )
    result: dict[str, Any] = {}
    for name, kind in expected.items():
        value = payload[name]
        if kind is float:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValidationError(f"Trial event field {name!r} must be a number")
            value = float(value)
        elif kind is int and (not isinstance(value, int) or isinstance(value, bool)):
            raise ValidationError(f"Trial event field {name!r} must be an integer")
        elif kind is bool and not isinstance(value, bool):
            raise ValidationError(f"Trial event field {name!r} must be a boolean")
        elif kind is str and not isinstance(value, str):
            raise ValidationError(f"Trial event field {name!r} must be a string")
        if isinstance(value, (int, float)) and value < 0:
            raise ValidationError(f"Trial event field {name!r} cannot be negative")
        allowed = _ENUMS.get((event_type, name))
        if allowed and value not in allowed:
            raise ValidationError(f"Trial event field {name!r} value {value!r} is not allow-listed")
        result[name] = value
    return result


def _privacy() -> dict[str, bool]:
    return {
        "local_only": True,
        "uploaded": False,
        "contains_model_data": False,
        "contains_paths": False,
        "contains_user_identity": False,
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "ERROR_CODES",
    "EXPORT_FORMATS",
    "RECOVERY_ACTIONS",
    "TRIAL_CASE_KEYS",
    "TRIAL_EVENT_TYPES",
    "TRIAL_PROTOCOL_VERSION",
    "TRIAL_SCHEMA_VERSION",
    "TrialRecorder",
    "aggregate_trial_sessions",
    "summarize_trial_session",
    "trial_event_schema",
]
