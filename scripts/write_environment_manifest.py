#!/usr/bin/env python3
"""Write reproducibility data without assuming that the project is in Git."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
from pathlib import Path


PACKAGES = ("nn-davinci", "flask", "cairosvg", "python-pptx", "onnx", "torch", "torchvision", "tensorflow", "keras", "jax", "torchlens", "torchcam", "numpy", "PyYAML")


def command_version(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        return (result.stdout or result.stderr).strip().splitlines()[0]
    except (OSError, subprocess.CalledProcessError, IndexError):
        return None


def cpu_model() -> str:
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lower().startswith("model name") and ":" in line:
                return line.split(":", 1)[1].strip()
    return platform.processor() or "unknown"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).parents[1]
    tracked_roots = [
        root / name
        for name in (
            "src", "tests", "scripts", "docs", "examples", "schemas", "templates",
            "verification", "requirements",
        )
    ]
    files = [
        path
        for base in tracked_roots
        for path in base.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and not any(part.endswith(".egg-info") for part in path.parts)
    ]
    files += [
        root / name
        for name in (
            "README.md", "pyproject.toml", "package.json", "package-lock.json",
            "eslint.config.mjs", "LICENSE", ".gitignore",
        )
        if (root / name).is_file()
    ]
    manifest = {
        "project_version": __import__("nn_davinci").__version__,
        "generated_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "git_repository": (root / ".git").exists(),
        "git_note": "No Git repository was initialized by the v0.2 hardening work." if not (root / ".git").exists() else "Existing Git metadata detected.",
        "platform": platform.platform(),
        "python": platform.python_version(),
        "hardware": {
            "cpu_model": cpu_model(),
            "logical_cpu_count": __import__("os").cpu_count(),
            "machine": platform.machine(),
            "kernel": platform.release(),
        },
        "tools": {
            "browser": command_version(["google-chrome", "--version"]),
            "node": command_version(["node", "--version"]),
            "npm": command_version(["npm", "--version"]),
            "pdflatex": command_version(["pdflatex", "--version"]),
            "pdffonts": command_version(["pdffonts", "-v"]),
        },
        "packages": {},
        "sources": {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(set(files))
        },
    }
    for package in PACKAGES:
        try:
            manifest["packages"][package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            manifest["packages"][package] = None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "sources": len(manifest["sources"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
