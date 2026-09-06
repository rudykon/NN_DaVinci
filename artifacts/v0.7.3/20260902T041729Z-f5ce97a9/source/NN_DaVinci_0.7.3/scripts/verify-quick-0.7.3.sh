#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE_DIR="$(cd "$PROJECT_DIR/.." && pwd)"
PYTHON_BIN="${NN_DAVINCI_PYTHON:-$WORKSPACE_DIR/envs/python-tools/bin/python}"
PARENT_TEST_IDS="${NNDV_PARENT_072_TEST_IDS:-$WORKSPACE_DIR/NN_DaVinci_0.7.2_Dev/artifacts/v0.7.2/20260901T142604Z-010606e8/reports/quick/collected-test-ids.txt}"
OWN_RUN=0
SUCCESS=0
if [[ -n "${NNDV_QUICK_RUN_DIR:-}" ]]; then
  RUN_DIR="$NNDV_QUICK_RUN_DIR"
  mkdir -p "$RUN_DIR"
else
  RUN_DIR="$(mktemp -d "${TMPDIR:-/tmp}/nndv-073-quick-XXXXXX")"
  OWN_RUN=1
fi
STARTED="$(date +%s)"

finish() {
  status=$?
  if [[ "$OWN_RUN" -eq 1 && "$SUCCESS" -eq 1 && "$status" -eq 0 && "${NNDV_KEEP_DIAGNOSTICS:-0}" != "1" ]]; then
    "$PYTHON_BIN" -c 'import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)' "$RUN_DIR"
  else
    echo "0.7.3 quick verification diagnostics: $RUN_DIR" >&2
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
if [[ ! -f "$PARENT_TEST_IDS" ]]; then
  echo "pinned 0.7.2 test-ID baseline not found: $PARENT_TEST_IDS" >&2
  exit 1
fi
if [[ ! -x "$PROJECT_DIR/node_modules/.bin/eslint" ]]; then
  echo "node_modules is missing; run npm ci --offline --ignore-scripts" >&2
  exit 1
fi

cd "$PROJECT_DIR"
"$PYTHON_BIN" - "$PARENT_TEST_IDS" <<'PY'
import hashlib
import json
from pathlib import Path
import sys
import tomllib
import nn_davinci

root = Path.cwd()
assert nn_davinci.__version__ == "0.7.3"
assert tomllib.loads((root / "pyproject.toml").read_text())['project']['version'] == "0.7.3"
assert json.loads((root / "package.json").read_text())['version'] == "0.7.3"
lock = json.loads((root / "package-lock.json").read_text())
assert lock['version'] == lock['packages']['']['version'] == "0.7.3"
baseline = Path(sys.argv[1])
ids = baseline.read_text(encoding="utf-8").splitlines()
assert len(ids) == len(set(ids)) == 353
assert hashlib.sha256(baseline.read_bytes()).hexdigest() == "934f1c14e1dc3e31d9a314d7f05fd2d0eab2afb54106f72f3f4b9a1b28bd331b"
for path in (root / "schemas").glob("*.json"):
    json.loads(path.read_text(encoding="utf-8"))
print("0.7.3 version and exact 353-test parent identity PASS")
PY

for source in src/nn_davinci/web/*.js tests/e2e/*.mjs scripts/*.mjs; do
  node --check "$source"
done
npm run lint
"$PROJECT_DIR/node_modules/.bin/prettier" --check \
  src/nn_davinci/web/*.js src/nn_davinci/web/*.css tests/e2e/*.mjs \
  scripts/semantic_svg_dom_oracle_0_7_3.mjs
"$PYTHON_BIN" -m compileall -q src tests scripts
"$PYTHON_BIN" -m ruff check src tests scripts
"$PYTHON_BIN" -m mypy \
  src/nn_davinci/architecture_evidence.py src/nn_davinci/architecture_role_graph.py \
  src/nn_davinci/architecture_parity.py src/nn_davinci/metamorphic_corpus.py \
  src/nn_davinci/scene_math.py src/nn_davinci/scene_ir.py src/nn_davinci/model_scene.py \
  src/nn_davinci/scene_projection.py src/nn_davinci/scene_export.py src/nn_davinci/scene_gltf.py \
  src/nn_davinci/pdf_fonts.py src/nn_davinci/project.py src/nn_davinci/api.py \
  src/nn_davinci/server.py src/nn_davinci/cli.py

"$PYTHON_BIN" -m coverage erase
"$PYTHON_BIN" -m coverage run --branch --source=nn_davinci \
  scripts/run_tests.py --json "$RUN_DIR/python-tests.json" \
  --test-ids "$RUN_DIR/collected-test-ids.txt" --baseline-ids "$PARENT_TEST_IDS"
CORE_INCLUDE='src/nn_davinci/ir.py,src/nn_davinci/layout/__init__.py,src/nn_davinci/layout/engine.py,src/nn_davinci/project.py,src/nn_davinci/quality.py,src/nn_davinci/render/__init__.py,src/nn_davinci/render/export.py,src/nn_davinci/render/html.py,src/nn_davinci/render/svg.py,src/nn_davinci/render/tikz.py,src/nn_davinci/server.py'
EXPANDED_CORE_INCLUDE="$CORE_INCLUDE,src/nn_davinci/labels.py,src/nn_davinci/scaling.py,src/nn_davinci/verification.py"
SCENE_CORE_INCLUDE='src/nn_davinci/scene_math.py,src/nn_davinci/scene_ir.py,src/nn_davinci/model_scene.py,src/nn_davinci/scene_projection.py,src/nn_davinci/scene_export.py,src/nn_davinci/scene_gltf.py'
"$PYTHON_BIN" -m coverage json --include="$CORE_INCLUDE" -o "$RUN_DIR/core-coverage.json"
"$PYTHON_BIN" -m coverage json --include="$EXPANDED_CORE_INCLUDE" -o "$RUN_DIR/expanded-core-coverage.json"
"$PYTHON_BIN" -m coverage json --include="$SCENE_CORE_INCLUDE" -o "$RUN_DIR/scene-core-coverage.json"
"$PYTHON_BIN" -m coverage json -o "$RUN_DIR/all-package-coverage.json"
"$PYTHON_BIN" scripts/summarize_coverage.py \
  --core "$RUN_DIR/core-coverage.json" --expanded-core "$RUN_DIR/expanded-core-coverage.json" \
  --all-package "$RUN_DIR/all-package-coverage.json" --tests "$RUN_DIR/python-tests.json" \
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
floors = {"old_core": 89.21644685802949, "expanded_core": 89.42815953868333, "scene_core": 82.77905198776759, "all_package": 84.86438488860188}
observed = {
    "old_core": coverage["old_core"]["combined"]["percent"],
    "expanded_core": coverage["expanded_core"]["combined"]["percent"],
    "scene_core": scene["percent_covered"],
    "all_package": coverage["all_package"]["combined"]["percent"],
}
failures = []
if tests.get("baseline_count") != 353 or tests.get("baseline_ids_missing"):
    failures.append("one or more exact 0.7.2 test IDs are missing")
if not (tests.get("collected", 0) >= 353 and tests.get("passed") == tests.get("collected") and all(tests.get(name) == 0 for name in ("failures", "errors", "skipped", "deselected"))):
    failures.append("Python test accounting is not an exact all-pass")
for name, floor in floors.items():
    if observed[name] + 1e-12 < floor:
        failures.append(f"{name} coverage regressed: {observed[name]:.12f}% < {floor:.12f}%")
if failures:
    raise SystemExit("0.7.3 quick verification failed:\n- " + "\n- ".join(failures))
summary = {
    "schema_version": "nndv-0.7.3-quick-verification-1",
    "release": "0.7.3 — Reader-Visible Scientific Completeness & Generalization Hotfix",
    "status": "PASS",
    "parent_0_7_2": {"test_count": 353, "test_ids_sha256": "934f1c14e1dc3e31d9a314d7f05fd2d0eab2afb54106f72f3f4b9a1b28bd331b"},
    "python": {
        "collected": tests["collected"], "passed": tests["passed"], "failed": tests["failures"],
        "errors": tests["errors"], "skipped": tests["skipped"], "deselected": tests["deselected"],
        "inherited_0_7_2_tests": 353, "new_0_7_3_tests": tests["collected"] - 353,
        "baseline_0_7_2_missing": tests["baseline_ids_missing"],
        "test_ids_sha256": hashlib.sha256((root / "collected-test-ids.txt").read_bytes()).hexdigest(),
        "duration_seconds": tests["duration_seconds"],
    },
    "coverage": {"observed_percent": observed, "authoritative_parent_0_7_2_floors_percent": floors, "no_regression_from_0_7_2": True},
    "elapsed_seconds": round(time.time() - int(sys.argv[2]), 3),
}
(root / "quick-verification.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print("NNDV_073_QUICK_RESULT=" + json.dumps(summary, sort_keys=True))
PY

SUCCESS=1
