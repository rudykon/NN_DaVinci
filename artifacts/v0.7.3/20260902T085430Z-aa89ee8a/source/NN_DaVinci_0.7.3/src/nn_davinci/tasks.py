"""Observable, cancellable local tasks with refresh-safe result records."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from typing import Any, Callable
from uuid import uuid4

from .errors import ValidationError

TASK_SCHEMA_VERSION = "1.0"
TASK_STATES = ("queued", "running", "succeeded", "failed", "cancelled")
TASK_KINDS = ("import", "analyze", "layout", "runtime", "export")


class TaskCancelled(RuntimeError):
    pass


@dataclass(slots=True)
class TaskRecord:
    id: str
    kind: str
    status: str = "queued"
    stage: str = "queued"
    progress: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: str | None = None
    finished_at: str | None = None
    elapsed_seconds: float = 0.0
    input_size: dict[str, int] = field(default_factory=dict)
    resource_budget: dict[str, Any] = field(default_factory=dict)
    result_id: str | None = None
    error: dict[str, Any] | None = None
    recovery_actions: list[dict[str, str]] = field(default_factory=list)
    retry_of: str | None = None
    schema_version: str = TASK_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TaskContext:
    def __init__(self, manager: "TaskManager", task_id: str, cancelled: threading.Event):
        self.manager = manager
        self.task_id = task_id
        self.cancelled = cancelled

    def report(self, stage: str, progress: float) -> None:
        self.check_cancelled()
        self.manager._update(self.task_id, stage=stage, progress=max(0.0, min(1.0, float(progress))))

    def check_cancelled(self) -> None:
        if self.cancelled.is_set():
            raise TaskCancelled("Task was cancelled")


TaskFunction = Callable[[TaskContext], Any]


class TaskManager:
    """Small local executor; no accounts, remote workers, or public binding."""

    def __init__(self, root: str | Path | None = None, *, workers: int = 2, retention_seconds: int = 24 * 60 * 60):
        uid = getattr(os, "getuid", lambda: 0)()
        self.root = Path(root) if root else Path(tempfile.gettempdir()) / f"nn-davinci-tasks-{uid}"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.root.chmod(0o700)
        except OSError:
            pass
        self.retention_seconds = retention_seconds
        self.executor = ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="nndv-task")
        self.records: dict[str, TaskRecord] = {}
        self.events: dict[str, threading.Event] = {}
        self.futures: dict[str, Future[Any]] = {}
        self.functions: dict[str, TaskFunction] = {}
        self.lock = threading.RLock()
        self._restore_records()
        self.cleanup()

    def submit(
        self,
        kind: str,
        function: TaskFunction,
        *,
        input_size: dict[str, int] | None = None,
        resource_budget: dict[str, Any] | None = None,
        retry_of: str | None = None,
    ) -> TaskRecord:
        if kind not in TASK_KINDS:
            raise ValidationError(f"Unknown task kind {kind!r}", hint=f"Choose one of: {', '.join(TASK_KINDS)}.")
        task_id = f"task_{uuid4().hex}"
        record = TaskRecord(
            id=task_id,
            kind=kind,
            input_size=dict(input_size or {}),
            resource_budget=dict(resource_budget or _default_budget(kind)),
            retry_of=retry_of,
        )
        event = threading.Event()
        with self.lock:
            self.records[task_id] = record
            self.events[task_id] = event
            self.functions[task_id] = function
            self._persist(record)
            self.futures[task_id] = self.executor.submit(self._run, task_id, function, event)
        return record

    def get(self, task_id: str, *, include_result: bool = False) -> dict[str, Any]:
        with self.lock:
            record = self.records.get(task_id)
            if record is None:
                raise ValidationError(f"Unknown task {task_id!r}")
            payload = record.to_dict()
        if include_result and record.result_id:
            result_path = self.root / f"{record.result_id}.json"
            if result_path.exists():
                payload["result"] = json.loads(result_path.read_text(encoding="utf-8"))
        return payload

    def list(self) -> list[dict[str, Any]]:
        with self.lock:
            records = sorted(self.records.values(), key=lambda item: item.created_at, reverse=True)
            return [record.to_dict() for record in records]

    def cancel(self, task_id: str) -> dict[str, Any]:
        with self.lock:
            record = self.records.get(task_id)
            if record is None:
                raise ValidationError(f"Unknown task {task_id!r}")
            if record.status in {"succeeded", "failed", "cancelled"}:
                return record.to_dict()
            self.events[task_id].set()
            future = self.futures.get(task_id)
            if record.status == "queued" and future and future.cancel():
                self._finish_cancelled(record)
            else:
                record.stage = "cancelling"
                self._persist(record)
            return record.to_dict()

    def retry(self, task_id: str) -> TaskRecord:
        with self.lock:
            original = self.records.get(task_id)
            function = self.functions.get(task_id)
            if original is None:
                raise ValidationError(f"Unknown task {task_id!r}")
            if original.status not in {"failed", "cancelled"}:
                raise ValidationError("Only failed or cancelled tasks can be retried")
            if function is None:
                raise ValidationError(
                    "Task input is no longer available for retry",
                    hint="Repeat the operation from the editor; persisted results survive refresh, but executable inputs are process-local.",
                )
            return self.submit(
                original.kind,
                function,
                input_size=original.input_size,
                resource_budget=original.resource_budget,
                retry_of=original.id,
            )

    def cleanup(self) -> int:
        now = time.time()
        removed = 0
        for path in self.root.iterdir():
            try:
                age = now - path.stat().st_mtime
            except OSError:
                continue
            if age <= self.retention_seconds or not path.is_file():
                continue
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        return removed

    def shutdown(self, *, wait: bool = False) -> None:
        self.executor.shutdown(wait=wait, cancel_futures=True)

    def _run(self, task_id: str, function: TaskFunction, cancelled: threading.Event) -> None:
        started = time.monotonic()
        record = self.records[task_id]
        with self.lock:
            if cancelled.is_set():
                self._finish_cancelled(record)
                return
            record.status = "running"
            record.stage = "starting"
            record.started_at = datetime.now(timezone.utc).isoformat()
            self._persist(record)
        context = TaskContext(self, task_id, cancelled)
        try:
            context.report("running", 0.02)
            result = function(context)
            context.check_cancelled()
            result_id = f"result_{task_id.removeprefix('task_')}"
            self._persist_result(result_id, result)
            with self.lock:
                record.status = "succeeded"
                record.stage = "complete"
                record.progress = 1.0
                record.result_id = result_id
                record.finished_at = datetime.now(timezone.utc).isoformat()
                record.elapsed_seconds = round(time.monotonic() - started, 6)
                self._persist(record)
        except TaskCancelled:
            with self.lock:
                record.elapsed_seconds = round(time.monotonic() - started, 6)
                self._finish_cancelled(record)
        except Exception as exc:
            with self.lock:
                record.status = "failed"
                record.stage = "failed"
                record.finished_at = datetime.now(timezone.utc).isoformat()
                record.elapsed_seconds = round(time.monotonic() - started, 6)
                record.error = {"type": type(exc).__name__, "message": str(exc)}
                record.recovery_actions = _recovery_actions(record.kind, exc)
                self._persist(record)

    def _finish_cancelled(self, record: TaskRecord) -> None:
        record.status = "cancelled"
        record.stage = "cancelled"
        record.finished_at = datetime.now(timezone.utc).isoformat()
        record.recovery_actions = [{"id": "retry", "label": "Retry task"}]
        self._persist(record)

    def _update(self, task_id: str, **values: Any) -> None:
        with self.lock:
            record = self.records[task_id]
            for key, value in values.items():
                setattr(record, key, value)
            if record.started_at:
                try:
                    started = datetime.fromisoformat(record.started_at)
                    record.elapsed_seconds = max(0.0, (datetime.now(timezone.utc) - started).total_seconds())
                except ValueError:
                    pass
            self._persist(record)

    def _persist(self, record: TaskRecord) -> None:
        target = self.root / f"{record.id}.json"
        temporary = self.root / f".{record.id}.{uuid4().hex}.tmp"
        temporary.write_text(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True), encoding="utf-8")
        temporary.replace(target)

    def _persist_result(self, result_id: str, result: Any) -> None:
        payload = _json_result(result)
        target = self.root / f"{result_id}.json"
        temporary = self.root / f".{result_id}.{uuid4().hex}.tmp"
        temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        temporary.replace(target)

    def _restore_records(self) -> None:
        for path in self.root.glob("task_*.json"):
            try:
                record = TaskRecord(**json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
            if record.status in {"queued", "running"}:
                record.status = "failed"
                record.stage = "interrupted"
                record.finished_at = datetime.now(timezone.utc).isoformat()
                record.error = {"type": "InterruptedTask", "message": "The local server stopped before the task completed."}
                record.recovery_actions = [{"id": "repeat", "label": "Repeat the operation from the editor"}]
                self._persist(record)
            self.records[record.id] = record


def _default_budget(kind: str) -> dict[str, Any]:
    return {
        "wall_seconds": 120 if kind in {"runtime", "export"} else 60,
        "memory_mib": 2_048,
        "maximum_visible_nodes": 500,
        "maximum_dom_objects": 2_000,
        "cooperative_cancel_seconds": 1,
    }


def _recovery_actions(kind: str, error: Exception) -> list[dict[str, str]]:
    message = str(error).lower()
    actions = [{"id": "retry", "label": "Retry"}]
    if kind == "import" or any(word in message for word in ("shape", "input", "trace")):
        actions.extend([
            {"id": "sample-input", "label": "Add or correct sample input"},
            {"id": "module-view", "label": "Use framework/module view"},
        ])
    if kind in {"layout", "export"} or any(word in message for word in ("large", "budget", "node")):
        actions.extend([
            {"id": "summary", "label": "Use semantic summary"},
            {"id": "focus", "label": "Reduce focus or semantic level"},
            {"id": "page", "label": "Switch page specification"},
        ])
    return actions


def _json_result(result: Any) -> Any:
    if hasattr(result, "to_dict"):
        return result.to_dict()
    if isinstance(result, Path):
        return {"path": str(result)}
    if isinstance(result, dict):
        return {str(key): _json_result(value) for key, value in result.items()}
    if isinstance(result, (list, tuple)):
        return [_json_result(value) for value in result]
    if isinstance(result, (str, int, float, bool)) or result is None:
        return result
    return str(result)


__all__ = [
    "TASK_KINDS",
    "TASK_SCHEMA_VERSION",
    "TASK_STATES",
    "TaskCancelled",
    "TaskContext",
    "TaskManager",
    "TaskRecord",
]
