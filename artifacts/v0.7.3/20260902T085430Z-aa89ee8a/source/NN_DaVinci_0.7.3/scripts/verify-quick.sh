#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE_DIR="$(cd "$PROJECT_DIR/.." && pwd)"
PYTHON_BIN="${NN_DAVINCI_PYTHON:-$WORKSPACE_DIR/envs/python-tools/bin/python}"
DEVTOOLS_DIR="${NN_DAVINCI_DEVTOOLS:-$PROJECT_DIR/.devtools}"
STARTED="$(date +%s)"
SUCCESS=0
OWN_RUN=0
if [[ -n "${NNDV_QUICK_RUN_DIR:-}" ]]; then
  RUN_DIR="$NNDV_QUICK_RUN_DIR"
  mkdir -p "$RUN_DIR"
else
  RUN_DIR="$(mktemp -d "${TMPDIR:-/tmp}/nndv-quick-XXXXXX")"
  OWN_RUN=1
fi

finish() {
  status=$?
  if [[ "$OWN_RUN" -eq 1 && "$SUCCESS" -eq 1 && "$status" -eq 0 && "${NNDV_KEEP_DIAGNOSTICS:-0}" != "1" ]]; then
    "$PYTHON_BIN" -c 'import shutil,sys; shutil.rmtree(sys.argv[1])' "$RUN_DIR"
  elif [[ "$status" -ne 0 || "${NNDV_KEEP_DIAGNOSTICS:-0}" == "1" ]]; then
    echo "Quick verification diagnostics: $RUN_DIR" >&2
  fi
}
trap finish EXIT

export PYTHONPATH="$PROJECT_DIR:$PROJECT_DIR/src:$DEVTOOLS_DIR${PYTHONPATH:+:$PYTHONPATH}"
export MPLCONFIGDIR="$RUN_DIR/matplotlib"
export MYPY_CACHE_DIR="$RUN_DIR/mypy-cache"
export RUFF_CACHE_DIR="$RUN_DIR/ruff-cache"
export COVERAGE_FILE="$RUN_DIR/.coverage"
export NNDV_TASK_ROOT="$RUN_DIR/task-runtime"
export KERAS_BACKEND="${KERAS_BACKEND:-tensorflow}"
export TF_CPP_MIN_LOG_LEVEL="${TF_CPP_MIN_LOG_LEVEL:-3}"
export JAX_PLATFORMS="${JAX_PLATFORMS:-cpu}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-}"
mkdir -p "$MPLCONFIGDIR" "$MYPY_CACHE_DIR" "$RUFF_CACHE_DIR"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python environment not found: $PYTHON_BIN" >&2
  exit 1
fi
if [[ ! -d "$DEVTOOLS_DIR/coverage" || ! -x "$PROJECT_DIR/node_modules/.bin/eslint" ]]; then
  echo "Workspace verification dependencies are missing (.devtools and/or node_modules). See README.md." >&2
  exit 1
fi

cd "$PROJECT_DIR"
EXPECTED_ANCHOR_SHA256="10979b1d7112b7639207405dffe23f534762a02fb047b61540c5e04c955a3224"
"$PYTHON_BIN" scripts/verify_trust_anchor.py \
  --trust-anchor docs/TRUST_ANCHOR_0.2.2.json \
  --expected-anchor-sha256 "$EXPECTED_ANCHOR_SHA256" \
  --project-root "$PROJECT_DIR" --output "$RUN_DIR/trust-anchor-check.json"
"$PYTHON_BIN" scripts/generate_acceptance_matrix_0_2_3.py
"$PYTHON_BIN" scripts/write_verification_lock.py
node --check src/nn_davinci/web/app.js
npm run lint
npm run format:check
"$PYTHON_BIN" -m compileall -q src tests scripts
"$PYTHON_BIN" -m ruff check src tests scripts
"$PYTHON_BIN" -m mypy src/nn_davinci/ir.py src/nn_davinci/layout src/nn_davinci/render src/nn_davinci/project.py src/nn_davinci/quality.py src/nn_davinci/server.py src/nn_davinci/labels.py src/nn_davinci/scaling.py src/nn_davinci/verification.py src/nn_davinci/semantic.py src/nn_davinci/viewport.py src/nn_davinci/tasks.py src/nn_davinci/import_wizard.py src/nn_davinci/optimizer.py src/nn_davinci/api.py src/nn_davinci/cli.py src/nn_davinci/real_models.py src/nn_davinci/composer.py src/nn_davinci/paper_production.py src/nn_davinci/diff_corpus.py src/nn_davinci/plugins.py src/nn_davinci/trial.py src/nn_davinci/trial_models.py

"$PYTHON_BIN" -m coverage erase
"$PYTHON_BIN" -m coverage run --branch --source=nn_davinci scripts/run_tests.py --json "$RUN_DIR/python-tests.json" --test-ids "$RUN_DIR/collected-test-ids.txt"
CORE_INCLUDE='src/nn_davinci/ir.py,src/nn_davinci/layout/__init__.py,src/nn_davinci/layout/engine.py,src/nn_davinci/project.py,src/nn_davinci/quality.py,src/nn_davinci/render/__init__.py,src/nn_davinci/render/export.py,src/nn_davinci/render/html.py,src/nn_davinci/render/svg.py,src/nn_davinci/render/tikz.py,src/nn_davinci/server.py'
EXPANDED_CORE_INCLUDE="$CORE_INCLUDE,src/nn_davinci/labels.py,src/nn_davinci/scaling.py,src/nn_davinci/verification.py"
"$PYTHON_BIN" -m coverage json --include="$CORE_INCLUDE" -o "$RUN_DIR/core-coverage.json"
"$PYTHON_BIN" -m coverage json --include="$EXPANDED_CORE_INCLUDE" -o "$RUN_DIR/expanded-core-coverage.json"
"$PYTHON_BIN" -m coverage json -o "$RUN_DIR/all-package-coverage.json"
"$PYTHON_BIN" scripts/summarize_coverage.py --core "$RUN_DIR/core-coverage.json" --expanded-core "$RUN_DIR/expanded-core-coverage.json" --all-package "$RUN_DIR/all-package-coverage.json" --tests "$RUN_DIR/python-tests.json" --output "$RUN_DIR/coverage-summary.json"
"$PYTHON_BIN" -m nn_davinci validate examples/resnet.json

"$PYTHON_BIN" - "$RUN_DIR" "$STARTED" <<'PY'
import hashlib
import json
import pathlib
import sys
import time

root = pathlib.Path(sys.argv[1])
tests = json.loads((root / "python-tests.json").read_text(encoding="utf-8"))
coverage = json.loads((root / "coverage-summary.json").read_text(encoding="utf-8"))
ids_hash = hashlib.sha256((root / "collected-test-ids.txt").read_bytes()).hexdigest()
elapsed = time.time() - int(sys.argv[2])
summary = {
    "checks": 12, "python_tests": tests["passed"],
    "collected": tests["collected"], "passed": tests["passed"],
    "failed": tests["failures"], "errors": tests["errors"],
    "skipped": tests["skipped"], "deselected": tests["deselected"],
    "baseline_python_tests": tests["baseline_count"],
    "collected_test_ids_sha256": ids_hash,
    "artifact_assertions": 0, "font_tikz_checks": 0,
    "packaging_checks": 0, "e2e_scenarios": 0,
    "coverage": {"old_core": coverage["old_core"], "expanded_core": coverage["expanded_core"], "all_package": coverage["all_package"]},
    "elapsed_seconds": round(elapsed, 3),
}
(root / "quick-verification.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print("NNDV_QUICK_RESULT " + json.dumps(summary, separators=(",", ":"), sort_keys=True))
PY

SUCCESS=1
