#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE_DIR="$(cd "$PROJECT_DIR/.." && pwd)"
PYTHON_BIN="${NN_DAVINCI_PYTHON:-$WORKSPACE_DIR/envs/python-tools/bin/python}"
ARTIFACT_ROOT="$PROJECT_DIR/artifacts/v0.6.0"
RUN_ID="${NNDV_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')}"
STARTED_EPOCH="$(date +%s)"
STARTED_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
CONTROL_DIR="$(mktemp -d "${TMPDIR:-/tmp}/nndv-060-full-${RUN_ID}-XXXXXX")"
SNAPSHOT_DIR="$CONTROL_DIR/clean-source/NN_DaVinci_0.6.0"
SOURCE_REPORT="$CONTROL_DIR/source-snapshot.json"
STAGING_DIR="$CONTROL_DIR/artifact-staging"
WORK_DIR="$CONTROL_DIR/work"
SUCCESS=0

finish() {
  status=$?
  if [[ "$SUCCESS" -eq 1 && "$status" -eq 0 && "${NNDV_KEEP_DIAGNOSTICS:-0}" != "1" ]]; then
    "$PYTHON_BIN" - "$CONTROL_DIR" <<'PY'
from pathlib import Path
import shutil
import sys

path = Path(sys.argv[1]).resolve()
temporary = Path("/tmp").resolve()
if path.parent != temporary or not path.name.startswith("nndv-060-full-") or path.is_symlink():
    raise SystemExit(f"refusing to clean unexpected full controller path: {path}")
shutil.rmtree(path)
PY
  else
    echo "0.6.0 full diagnostics retained: $CONTROL_DIR" >&2
  fi
}
trap finish EXIT

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python verification environment not found: $PYTHON_BIN" >&2
  exit 1
fi
if [[ -e "$ARTIFACT_ROOT/$RUN_ID" || -e "$ARTIFACT_ROOT/$RUN_ID.inventory-verification.json" ]]; then
  echo "refusing to overwrite v0.6.0 run: $RUN_ID" >&2
  exit 1
fi

mkdir -p \
  "$STAGING_DIR/logs" \
  "$STAGING_DIR/reports/quick" \
  "$STAGING_DIR/reports/e2e" \
  "$STAGING_DIR/reports/exports" \
  "$STAGING_DIR/reports/performance" \
  "$STAGING_DIR/reports/packaging" \
  "$STAGING_DIR/reports/docs" \
  "$STAGING_DIR/reports/source" \
  "$STAGING_DIR/exports/figure-templates" \
  "$STAGING_DIR/exports/submission-package" \
  "$STAGING_DIR/distributions" \
  "$WORK_DIR/quick" \
  "$WORK_DIR/editor" \
  "$WORK_DIR/responsive" \
  "$WORK_DIR/semantic" \
  "$WORK_DIR/product" \
  "$WORK_DIR/trial" \
  "$WORK_DIR/figure" \
  "$WORK_DIR/package-install"

cd "$PROJECT_DIR"
"$PYTHON_BIN" scripts/create_clean_snapshot.py "$PROJECT_DIR" "$SNAPSHOT_DIR" \
  --allowlist verification/source-allowlist-0.6.0.json \
  --reject-symlinks \
  --output "$SOURCE_REPORT" \
  > "$STAGING_DIR/logs/source-snapshot.log" 2>&1

(
  cd "$SNAPSHOT_DIR"
  npm ci --offline --ignore-scripts --no-audit --no-fund
) > "$STAGING_DIR/logs/npm-ci.log" 2>&1

cd "$SNAPSHOT_DIR"
export PYTHONPATH="$SNAPSHOT_DIR:$SNAPSHOT_DIR/src"
export PYTHONDONTWRITEBYTECODE=1
export MPLCONFIGDIR="$WORK_DIR/matplotlib"
export TEXMFVAR="$WORK_DIR/texmf-var"
export TEXMFCONFIG="$WORK_DIR/texmf-config"
export JAX_PLATFORMS=cpu
export CUDA_VISIBLE_DEVICES=''
mkdir -p "$MPLCONFIGDIR" "$TEXMFVAR" "$TEXMFCONFIG"

NN_DAVINCI_PYTHON="$PYTHON_BIN" \
  NNDV_QUICK_RUN_DIR="$WORK_DIR/quick" \
  NNDV_KEEP_DIAGNOSTICS=1 \
  ./scripts/verify-quick-0.6.0.sh \
  > "$STAGING_DIR/logs/quick.log" 2>&1
cp "$WORK_DIR/quick/quick-verification.json" "$STAGING_DIR/reports/quick/"
cp "$WORK_DIR/quick/python-tests.json" "$STAGING_DIR/reports/quick/"
cp "$WORK_DIR/quick/collected-test-ids.txt" "$STAGING_DIR/reports/quick/"
cp "$WORK_DIR/quick/core-coverage.json" "$STAGING_DIR/reports/quick/"
cp "$WORK_DIR/quick/expanded-core-coverage.json" "$STAGING_DIR/reports/quick/"
cp "$WORK_DIR/quick/figure-core-coverage.json" "$STAGING_DIR/reports/quick/"
cp "$WORK_DIR/quick/all-package-coverage.json" "$STAGING_DIR/reports/quick/"
cp "$WORK_DIR/quick/coverage-summary.json" "$STAGING_DIR/reports/quick/"

"$PYTHON_BIN" scripts/audit_release_0_6.py \
  --project-root "$SNAPSHOT_DIR" \
  --output "$STAGING_DIR/reports/docs/release-audit.json" \
  > "$STAGING_DIR/logs/release-audit.log" 2>&1
"$PYTHON_BIN" scripts/benchmark_figure_studio.py \
  --output "$STAGING_DIR/reports/performance/figure-studio.json" \
  > "$STAGING_DIR/logs/figure-performance.log" 2>&1
"$PYTHON_BIN" scripts/validate_figure_exports.py \
  --output-dir "$STAGING_DIR/exports/figure-templates" \
  --report "$STAGING_DIR/reports/exports/figure-export-report.json" \
  > "$STAGING_DIR/logs/figure-exports.log" 2>&1
"$PYTHON_BIN" - "$STAGING_DIR/exports/submission-package" <<'PY' \
  > "$STAGING_DIR/logs/submission-package.log" 2>&1
from pathlib import Path
import sys

from nn_davinci.figure_export import export_submission_package
from nn_davinci.figure_templates import instantiate_template

_, figure = instantiate_template("transformer-attention-ffn")
outputs = export_submission_package(
    figure,
    Path(sys.argv[1]),
    caption="Editable Transformer attention and feed-forward architecture template.",
)
expected = {
    "figure.svg", "figure.pdf", "figure.tex", "figure.pptx",
    "figure.nndv.json", "caption.md", "provenance.json", "proof.json",
}
observed = {path.name for path in outputs}
if observed != expected or any(not path.is_file() or path.stat().st_size == 0 for path in outputs):
    raise SystemExit(f"submission package inventory mismatch: {sorted(observed)}")
print(f"submission package PASS files={len(outputs)}")
PY

NNDV_PYTHON="$PYTHON_BIN" \
  NNDV_E2E_DIR="$WORK_DIR/editor" \
  NNDV_E2E_REPORT="$STAGING_DIR/reports/e2e/editor.json" \
  NNDV_KEEP_DIAGNOSTICS=1 \
  npm run e2e > "$STAGING_DIR/logs/e2e-editor.log" 2>&1
NNDV_PYTHON="$PYTHON_BIN" \
  NNDV_RESPONSIVE_SCREENSHOT_DIR="$WORK_DIR/responsive/screens" \
  NNDV_RESPONSIVE_E2E_REPORT="$STAGING_DIR/reports/e2e/responsive.json" \
  NNDV_KEEP_DIAGNOSTICS=1 \
  npm run e2e:responsive > "$STAGING_DIR/logs/e2e-responsive.log" 2>&1
NNDV_PYTHON="$PYTHON_BIN" \
  NNDV_SEMANTIC_E2E_DIR="$WORK_DIR/semantic" \
  NNDV_SEMANTIC_E2E_REPORT="$STAGING_DIR/reports/e2e/semantic.json" \
  NNDV_KEEP_DIAGNOSTICS=1 \
  npm run e2e:semantic > "$STAGING_DIR/logs/e2e-semantic.log" 2>&1
NNDV_PYTHON="$PYTHON_BIN" \
  NNDV_PRODUCT_E2E_DIR="$WORK_DIR/product" \
  NNDV_PRODUCT_E2E_REPORT="$STAGING_DIR/reports/e2e/product.json" \
  NNDV_KEEP_DIAGNOSTICS=1 \
  npm run e2e:product > "$STAGING_DIR/logs/e2e-product.log" 2>&1
NNDV_PYTHON="$PYTHON_BIN" \
  NNDV_TRIAL_E2E_DIR="$WORK_DIR/trial" \
  NNDV_TRIAL_E2E_REPORT="$STAGING_DIR/reports/e2e/trial.json" \
  NNDV_KEEP_DIAGNOSTICS=1 \
  npm run e2e:trial > "$STAGING_DIR/logs/e2e-trial.log" 2>&1
NNDV_PYTHON="$PYTHON_BIN" \
  NNDV_FIGURE_E2E_DIR="$WORK_DIR/figure" \
  NNDV_FIGURE_E2E_REPORT="$STAGING_DIR/reports/e2e/figure-studio.json" \
  NNDV_KEEP_DIAGNOSTICS=1 \
  npm run e2e:figure > "$STAGING_DIR/logs/e2e-figure-studio.log" 2>&1

"$PYTHON_BIN" -m build --no-isolation --outdir "$STAGING_DIR/distributions" . \
  > "$STAGING_DIR/logs/package-build.log" 2>&1
"$PYTHON_BIN" scripts/verify_package_install.py \
  "$STAGING_DIR/distributions" "$WORK_DIR/package-install/venvs" \
  --project-root "$SNAPSHOT_DIR" \
  --expected-version 0.6.0 \
  --output "$STAGING_DIR/reports/packaging/package-install.json" \
  > "$STAGING_DIR/logs/package-install.log" 2>&1
"$PYTHON_BIN" scripts/write_environment_manifest.py "$STAGING_DIR/reports/environment.json" \
  > "$STAGING_DIR/logs/environment.log" 2>&1

"$PYTHON_BIN" - "$STAGING_DIR/reports/full/commands.json" <<'PY'
import json
from pathlib import Path
import sys

commands = [
    "clean-source-snapshot", "npm-ci-offline", "quick", "release-audit",
    "figure-performance", "28-vector-exports", "submission-package",
    "e2e-editor", "e2e-responsive", "e2e-semantic", "e2e-product",
    "e2e-trial-automation", "e2e-figure-studio", "package-build",
    "wheel-sdist-install", "environment-manifest",
]
path = Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps({
    "schema_version": "nndv-0.6.0-full-command-report-1",
    "commands": [{"id": name, "exit_code": 0} for name in commands],
    "failed": 0,
}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

"$PYTHON_BIN" scripts/finalize_artifact_0_6.py \
  --staging "$STAGING_DIR" \
  --source-root "$SNAPSHOT_DIR" \
  --source-report "$SOURCE_REPORT" \
  --artifact-root "$ARTIFACT_ROOT" \
  --run-id "$RUN_ID" \
  --started-utc "$STARTED_UTC" \
  --started-epoch "$STARTED_EPOCH"

"$PYTHON_BIN" scripts/verify_release_artifact_0_6.py "$ARTIFACT_ROOT/$RUN_ID" \
  --output "$ARTIFACT_ROOT/$RUN_ID.inventory-verification.json"

"$PYTHON_BIN" - "$ARTIFACT_ROOT/$RUN_ID" "$ARTIFACT_ROOT/$RUN_ID.inventory-verification.json" <<'PY'
import json
from pathlib import Path
import sys

artifact = Path(sys.argv[1]).resolve()
verification = json.loads((artifact / "verification.json").read_text(encoding="utf-8"))
inventory = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
python = verification["python"]
coverage = verification["coverage"]
print(
    "NNDV_060_FULL_RESULT "
    f"status={verification['status']} run_id={verification['run_id']} "
    f"python={python['passed']}/{python['collected']} failed={python['failed']} errors={python['errors']} "
    f"skipped={python['skipped']} deselected={python['deselected']} inherited={python['inherited_0_5_2_tests']} "
    f"chrome_suites={verification['chrome']['suites']} chrome_assertions={verification['chrome']['assertions']} "
    f"browser_errors={verification['chrome']['console_page_request_errors']} "
    f"formats={verification['exports']['formats']} export_failures={verification['exports']['failures']} "
    f"old_core_line={coverage['old_core']['line']['percent']:.5f}% "
    f"old_core_branch={coverage['old_core']['branch']['percent']:.5f}% "
    f"source_files={inventory['source_file_count']} source_digest={inventory['source_digest']} "
    f"manifest_entries={inventory['manifest_entries']} manifest_sha256={inventory['manifest_sha256']} "
    f"sha256sums_sha256={inventory['sha256sums_sha256']} elapsed={verification['elapsed_seconds']:.3f}s "
    f"artifact={artifact}"
)
PY

SUCCESS=1
