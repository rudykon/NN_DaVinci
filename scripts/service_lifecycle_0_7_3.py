#!/usr/bin/env python3
"""Safe start/status/stop/restart lifecycle for the local NN_DaVinci service."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from typing import Any
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener


PRODUCT_VERSION = "0.7.3"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _state_root(value: str | None) -> Path:
    if value:
        return Path(value).resolve()
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
    return runtime / f"nn-davinci-{os.getuid()}"


def _paths(root: Path, port: int) -> tuple[Path, Path]:
    return root / f"service-{port}.pid.json", root / f"service-{port}.log"


def _process_record(pid: int) -> tuple[str, list[str]] | None:
    proc = Path("/proc") / str(pid)
    try:
        stat = (proc / "stat").read_text(encoding="utf-8").split()
        cmdline = [part.decode("utf-8", errors="replace") for part in (proc / "cmdline").read_bytes().split(b"\0") if part]
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
        return None
    if len(stat) < 22 or not cmdline:
        return None
    return stat[21], cmdline


def _cmdline_digest(cmdline: list[str]) -> str:
    return sha256(b"\0".join(item.encode("utf-8") for item in cmdline)).hexdigest()


def _load_state(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_state(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def _health(host: str, port: int, *, timeout: float = 0.5) -> dict[str, Any] | None:
    request_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(f"http://{request_host}:{port}/api/health", timeout=timeout) as response:
            value = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _identity_status(state: dict[str, Any] | None) -> tuple[bool, str, dict[str, Any] | None]:
    if state is None:
        return False, "state-file-absent-or-invalid", None
    try:
        pid = int(state["pid"])
        host = str(state["host"])
        port = int(state["port"])
    except (KeyError, TypeError, ValueError):
        return False, "state-file-fields-invalid", None
    process = _process_record(pid)
    if process is None:
        return False, "recorded-process-absent", None
    start_ticks, cmdline = process
    if start_ticks != str(state.get("process_start_ticks")):
        return False, "pid-reused-start-time-mismatch", None
    if _cmdline_digest(cmdline) != state.get("cmdline_digest"):
        return False, "pid-command-identity-mismatch", None
    expected_markers = {"-m", "nn_davinci.cli", "serve", "--port", str(port)}
    if not expected_markers.issubset(set(cmdline)):
        return False, "pid-command-markers-mismatch", None
    health = _health(host, port)
    if health is None:
        return False, "health-unreachable", None
    if (
        health.get("pid") != pid
        or health.get("product_version") != PRODUCT_VERSION
        or health.get("source_identity") != state.get("source_identity")
        or health.get("build_identity") != state.get("build_identity")
        or health.get("readiness") is not True
    ):
        return False, "health-process-identity-mismatch", health
    return True, "ready", health


def _port_available(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    bind_host = host
    with socket.socket(family, socket.SOCK_STREAM) as candidate:
        candidate.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            candidate.bind((bind_host, port))
        except OSError:
            return False
    return True


def status(*, host: str, port: int, state_root: Path) -> tuple[int, dict[str, Any]]:
    state_path, log_path = _paths(state_root, port)
    state = _load_state(state_path)
    valid, reason, health = _identity_status(state)
    report = {
        "schema_version": "nndv-0.7.3-service-status-1",
        "status": "RUNNING" if valid else "STOPPED" if state is None else "STALE",
        "identity_valid": valid,
        "reason": reason,
        "host": host,
        "port": port,
        "state_file": str(state_path),
        "log_file": str(log_path),
        "state": state,
        "health": health,
    }
    return (0 if valid else 3), report


def start(*, host: str, port: int, state_root: Path, timeout: float) -> tuple[int, dict[str, Any]]:
    state_path, log_path = _paths(state_root, port)
    existing = _load_state(state_path)
    valid, reason, health = _identity_status(existing)
    if valid:
        return 2, {"status": "ALREADY_RUNNING", "reason": reason, "state": existing, "health": health}
    if not _port_available(host, port):
        return 4, {"status": "PORT_CONFLICT", "host": host, "port": port, "reason": "listener-or-bind-conflict"}
    state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    source_identity = f"source-root:{sha256(str(PROJECT_ROOT).encode('utf-8')).hexdigest()}"
    build_identity = f"lifecycle:{PRODUCT_VERSION}:{sha256(Path(__file__).read_bytes()).hexdigest()}"
    command = [
        sys.executable,
        "-m",
        "nn_davinci.cli",
        "serve",
        "--host",
        host,
        "--port",
        str(port),
        "--no-browser",
    ]
    environment = os.environ.copy()
    source_path = str(PROJECT_ROOT / "src")
    environment["PYTHONPATH"] = source_path + (os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else "")
    environment["NNDV_SERVICE_HOST"] = host
    environment["NNDV_SERVICE_PORT"] = str(port)
    environment["NNDV_SOURCE_IDENTITY"] = source_identity
    environment["NNDV_BUILD_IDENTITY"] = build_identity
    with log_path.open("ab", buffering=0) as log:
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    record = None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = _process_record(process.pid)
        health = _health(host, port)
        if record is not None and health is not None and health.get("pid") == process.pid and health.get("readiness") is True:
            break
        if process.poll() is not None:
            return 5, {"status": "START_FAILED", "reason": f"process-exit-{process.returncode}", "log_file": str(log_path)}
        time.sleep(0.1)
    else:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
        return 5, {"status": "START_TIMEOUT", "pid": process.pid, "log_file": str(log_path)}
    assert record is not None and health is not None
    start_ticks, cmdline = record
    state = {
        "schema_version": "nndv-0.7.3-service-pid-1",
        "product_version": PRODUCT_VERSION,
        "pid": process.pid,
        "process_start_ticks": start_ticks,
        "cmdline_digest": _cmdline_digest(cmdline),
        "host": host,
        "port": port,
        "source_root": str(PROJECT_ROOT),
        "source_identity": source_identity,
        "build_identity": build_identity,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "log_file": str(log_path),
        "lan_risk": host not in {"127.0.0.1", "localhost", "::1"},
    }
    _write_state(state_path, state)
    stable_deadline = time.monotonic() + 0.75
    while time.monotonic() < stable_deadline:
        if process.poll() is not None or _health(host, port) is None:
            return 5, {"status": "UNSTABLE_AFTER_START", "pid": process.pid, "log_file": str(log_path)}
        time.sleep(0.1)
    report = {"status": "STARTED", "state": state, "health": _health(host, port)}
    if state["lan_risk"]:
        report["security_warning"] = "UNAUTHENTICATED LAN BINDING: this is not approved for public or multi-user deployment."
    return 0, report


def stop(*, host: str, port: int, state_root: Path, timeout: float) -> tuple[int, dict[str, Any]]:
    state_path, _log_path = _paths(state_root, port)
    state = _load_state(state_path)
    valid, reason, health = _identity_status(state)
    if not valid or state is None:
        if state is not None and reason == "recorded-process-absent" and _port_available(host, port):
            state_path.unlink(missing_ok=True)
            return 0, {
                "status": "ALREADY_STOPPED",
                "reason": reason,
                "process_gone": True,
                "port_released": True,
                "stale_state_removed": True,
            }
        return 6, {"status": "REFUSED", "reason": reason, "health": health, "message": "PID identity was not proven; no signal was sent."}
    pid = int(state["pid"])
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and (_process_record(pid) is not None or not _port_available(host, port)):
        time.sleep(0.1)
    if _process_record(pid) is not None:
        # The exact start-time and command identity were proven above; a force
        # signal therefore cannot target an unrelated or PID-reused process.
        current = _process_record(pid)
        if current is None or current[0] != state["process_start_ticks"] or _cmdline_digest(current[1]) != state["cmdline_digest"]:
            return 6, {"status": "REFUSED", "reason": "identity-changed-before-force-stop"}
        os.kill(pid, signal.SIGKILL)
        force_deadline = time.monotonic() + 3.0
        while time.monotonic() < force_deadline and _process_record(pid) is not None:
            time.sleep(0.1)
    process_gone = _process_record(pid) is None
    port_released = _port_available(host, port)
    if not process_gone or not port_released:
        return 7, {"status": "STOP_FAILED", "pid": pid, "process_gone": process_gone, "port_released": port_released}
    state_path.unlink(missing_ok=True)
    return 0, {"status": "STOPPED", "pid": pid, "process_gone": True, "port_released": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "status", "stop", "restart"))
    parser.add_argument("--host", default=os.environ.get("NNDV_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("NNDV_PORT", "8765")))
    parser.add_argument("--state-dir", default=os.environ.get("NNDV_SERVICE_STATE_DIR"))
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()
    state_root = _state_root(args.state_dir)
    if args.action == "start":
        code, report = start(host=args.host, port=args.port, state_root=state_root, timeout=args.timeout)
    elif args.action == "status":
        code, report = status(host=args.host, port=args.port, state_root=state_root)
    elif args.action == "stop":
        code, report = stop(host=args.host, port=args.port, state_root=state_root, timeout=args.timeout)
    else:
        stop_code, stop_report = stop(host=args.host, port=args.port, state_root=state_root, timeout=args.timeout)
        if stop_code not in {0, 6}:
            code, report = stop_code, {"status": "RESTART_FAILED", "stop": stop_report}
        elif stop_code == 6 and stop_report.get("reason") != "state-file-absent-or-invalid":
            code, report = stop_code, {"status": "RESTART_REFUSED", "stop": stop_report}
        else:
            start_code, start_report = start(host=args.host, port=args.port, state_root=state_root, timeout=args.timeout)
            code, report = start_code, {"status": "RESTARTED" if start_code == 0 else "RESTART_FAILED", "stop": stop_report, "start": start_report}
    print(json.dumps(report, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
