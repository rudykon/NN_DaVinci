#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE_DIR="$(cd "$PROJECT_DIR/.." && pwd)"
PYTHON_BIN="${NN_DAVINCI_PYTHON:-$WORKSPACE_DIR/envs/python-tools/bin/python}"
DEVTOOLS_DIR="${NN_DAVINCI_DEVTOOLS:-$PROJECT_DIR/.devtools}"
EXPECTED_ANCHOR_SHA256="10979b1d7112b7639207405dffe23f534762a02fb047b61540c5e04c955a3224"
SUCCESS=0

if [[ "${NNDV_IN_CLEAN_SNAPSHOT:-0}" != "1" ]]; then
  CONTROL_DIR="$(mktemp -d "${TMPDIR:-/tmp}/nndv-052-controller-XXXXXX")"
  SNAPSHOT_DIR="$CONTROL_DIR/source-$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')/NN_DaVinci"
  SNAPSHOT_REPORT="$CONTROL_DIR/source-snapshot.json"
  finish_outer() {
    status=$?
    if [[ "$SUCCESS" -eq 1 && "$status" -eq 0 && "${NNDV_KEEP_DIAGNOSTICS:-0}" != "1" ]]; then
      "$PYTHON_BIN" -c 'import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)' "$CONTROL_DIR"
    else
      echo "Full verification controller diagnostics: $CONTROL_DIR" >&2
    fi
  }
  trap finish_outer EXIT
  "$PYTHON_BIN" scripts/verify_trust_anchor.py --trust-anchor "$PROJECT_DIR/docs/TRUST_ANCHOR_0.2.2.json" \
    --expected-anchor-sha256 "$EXPECTED_ANCHOR_SHA256" --project-root "$PROJECT_DIR" \
    --output "$CONTROL_DIR/pre-snapshot-trust.json"
  "$PYTHON_BIN" scripts/create_clean_snapshot.py "$PROJECT_DIR" "$SNAPSHOT_DIR" --output "$SNAPSHOT_REPORT"
  mkdir -p "$CONTROL_DIR/npm-cache"
  (
    cd "$SNAPSHOT_DIR"
    npm ci --ignore-scripts --cache "$CONTROL_DIR/npm-cache"
  ) > "$CONTROL_DIR/npm-ci.log" 2>&1
  NNDV_IN_CLEAN_SNAPSHOT=1 \
    NNDV_ORIGINAL_PROJECT_DIR="$PROJECT_DIR" \
    NNDV_ARTIFACT_ROOT="$PROJECT_DIR/artifacts/v0.5.2" \
    NNDV_SNAPSHOT_REPORT="$SNAPSHOT_REPORT" \
    NNDV_NPM_CI_LOG="$CONTROL_DIR/npm-ci.log" \
    NNDV_CONTROLLER_DIR="$CONTROL_DIR" \
    NN_DAVINCI_PYTHON="$PYTHON_BIN" \
    NN_DAVINCI_DEVTOOLS="$DEVTOOLS_DIR" \
    "$SNAPSHOT_DIR/scripts/verify-full.sh"
  SUCCESS=1
  exit 0
fi

if [[ -z "${NNDV_ARTIFACT_ROOT:-}" || -z "${NNDV_SNAPSHOT_REPORT:-}" || -z "${NNDV_CONTROLLER_DIR:-}" ]]; then
  echo "inner full verification requires clean-snapshot controller paths" >&2
  exit 1
fi
RUN_ID="${NNDV_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')}"
STARTED_EPOCH="$(date +%s)"
STARTED_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/nndv-052-non-authoritative-${RUN_ID}-XXXXXX")"
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/nndv-052-work-${RUN_ID}-XXXXXX")"
OUTSIDE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/nndv-052-logs-${RUN_ID}-XXXXXX")"
ARTIFACT_ROOT="$NNDV_ARTIFACT_ROOT"
FINAL_DIR="$ARTIFACT_ROOT/$RUN_ID"
COPY_DIR="$ARTIFACT_ROOT/.sealed-copy-$RUN_ID"
COPY_ATTESTATION="$OUTSIDE_DIR/copy-attestation.json"
PERSISTED_COPY_ATTESTATION="$ARTIFACT_ROOT/$RUN_ID.copy-attestation.json"
FINAL_ATTESTATION="$ARTIFACT_ROOT/$RUN_ID.attestation.json"
RELEASE_DECISION="$ARTIFACT_ROOT/$RUN_ID.release-decision.json"
OUTER_CHECKSUM="$ARTIFACT_ROOT/$RUN_ID.outer.sha256"
mkdir -p "$ARTIFACT_ROOT"
if [[ -e "$FINAL_DIR" || -e "$COPY_DIR" ]]; then
  echo "refusing to overwrite a verification path: $FINAL_DIR or $COPY_DIR" >&2
  exit 1
fi

finish_inner() {
  status=$?
  if [[ "$SUCCESS" -eq 1 && "$status" -eq 0 && "${NNDV_KEEP_DIAGNOSTICS:-0}" != "1" ]]; then
    "$PYTHON_BIN" -c 'import shutil,sys; [shutil.rmtree(p, ignore_errors=True) for p in sys.argv[1:]]' "$STAGING_DIR" "$WORK_DIR" "$OUTSIDE_DIR"
  else
    echo "Full verification failed; non-authoritative staging retained: $STAGING_DIR" >&2
    echo "Full verification work/logs retained: $WORK_DIR $OUTSIDE_DIR" >&2
  fi
}
trap finish_inner EXIT

NNDV_NPM_CI_LOG="${NNDV_NPM_CI_LOG:-}" \
  "$PROJECT_DIR/scripts/run_full_workload.sh" "$STAGING_DIR" "$WORK_DIR" "$NNDV_SNAPSHOT_REPORT" "$RUN_ID" \
  > "$OUTSIDE_DIR/full.log" 2>&1
cp "$OUTSIDE_DIR/full.log" "$STAGING_DIR/logs/full.log"

"$PYTHON_BIN" scripts/finalize_verification.py "$STAGING_DIR" \
  --started-epoch "$STARTED_EPOCH" --started-utc "$STARTED_UTC" --run-id "$RUN_ID" \
  --final-relative-root "artifacts/v0.5.2/$RUN_ID" --output "$STAGING_DIR/verification.json" \
  > "$OUTSIDE_DIR/finalize.log" 2>&1
cp "$OUTSIDE_DIR/finalize.log" "$STAGING_DIR/logs/finalize.log"

"$PYTHON_BIN" scripts/seal_evidence.py "$STAGING_DIR" > "$OUTSIDE_DIR/seal.log"
cp -a "$STAGING_DIR" "$COPY_DIR"

# The first replay must not inherit the clean source snapshot, npm cache, or
# any other controller-owned input.  Validate the narrowly-scoped temporary
# target before removing it, then run both replays exclusively from the sealed
# copy.  The optional assertion is diagnostic only; the verifier never reads
# from this path.
cd "$OUTSIDE_DIR"
"$PYTHON_BIN" - "$NNDV_CONTROLLER_DIR" <<'PY'
import pathlib
import shutil
import sys

controller = pathlib.Path(sys.argv[1]).resolve()
temporary_root = pathlib.Path("/tmp").resolve()
if controller.parent != temporary_root or not controller.name.startswith("nndv-052-controller-"):
    raise SystemExit(f"refusing to remove unexpected controller path: {controller}")
if not controller.is_dir():
    raise SystemExit(f"verification controller is not a directory: {controller}")
shutil.rmtree(controller)
PY
"$PYTHON_BIN" "$COPY_DIR/source/replay-source/scripts/verify_sealed_bundle.py" "$COPY_DIR" \
  --expected-anchor-sha256 "$EXPECTED_ANCHOR_SHA256" --assert-absent "$NNDV_CONTROLLER_DIR" \
  --output "$COPY_ATTESTATION" \
  > "$OUTSIDE_DIR/copy-verifier.log"
cp "$COPY_ATTESTATION" "$PERSISTED_COPY_ATTESTATION"
mv "$COPY_DIR" "$FINAL_DIR"
"$PYTHON_BIN" "$FINAL_DIR/source/replay-source/scripts/verify_sealed_bundle.py" "$FINAL_DIR" \
  --expected-anchor-sha256 "$EXPECTED_ANCHOR_SHA256" --assert-absent "$NNDV_CONTROLLER_DIR" \
  --output "$FINAL_ATTESTATION" \
  > "$OUTSIDE_DIR/final-verifier.log"
"$PYTHON_BIN" "$FINAL_DIR/source/replay-source/scripts/write_release_decision.py" \
  --verification "$FINAL_DIR/verification.json" --copy-attestation "$PERSISTED_COPY_ATTESTATION" \
  --final-attestation "$FINAL_ATTESTATION" --output "$RELEASE_DECISION" \
  > "$OUTSIDE_DIR/release-decision.log"
"$PYTHON_BIN" - "$PERSISTED_COPY_ATTESTATION" "$FINAL_ATTESTATION" "$RELEASE_DECISION" "$OUTER_CHECKSUM" <<'PY'
import hashlib, pathlib, sys
copy, final, decision, output = map(pathlib.Path, sys.argv[1:])
output.write_text("".join(
    f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
    for path in (copy, final, decision)
), encoding="utf-8")
PY

"$PYTHON_BIN" - "$FINAL_DIR/verification.json" "$FINAL_DIR/SHA256SUMS" "$FINAL_DIR" "$FINAL_ATTESTATION" "$RELEASE_DECISION" <<'PY'
import hashlib, json, pathlib, sys
verification_path, sums_path, evidence_path, attestation_path, decision_path = map(pathlib.Path, sys.argv[1:])
report = json.loads(verification_path.read_text(encoding="utf-8"))
attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
decision = json.loads(decision_path.read_text(encoding="utf-8"))
tests, matrix, counts = report["tests"], report["acceptance_matrix"], report["counts"]
print(
    "NNDV_FULL_RESULT "
    f"runner_result={report['runner_result']} pre_seal_audit={report['pre_seal_audit']} release_audit={decision['release_audit']} "
    f"checks={counts['checks']} python_tests={counts['python_tests']} "
    f"inherited_0_3_tests={tests['inherited_0_3_tests']} product_0_4_tests={tests['product_0_4_tests']} product_0_5_tests={tests['product_0_5_tests']} "
    f"artifact_assertions={counts['artifact_assertions']} font_tikz_checks={counts['font_tikz_checks']} "
    f"packaging_checks={counts['packaging_checks']} e2e_scenarios={counts['e2e_scenarios']} "
    f"collected={tests['collected']} passed={tests['passed']} failed={tests['failed']} errors={tests['errors']} "
    f"skipped={tests['skipped']} deselected={tests['deselected']} frozen_ids={tests['frozen_ids']} "
    f"matrix_blockers={matrix['release_blocker_checks']} matrix_passed={matrix['counts']['passed']} "
    f"product_checks={report['product_0_4']['acceptance']['passed']} product_e2e_assertions={report['e2e']['product_workflow']['assertions']} "
    f"trial_checks={report['product_0_5']['trial_kit_acceptance']['counts']['passed']} trial_e2e_assertions={report['e2e']['trial_workflow']['assertions']} "
    f"post_seal={attestation['passed']} sha256sums_sha256={hashlib.sha256(sums_path.read_bytes()).hexdigest()} "
    f"elapsed={report['elapsed_seconds']:.3f}s evidence={evidence_path.resolve()}"
)
PY
SUCCESS=1
