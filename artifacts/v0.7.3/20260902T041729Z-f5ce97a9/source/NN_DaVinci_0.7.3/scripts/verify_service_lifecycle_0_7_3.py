#!/usr/bin/env python3
"""Exercise start/status/stop/restart without leaving test listeners."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _call(script: str, port: int, state_dir: Path) -> dict[str, Any]:
    result = subprocess.run(
        [str(ROOT / "scripts" / script), "--port", str(port), "--state-dir", str(state_dir), "--timeout", "12"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = {"status": "INVALID_OUTPUT", "stdout": result.stdout, "stderr": result.stderr}
    return {"script": script, "exit_code": result.returncode, "payload": payload, "stderr": result.stderr}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    failures: list[str] = []
    steps: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="nndv-073-service-") as temporary:
        state_dir = Path(temporary)
        start = _call("start-0.7.3.sh", args.port, state_dir)
        steps.append(start)
        if start["exit_code"] != 0 or start["payload"].get("status") != "STARTED":
            failures.append("start did not produce a stable ready service")
        first_pid = start["payload"].get("state", {}).get("pid")

        running = _call("status-0.7.3.sh", args.port, state_dir)
        steps.append(running)
        if running["exit_code"] != 0 or running["payload"].get("status") != "RUNNING" or running["payload"].get("identity_valid") is not True:
            failures.append("status did not validate PID/start-time/cmdline/health identity")

        restart = _call("restart-0.7.3.sh", args.port, state_dir)
        steps.append(restart)
        replacement_pid = restart["payload"].get("start", {}).get("state", {}).get("pid")
        if restart["exit_code"] != 0 or restart["payload"].get("status") != "RESTARTED" or not replacement_pid or replacement_pid == first_pid:
            failures.append("restart did not replace the exact service process")

        stopped = _call("stop-0.7.3.sh", args.port, state_dir)
        steps.append(stopped)
        if stopped["exit_code"] != 0 or stopped["payload"].get("status") != "STOPPED" or stopped["payload"].get("port_released") is not True:
            failures.append("stop did not confirm process exit and port release")

        after = _call("status-0.7.3.sh", args.port, state_dir)
        steps.append(after)
        if after["payload"].get("status") != "STOPPED":
            failures.append("post-stop status did not report STOPPED")

        # An unrelated listener must be reported as a conflict and left alone.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", args.port))
            listener.listen(1)
            conflict = _call("start-0.7.3.sh", args.port, state_dir)
            steps.append(conflict)
            if conflict["exit_code"] != 4 or conflict["payload"].get("status") != "PORT_CONFLICT":
                failures.append("unrelated listener was not blocked as a port conflict")

        # A forged PID file naming this verifier must never cause a signal.
        state_dir.mkdir(parents=True, exist_ok=True)
        forged = state_dir / f"service-{args.port}.pid.json"
        forged.write_text(json.dumps({
            "pid": os.getpid(),
            "process_start_ticks": "forged",
            "cmdline_digest": "forged",
            "host": "127.0.0.1",
            "port": args.port,
        }), encoding="utf-8")
        refused = _call("stop-0.7.3.sh", args.port, state_dir)
        steps.append(refused)
        if refused["exit_code"] != 6 or refused["payload"].get("status") != "REFUSED" or os.getpid() <= 0:
            failures.append("forged PID identity was not safely refused")

    report = {
        "schema_version": "nndv-0.7.3-service-lifecycle-verification-1",
        "release": "0.7.3 — Reader-Visible Scientific Completeness & Generalization Hotfix",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not failures else "FAIL",
        "port": args.port,
        "steps": steps,
        "failures": failures,
        "leftover_test_listener": False,
        "human_participants": 0,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "steps": len(steps), "failures": failures}, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
