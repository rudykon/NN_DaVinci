#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE_DIR="$(cd "$PROJECT_DIR/.." && pwd)"
PYTHON_BIN="${NN_DAVINCI_PYTHON:-$WORKSPACE_DIR/envs/python-tools/bin/python}"
if [[ "$PYTHON_BIN" != /* ]]; then
  PYTHON_DIR="$(cd "$(dirname "$PYTHON_BIN")" && pwd)"
  PYTHON_BIN="$PYTHON_DIR/$(basename "$PYTHON_BIN")"
fi
PARENT_SOURCE_DIR="${NNDV_PARENT_061_SOURCE:-$WORKSPACE_DIR/NN_DaVinci_0.6.1_Dev}"
PARENT_RUN_ID="20260830T122225Z-0f6f36c2"
PARENT_SOURCE_FILES=294
PARENT_SOURCE_DIGEST="26469ab2eb7fd2d10a4d058ec7061017f8de005d714ca2760e2412a414d7ad7f"
AUTHORITATIVE_061_ARTIFACT="${NNDV_AUTHORITATIVE_061_ARTIFACT:-$PARENT_SOURCE_DIR/artifacts/v0.6.1/$PARENT_RUN_ID}"
PARENT_FIGURE_PERFORMANCE="$AUTHORITATIVE_061_ARTIFACT/reports/performance/figure-studio.json"
ARTIFACT_ROOT="$PROJECT_DIR/artifacts/v0.7.0"
RUN_ID="${NNDV_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')}"
STARTED_EPOCH="$(date +%s)"
STARTED_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
TEMPORARY_ROOT="${TMPDIR:-/tmp}"

if [[ ! "$RUN_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "unsafe 0.7.0 run identifier: $RUN_ID" >&2
  exit 1
fi

CONTROL_DIR="$(mktemp -d "$TEMPORARY_ROOT/nndv-070-full-${RUN_ID}-XXXXXX")"
SNAPSHOT_DIR="$CONTROL_DIR/clean-source/NN_DaVinci_0.7.0"
PARENT_SNAPSHOT_DIR="$CONTROL_DIR/parent-source/NN_DaVinci_0.6.1"
STAGING_DIR="$CONTROL_DIR/artifact-staging"
WORK_DIR="$CONTROL_DIR/work"
SOURCE_REPORT="$STAGING_DIR/reports/source/snapshot.json"
PARENT_SOURCE_REPORT="$STAGING_DIR/reports/source/parent-0.6.1-snapshot.json"
PARENT_ARTIFACT_REPORT="$STAGING_DIR/reports/source/parent-0.6.1-artifact-verification.json"
COMMAND_LEDGER="$CONTROL_DIR/commands.ndjson"
COMMAND_REPORT="$STAGING_DIR/reports/full/commands.json"
BROWSER_TMP_ROOT=""
SUCCESS=0

record_command() {
  "$PYTHON_BIN" - "$COMMAND_LEDGER" "$@" <<'PY'
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ledger = Path(sys.argv[1])
identifier = sys.argv[2]
started_utc = sys.argv[3]
ended_utc = sys.argv[4]
started_ns = int(sys.argv[5])
ended_ns = int(sys.argv[6])
exit_code = int(sys.argv[7])
working_directory = sys.argv[8]
log = sys.argv[9]
argv = sys.argv[10:]
record = {
    "id": identifier,
    "argv": argv,
    "working_directory": working_directory,
    "started_utc": started_utc,
    "ended_utc": ended_utc,
    "duration_seconds": round(max(0, ended_ns - started_ns) / 1_000_000_000, 6),
    "exit_code": exit_code,
    "log": log,
}
ledger.parent.mkdir(parents=True, exist_ok=True)
with ledger.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
PY
}

run_logged() {
  local identifier="$1"
  local log_path="$2"
  shift 2
  local started_utc
  local ended_utc
  local started_ns
  local ended_ns
  local exit_code
  local working_directory
  started_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  started_ns="$(date +%s%N)"
  working_directory="$(pwd -P)"
  mkdir -p "$(dirname "$log_path")"
  set +e
  "$@" > "$log_path" 2>&1
  exit_code=$?
  set -e
  ended_ns="$(date +%s%N)"
  ended_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  record_command \
    "$identifier" "$started_utc" "$ended_utc" "$started_ns" "$ended_ns" \
    "$exit_code" "$working_directory" "$log_path" "$@"
  return "$exit_code"
}

write_command_report() {
  [[ -d "$STAGING_DIR/reports/full" ]] || return 0
  "$PYTHON_BIN" - "$COMMAND_LEDGER" "$COMMAND_REPORT" "$RUN_ID" "$CONTROL_DIR" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import sys

ledger = Path(sys.argv[1])
output = Path(sys.argv[2])
records = []
if ledger.is_file():
    for line_number, raw in enumerate(ledger.read_text(encoding="utf-8").splitlines(), 1):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"invalid command ledger line {line_number}: {exc}") from exc
        if not isinstance(value, dict):
            raise SystemExit(f"command ledger line {line_number} is not an object")
        records.append(value)
for sequence, record in enumerate(records, 1):
    record["sequence"] = sequence
    log = Path(str(record.get("log", ""))).resolve(strict=True)
    staging = (Path(sys.argv[4]) / "artifact-staging").resolve(strict=True)
    try:
        record["log"] = log.relative_to(staging).as_posix()
    except ValueError as exc:
        raise SystemExit(f"command log lies outside artifact staging: {log}") from exc
failed = sum(record.get("exit_code") != 0 for record in records)
report = {
    "schema_version": "nndv-0.7.0-full-command-report-1",
    "release": "0.7.0 Beta — 3D Neural Figure & UX Completion",
    "run_id": sys.argv[3],
    "controller_root": sys.argv[4],
    "scope": "commands completed before atomic artifact finalization",
    "fresh_control_root": True,
    "old_artifacts_used_as_current_output": False,
    "command_count": len(records),
    "completed": sum(record.get("exit_code") == 0 for record in records),
    "failed": failed,
    "commands": records,
}
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

finish() {
  local status=$?
  set +e
  write_command_report
  if [[ -n "$BROWSER_TMP_ROOT" && -d "$BROWSER_TMP_ROOT" ]]; then
    "$PYTHON_BIN" - "$BROWSER_TMP_ROOT" <<'PY'
from pathlib import Path
import shutil
import sys

path = Path(sys.argv[1])
temporary = Path("/tmp").resolve(strict=True)
if path.is_symlink():
    raise SystemExit(f"refusing to clean a symlinked browser temporary path: {path}")
resolved = path.resolve(strict=True)
if resolved.parent != temporary or not resolved.name.startswith("n7b-"):
    raise SystemExit(f"refusing to clean unexpected browser temporary path: {resolved}")
shutil.rmtree(resolved)
PY
  fi
  if [[ "$SUCCESS" -eq 1 && "$status" -eq 0 && "${NNDV_KEEP_DIAGNOSTICS:-0}" != "1" ]]; then
    "$PYTHON_BIN" - "$CONTROL_DIR" "$TEMPORARY_ROOT" <<'PY'
from pathlib import Path
import shutil
import sys

path = Path(sys.argv[1])
temporary = Path(sys.argv[2]).resolve(strict=True)
if path.is_symlink():
    raise SystemExit(f"refusing to clean a symlinked controller path: {path}")
resolved = path.resolve(strict=True)
if resolved.parent != temporary or not resolved.name.startswith("nndv-070-full-"):
    raise SystemExit(f"refusing to clean unexpected full controller path: {resolved}")
shutil.rmtree(resolved)
PY
  else
    echo "0.7.0 full diagnostics retained: $CONTROL_DIR" >&2
  fi
  set -e
}
trap finish EXIT

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python verification environment not found: $PYTHON_BIN" >&2
  exit 1
fi
if [[ ! -d "$PARENT_SOURCE_DIR" || -L "$PARENT_SOURCE_DIR" ]]; then
  echo "frozen 0.6.1 source root is absent or unsafe: $PARENT_SOURCE_DIR" >&2
  exit 1
fi
if [[ ! -d "$AUTHORITATIVE_061_ARTIFACT" || -L "$AUTHORITATIVE_061_ARTIFACT" ]]; then
  echo "authoritative 0.6.1 artifact is absent or unsafe: $AUTHORITATIVE_061_ARTIFACT" >&2
  exit 1
fi
if [[ "$(basename "$AUTHORITATIVE_061_ARTIFACT")" != "$PARENT_RUN_ID" ]]; then
  echo "authoritative parent artifact is not the pinned 0.6.1 run: $AUTHORITATIVE_061_ARTIFACT" >&2
  exit 1
fi
if [[ ! -f "$PARENT_FIGURE_PERFORMANCE" || -L "$PARENT_FIGURE_PERFORMANCE" ]]; then
  echo "authoritative parent Figure performance report is absent or unsafe" >&2
  exit 1
fi
if [[ -L "$PROJECT_DIR/artifacts" \
  || -L "$ARTIFACT_ROOT" \
  || ( -e "$PROJECT_DIR/artifacts" && ! -d "$PROJECT_DIR/artifacts" ) \
  || ( -e "$ARTIFACT_ROOT" && ! -d "$ARTIFACT_ROOT" ) ]]; then
  echo "0.7.0 artifact root is unsafe: $ARTIFACT_ROOT" >&2
  exit 1
fi
mkdir -p "$ARTIFACT_ROOT"
if [[ -L "$ARTIFACT_ROOT" || ! -d "$ARTIFACT_ROOT" ]]; then
  echo "0.7.0 artifact root could not be created safely: $ARTIFACT_ROOT" >&2
  exit 1
fi
BROWSER_TMP_ROOT="$(mktemp -d "/tmp/n7b-XXXXXX")"
if [[ -e "$ARTIFACT_ROOT/$RUN_ID" \
  || -e "$ARTIFACT_ROOT/$RUN_ID.inventory-verification.json" \
  || -e "$ARTIFACT_ROOT/$RUN_ID.finalize.log" \
  || -e "$ARTIFACT_ROOT/$RUN_ID.verify.log" ]]; then
  echo "refusing to overwrite 0.7.0 run: $RUN_ID" >&2
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
  "$STAGING_DIR/reports/migration" \
  "$STAGING_DIR/reports/visual" \
  "$STAGING_DIR/reports/source" \
  "$STAGING_DIR/reports/full" \
  "$STAGING_DIR/evidence/scene-studio" \
  "$STAGING_DIR/exports" \
  "$STAGING_DIR/screenshots/responsive" \
  "$STAGING_DIR/distributions" \
  "$BROWSER_TMP_ROOT/editor" \
  "$BROWSER_TMP_ROOT/responsive" \
  "$BROWSER_TMP_ROOT/semantic" \
  "$BROWSER_TMP_ROOT/product" \
  "$BROWSER_TMP_ROOT/trial" \
  "$BROWSER_TMP_ROOT/figure" \
  "$BROWSER_TMP_ROOT/scene" \
  "$WORK_DIR/quick" \
  "$WORK_DIR/editor/runtime" \
  "$WORK_DIR/semantic/runtime" \
  "$WORK_DIR/product/runtime" \
  "$WORK_DIR/trial/runtime" \
  "$WORK_DIR/figure/runtime" \
  "$WORK_DIR/package-install"

cd "$PROJECT_DIR"
run_logged clean-0.7.0-source-snapshot "$STAGING_DIR/logs/source-snapshot.log" \
  "$PYTHON_BIN" scripts/create_clean_snapshot.py "$PROJECT_DIR" "$SNAPSHOT_DIR" \
  --allowlist verification/source-allowlist-0.7.0.json \
  --reject-symlinks \
  --output "$SOURCE_REPORT"

run_logged independent-parent-0.6.1-source-snapshot "$STAGING_DIR/logs/parent-source-snapshot.log" \
  "$PYTHON_BIN" "$PARENT_SOURCE_DIR/scripts/create_clean_snapshot.py" \
  "$PARENT_SOURCE_DIR" "$PARENT_SNAPSHOT_DIR" \
  --allowlist verification/source-allowlist-0.6.1.json \
  --reject-symlinks \
  --output "$PARENT_SOURCE_REPORT"

run_logged parent-0.6.1-source-identity "$STAGING_DIR/logs/parent-source-identity.log" \
  "$PYTHON_BIN" - "$PARENT_SOURCE_REPORT" "$PARENT_SOURCE_FILES" "$PARENT_SOURCE_DIGEST" <<'PY'
import json
from pathlib import Path
import sys

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
expected_files = int(sys.argv[2])
expected_digest = sys.argv[3]
if not (
    report.get("passed") is True
    and report.get("release") == "0.6.1"
    and report.get("file_count") == expected_files
    and len(report.get("files", {})) == expected_files
    and report.get("source_tree_digest") == expected_digest
    and report.get("forbidden_paths") == []
):
    raise SystemExit(
        "frozen 0.6.1 source identity mismatch: "
        + json.dumps(
            {
                "passed": report.get("passed"),
                "release": report.get("release"),
                "file_count": report.get("file_count"),
                "source_tree_digest": report.get("source_tree_digest"),
                "forbidden_paths": report.get("forbidden_paths"),
            },
            sort_keys=True,
        )
    )
print(f"parent source PASS files={expected_files} digest={expected_digest}")
PY

cd "$SNAPSHOT_DIR"
run_logged npm-ci-offline "$STAGING_DIR/logs/npm-ci.log" \
  npm ci --offline --ignore-scripts --no-audit --no-fund

export PYTHONPATH="$SNAPSHOT_DIR:$SNAPSHOT_DIR/src"
export PYTHONPYCACHEPREFIX="$WORK_DIR/pycache"
# Keep bytecode outside the clean snapshot while allowing later fresh
# subprocesses to reuse caches produced by this same controller.  Disabling
# writes here forces every browser server to recompile large optional stacks
# such as PyTorch and makes cold-start latency depend on source compilation.
unset PYTHONDONTWRITEBYTECODE
export MPLCONFIGDIR="$WORK_DIR/matplotlib"
export TEXMFVAR="$WORK_DIR/texmf-var"
export TEXMFCONFIG="$WORK_DIR/texmf-config"
export JAX_PLATFORMS=cpu
export CUDA_VISIBLE_DEVICES=''
mkdir -p "$MPLCONFIGDIR" "$TEXMFVAR" "$TEXMFCONFIG"

run_logged authoritative-parent-0.6.1-artifact-read-only "$STAGING_DIR/logs/parent-artifact-verification.log" \
  "$PYTHON_BIN" "$PARENT_SNAPSHOT_DIR/scripts/verify_release_artifact_0_6_1.py" \
  "$AUTHORITATIVE_061_ARTIFACT" --output "$PARENT_ARTIFACT_REPORT"

run_logged authoritative-parent-0.6.1-artifact-identity "$STAGING_DIR/logs/parent-artifact-identity.log" \
  "$PYTHON_BIN" - "$PARENT_ARTIFACT_REPORT" "$PARENT_RUN_ID" "$PARENT_SOURCE_FILES" "$PARENT_SOURCE_DIGEST" <<'PY'
import json
from pathlib import Path
import sys

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if not (
    report.get("status") == "PASS"
    and report.get("run_id") == sys.argv[2]
    and report.get("source_file_count") == int(sys.argv[3])
    and report.get("source_digest") == sys.argv[4]
    and report.get("failures") == []
):
    raise SystemExit("authoritative 0.6.1 artifact identity or inventory verification failed")
print(f"parent artifact PASS run_id={report['run_id']} files={report['source_file_count']}")
PY

run_logged quick-0.7.0 "$STAGING_DIR/logs/quick.log" \
  env \
  NN_DAVINCI_PYTHON="$PYTHON_BIN" \
  NNDV_QUICK_RUN_DIR="$WORK_DIR/quick" \
  NNDV_KEEP_DIAGNOSTICS=1 \
  ./scripts/verify-quick-0.7.0.sh

for quick_report in \
  quick-verification.json \
  python-tests.json \
  collected-test-ids.txt \
  core-coverage.json \
  expanded-core-coverage.json \
  scene-core-coverage.json \
  all-package-coverage.json \
  coverage-summary.json
do
  cp "$WORK_DIR/quick/$quick_report" "$STAGING_DIR/reports/quick/$quick_report"
done

run_logged release-audit-0.7.0 "$STAGING_DIR/logs/release-audit.log" \
  "$PYTHON_BIN" scripts/audit_release_0_7.py \
  --project-root "$SNAPSHOT_DIR" \
  --output "$STAGING_DIR/reports/docs/release-audit.json"

run_logged project-1.3-to-1.4-migration "$STAGING_DIR/logs/project-migration.log" \
  "$PYTHON_BIN" scripts/verify_scene_migration_0_7.py \
  --project-root "$SNAPSHOT_DIR" \
  --output "$STAGING_DIR/reports/migration/project-1.3-to-1.4.json"

run_logged scene-studio-performance-three-repeats "$STAGING_DIR/logs/scene-performance.log" \
  "$PYTHON_BIN" scripts/benchmark_scene_studio_0_7.py \
  --output "$STAGING_DIR/reports/performance/scene-studio.json" \
  --baseline-figure-report "$PARENT_FIGURE_PERFORMANCE" \
  --repeats 3

run_logged fresh-fourteen-case-scene-generation "$STAGING_DIR/logs/scene-artifact-generation.log" \
  "$PYTHON_BIN" scripts/generate_scene_artifacts_0_7.py \
  --output-dir "$STAGING_DIR/exports/scene-corpus" \
  --report "$STAGING_DIR/reports/exports/scene-artifacts.json"

run_logged independent-scene-artifact-validation "$STAGING_DIR/logs/scene-artifact-validation.log" \
  "$PYTHON_BIN" scripts/validate_scene_artifacts_0_7.py \
  --output-dir "$STAGING_DIR/exports/scene-corpus" \
  --generation-report "$STAGING_DIR/reports/exports/scene-artifacts.json" \
  --report "$STAGING_DIR/reports/exports/scene-artifacts-validation.json"

run_logged e2e-editor "$STAGING_DIR/logs/e2e-editor.log" \
  env \
  TMPDIR="$BROWSER_TMP_ROOT/editor" \
  NNDV_PYTHON="$PYTHON_BIN" \
  NNDV_TASK_ROOT="$WORK_DIR/editor/tasks" \
  NNDV_E2E_DIR="$WORK_DIR/editor/runtime" \
  NNDV_E2E_REPORT="$STAGING_DIR/reports/e2e/editor.json" \
  NNDV_KEEP_DIAGNOSTICS=1 \
  npm run e2e

run_logged e2e-responsive "$STAGING_DIR/logs/e2e-responsive.log" \
  env \
  TMPDIR="$BROWSER_TMP_ROOT/responsive" \
  NNDV_PYTHON="$PYTHON_BIN" \
  NNDV_TASK_ROOT="$WORK_DIR/responsive/tasks" \
  NNDV_RESPONSIVE_SCREENSHOT_DIR="$STAGING_DIR/screenshots/responsive" \
  NNDV_RESPONSIVE_E2E_REPORT="$STAGING_DIR/reports/e2e/responsive.json" \
  NNDV_KEEP_DIAGNOSTICS=1 \
  npm run e2e:responsive

run_logged e2e-semantic "$STAGING_DIR/logs/e2e-semantic.log" \
  env \
  TMPDIR="$BROWSER_TMP_ROOT/semantic" \
  NNDV_PYTHON="$PYTHON_BIN" \
  NNDV_TASK_ROOT="$WORK_DIR/semantic/tasks" \
  NNDV_SEMANTIC_E2E_DIR="$WORK_DIR/semantic/runtime" \
  NNDV_SEMANTIC_E2E_REPORT="$STAGING_DIR/reports/e2e/semantic.json" \
  NNDV_KEEP_DIAGNOSTICS=1 \
  npm run e2e:semantic

run_logged e2e-product "$STAGING_DIR/logs/e2e-product.log" \
  env \
  TMPDIR="$BROWSER_TMP_ROOT/product" \
  NNDV_PYTHON="$PYTHON_BIN" \
  NNDV_TASK_ROOT="$WORK_DIR/product/tasks" \
  NNDV_PRODUCT_E2E_DIR="$WORK_DIR/product/runtime" \
  NNDV_PRODUCT_E2E_REPORT="$STAGING_DIR/reports/e2e/product.json" \
  NNDV_KEEP_DIAGNOSTICS=1 \
  npm run e2e:product

run_logged e2e-trial "$STAGING_DIR/logs/e2e-trial.log" \
  env \
  TMPDIR="$BROWSER_TMP_ROOT/trial" \
  NNDV_PYTHON="$PYTHON_BIN" \
  NNDV_TASK_ROOT="$WORK_DIR/trial/tasks" \
  NNDV_TRIAL_E2E_DIR="$WORK_DIR/trial/runtime" \
  NNDV_TRIAL_E2E_REPORT="$STAGING_DIR/reports/e2e/trial.json" \
  NNDV_KEEP_DIAGNOSTICS=1 \
  npm run e2e:trial

run_logged e2e-figure-studio "$STAGING_DIR/logs/e2e-figure-studio.log" \
  env \
  TMPDIR="$BROWSER_TMP_ROOT/figure" \
  NNDV_PYTHON="$PYTHON_BIN" \
  NNDV_TASK_ROOT="$WORK_DIR/figure/tasks" \
  NNDV_FIGURE_E2E_DIR="$WORK_DIR/figure/runtime" \
  NNDV_FIGURE_E2E_REPORT="$STAGING_DIR/reports/e2e/figure-studio.json" \
  NNDV_KEEP_DIAGNOSTICS=1 \
  npm run e2e:figure

run_logged e2e-scene-studio "$STAGING_DIR/logs/e2e-scene-studio.log" \
  env \
  TMPDIR="$BROWSER_TMP_ROOT/scene" \
  NNDV_PYTHON="$PYTHON_BIN" \
  NNDV_TASK_ROOT="$WORK_DIR/scene/tasks" \
  NNDV_SCENE_E2E_DIR="$STAGING_DIR/evidence/scene-studio" \
  NNDV_SCENE_E2E_REPORT="$STAGING_DIR/reports/e2e/scene-studio.json" \
  NNDV_KEEP_DIAGNOSTICS=1 \
  npm run e2e:scene

run_logged independent-scene-visual-validation "$STAGING_DIR/logs/scene-visual-validation.log" \
  "$PYTHON_BIN" scripts/validate_scene_visual_evidence_0_7.py \
  "$STAGING_DIR/reports/e2e/scene-studio.json" \
  --artifact-root "$STAGING_DIR/evidence/scene-studio/scene-studio-artifacts" \
  --screenshots-root "$STAGING_DIR/evidence/scene-studio/scene-studio-artifacts/screenshots" \
  --output "$STAGING_DIR/reports/visual/scene-studio.json"

run_logged package-build "$STAGING_DIR/logs/package-build.log" \
  "$PYTHON_BIN" -m build --no-isolation --outdir "$STAGING_DIR/distributions" .

run_logged wheel-sdist-install-0.7.0 "$STAGING_DIR/logs/package-install.log" \
  "$PYTHON_BIN" scripts/verify_package_install.py \
  "$STAGING_DIR/distributions" "$WORK_DIR/package-install/venvs" \
  --project-root "$SNAPSHOT_DIR" \
  --expected-version 0.7.0 \
  --output "$STAGING_DIR/reports/packaging/package-install.json"

run_logged environment-manifest "$STAGING_DIR/logs/environment.log" \
  "$PYTHON_BIN" scripts/write_environment_manifest.py \
  "$STAGING_DIR/reports/environment.json"

write_command_report

"$PYTHON_BIN" scripts/finalize_artifact_0_7.py \
  --staging "$STAGING_DIR" \
  --artifact-root "$ARTIFACT_ROOT" \
  --run-id "$RUN_ID" \
  --started-utc "$STARTED_UTC" \
  --started-epoch "$STARTED_EPOCH" \
  --project-root "$SNAPSHOT_DIR" \
  > "$ARTIFACT_ROOT/$RUN_ID.finalize.log" 2>&1

"$PYTHON_BIN" scripts/verify_release_artifact_0_7.py "$ARTIFACT_ROOT/$RUN_ID" \
  --output "$ARTIFACT_ROOT/$RUN_ID.inventory-verification.json" \
  > "$ARTIFACT_ROOT/$RUN_ID.verify.log" 2>&1

"$PYTHON_BIN" - \
  "$ARTIFACT_ROOT/$RUN_ID" \
  "$ARTIFACT_ROOT/$RUN_ID.inventory-verification.json" <<'PY'
import json
from pathlib import Path
import sys

artifact = Path(sys.argv[1]).resolve(strict=True)
verification = json.loads((artifact / "verification.json").read_text(encoding="utf-8"))
inventory = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
python = verification["python"]
scene = verification["scene"]
chrome = verification["chrome"]
source = verification["source"]
print(
    "NNDV_070_FULL_RESULT "
    f"status={verification['status']} run_id={verification['run_id']} "
    f"python={python['passed']}/{python['collected']} failed={python['failed']} "
    f"errors={python['errors']} skipped={python['skipped']} deselected={python['deselected']} "
    f"inherited_0_6_1={python['inherited_0_6_1_tests']} "
    f"scene_cases={scene['cases']} scene_exports={scene['exports']} "
    f"scene_ir={scene['scene_ir']} project_schema={scene['project_schema']} "
    f"chrome_suites={chrome['suites']} scene_browser_errors={chrome['scene_browser_errors']} "
    f"parent_run={verification['parent']['run_id']} parent_source_files={verification['parent']['source_files']} "
    f"source_files={source['file_count']} source_digest={source['source_tree_digest']} "
    f"manifest_entries={inventory['manifest_entries']} manifest_sha256={inventory['manifest_sha256']} "
    f"elapsed={verification['elapsed_seconds']:.3f}s artifact={artifact}"
)
PY

SUCCESS=1
