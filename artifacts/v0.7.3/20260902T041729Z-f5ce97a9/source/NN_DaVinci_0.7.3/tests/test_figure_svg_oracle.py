from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[1]
GENERATOR = PROJECT / "scripts/generate_figure_svg_oracle_fixtures.py"
ORACLE = PROJECT / "scripts/figure_svg_oracle.mjs"
VALIDATOR = PROJECT / "scripts/validate_figure_svg_oracle_fixtures.py"
EXPECTATIONS = PROJECT / "verification/fixtures/figure-svg-oracle-expectations.json"


def run(arguments: list[str], *, env: dict[str, str] | None = None, timeout: int = 90) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        cwd=PROJECT,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def browser_environment() -> dict[str, str]:
    if shutil.which(os.environ.get("NNDV_BROWSER", "google-chrome")) is None:
        raise unittest.SkipTest("Google Chrome is unavailable")
    environment = dict(os.environ)
    local_playwright = PROJECT / "node_modules/playwright-core/index.mjs"
    configured = environment.get("NNDV_PLAYWRIGHT_MODULE")
    if local_playwright.is_file():
        environment.pop("NNDV_PLAYWRIGHT_MODULE", None)
    elif not configured or not Path(configured).is_file():
        raise unittest.SkipTest("playwright-core is unavailable; install npm dependencies or set NNDV_PLAYWRIGHT_MODULE")
    return environment


class FigureSvgOracleStaticTests(unittest.TestCase):
    def test_fixture_generator_matches_executable_expectations(self) -> None:
        with tempfile.TemporaryDirectory(prefix="nndv-oracle-static-") as temporary:
            fixtures = Path(temporary) / "fixtures"
            completed = run([sys.executable, str(GENERATOR), str(fixtures)])
            self.assertEqual(completed.returncode, 0, completed.stderr)
            index = json.loads((fixtures / "fixture-index.json").read_text())
            expected = json.loads(EXPECTATIONS.read_text())
            self.assertEqual(set(index["fixtures"]), set(expected["fixtures"]))
            self.assertEqual(len(index["fixtures"]), 21)
            self.assertEqual(sum(item["expected_pass"] for item in expected["fixtures"].values()), 2)
            covered = {name for item in expected["fixtures"].values() for name in item["covers"]}
            self.assertEqual(covered, set(expected["required_coverage"]))
            for svg_path in fixtures.glob("*.svg"):
                source = svg_path.read_text()
                self.assertIn("&quot;pass&quot;: true", source)
                self.assertIn('data-horizontal-scale="1"', source)
                self.assertIn('data-transform-text-scale="1"', source)

    def test_oracle_is_dom_only_and_uses_required_chrome_geometry_apis(self) -> None:
        source = ORACLE.read_text()
        for browser_api in (
            "getBBox",
            "getBoundingClientRect",
            "getComputedTextLength",
            "getComputedStyle",
            "getScreenCTM",
            "document.fonts",
        ):
            self.assertIn(browser_api, source)
        self.assertIn("svg_path_flatten.js", source)
        self.assertNotIn("nn_davinci", source)
        self.assertNotIn("figure_proof", source)
        self.assertNotIn(".dataset.fontSizePt", source)
        self.assertNotIn(".dataset.horizontalScale", source)
        self.assertNotIn(".dataset.transformTextScale", source)


class FigureSvgOracleChromeTests(unittest.TestCase):
    fixtures: Path
    report: dict
    validation: dict
    environment: dict[str, str]
    temporary: tempfile.TemporaryDirectory[str]

    @classmethod
    def setUpClass(cls) -> None:
        cls.environment = browser_environment()
        cls.temporary = tempfile.TemporaryDirectory(prefix="nndv-figure-svg-oracle-")
        root = Path(cls.temporary.name)
        cls.fixtures = root / "fixtures"
        generated = run([sys.executable, str(GENERATOR), str(cls.fixtures)])
        if generated.returncode != 0:
            raise AssertionError(generated.stderr)
        report_path = root / "report.json"
        svg_files = sorted(cls.fixtures.glob("*.svg"))
        oracle = run(
            [
                "node",
                str(ORACLE),
                "--allow-failures",
                "--output",
                str(report_path),
                *(str(item) for item in svg_files),
            ],
            env=cls.environment,
        )
        if oracle.returncode != 0:
            raise AssertionError(oracle.stderr)
        validation_path = root / "validation.json"
        validated = run([sys.executable, str(VALIDATOR), str(report_path), "--output", str(validation_path)])
        if validated.returncode != 0:
            raise AssertionError(validated.stdout + validated.stderr)
        cls.report = json.loads(report_path.read_text())
        cls.validation = json.loads(validation_path.read_text())

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_chrome_oracle_classifies_all_adversarial_fixtures(self) -> None:
        contract = self.report["measurement_contract"]
        self.assertEqual(
            contract,
            {
                "final_dom_only": True,
                "metadata_trusted": False,
                "python_proof_imported": False,
                "data_scale_claims_trusted": False,
                "stroke_under_full_ctm": True,
                "path_flattener": "svg_path_flatten.js",
                "tolerance": contract["tolerance"],
            },
        )
        self.assertEqual(self.report["summary"], {"files": 21, "passed": 2, "failed": 19, "issues": 29})
        self.assertIs(self.validation["passed"], True)
        self.assertEqual(self.validation["fixture_count"], 21)
        self.assertEqual(self.validation["classification_count"], 21)
        self.assertEqual(self.validation["assertion_count"], 44)
        self.assertEqual(self.validation["coverage_count"], 25)
        by_name = {Path(item["file"]).name: item for item in self.report["reports"]}
        self.assertEqual(by_name["caption-1000.svg"]["summary"]["maximum_text_characters"], 1000)
        self.assertGreaterEqual(by_name["curve-through-tensor.svg"]["edges"][0]["flattened_point_count"], 8)
        self.assertAlmostEqual(by_name["local-6pt-style.svg"]["summary"]["minimum_font_pt"], 6, delta=0.01)
        self.assertAlmostEqual(
            by_name["text-translate-scale.svg"]["summary"]["minimum_horizontal_ctm_scale"],
            0.55,
            delta=0.001,
        )
        self.assertEqual(by_name["font-fallback.svg"]["summary"]["fallback_text_count"], 1)
        self.assertEqual(by_name["multipage-second-page-clip.svg"]["summary"]["page_count"], 2)
        positive = by_name["positive.svg"]
        self.assertGreaterEqual(positive["summary"]["stroke_count"], 4)
        self.assertAlmostEqual(positive["summary"]["minimum_stroke_pt"], 0.567, delta=0.01)
        self.assertTrue(all(item["effective_stroke_pt"] > 0 for item in positive["strokes"]))

    def test_oracle_default_exit_status_is_a_strict_gate(self) -> None:
        root = Path(self.temporary.name)
        positive_report = root / "positive.json"
        negative_report = root / "negative.json"
        positive = run(
            ["node", str(ORACLE), "--output", str(positive_report), str(self.fixtures / "positive.svg")],
            env=self.environment,
        )
        negative = run(
            [
                "node",
                str(ORACLE),
                "--output",
                str(negative_report),
                str(self.fixtures / "local-6pt-style.svg"),
            ],
            env=self.environment,
        )
        self.assertEqual(positive.returncode, 0, positive.stderr)
        self.assertEqual(negative.returncode, 1, negative.stderr)
        self.assertIs(json.loads(positive_report.read_text())["passed"], True)
        self.assertIs(json.loads(negative_report.read_text())["passed"], False)

    def test_validator_rejects_a_tampered_classification(self) -> None:
        tampered_report = json.loads(json.dumps(self.report))
        tampered_report["reports"][0]["passed"] = not tampered_report["reports"][0]["passed"]
        tampered = Path(self.temporary.name) / "tampered.json"
        tampered.write_text(json.dumps(tampered_report), encoding="utf-8")
        completed = run([sys.executable, str(VALIDATOR), str(tampered)])
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("expected", completed.stderr)
