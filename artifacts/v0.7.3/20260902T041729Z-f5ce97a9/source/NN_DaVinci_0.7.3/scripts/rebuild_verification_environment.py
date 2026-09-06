#!/usr/bin/env python3
"""Rebuild an isolated verification venv from the exact platform lock."""

from __future__ import annotations

import argparse
import email
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import venv
import zipfile

from packaging.tags import sys_tags
from packaging.utils import canonicalize_name


LOCAL_FALLBACK_ALLOWLIST = frozenset({"torchcam"})


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def read_lock(path: Path) -> dict[str, str]:
    locked: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "==" not in line or any(marker in line for marker in (";", " @ ")):
            raise ValueError(f"verification lock is not an exact platform pin: {line!r}")
        name, version = line.split("==", 1)
        key = canonicalize_name(name)
        if key in locked:
            raise ValueError(f"duplicate locked distribution: {name}")
        locked[key] = version
    return locked


def wheel_identity(path: Path) -> tuple[str, str]:
    with zipfile.ZipFile(path) as archive:
        metadata_names = [
            name for name in archive.namelist()
            if name.endswith(".dist-info/METADATA") and name.count("/") == 1
        ]
        if len(metadata_names) != 1:
            raise ValueError(f"wheel has {len(metadata_names)} METADATA files: {path.name}")
        metadata = email.message_from_bytes(archive.read(metadata_names[0]))
    return canonicalize_name(metadata["Name"]), metadata["Version"]


def compatible_tag(distribution: importlib.metadata.Distribution) -> str:
    wheel_text = distribution.read_text("WHEEL") or ""
    wheel = email.message_from_string(wheel_text)
    available = wheel.get_all("Tag") or []
    supported = {str(tag) for tag in sys_tags()}
    for tag in available:
        if tag in supported:
            return tag
    if available:
        return available[0]
    raise ValueError(f"installed distribution {distribution.metadata['Name']} has no WHEEL tag")


def reconstruct_installed_wheel(name: str, version: str, destination: Path) -> Path:
    """Build a wheel image from an installed distribution's RECORD.

    This fallback is explicit in evidence; it is used only when the exact
    platform wheel is unavailable from the configured index.
    """
    distribution = importlib.metadata.distribution(name)
    if distribution.version != version:
        raise ValueError(f"installed fallback {name}=={distribution.version}, lock requires {version}")
    root = Path(distribution.locate_file("")).resolve()
    tag = compatible_tag(distribution)
    wheel_name = re.sub(r"[-_.]+", "_", distribution.metadata["Name"])
    safe_version = re.sub(r"[-]+", "_", version)
    target = destination / f"{wheel_name}-{safe_version}-{tag}.whl"
    files = []
    for item in distribution.files or ():
        source = Path(distribution.locate_file(item)).resolve()
        if source.is_file() and source.is_relative_to(root):
            files.append((source.relative_to(root).as_posix(), source))
    if not files:
        raise ValueError(f"installed distribution {name} has no reconstructable files")
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for relative, source in sorted(files):
            archive.write(source, relative)
    return target


def run(command: list[str], *, environment: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, env=environment)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project-wheel", type=Path)
    parser.add_argument("--index-url", default="https://pypi.org/simple")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--smoke-module", action="append", dest="smoke_modules")
    args = parser.parse_args()
    lock = args.lock.resolve()
    locked = read_lock(lock)
    work = args.work_root.resolve()
    if work.exists():
        raise SystemExit(f"lock rebuild work root already exists: {work}")
    wheelhouse = work / "wheelhouse"
    environment_root = work / "venv"
    wheelhouse.mkdir(parents=True)
    download_log: list[dict[str, object]] = []
    pip_environment = {**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
    requested = [f"{name}=={version}" for name, version in sorted(locked.items())]
    index_requested = [
        f"{name}=={version}" for name, version in sorted(locked.items())
        if not re.search(r"(?:dev|local)", version, re.IGNORECASE)
    ]
    if not args.offline:
        command = [
            sys.executable, "-m", "pip", "download", "--only-binary=:all:", "--no-deps",
            "--dest", str(wheelhouse), "--index-url", args.index_url, *index_requested,
        ]
        result = run(command, environment=pip_environment)
        download_log.append({
            "source": "configured_index", "command": command, "exit_code": result.returncode,
            "stdout_tail": result.stdout[-4000:], "stderr_tail": result.stderr[-4000:],
        })

    available: dict[tuple[str, str], Path] = {}
    for path in wheelhouse.glob("*.whl"):
        try:
            available[wheel_identity(path)] = path
        except (OSError, ValueError, zipfile.BadZipFile):
            continue
    origins: dict[str, str] = {}
    missing_from_index: list[tuple[str, str]] = []
    for name, version in sorted(locked.items()):
        key = (name, version)
        if key not in available:
            missing_from_index.append(key)
            if name not in LOCAL_FALLBACK_ALLOWLIST:
                raise SystemExit(
                    f"exact wheel is unavailable from the configured index and no local fallback is allowed: {name}=={version}"
                )
            path = reconstruct_installed_wheel(name, version, wheelhouse)
            available[key] = path
            origins[path.name] = "allowlisted_torchcam_installed_distribution_record_fallback"
        else:
            origins[available[key].name] = "configured_index"
    extras = sorted(set(available) - {(name, version) for name, version in locked.items()})
    missing = sorted((name, version) for name, version in locked.items() if (name, version) not in available)
    if missing or extras:
        raise SystemExit(f"wheelhouse identity mismatch: missing={missing}, extras={extras}")

    venv.EnvBuilder(with_pip=True, clear=False, symlinks=False).create(environment_root)
    python = environment_root / "bin/python"
    install = run([
        str(python), "-m", "pip", "install", "--no-index", "--no-deps",
        "--find-links", str(wheelhouse), *requested,
    ], environment={**pip_environment, "PYTHONNOUSERSITE": "1", "PYTHONPATH": ""})
    project_install = None
    if install.returncode == 0 and args.project_wheel:
        project_install = run([
            str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(args.project_wheel.resolve()),
        ], environment={**pip_environment, "PYTHONNOUSERSITE": "1", "PYTHONPATH": ""})
    pip_check = run([str(python), "-m", "pip", "check"], environment={**pip_environment, "PYTHONNOUSERSITE": "1", "PYTHONPATH": ""})
    inventory_run = run([
        str(python), "-c",
        "import importlib.metadata as m,json; print(json.dumps({m.metadata(d)['Name'].lower().replace('_','-'):m.version(d) for d in [x.metadata['Name'] for x in m.distributions()]}))",
    ], environment={**pip_environment, "PYTHONNOUSERSITE": "1", "PYTHONPATH": ""})
    installed = json.loads(inventory_run.stdout) if inventory_run.returncode == 0 else {}
    lock_matches = all(installed.get(name) == version for name, version in locked.items())
    smoke_modules = args.smoke_modules or ["flask", "cairosvg", "pptx", "onnx", "torch", "tensorflow", "keras", "jax"]
    if args.project_wheel:
        smoke_modules.append("nn_davinci")
    smoke = run([
        str(python), "-c", "import importlib,sys; [importlib.import_module(n) for n in sys.argv[1:]]", *smoke_modules,
    ], environment={**pip_environment, "PYTHONNOUSERSITE": "1", "PYTHONPATH": "", "JAX_PLATFORMS": "cpu", "CUDA_VISIBLE_DEVICES": ""})
    wheels = []
    hashes = {}
    for path in sorted(wheelhouse.glob("*.whl")):
        name, version = wheel_identity(path)
        value = digest(path)
        hashes[path.name] = value
        wheels.append({
            "name": name, "version": version, "filename": path.name,
            "sha256": value, "bytes": path.stat().st_size, "origin": origins[path.name],
        })
    passed = all((
        install.returncode == 0,
        project_install is None or project_install.returncode == 0,
        pip_check.returncode == 0,
        inventory_run.returncode == 0,
        lock_matches,
        smoke.returncode == 0,
        len(wheels) == len(locked),
    ))
    report = {
        "schema_version": "0.2.3-verification-lock-rebuild-1",
        "python": platform.python_version(), "platform": platform.platform(),
        "index_url": args.index_url, "offline_requested": args.offline,
        "lock_sha256": digest(lock), "locked_distributions": len(locked),
        "independent_environment": environment_root.is_dir() and not (environment_root / "pyvenv.cfg").read_text().lower().find("include-system-site-packages = true") >= 0,
        "environment_retained": False,
        "wheel_hashes": hashes, "wheels": wheels,
        "local_fallback_allowlist": sorted(LOCAL_FALLBACK_ALLOWLIST),
        "missing_from_configured_index": [f"{name}=={version}" for name, version in missing_from_index],
        "wheel_origin_counts": {
            origin: sum(item["origin"] == origin for item in wheels)
            for origin in sorted(set(origins.values()))
        },
        "download_attempts": download_log,
        "install_exit_code": install.returncode,
        "project_install_exit_code": None if project_install is None else project_install.returncode,
        "pip_check_exit_code": pip_check.returncode, "pip_check_passed": pip_check.returncode == 0,
        "pip_check_output": (pip_check.stdout + pip_check.stderr)[-4000:],
        "lock_matches": lock_matches, "installed_locked_versions": {name: installed.get(name) for name in sorted(locked)},
        "import_smoke_modules": smoke_modules, "import_smoke_exit_code": smoke.returncode,
        "import_smoke_passed": smoke.returncode == 0,
        "import_smoke_output": (smoke.stdout + smoke.stderr)[-8000:],
        "failures": [] if passed else [
            f"install={install.returncode}", f"project_install={None if project_install is None else project_install.returncode}",
            f"pip_check={pip_check.returncode}", f"inventory={inventory_run.returncode}",
            f"lock_matches={lock_matches}", f"smoke={smoke.returncode}", f"wheels={len(wheels)}/{len(locked)}",
        ],
        "passed": passed,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"passed": passed, "locked": len(locked), "wheels": len(wheels), "wheel_origin_counts": report["wheel_origin_counts"]}, sort_keys=True))
    if not passed:
        raise SystemExit("verification lock environment rebuild failed: " + "; ".join(report["failures"]))


if __name__ == "__main__":
    main()
