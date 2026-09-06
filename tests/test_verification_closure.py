from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile

from scripts.validate_acceptance_matrix import (
    MatrixValidationError,
    evaluate_matrix,
    resolve_json_pointer,
    validate_matrix_schema,
)


ROOT = Path(__file__).parents[1]
ANCHOR_SHA = "10979b1d7112b7639207405dffe23f534762a02fb047b61540c5e04c955a3224"


class TrustAnchorTests(unittest.TestCase):
    def test_external_anchor_and_frozen_ids_match_immutable_values(self):
        anchor_path = ROOT / "docs" / "TRUST_ANCHOR_0.2.2.json"
        ids_path = ROOT / "verification" / "fixtures" / "python-test-ids-0.2.0.txt"
        self.assertEqual(hashlib.sha256(anchor_path.read_bytes()).hexdigest(), ANCHOR_SHA)
        self.assertEqual(stat.S_IMODE(anchor_path.stat().st_mode), 0o444)
        anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
        baseline = anchor["legacy_test_baseline"]
        self.assertEqual(stat.S_IMODE(ids_path.stat().st_mode), 0o444)
        self.assertEqual(hashlib.sha256(ids_path.read_bytes()).hexdigest(), baseline["sha256"])
        self.assertEqual(len(ids_path.read_text(encoding="utf-8").splitlines()), 73)

    def test_json_pointer_requires_real_value_and_correct_escape(self):
        document = {"a/b": {"~key": [3, 4]}}
        self.assertEqual(resolve_json_pointer(document, "/a~1b/~0key/1"), 4)
        with self.assertRaisesRegex(MatrixValidationError, "is absent"):
            resolve_json_pointer(document, "/missing")
        with self.assertRaisesRegex(MatrixValidationError, "leading"):
            resolve_json_pointer(document, "#/a")


class ExecutableMatrixTests(unittest.TestCase):
    def test_coverage_validator_enforces_predicate(self):
        from scripts.validate_acceptance_matrix import VALIDATORS

        document = {
            "old_core": {
                "line": {"covered": 1, "total": 2, "fraction": 0.5},
                "branch": {"covered": 4, "total": 5, "fraction": 0.8},
                "combined": {"covered": 5, "total": 7, "fraction": 5 / 7},
            }
        }
        row = {"comparison": "gte", "threshold": 0.885}
        _, okay, reason = VALIDATORS["coverage_arithmetic"].function(row, 0.5, {"document": document})
        self.assertFalse(okay)
        self.assertIn("does not satisfy", reason)

    def test_versioned_matrix_maps_legacy_ids_and_counts_unique_predicates(self):
        from scripts.validate_acceptance_matrix import validate_anchor

        anchor, _ = validate_anchor(ROOT / "docs/TRUST_ANCHOR_0.2.2.json", ANCHOR_SHA)
        matrix = json.loads((ROOT / "verification/acceptance-matrix-0.2.2.json").read_text(encoding="utf-8"))
        rows = validate_matrix_schema(matrix, anchor, ROOT)
        self.assertEqual(len(rows), 34)
        self.assertEqual(
            set(matrix["migration"]["legacy_id_mapping"]),
            set(anchor["legacy_acceptance_matrix"]["requirement_ids"]),
        )
        signatures = {
            (
                item["validator_id"],
                item["evidence_path"],
                item["json_pointer"],
                item["comparison"],
                json.dumps(item["expected_value"], sort_keys=True),
                tuple(item["inputs"]),
            )
            for item in rows
        }
        self.assertEqual(len(signatures), len(rows))

    def test_full_and_finalize_logs_are_covered_and_tampering_fails(self):
        from scripts.verify_checksum_manifest import verify

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "evidence"
            (root / "logs").mkdir(parents=True)
            for name in ("full.log", "finalize.log"):
                (root / "logs" / name).write_text(f"closed {name}\n", encoding="utf-8")
            subprocess.run(
                [sys.executable, str(ROOT / "scripts/seal_evidence.py"), str(root)],
                check=True,
                capture_output=True,
                text=True,
            )
            checksum = (root / "SHA256SUMS").read_text(encoding="utf-8")
            self.assertIn("logs/full.log", checksum)
            self.assertIn("logs/finalize.log", checksum)
            self.assertTrue(verify(root)["passed"])
            for name in ("full.log", "finalize.log"):
                path = root / "logs" / name
                original = path.read_text(encoding="utf-8")
                path.write_text(original + "tampered\n", encoding="utf-8")
                self.assertIn(f"logs/{name}", verify(root)["mismatch"])
                path.write_text(original, encoding="utf-8")

    def test_checksum_manifest_covers_nested_and_ambiguous_filenames(self):
        from scripts.verify_checksum_manifest import verify

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "evidence"
            (root / "nested").mkdir(parents=True)
            names = ["nested/SHA256SUMS", "line\nbreak.txt", "two  spaces", "back\\slash", "*leading-star"]
            for name in names:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name, encoding="utf-8")
            subprocess.run([sys.executable, str(ROOT / "scripts/seal_evidence.py"), str(root)], check=True)
            document = json.loads((root / "SHA256SUMS").read_text(encoding="utf-8"))
            self.assertEqual({item["path"] for item in document["entries"]}, set(names))
            self.assertTrue(verify(root)["passed"])
            (root / "nested/SHA256SUMS").write_text("tampered", encoding="utf-8")
            self.assertIn("nested/SHA256SUMS", verify(root)["mismatch"])

    def test_wheel_identity_ignores_vendored_dist_info(self):
        from scripts.rebuild_verification_environment import wheel_identity

        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "setuptools-84.0.0-py3-none-any.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr("setuptools-84.0.0.dist-info/METADATA", "Name: setuptools\nVersion: 84.0.0\n")
                archive.writestr("setuptools/_vendor/example-1.0.dist-info/METADATA", "Name: example\nVersion: 1.0\n")
            self.assertEqual(wheel_identity(wheel), ("setuptools", "84.0.0"))

    def test_verification_lock_expands_torch_cuda_toolkit_extras(self):
        from scripts.write_verification_lock import closure

        locked = closure()
        required = {
            "nvidia-cuda-cupti",
            "nvidia-cuda-runtime",
            "nvidia-cufft",
            "nvidia-cufile",
            "nvidia-curand",
            "nvidia-cusolver",
            "nvidia-cusparse",
            "nvidia-nvjitlink",
            "nvidia-nvtx",
        }
        self.assertEqual(len(locked), 102)
        self.assertTrue(required <= locked.keys())
        lock_text = (ROOT / "requirements/verification-linux-x86_64-py313-0.2.3.lock").read_text(encoding="utf-8")
        self.assertTrue(all(f"{name}=={locked[name]}" in lock_text for name in required))

    def test_matrix_treats_lock_as_typed_text_and_recomputes_wheel_rows(self):
        from scripts.validate_acceptance_matrix import VALIDATORS, load_matrix_input

        lock_path = ROOT / "requirements/verification-linux-x86_64-py313-0.2.3.lock"
        lock = load_matrix_input(lock_path)
        pins = {
            line.split("==", 1)[0].lower().replace("_", "-"): line.split("==", 1)[1] for line in lock["text"].splitlines() if line and not line.startswith("#")
        }
        wheels = [
            {"name": name, "version": version, "filename": f"{name}.whl", "sha256": "a" * 64, "origin": "configured_index"} for name, version in pins.items()
        ]
        document = {
            "independent_environment": True,
            "lock_matches": True,
            "pip_check_passed": True,
            "import_smoke_passed": True,
            "locked_distributions": len(pins),
            "wheels": wheels,
            "wheel_hashes": {item["filename"]: item["sha256"] for item in wheels},
            "installed_locked_versions": pins,
            "local_fallback_allowlist": ["torchcam"],
        }
        row = {"comparison": "ne", "expected_value": {}}
        _, passed, _ = VALIDATORS["lock_rebuild"].function(row, document["wheel_hashes"], {"document": document, "inputs": [lock]})
        self.assertTrue(passed)
        document["wheels"][0]["version"] = "tampered"
        _, passed, _ = VALIDATORS["lock_rebuild"].function(row, document["wheel_hashes"], {"document": document, "inputs": [lock]})
        self.assertFalse(passed)

    def test_post_seal_replay_disables_caches_and_rechecks_inventory(self):
        from scripts.verify_sealed_bundle import release_counts_from_raw

        source = (ROOT / "scripts/verify_sealed_bundle.py").read_text(encoding="utf-8")
        self.assertIn('"PYTHONDONTWRITEBYTECODE": "1"', source)
        self.assertIn('"XDG_CACHE_HOME": str(temporary_root / "xdg-cache")', source)
        self.assertIn("hashes_after = checksum_replay(root)", source)
        self.assertIn("semantic replay wrote into sealed evidence", source)
        self.assertEqual(
            release_counts_from_raw(
                blocker_count=34,
                tests={"passed": 130},
                artifact={"checks": 20},
                package={"checks": 12},
                e2e={"scenarios": [{}] * 10},
                semantic_e2e={"status": "passed", "assertion_count": 27},
            ),
            {
                "checks": 34,
                "python_tests": 130,
                "artifact_assertions": 20,
                "font_tikz_checks": 14,
                "packaging_checks": 12,
                "e2e_scenarios": 10,
                "semantic_e2e_workflows": 1,
                "semantic_e2e_assertions": 27,
            },
        )
        self.assertEqual(
            release_counts_from_raw(
                blocker_count=34,
                tests={"passed": 149},
                artifact={"checks": 20},
                package={"checks": 12},
                e2e={"scenarios": [{}] * 10},
                responsive_e2e={"status": "passed", "viewport_count": 7},
                semantic_e2e={"status": "passed", "assertion_count": 27},
            )["responsive_e2e_viewports"],
            7,
        )

    def test_post_seal_test_gate_cannot_be_resealed_down_to_frozen_73(self):
        from scripts.verify_sealed_bundle import test_summary_gate

        frozen = [f"test_{index}" for index in range(73)]
        tests = {
            "collected": 73,
            "passed": 73,
            "tests": 73,
            "failures": 0,
            "errors": 0,
            "skipped": 0,
            "deselected": 0,
        }
        observed, passed = test_summary_gate(
            tests,
            frozen,
            frozen,
            {"test_id_count": 73, "sha256": "a" * 64, "mode_octal": "0444"},
            "a" * 64,
            "0444",
            89,
        )
        self.assertFalse(passed)
        self.assertEqual(observed["minimum_passed"], 89)
        self.assertEqual(observed["collected_id_lines"], 73)

    def test_post_seal_matrix_predicate_replays_pointer_type_and_threshold(self):
        from scripts.verify_sealed_bundle import replay_matrix_predicate

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "tests.json"
            path.write_text('{"passed": 73}', encoding="utf-8")
            row = {
                "requirement_id": "TEST-01",
                "evidence_path": "tests.json",
                "json_pointer": "/passed",
                "observed_value_type": "integer",
                "comparison": "gte",
                "expected_value": 89,
            }
            result = replay_matrix_predicate(root, row)
            self.assertFalse(result["passed"])
            self.assertIn("73", result["reason"])
            path.write_text('{"passed": "110"}', encoding="utf-8")
            result = replay_matrix_predicate(root, row)
            self.assertFalse(result["passed"])
            self.assertIn("does not match integer", result["reason"])

    def _named_graph_fixture(self):
        names = ("locally_dense", "sparse_skip", "strongly_connected", "wide_layer_dag")
        hashes = {name: hashlib.sha256(name.encode()).hexdigest() for name in names}
        structures = {
            "locally_dense": {"edge_set_exact": True, "node_set_exact": True, "pair_budget_complete": True, "pair_budget_truncated": False},
            "sparse_skip": {"edge_set_exact": True, "rank_monotonic": True},
            "strongly_connected": {"edge_set_exact": True, "component_count": 1, "component_size": 1000},
            "wide_layer_dag": {"edge_set_exact": True, "source_rank": 0, "sink_rank": 3, "rank_values": [0, 1, 2, 3]},
        }
        named = {
            name: {
                "structure": structures[name],
                "runs": [{"graph_sha256": hashes[name], "total_seconds": 1.0, "peak_rss_bytes": 100, "svg_bytes": 100} for _ in range(3)],
            }
            for name in names
        }
        return named, hashes

    def test_post_seal_named_graph_recomputes_each_run_budgets(self):
        from scripts.verify_sealed_bundle import named_graph_gate

        for field, value in (("total_seconds", 999), ("peak_rss_bytes", 9_999_999_999), ("svg_bytes", 999_999_999)):
            with self.subTest(field=field):
                named, hashes = self._named_graph_fixture()
                named["wide_layer_dag"]["runs"][1][field] = value
                observed, passed = named_graph_gate(named, hashes, seconds=5, rss=1 << 30, svg=20 << 20)
                self.assertFalse(passed)
                self.assertFalse(observed["wide_layer_dag"]["runs_ok"])

    def test_post_seal_spatial_gate_includes_nested_runs(self):
        from scripts.verify_sealed_bundle import spatial_named_gate

        names = ("same_x_y_disjoint", "same_y_x_disjoint", "nested_x_y_filtered")
        clean = {
            name: {
                "runs": [
                    {
                        "rectangles": 10_000,
                        "pairs": 0,
                        "retained_pairs": 0,
                        "lower_bound": 0,
                        "complete": True,
                        "truncated": False,
                        "wall_seconds": 0.1,
                        "algorithm": "x-sweep+y-avl-interval-v2",
                    }
                    for _ in range(3)
                ]
            }
            for name in names
        }
        _, passed = spatial_named_gate(clean, seconds=2.0)
        self.assertTrue(passed)
        for mutation in ("incomplete", "time"):
            data = json.loads(json.dumps(clean))
            if mutation == "incomplete":
                data["nested_x_y_filtered"]["runs"][0].update({"complete": False, "truncated": True})
            else:
                data["nested_x_y_filtered"]["runs"][0]["wall_seconds"] = 999
            observed, passed = spatial_named_gate(data, seconds=2.0)
            self.assertFalse(passed)
            self.assertFalse(observed["nested_x_y_filtered"]["passed"])

    def test_replay_source_and_runtime_manifests_require_exact_file_sets(self):
        from scripts.verify_sealed_bundle import exact_regular_file_set

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "expected.txt").write_text("ok", encoding="utf-8")
            self.assertTrue(exact_regular_file_set(root, {"expected.txt"})["passed"])
            (root / "extra.txt").write_text("extra", encoding="utf-8")
            result = exact_regular_file_set(root, {"expected.txt"})
            self.assertFalse(result["passed"])
            self.assertEqual(result["extra"], ["extra.txt"])
            if hasattr(os, "symlink"):
                (root / "link").symlink_to(root / "expected.txt")
                result = exact_regular_file_set(root, {"expected.txt", "extra.txt"})
                self.assertFalse(result["passed"])
                self.assertIn("symlink:link", result["invalid"])

    def test_full_controller_cleanup_is_idempotent_after_self_contained_replay(self):
        source = (ROOT / "scripts/verify-full.sh").read_text(encoding="utf-8")
        self.assertIn("shutil.rmtree(sys.argv[1], ignore_errors=True)", source)
        deletion = source.index("shutil.rmtree(controller)")
        copied_replay = source.index('"$COPY_DIR/source/replay-source/scripts/verify_sealed_bundle.py"')
        self.assertLess(deletion, copied_replay)

    def test_release_decision_exists_only_after_two_clean_attestations(self):
        from scripts import write_release_decision
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            verification = root / "verification.json"
            verification.write_text(
                json.dumps(
                    {
                        "run_id": "run",
                        "runner_result": "PASS",
                        "pre_seal_audit": "PASS",
                    }
                ),
                encoding="utf-8",
            )
            replay = {
                "run_id": "run",
                "passed": True,
                "raw_blocker_replay": {"independent_blockers": 34, "passed": 34, "failed": 0, "skipped": 0, "not_run": 0},
                "matrix_predicate_replay": {"executed": 34, "passed": 34, "failed": 0},
            }
            copy = root / "copy.json"
            final = root / "final.json"
            copy.write_text(json.dumps(replay), encoding="utf-8")
            final.write_text(json.dumps(replay), encoding="utf-8")
            output = root / "release-decision.json"
            with patch.object(
                sys,
                "argv",
                [
                    "write_release_decision.py",
                    "--verification",
                    str(verification),
                    "--copy-attestation",
                    str(copy),
                    "--final-attestation",
                    str(final),
                    "--output",
                    str(output),
                ],
            ):
                write_release_decision.main()
            decision = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(decision["release_audit"], "PASS")
            self.assertEqual(decision["copy_attestation"]["sha256"], hashlib.sha256(copy.read_bytes()).hexdigest())
            verification.write_text(
                json.dumps(
                    {
                        "run_id": "run",
                        "runner_result": "PASS",
                        "pre_seal_audit": "PASS",
                        "release_audit": "PASS",
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "write_release_decision.py",
                        "--verification",
                        str(verification),
                        "--copy-attestation",
                        str(copy),
                        "--final-attestation",
                        str(final),
                        "--output",
                        str(output),
                    ],
                ),
                self.assertRaises(SystemExit),
            ):
                write_release_decision.main()
            self.assertEqual(json.loads(output.read_text())["release_audit"], "FAIL")

    def _write_anchor(self, root: Path) -> tuple[Path, str]:
        anchor = {
            "immutable_during_task": True,
            "legacy_acceptance_matrix": {"requirement_ids": ["TEMP-01", "STAT-03"]},
            "legacy_test_baseline": {"sha256": "x", "mode_octal": "0444", "test_id_count": 73},
        }
        path = root / "anchor.json"
        path.write_text(json.dumps(anchor), encoding="utf-8")
        path.chmod(0o444)
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def _row(self, requirement_id: str, validator: str, requirement_class: str, evidence: str, pointer: str, comparison: str, expected):
        return {
            "requirement_id": requirement_id,
            "title": requirement_id,
            "validator_id": validator,
            "requirement_class": requirement_class,
            "inputs": [evidence],
            "evidence_path": evidence,
            "json_pointer": pointer,
            "observed_value_type": "boolean" if isinstance(expected, bool) else "number",
            "comparison": comparison,
            "expected_value": expected,
            "command_provenance": ["scripts/validate_acceptance_matrix.py"],
            "release_blocker": True,
        }

    @staticmethod
    def _matrix(rows):
        return {
            "schema_version": "3.0.0",
            "release": "0.2.2",
            "migration": {"legacy_id_mapping": {"TEMP-01": "TEMP-01", "STAT-03": "STAT-03"}},
            "requirements": rows,
        }

    def test_temporary_false_mutation_fails_only_dependent_requirement(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            anchor, anchor_sha = self._write_anchor(run)
            (run / "temporary-files.json").write_text(
                json.dumps(
                    {
                        "passed": True,
                        "workspace_forbidden": [],
                        "retained_run_caches": [],
                    }
                ),
                encoding="utf-8",
            )
            coverage = {
                "old_core": {
                    "line": {"covered": 91, "total": 100, "fraction": 0.91},
                    "branch": {"covered": 81, "total": 100, "fraction": 0.81},
                    "combined": {"covered": 172, "total": 200, "fraction": 0.86},
                }
            }
            (run / "coverage.json").write_text(json.dumps(coverage), encoding="utf-8")
            matrix = self._matrix(
                [
                    self._row("TEMP-01", "temporary_hygiene", "temporary", "temporary-files.json", "/passed", "eq", True),
                    self._row("STAT-03", "coverage_arithmetic", "coverage", "coverage.json", "/old_core/line/fraction", "gte", 0.9),
                ]
            )
            matrix_path = run / "matrix.json"
            matrix_path.write_text(json.dumps(matrix), encoding="utf-8")
            first = evaluate_matrix(run, matrix_path, ROOT, anchor, anchor_sha)
            self.assertTrue(first["passed"])
            temporary = json.loads((run / "temporary-files.json").read_text())
            temporary["passed"] = False
            (run / "temporary-files.json").write_text(json.dumps(temporary), encoding="utf-8")
            mutated = evaluate_matrix(run, matrix_path, ROOT, anchor, anchor_sha)
            statuses = {item["requirement_id"]: item for item in mutated["requirements"]}
            self.assertEqual(statuses["TEMP-01"]["status"], "failed")
            self.assertIn("disagrees", statuses["TEMP-01"]["failure_reason"])
            self.assertEqual(statuses["STAT-03"]["status"], "passed")
            self.assertFalse(mutated["passed"])

    def test_schema_rejects_blanket_validator_and_missing_command(self):
        anchor = {"legacy_acceptance_matrix": {"requirement_ids": ["TEMP-01", "STAT-03"]}}
        row = self._row("TEMP-01", "temporary_hygiene", "temporary", "x.json", "/passed", "eq", True)
        other = {**row, "requirement_id": "STAT-03"}
        matrix = self._matrix([row, other])
        with self.assertRaisesRegex(MatrixValidationError, "does not support class|one validator"):
            validate_matrix_schema(matrix, anchor, ROOT)
        row["command_provenance"] = ["scripts/does-not-exist.py"]
        with self.assertRaisesRegex(MatrixValidationError, "does not exist"):
            validate_matrix_schema(
                {**matrix, "requirements": [row, {**other, "validator_id": "coverage_arithmetic", "requirement_class": "coverage"}]}, anchor, ROOT
            )

    def test_path_traversal_and_symlink_escape_are_errors(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unavailable")
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            anchor, anchor_sha = self._write_anchor(run)
            outside = run.parent / f"{run.name}-outside.json"
            outside.write_text('{"passed": true}', encoding="utf-8")
            self.addCleanup(outside.unlink, missing_ok=True)
            (run / "link.json").symlink_to(outside)
            coverage = {
                "old_core": {
                    "line": {"covered": 1, "total": 1, "fraction": 1},
                    "branch": {"covered": 1, "total": 1, "fraction": 1},
                    "combined": {"covered": 2, "total": 2, "fraction": 1},
                }
            }
            (run / "coverage.json").write_text(json.dumps(coverage), encoding="utf-8")
            rows = [
                self._row("TEMP-01", "temporary_hygiene", "temporary", "link.json", "/passed", "eq", True),
                self._row("STAT-03", "coverage_arithmetic", "coverage", "coverage.json", "/old_core/line/fraction", "gte", 0.9),
            ]
            matrix_path = run / "matrix.json"
            matrix_path.write_text(json.dumps(self._matrix(rows)), encoding="utf-8")
            report = evaluate_matrix(run, matrix_path, ROOT, anchor, anchor_sha)
            self.assertEqual(report["requirements"][0]["status"], "error")
            self.assertIn("symlink", report["requirements"][0]["failure_reason"])


if __name__ == "__main__":
    unittest.main()
