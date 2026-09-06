#!/usr/bin/env python3
"""Generate/check the deduplicated executable 0.2.2 acceptance matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).parents[1]
TARGET = ROOT / "verification" / "acceptance-matrix-0.2.2.json"


def row(requirement_id: str, title: str, validator_id: str, requirement_class: str,
        evidence_path: str, pointer: str, value_type: str, comparison: str,
        expected: Any, command: str, *inputs: str) -> dict[str, Any]:
    return {
        "requirement_id": requirement_id, "title": title,
        "validator_id": validator_id, "requirement_class": requirement_class,
        "inputs": list(inputs), "evidence_path": evidence_path,
        "json_pointer": pointer, "observed_value_type": value_type,
        "comparison": comparison, "expected_value": expected,
        "command_provenance": [command], "release_blocker": True,
    }


def matrix() -> dict[str, Any]:
    r = row
    rows = [
        r("TEST-01", "Python suite and externally anchored frozen IDs", "python_test_summary", "tests", "tests/python-tests.json", "/passed", "integer", "gte", 89, "scripts/run_tests.py", "tests/trust-anchor-check.json"),
        r("STAT-01", "Coverage line/branch/combined arithmetic derives from raw JSON", "coverage_arithmetic", "coverage", "coverage/summary.json", "/old_core/combined/fraction", "number", "gte", 0, "scripts/summarize_coverage.py", "coverage/core.json", "coverage/expanded-core.json", "coverage/all-package.json"),
        r("STAT-02", "Release counters have distinct semantics", "release_count_schema", "statistics", "release-counts.json", "/checks", "integer", "gte", 1, "scripts/write_release_observations.py", "tests/python-tests.json", "exports/artifact-validation.json", "packaging/summary.json", "e2e/scenarios.json"),
        r("STAT-03", "Old-core line coverage does not regress", "coverage_arithmetic", "coverage", "coverage/summary.json", "/old_core/line/fraction", "number", "gte", 0.911849710982659, "scripts/summarize_coverage.py", "coverage/core.json"),
        r("COV-01", "Old-core branch coverage does not regress", "coverage_arithmetic", "coverage", "coverage/summary.json", "/old_core/branch/fraction", "number", "gte", 0.8329048843187661, "scripts/summarize_coverage.py", "coverage/core.json"),
        r("COV-02", "Expanded-core line coverage meets threshold", "coverage_arithmetic", "coverage", "coverage/summary.json", "/expanded_core/line/fraction", "number", "gte", 0.885, "scripts/summarize_coverage.py", "coverage/expanded-core.json"),
        r("COV-03", "Expanded-core branch coverage meets threshold", "coverage_arithmetic", "coverage", "coverage/summary.json", "/expanded_core/branch/fraction", "number", "gte", 0.8, "scripts/summarize_coverage.py", "coverage/expanded-core.json"),
        r("STAT-07", "All-package line coverage does not regress", "coverage_arithmetic", "coverage", "coverage/summary.json", "/all_package/line/fraction", "number", "gte", 0.8324851569126378, "scripts/summarize_coverage.py", "coverage/all-package.json"),
        r("COV-04", "All-package branch coverage does not regress", "coverage_arithmetic", "coverage", "coverage/summary.json", "/all_package/branch/fraction", "number", "gte", 0.7479289940828402, "scripts/summarize_coverage.py", "coverage/all-package.json"),
        r("STAT-04", "Coverage manifests/exclusions remain fixed and explained", "coverage_arithmetic", "coverage", "coverage/manifest-diff.json", "/coverage_exclusions", "array", "empty", [], "scripts/summarize_coverage.py", "coverage/summary.json"),
        r("STAT-05", "Release documents agree with current-run evidence", "documentation_consistency", "documentation", "docs/document-check.json", "/failures", "array", "empty", [], "scripts/check_release_docs.py", "coverage/summary.json"),
        r("GRAPH-01", "SCC/deep traversal differential is recursion-safe", "graph_semantics", "graph", "stress/results.json", "/scc_differential/deep_chain_without_recursion", "boolean", "eq", True, "scripts/benchmark_large_graph.py"),
        r("GRAPH-02", "Anchored graph corpus hashes and named structures are exact", "fixture_integrity", "visual", "stress/corpus-manifest-check.json", "/failures", "array", "empty", [], "scripts/capture_large_graph_evidence.py", "stress/results.json"),
        r("GRAPH-02A", "100-node full layout/render meets every run budget", "graph_semantics", "graph", "stress/results.json", "/deep_chain_100/runs", "array", "length_eq", 3, "scripts/benchmark_large_graph.py"),
        r("GRAPH-03", "1000-node full layout/render meets every run budget", "graph_semantics", "graph", "stress/results.json", "/deep_chain_1000/runs", "array", "length_eq", 3, "scripts/benchmark_large_graph.py"),
        r("GRAPH-04", "10000-node summary/focus meets every run budget", "graph_semantics", "graph", "stress/results.json", "/deep_chain_10000_focus/runs", "array", "length_eq", 3, "scripts/benchmark_large_graph.py"),
        r("GRAPH-07", "Web rejects unsafe 10k full rendering with actionable 422", "graph_semantics", "graph", "stress/web-preflight.json", "/http_status", "integer", "eq", 422, "scripts/capture_large_graph_evidence.py"),
        r("SPATIAL-01", "AVL spatial index passes axes/distributions/differentials", "graph_semantics", "graph", "stress/results.json", "/spatial_index/differential_distributions", "array", "length_eq", 20, "scripts/benchmark_large_graph.py"),
        r("SPATIAL-02", "Million-pair budget reports an explicit incomplete result", "graph_semantics", "graph", "stress/results.json", "/spatial_index/million_pair_budget/lower_bound", "integer", "gte", 1000001, "scripts/benchmark_large_graph.py"),
        r("CLI-01", "API/CLI/Web large-graph recovery policy is executable", "fixture_integrity", "visual", "stress/cli-preflight.json", "/failures", "array", "empty", [], "scripts/capture_cli_large_graph_evidence.py", "stress/web-preflight.json"),
        r("SVG-01", "Seven serialized publication SVGs pass strict Chrome geometry", "svg_geometry", "svg", "visual/seven-architecture-metrics.json", "/reports", "array", "length_eq", 7, "scripts/svg_quality_oracle.mjs", "visual/samples/publication-input-manifest.json"),
        r("SVG-02", "All independent adversarial SVG truth fixtures classify", "oracle_fixture_truth", "oracle-fixture", "visual/oracle-fixture-validation.json", "/cases", "array", "length_eq", 26, "scripts/validate_svg_oracle_fixtures.py", "visual/oracle-fixtures.json"),
        r("VIS-02", "Seven authority inputs, IDs, critical edges and provenance are exact", "fixture_integrity", "visual", "visual/fixture-integrity.json", "/failures", "array", "empty", [], "scripts/verify_visual_fixtures.py"),
        r("TEXT-02", "Required text and wrapping agree across SVG/PDF/TikZ", "fixture_integrity", "visual", "visual/format-text-consistency.json", "/failures", "array", "empty", [], "scripts/validate_vector_text_consistency.py"),
        r("E2E-01", "Ten stable isolated Chrome behavior scenarios pass", "browser_scenarios", "e2e", "e2e/scenarios.json", "/scenarios", "array", "length_eq", 10, "tests/e2e/editor.e2e.mjs"),
        r("EXPORT-01", "Seven fresh formats pass independent artifact checks", "export_semantics", "export", "exports/artifact-validation.json", "/checks", "integer", "gte", 20, "scripts/validate_acceptance_artifacts.py"),
        r("PKG-01", "Wheel and sdist install with dependencies and editable assets", "packaging_semantics", "packaging", "packaging/summary.json", "/checks", "integer", "gte", 10, "scripts/verify_package_install.py"),
        r("LOCK-01", "Verification lock rebuilds an independent environment with wheel hashes", "lock_rebuild", "dependencies", "packaging/lock-rebuild.json", "/wheel_hashes", "object", "ne", {}, "scripts/rebuild_verification_environment.py", "requirements/verification-linux-x86_64-py313-0.2.2.lock"),
        r("ENV-01", "Environment/root configuration inventory is complete and Git remains absent", "environment_integrity", "environment", "environment.json", "/git_repository", "boolean", "eq", False, "scripts/write_environment_manifest.py"),
        r("TEMP-01", "No workspace or retained run cache leaks", "temporary_hygiene", "temporary", "temporary-files.json", "/passed", "boolean", "eq", True, "scripts/write_release_observations.py"),
        r("MATRIX-01", "All fail-closed matrix and seal mutations are killed", "mutation_gate", "matrix", "matrix/mutation-report.json", "/cases", "array", "length_eq", 11, "scripts/run_matrix_mutations.py"),
        r("PUB-01", "Publication exports exclude editor controls and retain provenance", "export_semantics", "publication", "publication-controls.json", "/failures", "array", "empty", [], "scripts/validate_publication_exports.py"),
        r("LINEAGE-01", "Sealed consumed-input lineage is self-contained and clean", "consumed_input_lineage", "lineage", "source/consumed-inputs.json", "/forbidden_inputs", "array", "empty", [], "scripts/write_release_observations.py", "source/snapshot.json", "replay/runtime-manifest.json"),
        r("SEAL-01", "Root-only JSON checksum policy covers every retained regular file", "seal_precondition", "seal", "seal-policy.json", "/checksum_exclusion_scope", "string", "eq", "root-only", "scripts/seal_evidence.py"),
    ]
    aliases = {
        "TEST-01": "TEST-01", "STAT-01": "STAT-01", "STAT-02": "STAT-02",
        "STAT-03": "STAT-03", "STAT-04": "STAT-04", "STAT-05": "STAT-05",
        "STAT-06": "TEST-01", "STAT-07": "STAT-07", "GRAPH-01": "GRAPH-01",
        "GRAPH-02": "GRAPH-02", "GRAPH-02A": "GRAPH-02A", "GRAPH-03": "GRAPH-03",
        "GRAPH-04": "GRAPH-04", "GRAPH-05": "SPATIAL-01", "GRAPH-06": "GRAPH-02",
        "GRAPH-07": "GRAPH-07", "GRAPH-08": "CLI-01", "GRAPH-09": "SPATIAL-01",
        "SVG-01": "SVG-01", "SVG-02": "SVG-02", "SVG-03": "SVG-01",
        "SVG-04": "SVG-01", "SVG-05": "SVG-02", "SVG-06": "SVG-02",
        "SVG-07": "SVG-01", "SVG-08": "SVG-01", "VIS-01": "SVG-01",
        "VIS-02": "VIS-02", "VIS-03": "VIS-02", "TEXT-01": "SVG-01",
        "TEXT-02": "TEXT-02", "TEXT-03": "TEXT-02", "TEXT-04": "SVG-01",
        "TEXT-05": "TEXT-02", "E2E-01": "E2E-01", "E2E-02": "E2E-01",
        "E2E-03": "E2E-01", "E2E-04": "E2E-01", "EXPORT-01": "EXPORT-01",
        "PKG-01": "PKG-01", "DOC-01": "STAT-05", "DOC-02": "STAT-05",
        "ENV-01": "ENV-01", "ENV-02": "LOCK-01", "TEMP-01": "TEMP-01",
        "ART-01": "SEAL-01", "GIT-01": "ENV-01", "MATRIX-01": "MATRIX-01",
    }
    return {
        "schema_version": "3.0.0", "release": "0.2.2",
        "policy": "One row is one independently replayable semantic blocker; legacy aliases are not counted.",
        "migration": {
            "source": "acceptance-matrix-0.2.1.json", "legacy_rows": 48,
            "legacy_id_mapping": aliases,
            "reason": "Duplicate Python-summary, SVG-report-count, document, E2E and aggregate-status predicates were collapsed into explicit canonical blockers.",
        },
        "requirements": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(matrix(), ensure_ascii=False, indent=2) + "\n"
    if args.write:
        TARGET.write_text(rendered, encoding="utf-8")
    elif not TARGET.is_file() or TARGET.read_text(encoding="utf-8") != rendered:
        raise SystemExit("versioned 0.2.2 acceptance matrix differs from its deterministic definition")
    print(json.dumps({"independent_blockers": len(matrix()["requirements"]), "target": str(TARGET), "matched": TARGET.is_file() and TARGET.read_text(encoding="utf-8") == rendered}, sort_keys=True))


if __name__ == "__main__":
    main()
