#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE_DIR="$(cd "$PROJECT_DIR/.." && pwd)"
PYTHON_BIN="${NN_DAVINCI_PYTHON:-$WORKSPACE_DIR/envs/python-tools/bin/python}"
DEVTOOLS_DIR="${NN_DAVINCI_DEVTOOLS:-$PROJECT_DIR/.devtools}"
EVIDENCE_DIR="$1"
WORK_DIR="$2"
SNAPSHOT_REPORT="$3"
RUN_ID="$4"
EXPECTED_ANCHOR_SHA256="10979b1d7112b7639207405dffe23f534762a02fb047b61540c5e04c955a3224"

export PYTHONPATH="$PROJECT_DIR:$PROJECT_DIR/src:$DEVTOOLS_DIR${PYTHONPATH:+:$PYTHONPATH}"
export MPLCONFIGDIR="$WORK_DIR/matplotlib"
export TEXMFVAR="$WORK_DIR/texmf-var"
export TEXMFCONFIG="$WORK_DIR/texmf-config"
export JAX_PLATFORMS=cpu
export CUDA_VISIBLE_DEVICES=''
export PIP_CACHE_DIR="$WORK_DIR/pip-cache"
mkdir -p "$EVIDENCE_DIR"/{logs,tests,coverage,stress,visual,e2e,packaging,docs,requirements,source,matrix,exports} \
  "$EVIDENCE_DIR/product"/{real-models,paper-examples,publication-quality,scientific-fidelity,diff,performance} \
  "$EVIDENCE_DIR/trial"/{external-models,venue-proof,kit} \
  "$WORK_DIR"/{matplotlib,texmf-var,texmf-config,quick,compiled-tikz,font-reports,e2e-downloads,semantic-e2e-downloads,product-e2e-downloads,trial-e2e-downloads,package-install}
cd "$PROJECT_DIR"

"$PYTHON_BIN" scripts/verify_trust_anchor.py --trust-anchor docs/TRUST_ANCHOR_0.2.2.json \
  --expected-anchor-sha256 "$EXPECTED_ANCHOR_SHA256" --project-root "$PROJECT_DIR" \
  --output "$EVIDENCE_DIR/tests/trust-anchor-check.json" > "$EVIDENCE_DIR/logs/trust-anchor.log"
cp verification/fixtures/python-test-ids-0.2.0.txt "$EVIDENCE_DIR/tests/frozen-test-ids.txt"

NNDV_QUICK_RUN_DIR="$WORK_DIR/quick" scripts/verify-quick.sh > "$EVIDENCE_DIR/logs/quick.log" 2>&1
cp "$WORK_DIR/quick/python-tests.json" "$EVIDENCE_DIR/tests/python-tests.json"
cp "$WORK_DIR/quick/collected-test-ids.txt" "$EVIDENCE_DIR/tests/collected-test-ids.txt"
cp "$WORK_DIR/quick/core-coverage.json" "$EVIDENCE_DIR/coverage/core.json"
cp "$WORK_DIR/quick/expanded-core-coverage.json" "$EVIDENCE_DIR/coverage/expanded-core.json"
cp "$WORK_DIR/quick/all-package-coverage.json" "$EVIDENCE_DIR/coverage/all-package.json"
cp "$WORK_DIR/quick/coverage-summary.json" "$EVIDENCE_DIR/coverage/summary.json"
cp "$WORK_DIR/quick/quick-verification.json" "$EVIDENCE_DIR/quick-verification.json"
"$PYTHON_BIN" - "$EVIDENCE_DIR/coverage/summary.json" "$EVIDENCE_DIR/coverage/manifest-diff.json" <<'PY'
import json, pathlib, sys
summary = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
pathlib.Path(sys.argv[2]).write_text(json.dumps({
    "old_core_denominator_diff": summary["core_denominator_diff"],
    "all_package_total_denominator_diff": summary["all_package_total_denominator_diff"],
    "old_core_files": summary["core_files"], "expanded_core_files": summary["expanded_core_files"],
    "coverage_exclusions": summary["coverage_exclusions"],
}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
cp requirements/verification-linux-x86_64-py313-0.2.3.lock "$EVIDENCE_DIR/requirements/"
cp verification/verification-lock-metadata-0.2.3.json "$EVIDENCE_DIR/requirements/"

"$PYTHON_BIN" scripts/generate_acceptance_formats.py "$EVIDENCE_DIR/exports" > "$EVIDENCE_DIR/logs/export-generation.log"
"$PYTHON_BIN" scripts/validate_acceptance_artifacts.py "$EVIDENCE_DIR/exports" \
  --output "$EVIDENCE_DIR/exports/artifact-validation.json" > "$EVIDENCE_DIR/logs/artifact-validation.log"
mkdir -p "$WORK_DIR/export-compiled"
"$PYTHON_BIN" scripts/check_pdf_fonts.py "$EVIDENCE_DIR/exports/resnet-v02.pdf" \
  --report "$EVIDENCE_DIR/logs/export-pdffonts.log"
pdflatex -halt-on-error -interaction=nonstopmode -output-directory="$WORK_DIR/export-compiled" \
  "$EVIDENCE_DIR/exports/resnet-v02.tex" > "$EVIDENCE_DIR/logs/export-pdflatex.log"
test -s "$WORK_DIR/export-compiled/resnet-v02.pdf"

"$PYTHON_BIN" scripts/verify_visual_fixtures.py --output "$EVIDENCE_DIR/visual/fixture-integrity.json" \
  > "$EVIDENCE_DIR/logs/visual-integrity.log"
"$PYTHON_BIN" scripts/generate_visual_samples.py "$EVIDENCE_DIR/visual/samples" --run-id "$RUN_ID" \
  > "$EVIDENCE_DIR/logs/visual-generation.log"
VISUAL_SVGS=(
  "$EVIDENCE_DIR/visual/samples/resnet.svg" "$EVIDENCE_DIR/visual/samples/transformer.svg"
  "$EVIDENCE_DIR/visual/samples/unet.svg" "$EVIDENCE_DIR/visual/samples/rnn.svg"
  "$EVIDENCE_DIR/visual/samples/moe.svg" "$EVIDENCE_DIR/visual/samples/multimodal.svg"
  "$EVIDENCE_DIR/visual/samples/diffusion.svg"
)
node scripts/svg_quality_oracle.mjs --require-metadata --strict-roles \
  --manifest "$EVIDENCE_DIR/visual/samples/publication-input-manifest.json" \
  --output "$EVIDENCE_DIR/visual/seven-architecture-metrics.json" "${VISUAL_SVGS[@]}" \
  > "$EVIDENCE_DIR/logs/svg-oracle.log"
"$PYTHON_BIN" scripts/summarize_visual_oracle.py "$EVIDENCE_DIR/visual/seven-architecture-metrics.json" \
  --output-dir "$EVIDENCE_DIR/visual" > "$EVIDENCE_DIR/logs/svg-oracle-summary.log"

"$PYTHON_BIN" scripts/generate_svg_oracle_fixtures.py "$EVIDENCE_DIR/visual/oracle-fixture-files"
set +e
node scripts/svg_quality_oracle.mjs --require-metadata --strict-roles \
  --manifest "$EVIDENCE_DIR/visual/oracle-fixture-files/publication-input-manifest.json" \
  --output "$EVIDENCE_DIR/visual/oracle-fixtures.json" "$EVIDENCE_DIR"/visual/oracle-fixture-files/*.svg \
  > "$EVIDENCE_DIR/logs/svg-oracle-fixtures.log" 2>&1
ORACLE_FIXTURE_STATUS=$?
set -e
if [[ "$ORACLE_FIXTURE_STATUS" -ne 1 ]]; then
  echo "manual SVG truth set expected exit 1, got $ORACLE_FIXTURE_STATUS" >&2
  exit 1
fi
"$PYTHON_BIN" scripts/validate_svg_oracle_fixtures.py "$EVIDENCE_DIR/visual/oracle-fixtures.json" \
  --output "$EVIDENCE_DIR/visual/oracle-fixture-validation.json" \
  > "$EVIDENCE_DIR/logs/svg-oracle-fixture-validation.log"

mkdir -p "$EVIDENCE_DIR/visual/compiled-tikz" "$EVIDENCE_DIR/visual/font-reports"
for fixture in resnet transformer unet rnn moe multimodal diffusion; do
  "$PYTHON_BIN" scripts/check_pdf_fonts.py "$EVIDENCE_DIR/visual/samples/$fixture.pdf" \
    --report "$EVIDENCE_DIR/visual/font-reports/$fixture-pdf.txt"
  pdflatex -halt-on-error -interaction=nonstopmode -output-directory="$EVIDENCE_DIR/visual/compiled-tikz" \
    "$EVIDENCE_DIR/visual/samples/$fixture.tex" > "$EVIDENCE_DIR/logs/pdflatex-$fixture.log"
  test -s "$EVIDENCE_DIR/visual/compiled-tikz/$fixture.pdf"
  "$PYTHON_BIN" scripts/check_pdf_fonts.py "$EVIDENCE_DIR/visual/compiled-tikz/$fixture.pdf" \
    --report "$EVIDENCE_DIR/visual/font-reports/$fixture-tikz-pdf.txt"
done
"$PYTHON_BIN" scripts/validate_vector_text_consistency.py "$EVIDENCE_DIR/visual/samples" \
  --compiled-directory "$EVIDENCE_DIR/visual/compiled-tikz" \
  --output "$EVIDENCE_DIR/visual/format-text-consistency.json" > "$EVIDENCE_DIR/logs/vector-text.log"

"$PYTHON_BIN" scripts/benchmark_large_graph.py "$EVIDENCE_DIR/stress/results.json" > "$EVIDENCE_DIR/logs/stress.log"
"$PYTHON_BIN" scripts/capture_large_graph_evidence.py "$EVIDENCE_DIR/stress" > "$EVIDENCE_DIR/logs/stress-preflight.log"
"$PYTHON_BIN" scripts/capture_cli_large_graph_evidence.py "$EVIDENCE_DIR/stress/cli-preflight.json" \
  > "$EVIDENCE_DIR/logs/cli-preflight.log"

"$PYTHON_BIN" scripts/generate_real_model_report.py \
  --output "$EVIDENCE_DIR/product/real-models/compatibility.json" --repeats 3 \
  > "$EVIDENCE_DIR/logs/real-models.log"
"$PYTHON_BIN" scripts/generate_paper_examples.py --output "$EVIDENCE_DIR/product/paper-examples" \
  > "$EVIDENCE_DIR/logs/paper-examples.log"
node scripts/svg_quality_oracle.mjs --strict-roles \
  --output "$EVIDENCE_DIR/product/publication-quality/chrome-final-svg.json" \
  "$EVIDENCE_DIR/product/paper-examples/resnet50_overview_bottleneck/resnet50_overview_bottleneck.svg" \
  "$EVIDENCE_DIR/product/paper-examples/vision_transformer_attention/vision_transformer_attention.svg" \
  "$EVIDENCE_DIR/product/paper-examples/multiscale_unet/multiscale_unet.svg" \
  > "$EVIDENCE_DIR/logs/publication-quality-chrome.log"
"$PYTHON_BIN" scripts/validate_publication_quality.py \
  --paper-examples "$EVIDENCE_DIR/product/paper-examples/paper-examples-report.json" \
  --chrome-report "$EVIDENCE_DIR/product/publication-quality/chrome-final-svg.json" \
  --output "$EVIDENCE_DIR/product/publication-quality/acceptance.json" \
  > "$EVIDENCE_DIR/logs/publication-quality-acceptance.log"
"$PYTHON_BIN" scripts/validate_scientific_fidelity.py \
  --paper-examples "$EVIDENCE_DIR/product/paper-examples/paper-examples-report.json" \
  --golden-dir verification/fixtures/scientific-fidelity \
  --output "$EVIDENCE_DIR/product/scientific-fidelity/acceptance.json" \
  > "$EVIDENCE_DIR/logs/scientific-fidelity-acceptance.log"
"$PYTHON_BIN" scripts/generate_diff_corpus.py --output "$EVIDENCE_DIR/product/diff" \
  > "$EVIDENCE_DIR/logs/real-model-diff.log"
"$PYTHON_BIN" scripts/benchmark_product_0_4.py \
  --output "$EVIDENCE_DIR/product/performance/three-runs.json" \
  > "$EVIDENCE_DIR/logs/product-performance.log"
"$PYTHON_BIN" scripts/generate_external_trial_report.py \
  --output-root "$EVIDENCE_DIR/trial/external-models/cases" \
  --report "$EVIDENCE_DIR/trial/external-models/compatibility.json" --repeats 3 \
  > "$EVIDENCE_DIR/logs/trial-external-models.log"
"$PYTHON_BIN" scripts/generate_venue_proofs.py --output "$EVIDENCE_DIR/trial/venue-proof" \
  > "$EVIDENCE_DIR/logs/trial-venue-proof.log"

NNDV_PYTHON="$PYTHON_BIN" NNDV_E2E_DIR="$WORK_DIR/e2e-downloads" \
  NNDV_E2E_REPORT="$EVIDENCE_DIR/e2e/scenarios.json" npm run e2e > "$EVIDENCE_DIR/logs/e2e.log" 2>&1
NNDV_PYTHON="$PYTHON_BIN" NNDV_RESPONSIVE_E2E_REPORT="$EVIDENCE_DIR/e2e/responsive-workspace.json" npm run e2e:responsive \
  > "$EVIDENCE_DIR/logs/e2e-responsive-toolbar.log" 2>&1
"$PYTHON_BIN" - "$EVIDENCE_DIR/e2e/responsive-workspace.json" <<'PY'
import json, pathlib, sys
report = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
coverage = report.get("coverage", {})
required = {
    "canonical_workspace_drawers", "inspector_selection_entry",
    "mutually_exclusive_surfaces", "keyboard_and_focus_restore",
    "breakpoint_cleanup", "bounded_workflow_dialogs",
}
if (
    report.get("status") != "passed"
    or report.get("viewport_count") != 7
    or not all(coverage.get(key) is True for key in required)
    or coverage.get("duplicate_composer_initializations") != 0
    or coverage.get("unexpected_browser_errors") != 0
    or coverage.get("mobile_workflow") != [
        "import-model", "block-view", "paper-view", "composer-a-b",
        "save-project", "export-svg",
    ]
):
    raise SystemExit("responsive workspace E2E did not pass its complete 0.5.2 contract")
PY
"$PYTHON_BIN" scripts/validate_e2e_report.py "$EVIDENCE_DIR/e2e/scenarios.json" \
  --output "$EVIDENCE_DIR/e2e/summary.json" > "$EVIDENCE_DIR/logs/e2e-summary.log"
NNDV_PYTHON="$PYTHON_BIN" NNDV_SEMANTIC_E2E_DIR="$WORK_DIR/semantic-e2e-downloads" \
  NNDV_SEMANTIC_E2E_REPORT="$EVIDENCE_DIR/e2e/semantic-workflow.json" npm run e2e:semantic \
  > "$EVIDENCE_DIR/logs/e2e-semantic.log" 2>&1
"$PYTHON_BIN" - "$EVIDENCE_DIR/e2e/semantic-workflow.json" <<'PY'
import json, pathlib, sys
report = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
if report.get("status") != "passed" or report.get("scenario") != "semantic-paper-export-loop" or report.get("assertion_count", 0) < 27:
    raise SystemExit("semantic workflow E2E did not pass its complete 0.3 loop")
PY
NNDV_PYTHON="$PYTHON_BIN" NNDV_PRODUCT_E2E_DIR="$WORK_DIR/product-e2e-downloads" \
  NNDV_PRODUCT_E2E_REPORT="$EVIDENCE_DIR/e2e/product-workflow.json" npm run e2e:product \
  > "$EVIDENCE_DIR/logs/e2e-product.log" 2>&1
NNDV_PYTHON="$PYTHON_BIN" NNDV_TRIAL_E2E_DIR="$WORK_DIR/trial-e2e-downloads" \
  NNDV_TRIAL_E2E_REPORT="$EVIDENCE_DIR/e2e/trial-workflow.json" npm run e2e:trial \
  > "$EVIDENCE_DIR/logs/e2e-trial.log" 2>&1
cp -a docs/trial/. "$EVIDENCE_DIR/trial/kit/"
"$PYTHON_BIN" scripts/validate_trial_release.py \
  --external-models "$EVIDENCE_DIR/trial/external-models/compatibility.json" \
  --venue-proof "$EVIDENCE_DIR/trial/venue-proof/venue-proof-report.json" \
  --trial-e2e "$EVIDENCE_DIR/e2e/trial-workflow.json" \
  --human-status docs/trial/human-trial-status.json --docs-root docs/trial \
  --output "$EVIDENCE_DIR/trial/acceptance.json" \
  > "$EVIDENCE_DIR/logs/trial-acceptance.log"
"$PYTHON_BIN" scripts/validate_product_evidence.py \
  --real-models "$EVIDENCE_DIR/product/real-models/compatibility.json" \
  --paper-examples "$EVIDENCE_DIR/product/paper-examples/paper-examples-report.json" \
  --publication-quality "$EVIDENCE_DIR/product/publication-quality/acceptance.json" \
  --scientific-fidelity "$EVIDENCE_DIR/product/scientific-fidelity/acceptance.json" \
  --diff "$EVIDENCE_DIR/product/diff/real-model-diff-report.json" \
  --performance "$EVIDENCE_DIR/product/performance/three-runs.json" \
  --semantic-e2e "$EVIDENCE_DIR/e2e/semantic-workflow.json" \
  --product-e2e "$EVIDENCE_DIR/e2e/product-workflow.json" \
  --output "$EVIDENCE_DIR/product/acceptance.json" \
  > "$EVIDENCE_DIR/logs/product-acceptance.log"

"$PYTHON_BIN" -m build --no-isolation --outdir "$EVIDENCE_DIR/packaging/dist" . > "$EVIDENCE_DIR/logs/package-build.log"
PROJECT_WHEEL=("$EVIDENCE_DIR"/packaging/dist/*.whl)
"$PYTHON_BIN" scripts/rebuild_verification_environment.py \
  --lock requirements/verification-linux-x86_64-py313-0.2.3.lock \
  --work-root "$WORK_DIR/verification-lock-rebuild" \
  --project-wheel "${PROJECT_WHEEL[0]}" \
  --output "$EVIDENCE_DIR/packaging/lock-rebuild.json" \
  > "$EVIDENCE_DIR/logs/lock-rebuild.log"
"$PYTHON_BIN" scripts/verify_package_install.py "$EVIDENCE_DIR/packaging/dist" "$WORK_DIR/package-install/venvs" \
  --project-root "$PROJECT_DIR" --expected-version 0.5.2 --output "$EVIDENCE_DIR/packaging/summary.json" \
  > "$EVIDENCE_DIR/logs/package-install.log"
"$PYTHON_BIN" scripts/validate_publication_exports.py "$EVIDENCE_DIR/visual/samples" "$EVIDENCE_DIR/exports" \
  --output "$EVIDENCE_DIR/publication-controls.json" > "$EVIDENCE_DIR/logs/publication-controls.log"

"$PYTHON_BIN" scripts/write_environment_manifest.py "$EVIDENCE_DIR/environment.json" > "$EVIDENCE_DIR/logs/environment.log"
"$PYTHON_BIN" scripts/check_release_docs.py --coverage "$EVIDENCE_DIR/coverage/summary.json" \
  --output "$EVIDENCE_DIR/docs/document-check.json" > "$EVIDENCE_DIR/logs/document-check.log"
cp "$SNAPSHOT_REPORT" "$EVIDENCE_DIR/source/snapshot.json"
cp verification/acceptance-matrix-0.2.3.json "$EVIDENCE_DIR/source/acceptance-matrix-0.2.3.json"
if [[ -n "${NNDV_NPM_CI_LOG:-}" ]]; then
  cp "$NNDV_NPM_CI_LOG" "$EVIDENCE_DIR/logs/npm-ci.log"
fi
"$PYTHON_BIN" - "$EVIDENCE_DIR/source/commands.json" "$ORACLE_FIXTURE_STATUS" <<'PY'
import json, pathlib, sys
ids = [
    "trust-anchor", "quick", "seven-formats", "pdf-font-tikz", "visual-integrity",
    "strict-seven-svg", "oracle-fixture-validator", "vector-consistency", "large-graph",
    "cli-scale", "chrome-e2e", "chrome-responsive-workspace", "chrome-semantic-workflow", "package-build", "lock-rebuild", "package-install", "publication",
    "real-models", "paper-examples", "publication-quality", "scientific-fidelity", "real-model-diff", "product-performance",
    "chrome-product-workflow", "product-acceptance", "environment", "documentation", "npm-clean-install",
    "trial-external-models", "trial-venue-proof", "chrome-trial-workflow", "trial-kit-acceptance",
]
commands = [{"id": name, "exit_code": 0, "expected_exit_code": 0} for name in ids]
commands.append({"id": "oracle-negative-raw", "exit_code": int(sys.argv[2]), "expected_exit_code": 1})
pathlib.Path(sys.argv[1]).write_text(json.dumps({"commands": commands}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

rm -rf "$WORK_DIR/quick" "$WORK_DIR/e2e-downloads" "$WORK_DIR/semantic-e2e-downloads" "$WORK_DIR/product-e2e-downloads" "$WORK_DIR/trial-e2e-downloads" "$WORK_DIR/package-install" "$WORK_DIR/matplotlib" \
  "$WORK_DIR/texmf-var" "$WORK_DIR/texmf-config" "$WORK_DIR/pip-cache" "$WORK_DIR/export-compiled" \
  "$WORK_DIR/verification-lock-rebuild"
"$PYTHON_BIN" scripts/write_release_observations.py "$EVIDENCE_DIR" --project-root "$PROJECT_DIR" \
  --snapshot-report "$SNAPSHOT_REPORT" --run-id "$RUN_ID" > "$EVIDENCE_DIR/logs/release-observations.log"
"$PYTHON_BIN" scripts/run_matrix_mutations.py "$EVIDENCE_DIR" --matrix verification/acceptance-matrix-0.2.3.json \
  --project-root "$PROJECT_DIR" --trust-anchor docs/TRUST_ANCHOR_0.2.2.json \
  --expected-anchor-sha256 "$EXPECTED_ANCHOR_SHA256" --output "$EVIDENCE_DIR/matrix/mutation-report.json" \
  > "$EVIDENCE_DIR/logs/mutations.log"
"$PYTHON_BIN" scripts/validate_acceptance_matrix.py "$EVIDENCE_DIR" \
  --matrix verification/acceptance-matrix-0.2.3.json --project-root "$PROJECT_DIR" \
  --trust-anchor docs/TRUST_ANCHOR_0.2.2.json --expected-anchor-sha256 "$EXPECTED_ANCHOR_SHA256" \
  --output "$EVIDENCE_DIR/matrix/results.json" > "$EVIDENCE_DIR/logs/matrix.log"
