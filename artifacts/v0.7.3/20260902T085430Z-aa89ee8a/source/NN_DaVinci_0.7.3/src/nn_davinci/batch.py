from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .api import render
from .errors import ValidationError


def batch_render(manifest: str | Path | dict[str, Any], *, workers: int = 1) -> dict[str, Any]:
    if isinstance(manifest, dict):
        data = manifest
        base = Path.cwd()
    else:
        manifest_path = Path(manifest)
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        base = manifest_path.parent
    jobs = data.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise ValidationError("Batch manifest needs a non-empty 'jobs' list")
    defaults = data.get("defaults", {})

    def run(index: int, item: dict[str, Any]) -> dict[str, Any]:
        config = {**defaults, **item}
        source = Path(config.pop("source"))
        output = Path(config.pop("output", f"diagram-{index}.svg"))
        if not source.is_absolute():
            source = base / source
        if not output.is_absolute():
            output = base / output
        try:
            outputs = render(source, output, **config)
            return {"index": index, "source": str(source), "status": "ok", "outputs": [str(path) for path in outputs]}
        except Exception as exc:
            return {"index": index, "source": str(source), "status": "error", "error": type(exc).__name__, "message": str(exc)}

    results: list[dict[str, Any]] = []
    if workers <= 1:
        results = [run(index, item) for index, item in enumerate(jobs)]
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(run, index, item): index for index, item in enumerate(jobs)}
            for future in as_completed(futures):
                results.append(future.result())
        results.sort(key=lambda item: item["index"])
    return {"jobs": len(jobs), "succeeded": sum(item["status"] == "ok" for item in results), "failed": sum(item["status"] == "error" for item in results), "results": results}

