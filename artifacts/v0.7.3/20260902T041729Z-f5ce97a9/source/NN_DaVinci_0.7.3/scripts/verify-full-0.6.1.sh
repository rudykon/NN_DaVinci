#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE_DIR="$(cd "$PROJECT_DIR/.." && pwd)"
PYTHON_BIN="${NN_DAVINCI_PYTHON:-$WORKSPACE_DIR/envs/python-tools/bin/python}"
ARTIFACT_ROOT="$PROJECT_DIR/artifacts/v0.6.1"
AUTHORITATIVE_060_ARTIFACT="${NNDV_AUTHORITATIVE_060_ARTIFACT:-$WORKSPACE_DIR/NN_DaVinci_0.6.0_Dev/artifacts/v0.6.0/20260829T183558Z-09a7930b}"
RUN_ID="${NNDV_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')}"
STARTED_EPOCH="$(date +%s)"
STARTED_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
TEMPORARY_ROOT="${TMPDIR:-/tmp}"
CONTROL_DIR="$(mktemp -d "$TEMPORARY_ROOT/nndv-061-full-${RUN_ID}-XXXXXX")"
SNAPSHOT_DIR="$CONTROL_DIR/clean-source/NN_DaVinci_0.6.1"
SOURCE_REPORT="$CONTROL_DIR/source-snapshot.json"
STAGING_DIR="$CONTROL_DIR/artifact-staging"
WORK_DIR="$CONTROL_DIR/work"
SUCCESS=0

finish() {
  status=$?
  if [[ "$SUCCESS" -eq 1 && "$status" -eq 0 && "${NNDV_KEEP_DIAGNOSTICS:-0}" != "1" ]]; then
    "$PYTHON_BIN" - "$CONTROL_DIR" "$TEMPORARY_ROOT" <<'PY'
from pathlib import Path
import shutil
import sys

path = Path(sys.argv[1]).resolve()
temporary = Path(sys.argv[2]).resolve()
if path.parent != temporary or not path.name.startswith("nndv-061-full-") or path.is_symlink():
    raise SystemExit(f"refusing to clean unexpected full controller path: {path}")
shutil.rmtree(path)
PY
  else
    echo "0.6.1 full diagnostics retained: $CONTROL_DIR" >&2
  fi
}
trap finish EXIT

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python verification environment not found: $PYTHON_BIN" >&2
  exit 1
fi
if [[ ! -d "$AUTHORITATIVE_060_ARTIFACT" ]]; then
  echo "authoritative v0.6.0 before-artifact is absent: $AUTHORITATIVE_060_ARTIFACT" >&2
  exit 1
fi
if [[ -e "$ARTIFACT_ROOT/$RUN_ID" || -e "$ARTIFACT_ROOT/$RUN_ID.inventory-verification.json" ]]; then
  echo "refusing to overwrite v0.6.1 run: $RUN_ID" >&2
  exit 1
fi

mkdir -p \
  "$STAGING_DIR/logs" \
  "$STAGING_DIR/reports/quick" \
  "$STAGING_DIR/reports/e2e" \
  "$STAGING_DIR/reports/exports" \
  "$STAGING_DIR/reports/oracle-fixtures" \
  "$STAGING_DIR/reports/performance" \
  "$STAGING_DIR/reports/packaging" \
  "$STAGING_DIR/reports/docs" \
  "$STAGING_DIR/reports/source" \
  "$STAGING_DIR/reports/full" \
  "$STAGING_DIR/exports" \
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
  --allowlist verification/source-allowlist-0.6.1.json \
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
  ./scripts/verify-quick-0.6.1.sh \
  > "$STAGING_DIR/logs/quick.log" 2>&1
cp "$WORK_DIR/quick/quick-verification.json" "$STAGING_DIR/reports/quick/"
cp "$WORK_DIR/quick/python-tests.json" "$STAGING_DIR/reports/quick/"
cp "$WORK_DIR/quick/collected-test-ids.txt" "$STAGING_DIR/reports/quick/"
cp "$WORK_DIR/quick/core-coverage.json" "$STAGING_DIR/reports/quick/"
cp "$WORK_DIR/quick/expanded-core-coverage.json" "$STAGING_DIR/reports/quick/"
cp "$WORK_DIR/quick/figure-core-coverage.json" "$STAGING_DIR/reports/quick/"
cp "$WORK_DIR/quick/all-package-coverage.json" "$STAGING_DIR/reports/quick/"
cp "$WORK_DIR/quick/coverage-summary.json" "$STAGING_DIR/reports/quick/"

"$PYTHON_BIN" scripts/audit_release_0_6_1.py \
  --project-root "$SNAPSHOT_DIR" \
  --output "$STAGING_DIR/reports/docs/release-audit.json" \
  > "$STAGING_DIR/logs/release-audit.log" 2>&1
"$PYTHON_BIN" scripts/benchmark_figure_studio_0_6_1.py \
  --output "$STAGING_DIR/reports/performance/figure-studio.json" \
  > "$STAGING_DIR/logs/figure-performance.log" 2>&1

"$PYTHON_BIN" scripts/generate_figure_svg_oracle_fixtures.py \
  "$STAGING_DIR/exports/oracle-fixtures" \
  > "$STAGING_DIR/logs/oracle-fixture-generation.log" 2>&1
mapfile -t FIXTURE_SVGS < <(
  "$PYTHON_BIN" - "$STAGING_DIR/exports/oracle-fixtures" <<'PY'
from pathlib import Path
import sys
for path in sorted(Path(sys.argv[1]).glob("*.svg")):
    print(path)
PY
)
if [[ "${#FIXTURE_SVGS[@]}" -ne 21 ]]; then
  echo "expected 21 generated oracle fixture SVGs, found ${#FIXTURE_SVGS[@]}" >&2
  exit 1
fi
node scripts/figure_svg_oracle.mjs \
  --allow-failures \
  --output "$STAGING_DIR/reports/oracle-fixtures/figure-svg-oracle.json" \
  "${FIXTURE_SVGS[@]}" \
  > "$STAGING_DIR/logs/oracle-fixtures.log" 2>&1
"$PYTHON_BIN" scripts/validate_figure_svg_oracle_fixtures.py \
  "$STAGING_DIR/reports/oracle-fixtures/figure-svg-oracle.json" \
  --output "$STAGING_DIR/reports/oracle-fixtures/validation.json" \
  > "$STAGING_DIR/logs/oracle-fixture-validation.log" 2>&1

"$PYTHON_BIN" scripts/generate_publication_artifacts_0_6_1.py \
  --output-dir "$STAGING_DIR/exports/publication" \
  --report "$STAGING_DIR/reports/exports/publication-artifacts.json" \
  > "$STAGING_DIR/logs/publication-artifacts.log" 2>&1
mapfile -t PUBLICATION_SVGS < <(
  "$PYTHON_BIN" - "$STAGING_DIR/reports/exports/publication-artifacts.json" <<'PY'
import json
from pathlib import Path
import sys
report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
root = Path(report["output_root"])
for item in report["svg_inputs"]:
    path = root / item["relative_path"]
    if not path.is_file():
        raise SystemExit(f"fresh SVG input is missing: {path}")
    print(path)
PY
)
if [[ "${#PUBLICATION_SVGS[@]}" -ne 14 ]]; then
  echo "expected 14 fresh publication SVGs, found ${#PUBLICATION_SVGS[@]}" >&2
  exit 1
fi
node scripts/figure_svg_oracle.mjs \
  --output "$STAGING_DIR/reports/exports/figure-svg-oracle.json" \
  "${PUBLICATION_SVGS[@]}" \
  > "$STAGING_DIR/logs/publication-svg-oracle.log" 2>&1
"$PYTHON_BIN" scripts/validate_strict_figure_oracle_0_6_1.py \
  --oracle-report "$STAGING_DIR/reports/exports/figure-svg-oracle.json" \
  --export-report "$STAGING_DIR/reports/exports/publication-artifacts.json" \
  --output "$STAGING_DIR/reports/exports/strict-svg-validation.json" \
  > "$STAGING_DIR/logs/strict-svg-validation.log" 2>&1
"$PYTHON_BIN" scripts/validate_cross_format_positions_0_6_1.py \
  --oracle-report "$STAGING_DIR/reports/exports/figure-svg-oracle.json" \
  --export-report "$STAGING_DIR/reports/exports/publication-artifacts.json" \
  --proof-dir "$STAGING_DIR/exports/cross-format-proofs" \
  --output "$STAGING_DIR/reports/exports/cross-format-positions.json" \
  > "$STAGING_DIR/logs/cross-format-positions.log" 2>&1
mapfile -t HISTORICAL_060_SVGS < <(
  "$PYTHON_BIN" - "$AUTHORITATIVE_060_ARTIFACT" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

expected_run = "20260829T183558Z-09a7930b"
expected_manifest_sha256 = "797d5b38403154b1317d00e8a9e03c48373a2c046e10e4a43229f828769e3cc4"
templates = (
    "cnn-feature-pipeline",
    "diffusion-unet-conditioning",
    "moe-router-experts",
    "multimodal-fusion",
    "resnet-overview",
    "transformer-attention-ffn",
    "unet-encoder-decoder",
)
artifact = Path(sys.argv[1]).resolve(strict=True)
manifest_path = artifact / "MANIFEST.json"
manifest_bytes = manifest_path.read_bytes()
if artifact.name != expected_run or hashlib.sha256(manifest_bytes).hexdigest() != expected_manifest_sha256:
    raise SystemExit("the historical SVG negative control is not pinned to the authoritative 0.6.0 artifact")
manifest = json.loads(manifest_bytes)
if manifest.get("run_id") != expected_run or not isinstance(manifest.get("entries"), dict):
    raise SystemExit("the authoritative 0.6.0 manifest identity or entries are invalid")
expected_paths = [artifact / "exports" / "figure-templates" / name / "figure.svg" for name in templates]
observed_paths = sorted((artifact / "exports" / "figure-templates").glob("*/figure.svg"))
if observed_paths != sorted(expected_paths):
    raise SystemExit("the authoritative 0.6.0 artifact does not contain exactly the expected seven SVG templates")
for path in expected_paths:
    if path.is_symlink() or not path.is_file():
        raise SystemExit(f"historical SVG input is absent or unsafe: {path}")
    relative = path.relative_to(artifact).as_posix()
    claim = manifest["entries"].get(relative, {})
    observed = hashlib.sha256(path.read_bytes()).hexdigest()
    if claim.get("bytes") != path.stat().st_size or claim.get("sha256") != observed:
        raise SystemExit(f"historical SVG input differs from the pinned manifest: {relative}")
for path in expected_paths:
    print(path)
PY
)
if [[ "${#HISTORICAL_060_SVGS[@]}" -ne 7 ]]; then
  echo "expected exactly seven pinned authoritative 0.6.0 SVGs, found ${#HISTORICAL_060_SVGS[@]}" >&2
  exit 1
fi
node scripts/figure_svg_oracle.mjs \
  --allow-failures \
  --output "$STAGING_DIR/reports/exports/authoritative-0.6.0-figure-svg-oracle.json" \
  "${HISTORICAL_060_SVGS[@]}" \
  > "$STAGING_DIR/logs/authoritative-0.6.0-svg-negative-control.log" 2>&1
"$PYTHON_BIN" scripts/generate_before_after_proofs_0_6_1.py \
  --before-artifact "$AUTHORITATIVE_060_ARTIFACT" \
  --before-oracle-report "$STAGING_DIR/reports/exports/authoritative-0.6.0-figure-svg-oracle.json" \
  --after-export-report "$STAGING_DIR/reports/exports/publication-artifacts.json" \
  --output-dir "$STAGING_DIR/exports/before-after-proofs" \
  --report "$STAGING_DIR/reports/exports/before-after-proofs.json" \
  > "$STAGING_DIR/logs/before-after-proofs.log" 2>&1
"$PYTHON_BIN" scripts/validate_submission_package_0_6_1.py \
  --output-dir "$STAGING_DIR/exports/submission-package" \
  --report "$STAGING_DIR/reports/exports/submission-package.json" \
  > "$STAGING_DIR/logs/submission-package.log" 2>&1

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
  --expected-version 0.6.1 \
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
    "figure-performance", "21-oracle-fixture-generation", "21-oracle-fixture-chrome",
    "21-oracle-fixture-truth-validation", "14-figure-seven-format-generation",
    "14-final-svg-chrome-oracle", "strict-svg-hash-and-metric-validation",
    "svg-pdf-tikz-position-registration", "authoritative-0.6.0-seven-svg-collection",
    "authoritative-0.6.0-seven-svg-chrome-negative-control", "authoritative-0.6.0-before-after-proofs",
    "seven-format-submission-package", "e2e-editor", "e2e-responsive",
    "e2e-semantic", "e2e-product", "e2e-trial-automation", "e2e-figure-studio",
    "package-build", "wheel-sdist-install", "environment-manifest",
]
path = Path(sys.argv[1])
path.write_text(json.dumps({
    "schema_version": "nndv-0.6.1-full-command-report-1",
    "commands": [{"id": name, "exit_code": 0} for name in commands],
    "failed": 0,
}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

"$PYTHON_BIN" scripts/finalize_artifact_0_6_1.py \
  --staging "$STAGING_DIR" \
  --source-root "$SNAPSHOT_DIR" \
  --source-report "$SOURCE_REPORT" \
  --artifact-root "$ARTIFACT_ROOT" \
  --run-id "$RUN_ID" \
  --started-utc "$STARTED_UTC" \
  --started-epoch "$STARTED_EPOCH"

"$PYTHON_BIN" scripts/verify_release_artifact_0_6_1.py "$ARTIFACT_ROOT/$RUN_ID" \
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
strict = verification["strict_svg_oracle"]
historical = verification["strict_negative_control"]
cross = verification["cross_format_positions"]
print(
    "NNDV_061_FULL_RESULT "
    f"status={verification['status']} run_id={verification['run_id']} "
    f"python={python['passed']}/{python['collected']} failed={python['failed']} errors={python['errors']} "
    f"skipped={python['skipped']} deselected={python['deselected']} inherited_0_6_0={python['inherited_0_6_0_tests']} "
    f"chrome_suites={verification['chrome']['suites']} chrome_assertions={verification['chrome']['assertions']} "
    f"browser_errors={verification['chrome']['console_page_request_errors']} "
    f"figures={verification['exports']['figures']} formats={verification['exports']['requested_formats']} "
    f"strict_svg={strict['passed_svg_files']}/{strict['final_svg_files']} "
    f"historical_strict={historical['summary']['passed']}/{historical['summary']['files']} "
    f"historical_issues={historical['summary']['issues']} "
    f"minimum_font_pt={strict['metrics']['minimum_font_pt']} geometry_issues={strict['metrics']['geometry_issues']} "
    f"minimum_stroke_pt={strict['metrics']['minimum_stroke_pt']} "
    f"cross_format_max_mm={cross['maximum_key_position_error_mm']} "
    f"oracle_fixtures={verification['oracle_fixture_truth']['classification_count']}/21 "
    f"old_core_line={coverage['old_core']['line']['percent']:.5f}% "
    f"old_core_branch={coverage['old_core']['branch']['percent']:.5f}% "
    f"source_files={inventory['source_file_count']} source_digest={inventory['source_digest']} "
    f"manifest_entries={inventory['manifest_entries']} manifest_sha256={inventory['manifest_sha256']} "
    f"sha256sums_sha256={inventory['sha256sums_sha256']} elapsed={verification['elapsed_seconds']:.3f}s "
    f"participants={verification['human_evidence']['participants']} artifact={artifact}"
)
PY

SUCCESS=1
