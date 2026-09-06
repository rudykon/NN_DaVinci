from __future__ import annotations

import json
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

from nn_davinci.verification import format_coverage, meets_coverage_thresholds, summarize_coverage_totals


ROOT = Path(__file__).parents[1]


class CoverageSummaryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((ROOT / "verification" / "fixtures" / "coverage-summary-fixed.json").read_text(encoding="utf-8"))

    def test_line_branch_combined_are_distinct(self):
        summary = summarize_coverage_totals(self.fixture["core"])
        self.assertEqual(summary.line.fraction, Fraction(1736, 1952))
        self.assertEqual(summary.branch.fraction, Fraction(573, 734))
        self.assertEqual(summary.combined.fraction, Fraction(2309, 2686))
        self.assertAlmostEqual(summary.line.percent, 88.9344262295082)
        self.assertAlmostEqual(summary.branch.percent, 78.06539509536785)
        self.assertAlmostEqual(summary.combined.percent, self.fixture["core"]["percent_covered"])
        self.assertNotEqual(summary.branch.percent, self.fixture["core"]["percent_covered"])

    def test_thresholds_use_unrounded_fractions(self):
        core = summarize_coverage_totals(self.fixture["core"])
        self.assertFalse(meets_coverage_thresholds(core, minimum_line=Fraction(885, 1000), minimum_branch=Fraction(4, 5)))
        exactly = summarize_coverage_totals({"covered_lines": 177, "num_statements": 200, "covered_branches": 588, "num_branches": 734})
        self.assertTrue(meets_coverage_thresholds(exactly, minimum_line=Fraction(885, 1000), minimum_branch=Fraction(4, 5)))

    def test_all_package_raw_values_and_format_names(self):
        summary = summarize_coverage_totals(self.fixture["all_package"])
        self.assertEqual(summary.line.covered, 3621)
        self.assertEqual(summary.branch.covered, 1141)
        text = format_coverage("all_package", summary)
        self.assertIn("line=3621/4430=81.74%", text)
        self.assertIn("branch=1141/1590=71.76%", text)
        self.assertIn("combined=4762/6020=79.10%", text)


class CoverageManifestTests(unittest.TestCase):
    def test_core_manifest_and_exclusions_are_fixed(self):
        manifest = json.loads((ROOT / "verification" / "core-coverage-manifest.json").read_text(encoding="utf-8"))
        historical_all = json.loads((ROOT / "verification" / "fixtures" / "all-package-denominators-0.2.1-diagnostic.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["coverage_exclusions"], [])
        self.assertEqual(len(manifest["core_files"]), 11)
        self.assertIn("src/nn_davinci/layout/engine.py", manifest["core_files"])
        self.assertIn("src/nn_davinci/server.py", manifest["core_files"])
        self.assertEqual(manifest["observed_0_2_0"]["core"]["covered_branches"], 573)
        self.assertIs(historical_all["authoritative_for_pass"], False)
        self.assertEqual(sum(item["statements"] for item in historical_all["denominators_by_file"].values()), 4716)
        self.assertEqual(sum(item["branches"] for item in historical_all["denominators_by_file"].values()), 1690)


class EnvironmentManifestTests(unittest.TestCase):
    def test_root_build_and_verification_configs_are_hashed(self):
        from scripts import write_environment_manifest

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "environment.json"
            with patch.object(sys, "argv", ["write_environment_manifest.py", str(output)]):
                write_environment_manifest.main()
            sources = json.loads(output.read_text(encoding="utf-8"))["sources"]
        for required in (
            "eslint.config.mjs",
            "LICENSE",
            ".gitignore",
            "pyproject.toml",
            "package-lock.json",
            "verification/acceptance-matrix-0.2.1.json",
            "requirements/verification-0.2.1.txt",
            "verification/acceptance-matrix-0.2.2.json",
            "verification/source-allowlist-0.2.2.json",
            "verification/expanded-core-coverage-manifest.json",
            "verification/verification-lock-metadata-0.2.2.json",
            "docs/TRUST_ANCHOR_0.2.2.json",
            "requirements/verification-linux-x86_64-py313-0.2.2.lock",
            "verification/acceptance-matrix-0.2.3.json",
            "verification/source-allowlist-0.2.3.json",
            "verification/verification-lock-metadata-0.2.3.json",
            "requirements/verification-linux-x86_64-py313-0.2.3.lock",
        ):
            self.assertIn(required, sources)


class ReleaseDocumentTests(unittest.TestCase):
    def test_verification_time_comes_from_sealed_utc_fields(self):
        report = (ROOT / "docs" / "VERIFICATION_REPORT_0.2.md").read_text(encoding="utf-8")
        self.assertNotIn("Verification date:", report)
        self.assertIn("sealed `verification.json` `started_utc`", report)
        self.assertIn("`ended_utc`", report)


class AcceptanceMatrixTests(unittest.TestCase):
    def test_every_release_blocker_has_required_machine_fields(self):
        matrix = json.loads((ROOT / "verification/acceptance-matrix-0.2.1.json").read_text(encoding="utf-8"))
        required = {"requirement_id", "fixture_id/hash", "command", "independent_oracle", "threshold", "evidence_path"}
        self.assertGreaterEqual(len(matrix["requirements"]), 45)
        self.assertEqual(len({item["requirement_id"] for item in matrix["requirements"]}), len(matrix["requirements"]))
        self.assertTrue(all(required <= item.keys() and all(item[key] for key in required) for item in matrix["requirements"]))

    def test_0_2_2_matrix_has_executable_typed_predicates(self):
        matrix = json.loads((ROOT / "verification/acceptance-matrix-0.2.2.json").read_text(encoding="utf-8"))
        required = {
            "requirement_id",
            "title",
            "validator_id",
            "inputs",
            "evidence_path",
            "json_pointer",
            "observed_value_type",
            "comparison",
            "expected_value",
            "command_provenance",
            "release_blocker",
        }
        self.assertEqual(len(matrix["requirements"]), 34)
        self.assertEqual(len(matrix["migration"]["legacy_id_mapping"]), 48)
        self.assertTrue(all(required <= item.keys() and item["release_blocker"] for item in matrix["requirements"]))
        self.assertGreater(len({item["validator_id"] for item in matrix["requirements"]}), 5)

    def test_0_2_3_matrix_retains_canonical_ids_and_adds_parity_inputs(self):
        matrix = json.loads((ROOT / "verification/acceptance-matrix-0.2.3.json").read_text(encoding="utf-8"))
        previous = json.loads((ROOT / "verification/acceptance-matrix-0.2.2.json").read_text(encoding="utf-8"))
        self.assertEqual(matrix["schema_version"], "3.1.0")
        self.assertEqual(matrix["release"], "0.2.3")
        self.assertEqual(
            [item["requirement_id"] for item in matrix["requirements"]],
            [item["requirement_id"] for item in previous["requirements"]],
        )
        rows = {item["requirement_id"]: item for item in matrix["requirements"]}
        self.assertEqual(rows["TEST-01"]["expected_value"], 89)
        self.assertIn("tests/collected-test-ids.txt", rows["TEST-01"]["inputs"])
        self.assertEqual(rows["MATRIX-01"]["expected_value"], 54)


class PdfFontTableTests(unittest.TestCase):
    def test_emb_column_is_parsed_by_header_position_not_whitespace_field(self):
        from scripts.check_pdf_fonts import parse_embedded_table

        table = """name                                 type              encoding         emb sub uni object ID
------------------------------------ ----------------- ---------------- --- --- --- ---------
AAAAAA+CMSS8                         Type 1            Builtin          yes yes yes      9  0
BBBBBB+NotoSans-Regular              TrueType          WinAnsi          yes yes yes      8  0
"""
        self.assertEqual(parse_embedded_table(table), [True, True])
        self.assertEqual(parse_embedded_table(table.replace("yes yes yes", "no  yes yes", 1)), [False, True])


if __name__ == "__main__":
    unittest.main()
