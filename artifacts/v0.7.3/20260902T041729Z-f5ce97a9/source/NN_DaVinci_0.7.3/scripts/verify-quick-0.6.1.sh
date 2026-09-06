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
  RUN_DIR="$(mktemp -d "${TMPDIR:-/tmp}/nndv-061-quick-XXXXXX")"
  OWN_RUN=1
fi
STARTED="$(date +%s)"

finish() {
  status=$?
  if [[ "$OWN_RUN" -eq 1 && "$SUCCESS" -eq 1 && "$status" -eq 0 && "${NNDV_KEEP_DIAGNOSTICS:-0}" != "1" ]]; then
    "$PYTHON_BIN" -c 'import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)' "$RUN_DIR"
  else
    echo "0.6.1 quick verification diagnostics: $RUN_DIR" >&2
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
import json
from pathlib import Path
import tomllib
import nn_davinci

root = Path.cwd()
assert nn_davinci.__version__ == "0.6.1"
assert tomllib.loads((root / "pyproject.toml").read_text())['project']['version'] == "0.6.1"
assert json.loads((root / "package.json").read_text())['version'] == "0.6.1"
lock = json.loads((root / "package-lock.json").read_text())
assert lock['version'] == lock['packages']['']['version'] == "0.6.1"
for path in (root / "schemas").glob("*.json"):
    json.loads(path.read_text(encoding="utf-8"))
baseline = (root / "verification/fixtures/python-test-ids-0.6.0.txt").read_text(encoding="utf-8").splitlines()
assert len(baseline) == len(set(baseline)) == 171
print("0.6.1 version/schema/171-test baseline identity PASS")
PY
node --check src/nn_davinci/web/app.js
npm run lint
npm run format:check
"$PYTHON_BIN" -m compileall -q src tests scripts
"$PYTHON_BIN" -m ruff check src tests scripts
"$PYTHON_BIN" -m mypy \
  src/nn_davinci/ir.py src/nn_davinci/layout src/nn_davinci/render \
  src/nn_davinci/project.py src/nn_davinci/quality.py src/nn_davinci/server.py \
  src/nn_davinci/labels.py src/nn_davinci/scaling.py src/nn_davinci/verification.py \
  src/nn_davinci/semantic.py src/nn_davinci/viewport.py src/nn_davinci/tasks.py \
  src/nn_davinci/import_wizard.py src/nn_davinci/optimizer.py src/nn_davinci/api.py \
  src/nn_davinci/cli.py src/nn_davinci/real_models.py src/nn_davinci/composer.py \
  src/nn_davinci/paper_production.py src/nn_davinci/diff_corpus.py \
  src/nn_davinci/plugins.py src/nn_davinci/trial.py src/nn_davinci/trial_models.py \
  src/nn_davinci/figure_ir.py src/nn_davinci/tensor_geometry.py \
  src/nn_davinci/figure_export.py src/nn_davinci/figure_templates.py \
  src/nn_davinci/structure_lens.py src/nn_davinci/units.py \
  src/nn_davinci/text_layout.py src/nn_davinci/formula.py \
  src/nn_davinci/model_figure.py

"$PYTHON_BIN" -m coverage erase
"$PYTHON_BIN" -m coverage run --branch --source=nn_davinci \
  scripts/run_tests.py --json "$RUN_DIR/python-tests.json" \
  --test-ids "$RUN_DIR/collected-test-ids.txt" \
  --baseline-ids verification/fixtures/python-test-ids-0.6.0.txt
CORE_INCLUDE='src/nn_davinci/ir.py,src/nn_davinci/layout/__init__.py,src/nn_davinci/layout/engine.py,src/nn_davinci/project.py,src/nn_davinci/quality.py,src/nn_davinci/render/__init__.py,src/nn_davinci/render/export.py,src/nn_davinci/render/html.py,src/nn_davinci/render/svg.py,src/nn_davinci/render/tikz.py,src/nn_davinci/server.py'
EXPANDED_CORE_INCLUDE="$CORE_INCLUDE,src/nn_davinci/labels.py,src/nn_davinci/scaling.py,src/nn_davinci/verification.py"
FIGURE_CORE_INCLUDE='src/nn_davinci/figure_ir.py,src/nn_davinci/tensor_geometry.py,src/nn_davinci/figure_export.py,src/nn_davinci/figure_templates.py,src/nn_davinci/structure_lens.py,src/nn_davinci/units.py,src/nn_davinci/text_layout.py,src/nn_davinci/formula.py,src/nn_davinci/model_figure.py'
"$PYTHON_BIN" -m coverage json --include="$CORE_INCLUDE" -o "$RUN_DIR/core-coverage.json"
"$PYTHON_BIN" -m coverage json --include="$EXPANDED_CORE_INCLUDE" -o "$RUN_DIR/expanded-core-coverage.json"
"$PYTHON_BIN" -m coverage json --include="$FIGURE_CORE_INCLUDE" -o "$RUN_DIR/figure-core-coverage.json"
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
figure = json.loads((root / "figure-core-coverage.json").read_text())["totals"]
baseline_count = 171
failures = []
if tests.get("baseline_count") != baseline_count or tests.get("baseline_ids_missing"):
    failures.append("one or more authoritative 0.6.0 Python test IDs are missing")
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
        failures.append(f"coverage gate failed: {name}")
if failures:
    raise SystemExit("0.6.1 quick verification failed:\n- " + "\n- ".join(failures))
summary = {
    "schema_version": "nndv-0.6.1-quick-verification-1",
    "release": "0.6.1 Beta — Publication Fidelity & Model-to-Figure Completion",
    "status": "PASS",
    "checks": 14,
    "python": {
        "collected": tests["collected"],
        "passed": tests["passed"],
        "failed": tests["failures"],
        "errors": tests["errors"],
        "skipped": tests["skipped"],
        "deselected": tests["deselected"],
        "inherited_0_6_0_tests": baseline_count,
        "new_0_6_1_tests": tests["collected"] - baseline_count,
        "baseline_0_6_0_missing": tests["baseline_ids_missing"],
        "duration_seconds": tests["duration_seconds"],
        "test_ids_sha256": hashlib.sha256((root / "collected-test-ids.txt").read_bytes()).hexdigest(),
    },
    "coverage": {
        "old_core": coverage["old_core"],
        "expanded_core": coverage["expanded_core"],
        "figure_core": figure,
        "all_package": coverage["all_package"],
        "gates": {
            "old_core_passed": coverage["old_core_passed"],
            "expanded_core_passed": coverage["expanded_core_passed"],
            "all_package_passed": coverage["all_package_passed"],
        },
    },
    "elapsed_seconds": round(time.time() - int(sys.argv[2]), 3),
}
(root / "quick-verification.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print("NNDV_061_QUICK_RESULT=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
PY

SUCCESS=1
