#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE_DIR="$(cd "$PROJECT_DIR/.." && pwd)"
PYTHON_BIN="${NN_DAVINCI_PYTHON:-$WORKSPACE_DIR/envs/python-tools/bin/python}"
PARENT_DIR="${NNDV_PARENT_072_SOURCE:-$WORKSPACE_DIR/NN_DaVinci_0.7.2_Dev}"
PARENT_RUN_ID="20260901T142604Z-010606e8"
PARENT_ARTIFACT="${NNDV_AUTHORITATIVE_072_ARTIFACT:-$PARENT_DIR/artifacts/v0.7.2/$PARENT_RUN_ID}"
PARENT_CORPUS="$PARENT_ARTIFACT/exports/scene-corpus"
PARENT_PERFORMANCE="$PARENT_ARTIFACT/reports/performance/scene-studio.json"
PARENT_TEST_IDS="$PARENT_ARTIFACT/reports/quick/collected-test-ids.txt"
ARTIFACT_ROOT="$PROJECT_DIR/artifacts/v0.7.3"
RUN_ID="${NNDV_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')}"
STARTED_EPOCH="$(date +%s)"
STARTED_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

if [[ ! "$RUN_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "unsafe 0.7.3 run identifier: $RUN_ID" >&2
  exit 1
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "verification Python is missing: $PYTHON_BIN" >&2
  exit 1
fi
if [[ ! -d "$PARENT_DIR" || -L "$PARENT_DIR" || ! -d "$PARENT_ARTIFACT" || -L "$PARENT_ARTIFACT" ]]; then
  echo "pinned 0.7.2 parent source/artifact is missing or unsafe" >&2
  exit 1
fi
if [[ -L "$PROJECT_DIR/artifacts" || -L "$ARTIFACT_ROOT" ]]; then
  echo "artifact root is symlinked and unsafe" >&2
  exit 1
fi
mkdir -p "$ARTIFACT_ROOT"
if [[ -e "$ARTIFACT_ROOT/$RUN_ID" || -e "$ARTIFACT_ROOT/$RUN_ID.inventory-verification.json" ]]; then
  echo "refusing to overwrite 0.7.3 run: $RUN_ID" >&2
  exit 1
fi

CONTROL_DIR="$(mktemp -d "/tmp/nndv-073-full-${RUN_ID}-XXXXXX")"
STAGING_DIR="$CONTROL_DIR/artifact-staging"
WORK_DIR="$CONTROL_DIR/work"
SOURCE_SNAPSHOT="$STAGING_DIR/source/NN_DaVinci_0.7.3"
EXECUTION_DIR="$WORK_DIR/execution-source"
PARENT_SNAPSHOT="$WORK_DIR/parent-source/NN_DaVinci_0.7.2"
COMMAND_LEDGER="$CONTROL_DIR/commands.ndjson"
BROWSER_TMP_ROOT="$(mktemp -d "/tmp/nndv-073-browser-XXXXXX")"
SUCCESS=0

mkdir -p \
  "$STAGING_DIR/logs" "$STAGING_DIR/reports/quick" "$STAGING_DIR/reports/source" \
  "$STAGING_DIR/reports/docs" "$STAGING_DIR/reports/exports" "$STAGING_DIR/reports/visual" \
  "$STAGING_DIR/reports/semantic" "$STAGING_DIR/reports/generalization" \
  "$STAGING_DIR/reports/performance" "$STAGING_DIR/reports/service" \
  "$STAGING_DIR/reports/e2e" "$STAGING_DIR/reports/packaging" "$STAGING_DIR/reports/full" \
  "$STAGING_DIR/exports" "$STAGING_DIR/evidence/tikz-pdf-proofs" \
  "$STAGING_DIR/evidence/publication-before-after" "$STAGING_DIR/evidence/scene-studio" \
  "$STAGING_DIR/distributions" "$STAGING_DIR/docs" "$WORK_DIR/quick" "$WORK_DIR/package-install" \
  "$BROWSER_TMP_ROOT/editor" "$BROWSER_TMP_ROOT/responsive" "$BROWSER_TMP_ROOT/semantic" \
  "$BROWSER_TMP_ROOT/product" "$BROWSER_TMP_ROOT/trial" "$BROWSER_TMP_ROOT/figure" "$BROWSER_TMP_ROOT/scene"

finish() {
  local status=$?
  if [[ "$SUCCESS" -eq 1 && "$status" -eq 0 && "${NNDV_KEEP_DIAGNOSTICS:-0}" != "1" ]]; then
    "$PYTHON_BIN" - "$CONTROL_DIR" "$BROWSER_TMP_ROOT" <<'PY'
from pathlib import Path
import shutil
import sys
for raw, prefix in ((sys.argv[1], "nndv-073-full-"), (sys.argv[2], "nndv-073-browser-")):
    path = Path(raw)
    resolved = path.resolve(strict=True)
    if path.is_symlink() or resolved.parent != Path("/tmp") or not resolved.name.startswith(prefix):
        raise SystemExit(f"refusing to clean unexpected temporary path: {path}")
    shutil.rmtree(resolved)
PY
  else
    echo "0.7.3 full diagnostics retained: $CONTROL_DIR" >&2
    echo "0.7.3 browser diagnostics retained: $BROWSER_TMP_ROOT" >&2
  fi
}
trap finish EXIT

record_command() {
  "$PYTHON_BIN" - "$COMMAND_LEDGER" "$@" <<'PY'
import json
from pathlib import Path
import sys
ledger = Path(sys.argv[1])
record = {
    "id": sys.argv[2], "started_utc": sys.argv[3], "ended_utc": sys.argv[4],
    "duration_seconds": round((int(sys.argv[6]) - int(sys.argv[5])) / 1_000_000_000, 6),
    "exit_code": int(sys.argv[7]), "working_directory": sys.argv[8], "log": sys.argv[9],
    "argv": sys.argv[10:],
}
with ledger.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
PY
}

run_logged() {
  local identifier="$1"
  local log_path="$2"
  shift 2
  local started_utc ended_utc started_ns ended_ns exit_code working_directory
  started_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  started_ns="$(date +%s%N)"
  working_directory="$(pwd -P)"
  mkdir -p "$(dirname "$log_path")"
  set +e
  "$@" >"$log_path" 2>&1
  exit_code=$?
  set -e
  ended_ns="$(date +%s%N)"
  ended_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  record_command "$identifier" "$started_utc" "$ended_utc" "$started_ns" "$ended_ns" "$exit_code" "$working_directory" "$log_path" "$@"
  if [[ "$exit_code" -ne 0 ]]; then
    echo "full command failed: $identifier (see $log_path)" >&2
    tail -n 80 "$log_path" >&2
    return "$exit_code"
  fi
}

write_command_report() {
  "$PYTHON_BIN" - "$COMMAND_LEDGER" "$STAGING_DIR/reports/full/commands.json" "$RUN_ID" <<'PY'
import json
from pathlib import Path
import sys
records = [json.loads(line) for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() if line]
report = {
    "schema_version": "nndv-0.7.3-full-command-report-1",
    "release": "0.7.3 — Reader-Visible Scientific Completeness & Generalization Hotfix",
    "run_id": sys.argv[3], "status": "PASS" if records and all(row["exit_code"] == 0 for row in records) else "FAIL",
    "fresh_control_root": True, "old_artifacts_used_as_current_output": False,
    "command_count": len(records), "completed": sum(row["exit_code"] == 0 for row in records),
    "failed": sum(row["exit_code"] != 0 for row in records), "commands": records,
}
Path(sys.argv[2]).write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

cd "$PROJECT_DIR"
run_logged clean-current-source "$STAGING_DIR/logs/source-snapshot.log" \
  "$PYTHON_BIN" scripts/create_clean_snapshot.py "$PROJECT_DIR" "$SOURCE_SNAPSHOT" \
  --allowlist verification/source-allowlist-0.7.3.json --reject-symlinks \
  --output "$STAGING_DIR/reports/source/snapshot.json"
run_logged clean-parent-source "$STAGING_DIR/logs/parent-source-snapshot.log" \
  "$PYTHON_BIN" "$PARENT_DIR/scripts/create_clean_snapshot.py" "$PARENT_DIR" "$PARENT_SNAPSHOT" \
  --allowlist verification/source-allowlist-0.7.2.json --reject-symlinks \
  --output "$STAGING_DIR/reports/source/parent-0.7.2-snapshot.json"
run_logged verify-parent-artifact "$STAGING_DIR/logs/parent-artifact.log" \
  "$PYTHON_BIN" "$PARENT_SNAPSHOT/scripts/verify_release_artifact_0_7_2.py" "$PARENT_ARTIFACT" \
  --output "$STAGING_DIR/reports/source/parent-0.7.2-artifact-verification.json" \
  --expected-run-id "$PARENT_RUN_ID"
run_logged prepare-execution-source "$STAGING_DIR/logs/execution-copy.log" \
  cp -a "$SOURCE_SNAPSHOT" "$EXECUTION_DIR"

cd "$EXECUTION_DIR"
run_logged npm-ci-offline "$STAGING_DIR/logs/npm-ci.log" npm ci --offline --ignore-scripts --no-audit --no-fund

export PYTHONPATH="$EXECUTION_DIR:$EXECUTION_DIR/src"
export NN_DAVINCI_PYTHON="$PYTHON_BIN"
export PYTHONPYCACHEPREFIX="$WORK_DIR/pycache"
export MPLCONFIGDIR="$WORK_DIR/matplotlib"
export TEXMFVAR="$WORK_DIR/texmf-var"
export TEXMFCONFIG="$WORK_DIR/texmf-config"
export JAX_PLATFORMS=cpu
export CUDA_VISIBLE_DEVICES=''
export TF_CPP_MIN_LOG_LEVEL=3
mkdir -p "$MPLCONFIGDIR" "$TEXMFVAR" "$TEXMFCONFIG"

run_logged quick-0.7.3 "$STAGING_DIR/logs/quick.log" env \
  NN_DAVINCI_PYTHON="$PYTHON_BIN" NNDV_QUICK_RUN_DIR="$WORK_DIR/quick" \
  NNDV_KEEP_DIAGNOSTICS=1 NNDV_PARENT_072_TEST_IDS="$PARENT_TEST_IDS" \
  ./scripts/verify-quick-0.7.3.sh
for report in quick-verification.json python-tests.json collected-test-ids.txt core-coverage.json expanded-core-coverage.json scene-core-coverage.json all-package-coverage.json coverage-summary.json; do
  cp "$WORK_DIR/quick/$report" "$STAGING_DIR/reports/quick/$report"
done

run_logged release-audit "$STAGING_DIR/logs/release-audit.log" \
  "$PYTHON_BIN" scripts/audit_release_0_7_3.py --project-root "$EXECUTION_DIR" --output "$STAGING_DIR/reports/docs/release-audit.json"
run_logged scene-performance "$STAGING_DIR/logs/performance.log" \
  "$PYTHON_BIN" scripts/benchmark_scene_studio_0_7_3.py --output "$STAGING_DIR/reports/performance/scene-studio.json" \
  --baseline-scene-report "$PARENT_PERFORMANCE" --parent-source "$PARENT_SNAPSHOT" --repeats 3
run_logged scene-corpus-generate "$STAGING_DIR/logs/corpus-generate.log" \
  "$PYTHON_BIN" scripts/generate_scene_artifacts_0_7_3.py --output-dir "$STAGING_DIR/exports/scene-corpus" \
  --report "$STAGING_DIR/reports/exports/scene-artifacts.json"
run_logged scene-corpus-validate "$STAGING_DIR/logs/corpus-validate.log" \
  "$PYTHON_BIN" scripts/validate_scene_artifacts_0_7_3.py --output-dir "$STAGING_DIR/exports/scene-corpus" \
  --generation-report "$STAGING_DIR/reports/exports/scene-artifacts.json" \
  --report "$STAGING_DIR/reports/exports/scene-artifacts-validation.json"
run_logged svg-geometry-oracle "$STAGING_DIR/logs/svg-oracle.log" \
  node scripts/scene_svg_oracle_0_7_2.mjs --input-root "$STAGING_DIR/exports/scene-corpus" \
  --output "$STAGING_DIR/reports/visual/scene-svg-oracle.json"
run_logged publication-oracle "$STAGING_DIR/logs/publication-oracle.log" \
  "$PYTHON_BIN" scripts/scene_publication_oracle_0_7_2.py --input-root "$STAGING_DIR/exports/scene-corpus" \
  --svg-report "$STAGING_DIR/reports/visual/scene-svg-oracle.json" \
  --output "$STAGING_DIR/reports/visual/scene-publication-oracle.json" --expected-cases 14
run_logged compile-tikz-proofs "$STAGING_DIR/logs/tikz-proofs.log" \
  "$PYTHON_BIN" scripts/compile_tikz_proofs_0_7_3.py --input-root "$STAGING_DIR/exports/scene-corpus" \
  --output-root "$STAGING_DIR/evidence/tikz-pdf-proofs" --report "$STAGING_DIR/reports/semantic/tikz-pdf-proofs.json"
run_logged semantic-browser-dom "$STAGING_DIR/logs/semantic-dom.log" \
  node scripts/semantic_svg_dom_oracle_0_7_3.mjs "$STAGING_DIR/exports/scene-corpus/real-models"/* \
  --output "$STAGING_DIR/reports/semantic/browser-dom.json"
run_logged semantic-presentation "$STAGING_DIR/logs/semantic-presentation.log" \
  "$PYTHON_BIN" scripts/semantic_presentation_oracle_0_7_3.py "$STAGING_DIR/exports/scene-corpus/real-models"/* \
  --require-tikz-pdf --tikz-pdf-root "$STAGING_DIR/evidence/tikz-pdf-proofs" \
  --output "$STAGING_DIR/reports/semantic/presentation.json"
run_logged semantic-completeness-matrix "$STAGING_DIR/logs/semantic-matrix.log" \
  "$PYTHON_BIN" scripts/generate_semantic_completeness_matrix_0_7_3.py \
  --presentation "$STAGING_DIR/reports/semantic/presentation.json" \
  --browser-dom "$STAGING_DIR/reports/semantic/browser-dom.json" \
  --output "$STAGING_DIR/reports/semantic/completeness-matrix.json"
run_logged semantic-negative-mutations "$STAGING_DIR/logs/semantic-mutations.log" \
  "$PYTHON_BIN" scripts/generate_semantic_mutation_report_0_7_3.py \
  --case-dir "$STAGING_DIR/exports/scene-corpus/real-models/resnet50" \
  --output "$STAGING_DIR/reports/semantic/negative-mutations.json"
run_logged architecture-generalization "$STAGING_DIR/logs/generalization.log" \
  "$PYTHON_BIN" scripts/generate_generalization_report_0_7_3.py \
  --output "$STAGING_DIR/reports/generalization/metamorphic-corpus.json" --seed 7300
run_logged before-after-proof "$STAGING_DIR/logs/before-after.log" \
  "$PYTHON_BIN" scripts/generate_scene_before_after_0_7_1.py --before-root "$PARENT_CORPUS" \
  --after-root "$STAGING_DIR/exports/scene-corpus" --output-root "$STAGING_DIR/evidence/publication-before-after" \
  --report "$STAGING_DIR/reports/visual/before-after.json" --before-release 0.7.2 --after-release 0.7.3 \
  --before-run-id "$PARENT_RUN_ID" --release-title "0.7.3 — Reader-Visible Scientific Completeness & Generalization Hotfix" \
  --report-schema nndv-0.7.3-scene-before-after-report-1 --proof-schema nndv-0.7.3-scene-before-after-proof-1 --allow-identical
run_logged original-resolution-inspection "$STAGING_DIR/logs/visual-inspection.log" \
  "$PYTHON_BIN" scripts/write_visual_inspection_report_0_7_3.py \
  --before-after-root "$STAGING_DIR/evidence/publication-before-after" \
  --before-after-report "$STAGING_DIR/reports/visual/before-after.json" \
  --output "$STAGING_DIR/reports/visual/original-resolution-inspection.json"
run_logged service-lifecycle "$STAGING_DIR/logs/service-lifecycle.log" \
  "$PYTHON_BIN" scripts/verify_service_lifecycle_0_7_3.py --port 8766 --output "$STAGING_DIR/reports/service/lifecycle.json"

run_logged e2e-editor "$STAGING_DIR/logs/e2e-editor.log" env TMPDIR="$BROWSER_TMP_ROOT/editor" \
  NNDV_PYTHON="$PYTHON_BIN" NNDV_TASK_ROOT="$WORK_DIR/editor/tasks" NNDV_E2E_DIR="$WORK_DIR/editor/runtime" \
  NNDV_E2E_REPORT="$STAGING_DIR/reports/e2e/editor.json" NNDV_KEEP_DIAGNOSTICS=1 npm run e2e
run_logged e2e-responsive "$STAGING_DIR/logs/e2e-responsive.log" env TMPDIR="$BROWSER_TMP_ROOT/responsive" \
  NNDV_PYTHON="$PYTHON_BIN" NNDV_TASK_ROOT="$WORK_DIR/responsive/tasks" \
  NNDV_RESPONSIVE_SCREENSHOT_DIR="$STAGING_DIR/screenshots/responsive" \
  NNDV_RESPONSIVE_E2E_REPORT="$STAGING_DIR/reports/e2e/responsive.json" NNDV_KEEP_DIAGNOSTICS=1 npm run e2e:responsive
run_logged e2e-semantic "$STAGING_DIR/logs/e2e-semantic.log" env TMPDIR="$BROWSER_TMP_ROOT/semantic" \
  NNDV_PYTHON="$PYTHON_BIN" NNDV_TASK_ROOT="$WORK_DIR/semantic/tasks" NNDV_SEMANTIC_E2E_DIR="$WORK_DIR/semantic/runtime" \
  NNDV_SEMANTIC_E2E_REPORT="$STAGING_DIR/reports/e2e/semantic.json" NNDV_KEEP_DIAGNOSTICS=1 npm run e2e:semantic
run_logged e2e-product "$STAGING_DIR/logs/e2e-product.log" env TMPDIR="$BROWSER_TMP_ROOT/product" \
  NNDV_PYTHON="$PYTHON_BIN" NNDV_TASK_ROOT="$WORK_DIR/product/tasks" NNDV_PRODUCT_E2E_DIR="$WORK_DIR/product/runtime" \
  NNDV_PRODUCT_E2E_REPORT="$STAGING_DIR/reports/e2e/product.json" NNDV_KEEP_DIAGNOSTICS=1 npm run e2e:product
run_logged e2e-trial "$STAGING_DIR/logs/e2e-trial.log" env TMPDIR="$BROWSER_TMP_ROOT/trial" \
  NNDV_PYTHON="$PYTHON_BIN" NNDV_TASK_ROOT="$WORK_DIR/trial/tasks" NNDV_TRIAL_E2E_DIR="$WORK_DIR/trial/runtime" \
  NNDV_TRIAL_E2E_REPORT="$STAGING_DIR/reports/e2e/trial.json" NNDV_KEEP_DIAGNOSTICS=1 npm run e2e:trial
run_logged e2e-figure "$STAGING_DIR/logs/e2e-figure.log" env TMPDIR="$BROWSER_TMP_ROOT/figure" \
  NNDV_PYTHON="$PYTHON_BIN" NNDV_TASK_ROOT="$WORK_DIR/figure/tasks" NNDV_FIGURE_E2E_DIR="$WORK_DIR/figure/runtime" \
  NNDV_FIGURE_E2E_REPORT="$STAGING_DIR/reports/e2e/figure-studio.json" NNDV_KEEP_DIAGNOSTICS=1 npm run e2e:figure
run_logged e2e-scene "$STAGING_DIR/logs/e2e-scene.log" env TMPDIR="$BROWSER_TMP_ROOT/scene" \
  NNDV_PYTHON="$PYTHON_BIN" NNDV_TASK_ROOT="$WORK_DIR/scene/tasks" NNDV_SCENE_E2E_DIR="$STAGING_DIR/evidence/scene-studio" \
  NNDV_SCENE_E2E_REPORT="$STAGING_DIR/reports/e2e/scene-studio.json" NNDV_KEEP_DIAGNOSTICS=1 npm run e2e:scene
run_logged scene-visual-validation "$STAGING_DIR/logs/scene-visual.log" \
  "$PYTHON_BIN" scripts/validate_scene_visual_evidence_0_7_1.py "$STAGING_DIR/reports/e2e/scene-studio.json" \
  --artifact-root "$STAGING_DIR/evidence/scene-studio/scene-studio-artifacts" \
  --screenshots-root "$STAGING_DIR/evidence/scene-studio/scene-studio-artifacts/screenshots" \
  --output "$STAGING_DIR/reports/visual/scene-studio.json"
run_logged aggregate-e2e "$STAGING_DIR/logs/e2e-aggregate.log" \
  "$PYTHON_BIN" scripts/aggregate_e2e_0_7_3.py \
  --suite editor="$STAGING_DIR/reports/e2e/editor.json" --suite responsive="$STAGING_DIR/reports/e2e/responsive.json" \
  --suite semantic="$STAGING_DIR/reports/e2e/semantic.json" --suite product="$STAGING_DIR/reports/e2e/product.json" \
  --suite trial="$STAGING_DIR/reports/e2e/trial.json" --suite figure="$STAGING_DIR/reports/e2e/figure-studio.json" \
  --suite scene="$STAGING_DIR/reports/e2e/scene-studio.json" --output "$STAGING_DIR/reports/e2e/aggregate.json"

run_logged package-build "$STAGING_DIR/logs/package-build.log" \
  "$PYTHON_BIN" -m build --no-isolation --outdir "$STAGING_DIR/distributions" .
run_logged package-install "$STAGING_DIR/logs/package-install.log" \
  "$PYTHON_BIN" scripts/verify_package_install.py "$STAGING_DIR/distributions" "$WORK_DIR/package-install/venvs" \
  --project-root "$EXECUTION_DIR" --expected-version 0.7.3 --output "$STAGING_DIR/reports/packaging/package-install.json"
run_logged environment-manifest "$STAGING_DIR/logs/environment.log" \
  "$PYTHON_BIN" scripts/write_environment_manifest.py "$STAGING_DIR/reports/environment.json"

cp docs/RELEASE_NOTES_0.7.3.md docs/SEMANTIC_PRESENTATION_COMPLETENESS_0.7.3.md \
  docs/GENERALIZATION_REPORT_0.7.3.md docs/SERVICE_LIFECYCLE_0.7.3.md docs/KNOWN_LIMITATIONS.md "$STAGING_DIR/docs/"
write_command_report

cd "$PROJECT_DIR"
"$PYTHON_BIN" scripts/finalize_artifact_0_7_3.py --staging "$STAGING_DIR" --artifact-root "$ARTIFACT_ROOT" \
  --run-id "$RUN_ID" --started-utc "$STARTED_UTC" --started-epoch "$STARTED_EPOCH" \
  >"$ARTIFACT_ROOT/$RUN_ID.finalize.log" 2>&1
"$PYTHON_BIN" scripts/verify_release_artifact_0_7_3.py "$ARTIFACT_ROOT/$RUN_ID" \
  --expected-run-id "$RUN_ID" --output "$ARTIFACT_ROOT/$RUN_ID.inventory-verification.json" \
  >"$ARTIFACT_ROOT/$RUN_ID.verify.log" 2>&1

"$PYTHON_BIN" - "$ARTIFACT_ROOT/$RUN_ID" "$ARTIFACT_ROOT/$RUN_ID.inventory-verification.json" <<'PY'
import json
from pathlib import Path
import sys
root = Path(sys.argv[1])
verification = json.loads((root / "verification.json").read_text(encoding="utf-8"))
inventory = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
python = verification["python"]
source = verification["source"]
print(
    "NNDV_073_FULL_RESULT "
    f"status={verification['status']} run_id={verification['run_id']} "
    f"python={python['passed']}/{python['collected']} inherited_0_7_2={python['inherited_0_7_2_tests']} "
    f"new_0_7_3={python['new_0_7_3_tests']} scene_cases=14 scene_exports=140 "
    f"source_files={source['file_count']} source_digest={source['source_tree_digest']} "
    f"artifact_files={inventory['artifact_files']} manifest_entries={inventory['manifest_entries']} artifact={root}"
)
PY

SUCCESS=1
