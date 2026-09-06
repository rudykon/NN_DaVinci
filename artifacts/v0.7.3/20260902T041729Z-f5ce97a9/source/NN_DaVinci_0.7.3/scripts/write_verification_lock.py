#!/usr/bin/env python3
"""Generate/check the Linux x86_64 CPython 3.13 verification dependency closure."""

from __future__ import annotations

import argparse
from importlib import metadata
import json
import platform
from pathlib import Path

from packaging.requirements import Requirement


ROOT = Path(__file__).parents[1]
LOCK = ROOT / "requirements/verification-linux-x86_64-py313-0.2.3.lock"
META = ROOT / "verification/verification-lock-metadata-0.2.3.json"
ROOT_REQUIREMENTS = {
    "Flask", "CairoSVG", "python-pptx", "onnx", "torch", "torchvision", "tensorflow", "keras", "jax",
    "torchlens", "torchcam", "numpy", "PyYAML", "pillow", "setuptools", "pip", "build", "coverage", "mypy", "ruff",
}

# The workspace environment was originally created without expanding the
# extras on torch's ``cuda-toolkit[...]`` requirement.  The PyPI resolver pins
# below were independently resolved for Linux x86_64 on 2026-08-26.  Keeping
# them explicit lets ``--check`` detect lock drift even when the workstation
# happens to provide CUDA libraries outside the Python environment.
PINNED_TRANSITIVE_OVERRIDES = {
    "nvidia-cuda-cupti": "13.0.85",
    "nvidia-cuda-runtime": "13.0.96",
    "nvidia-cufft": "12.0.0.61",
    "nvidia-cufile": "1.15.1.6",
    "nvidia-curand": "10.4.0.35",
    "nvidia-cusolver": "12.0.4.66",
    "nvidia-cusparse": "12.6.3.3",
    "nvidia-nvjitlink": "13.3.33",
    "nvidia-nvtx": "13.0.85",
}


def closure() -> dict[str, str]:
    pending = [(name, frozenset()) for name in ROOT_REQUIREMENTS]
    resolved: dict[str, str] = {}
    processed: set[tuple[str, frozenset[str]]] = set()
    while pending:
        requested, requested_extras = pending.pop()
        requested_key = requested.lower().replace("_", "-")
        state = (requested_key, requested_extras)
        if state in processed:
            continue
        processed.add(state)
        try:
            distribution = metadata.distribution(requested)
        except metadata.PackageNotFoundError as exc:
            if requested_key not in PINNED_TRANSITIVE_OVERRIDES:
                raise SystemExit(f"verification dependency is absent: {requested}") from exc
            resolved[requested_key] = PINNED_TRANSITIVE_OVERRIDES[requested_key]
            continue
        canonical = distribution.metadata["Name"]
        key = canonical.lower().replace("_", "-")
        expected_version = PINNED_TRANSITIVE_OVERRIDES.get(key, distribution.version)
        if key in resolved and resolved[key] != expected_version:
            raise SystemExit(f"conflicting verification dependency versions for {key}")
        resolved[key] = expected_version
        for expression in distribution.requires or []:
            requirement = Requirement(expression)
            active = requirement.marker is None or requirement.marker.evaluate({"extra": ""})
            active = active or any(requirement.marker and requirement.marker.evaluate({"extra": extra}) for extra in requested_extras)
            if active:
                pending.append((requirement.name, frozenset(requirement.extras)))
    return dict(sorted(resolved.items()))


def documents() -> tuple[str, str]:
    packages = closure()
    header = [
        "# NN_DaVinci 0.2.3 authoritative verification lock",
        f"# Python: {platform.python_version()} (CPython 3.13)",
        f"# Platform: {platform.system()} {platform.machine()}",
        "# Index source: installed workspace verification environment; rebuild index https://pypi.org/simple",
        "# Scope: exact transitive closure of the declared verification roots on this platform only.",
    ]
    lock = "\n".join([*header, *(f"{name}=={version}" for name, version in packages.items())]) + "\n"
    metadata_document = {
        "schema_version": "0.2.3-platform-lock-1",
        "python": platform.python_version(), "implementation": platform.python_implementation(),
        "platform": platform.platform(), "machine": platform.machine(),
        "index_source": "https://pypi.org/simple", "universal_across_operating_systems": False,
        "resolver_note": "CUDA toolkit extras expanded; absent workstation packages use the pinned PyPI Linux resolver result dated 2026-08-26",
        "pinned_transitive_overrides": PINNED_TRANSITIVE_OVERRIDES,
        "root_requirements": sorted(ROOT_REQUIREMENTS, key=str.lower),
        "packages": [
            {"name": name, "version": version, "wheel_sha256": None, "wheel_status": "installed distribution has no retained wheel file; generated project wheel is hashed in packaging evidence"}
            for name, version in packages.items()
        ],
    }
    return lock, json.dumps(metadata_document, indent=2, sort_keys=True) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    lock, meta = documents()
    if args.write:
        LOCK.write_text(lock, encoding="utf-8")
        META.write_text(meta, encoding="utf-8")
    elif not LOCK.is_file() or not META.is_file() or LOCK.read_text(encoding="utf-8") != lock or META.read_text(encoding="utf-8") != meta:
        raise SystemExit("verification platform lock differs from the executing environment")
    print(json.dumps({"packages": len(closure()), "lock": str(LOCK), "matched": LOCK.is_file() and LOCK.read_text(encoding="utf-8") == lock}, sort_keys=True))


if __name__ == "__main__":
    main()
