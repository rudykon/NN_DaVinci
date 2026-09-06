#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE_DIR="$(cd "$PROJECT_DIR/.." && pwd)"
PYTHON_BIN="${NN_DAVINCI_PYTHON:-$WORKSPACE_DIR/envs/python-tools/bin/python}"
OWN_RUN=0
SUCCESS=0
if [[ -n "${NNDV_QUICK_RUN_DIR:-}" ]]; then
  RUN_DIR="$NNDV_QUICK_RUN_DIR"
  mkdir -p "$RUN_DIR"
else
  RUN_DIR="$(mktemp -d "${TMPDIR:-/tmp}/nndv-070-quick-XXXXXX")"
  OWN_RUN=1
fi
STARTED="$(date +%s)"

finish() {
  status=$?
  if [[ "$OWN_RUN" -eq 1 && "$SUCCESS" -eq 1 && "$status" -eq 0 && "${NNDV_KEEP_DIAGNOSTICS:-0}" != "1" ]]; then
    "$PYTHON_BIN" -c 'import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)' "$RUN_DIR"
  else
    echo "0.7.0 quick verification diagnostics: $RUN_DIR" >&2
  fi
}
trap finish EXIT

export PYTHONPATH="$PROJECT_DIR:$PROJECT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX="$RUN_DIR/pycache"
export MPLCONFIGDIR="$RUN_DIR/matplotlib"
export MYPY_CACHE_DIR="$RUN_DIR/mypy-cache"
export RUFF_CACHE_DIR="$RUN_DIR/ruff-cache"
export COVERAGE_FILE="$RUN_DIR/.coverage"
export NNDV_TASK_ROOT="$RUN_DIR/task-runtime"
export KERAS_BACKEND="${KERAS_BACKEND:-tensorflow}"
export TF_CPP_MIN_LOG_LEVEL="${TF_CPP_MIN_LOG_LEVEL:-3}"
export JAX_PLATFORMS="${JAX_PLATFORMS:-cpu}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-}"
mkdir -p "$MPLCONFIGDIR" "$MYPY_CACHE_DIR" "$RUFF_CACHE_DIR" "$NNDV_TASK_ROOT"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python environment not found: $PYTHON_BIN" >&2
  exit 1
fi
if [[ ! -x "$PROJECT_DIR/node_modules/.bin/eslint" ]]; then
  echo "node_modules is missing; run npm ci --offline --ignore-scripts" >&2
  exit 1
fi

cd "$PROJECT_DIR"
"$PYTHON_BIN" - <<'PY'
import hashlib
import json
from pathlib import Path
import tomllib
import nn_davinci
from nn_davinci.project import PROJECT_VERSION
from nn_davinci.scene_ir import SCENE_IR_VERSION

root = Path.cwd()
assert nn_davinci.__version__ == "0.7.0"
assert tomllib.loads((root / "pyproject.toml").read_text())['project']['version'] == "0.7.0"
assert json.loads((root / "package.json").read_text())['version'] == "0.7.0"
lock = json.loads((root / "package-lock.json").read_text())
assert lock['version'] == lock['packages']['']['version'] == "0.7.0"
assert PROJECT_VERSION == "1.4"
assert SCENE_IR_VERSION == "1.0"
for path in (root / "schemas").glob("*.json"):
    json.loads(path.read_text(encoding="utf-8"))
for required in (
    "schemas/figure-ir-1.0.schema.json",
    "schemas/scene-ir-1.0.schema.json",
    "schemas/project-1.4.schema.json",
):
    assert (root / required).is_file(), required
baseline_path = root / "verification/fixtures/python-test-ids-0.6.1.txt"
baseline = baseline_path.read_text(encoding="utf-8").splitlines()
assert len(baseline) == len(set(baseline)) == 246
assert hashlib.sha256(baseline_path.read_bytes()).hexdigest() == "62f9f1f1c1bf04ec44fac6688b4c7ac3e58127314b40e1e1e3fb790211be412d"
print("0.7.0 version / Project 1.4 / Scene IR 1.0 / 246-test baseline identity PASS")
PY

for source in src/nn_davinci/web/*.js tests/e2e/*.mjs; do
  node --check "$source"
done
npm run lint
"$PROJECT_DIR/node_modules/.bin/prettier" --check \
  src/nn_davinci/web/*.js src/nn_davinci/web/*.css tests/e2e/*.mjs
"$PYTHON_BIN" -m compileall -q src tests scripts
"$PYTHON_BIN" -m ruff check src tests scripts
"$PYTHON_BIN" -m mypy \
  src/nn_davinci/scene_math.py src/nn_davinci/scene_ir.py \
  src/nn_davinci/model_scene.py src/nn_davinci/scene_projection.py \
  src/nn_davinci/scene_export.py src/nn_davinci/scene_gltf.py \
  src/nn_davinci/project.py src/nn_davinci/api.py src/nn_davinci/server.py src/nn_davinci/cli.py

"$PYTHON_BIN" -m coverage erase
"$PYTHON_BIN" -m coverage run --branch --source=nn_davinci \
  scripts/run_tests.py --json "$RUN_DIR/python-tests.json" \
  --test-ids "$RUN_DIR/collected-test-ids.txt" \
  --baseline-ids verification/fixtures/python-test-ids-0.6.1.txt
CORE_INCLUDE='src/nn_davinci/ir.py,src/nn_davinci/layout/__init__.py,src/nn_davinci/layout/engine.py,src/nn_davinci/project.py,src/nn_davinci/quality.py,src/nn_davinci/render/__init__.py,src/nn_davinci/render/export.py,src/nn_davinci/render/html.py,src/nn_davinci/render/svg.py,src/nn_davinci/render/tikz.py,src/nn_davinci/server.py'
EXPANDED_CORE_INCLUDE="$CORE_INCLUDE,src/nn_davinci/labels.py,src/nn_davinci/scaling.py,src/nn_davinci/verification.py"
SCENE_CORE_INCLUDE='src/nn_davinci/scene_math.py,src/nn_davinci/scene_ir.py,src/nn_davinci/model_scene.py,src/nn_davinci/scene_projection.py,src/nn_davinci/scene_export.py,src/nn_davinci/scene_gltf.py'
"$PYTHON_BIN" -m coverage json --include="$CORE_INCLUDE" -o "$RUN_DIR/core-coverage.json"
"$PYTHON_BIN" -m coverage json --include="$EXPANDED_CORE_INCLUDE" -o "$RUN_DIR/expanded-core-coverage.json"
"$PYTHON_BIN" -m coverage json --include="$SCENE_CORE_INCLUDE" -o "$RUN_DIR/scene-core-coverage.json"
"$PYTHON_BIN" -m coverage json -o "$RUN_DIR/all-package-coverage.json"
"$PYTHON_BIN" scripts/summarize_coverage.py \
  --core "$RUN_DIR/core-coverage.json" \
  --expanded-core "$RUN_DIR/expanded-core-coverage.json" \
  --all-package "$RUN_DIR/all-package-coverage.json" \
  --tests "$RUN_DIR/python-tests.json" \
  --output "$RUN_DIR/coverage-summary.json"
"$PYTHON_BIN" -m nn_davinci validate examples/resnet.json

"$PYTHON_BIN" - "$RUN_DIR" "$STARTED" <<'PY'
import hashlib
import json
from pathlib import Path
import sys
import time

root = Path(sys.argv[1])
tests = json.loads((root / "python-tests.json").read_text())
coverage = json.loads((root / "coverage-summary.json").read_text())
scene = json.loads((root / "scene-core-coverage.json").read_text())["totals"]
baseline_count = 246
failures = []
if tests.get("baseline_count") != baseline_count or tests.get("baseline_ids_missing"):
    failures.append("one or more authoritative 0.6.1 Python test IDs are missing")
if not (
    tests.get("collected", 0) >= baseline_count
    and tests.get("passed") == tests.get("collected")
    and tests.get("failures") == 0
    and tests.get("errors") == 0
    and tests.get("skipped") == 0
    and tests.get("deselected") == 0
):
    failures.append("Python accounting is not an exact all-pass with zero skips/deselections")
for name in ("old_core_passed", "expanded_core_passed", "all_package_passed"):
    if coverage.get(name) is not True:
        failures.append(f"retained coverage gate failed: {name}")
if scene.get("num_statements", 0) <= 0 or scene.get("percent_covered", 0.0) < 80.0:
    failures.append("Scene core line/branch combined coverage is below 80%")
if failures:
    raise SystemExit("0.7.0 quick verification failed:\n- " + "\n- ".join(failures))
summary = {
    "schema_version": "nndv-0.7.0-quick-verification-1",
    "release": "0.7.0 Beta — 3D Neural Figure & UX Completion",
    "status": "PASS",
    "python": {
        "collected": tests["collected"],
        "passed": tests["passed"],
        "failed": tests["failures"],
        "errors": tests["errors"],
        "skipped": tests["skipped"],
        "deselected": tests["deselected"],
        "inherited_0_6_1_tests": baseline_count,
        "new_0_7_0_tests": tests["collected"] - baseline_count,
        "baseline_0_6_1_missing": tests["baseline_ids_missing"],
        "duration_seconds": tests["duration_seconds"],
        "test_ids_sha256": hashlib.sha256((root / "collected-test-ids.txt").read_bytes()).hexdigest(),
    },
    "coverage": {
        "old_core": coverage["old_core"],
        "expanded_core": coverage["expanded_core"],
        "scene_core": scene,
        "all_package": coverage["all_package"],
        "gates": {
            "old_core_passed": coverage["old_core_passed"],
            "expanded_core_passed": coverage["expanded_core_passed"],
            "all_package_passed": coverage["all_package_passed"],
            "scene_core_80_percent": True,
        },
    },
    "elapsed_seconds": round(time.time() - int(sys.argv[2]), 3),
}
(root / "quick-verification.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print("NNDV_070_QUICK_RESULT=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
PY

SUCCESS=1
