#!/usr/bin/env python3
"""Install a new wheel and sdist with dependencies and run package-data/CLI checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any


def run(command: list[str], *, environment: dict[str, str] | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, env=environment, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}\n{result.stdout}\n{result.stderr}")
    return result


def item(path: Path) -> dict[str, object]:
    return {"name": path.name, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def create_environment(path: Path) -> Path:
    virtualenv = shutil.which("virtualenv") or str(Path.home() / ".local/bin/virtualenv")
    run([virtualenv, "--no-download", "--setuptools", "bundle", "-p", sys.executable, str(path)])
    return path / "bin/python"


def smoke(python: Path, archive: Path, root: Path, output: Path, expected_version: str) -> dict[str, Any]:
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    install = run([str(python), "-m", "pip", "install", "--no-index", "--no-build-isolation", "--force-reinstall", str(archive)], environment=environment)
    pip_check = run([str(python), "-m", "pip", "check"], environment=environment)
    version = run([str(python), "-c", "import nn_davinci; print(nn_davinci.__version__)"], environment=environment).stdout.strip()
    cli_version = run([str(python.parent / "nnviz"), "--version"], environment=environment).stdout.strip()
    run([
        str(python.parent / "nnviz"), "render", str(root / "examples/resnet.json"), "-o", str(output),
        "--format", "svg", "--page", "double-column",
    ], environment=environment)
    assets = run([
        str(python), "-c",
        "from importlib.resources import files; r=files('nn_davinci')/'web'; print(all((r/n).is_file() for n in ('index.html','app.js','styles.css','favicon.svg','scene-renderer.js','scene-interactions.js','commands.js','state-machine.js','design-system.css','scene-studio.css')))"
    ], environment=environment).stdout.strip()
    templates = run([
        str(python), "-c",
        "from importlib.resources import files; import json; r=files('nn_davinci')/'figure_templates'; p=list(r.iterdir()); print(len(p)==7 and all(x.name.endswith('.nndv.json') and json.loads(x.read_text())['project_version']=='1.3' for x in p))",
    ], environment=environment).stdout.strip()
    scene_templates = run([
        str(python), "-c",
        "from importlib.resources import files; import json; r=files('nn_davinci')/'scene_templates'; p=list(r.iterdir()); print(len(p)==7 and all(x.name.endswith('.scene.json') and json.loads(x.read_text())['schema_version']=='1.0' for x in p))",
    ], environment=environment).stdout.strip()
    return {
        "install_command": install.args, "pip_check": pip_check.stdout.strip(), "version": version,
        "cli_version": cli_version, "svg_bytes": output.stat().st_size, "web_assets": assets == "True",
        "figure_templates": templates == "True",
        "scene_templates": scene_templates == "True",
        "passed": version == expected_version and cli_version == f"NN_DaVinci {expected_version}" and output.stat().st_size > 32 and assets == "True" and templates == "True" and scene_templates == "True",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dist", type=Path)
    parser.add_argument("work", type=Path)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    wheels = list(args.dist.glob("*.whl"))
    sdists = list(args.dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise SystemExit(f"expected exactly one wheel and sdist, found {wheels}, {sdists}")
    args.work.mkdir(parents=True, exist_ok=False)
    wheel_python = create_environment(args.work / "wheel-venv")
    sdist_python = create_environment(args.work / "sdist-venv")
    wheel = smoke(wheel_python, wheels[0], args.project_root, args.work / "wheel-installed.svg", args.expected_version)
    sdist = smoke(sdist_python, sdists[0], args.project_root, args.work / "sdist-installed.svg", args.expected_version)
    lock_check = run([sys.executable, str(args.project_root / "scripts/write_verification_lock.py")], cwd=args.project_root)
    report = {
        "checks": 16, "wheel": item(wheels[0]), "sdist": item(sdists[0]),
        "wheel_install": wheel, "sdist_install": sdist,
        "wheel_installed_with_dependencies": "--no-deps" not in wheel["install_command"],
        "sdist_installed_with_dependencies": "--no-deps" not in sdist["install_command"],
        "pip_check_passed": bool(wheel["pip_check"] == "No broken requirements found." and sdist["pip_check"] == "No broken requirements found."),
        "web_assets": bool(wheel["web_assets"] and sdist["web_assets"]),
        "figure_templates": bool(wheel["figure_templates"] and sdist["figure_templates"]),
        "scene_templates": bool(wheel["scene_templates"] and sdist["scene_templates"]),
        "cli_smoke": bool(wheel["passed"] and sdist["passed"]),
        "lock_matches": lock_check.returncode == 0, "lock_check": lock_check.stdout.strip(),
    }
    report["passed"] = all(report[key] for key in (
        "wheel_installed_with_dependencies", "sdist_installed_with_dependencies", "pip_check_passed",
        "web_assets", "figure_templates", "scene_templates", "cli_smoke", "lock_matches",
    ))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"checks": report["checks"], "passed": report["passed"]}, sort_keys=True))
    if not report["passed"]:
        raise SystemExit("package installation gate failed")


if __name__ == "__main__":
    main()
