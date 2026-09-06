#!/usr/bin/env python3
"""Aggregate consented local Trial Mode exports without identity or free text."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from nn_davinci.trial import TRIAL_SCHEMA_VERSION, aggregate_trial_sessions, summarize_trial_session


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sessions = []
    failures = []
    for path in args.inputs:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("schema_version") != TRIAL_SCHEMA_VERSION or value.get("privacy", {}).get("local_only") is not True:
                raise ValueError("not a compatible local-only Trial Mode export")
            sessions.extend(value.get("sessions", []))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            failures.append({"input": path.name, "error": str(exc)})
    report = {
        "schema_version": "0.5.0-human-trial-aggregate-1",
        "measurement_source": "consented-human-events",
        "input_files": len(args.inputs),
        "participant_count": None,
        "participant_count_note": "Set from the separately controlled anonymous recruitment log; session IDs do not identify people.",
        "sessions": [summarize_trial_session(session) for session in sessions],
        "aggregate": aggregate_trial_sessions(sessions),
        "semantic_review": {
            "serious_errors": None,
            "note": "Requires a human reviewer to compare each reported issue with Graph IR/source-path provenance.",
        },
        "failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"sessions": len(sessions), "failures": len(failures), "human_conclusion_ready": report["aggregate"]["human_conclusion_ready"]}, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
