from __future__ import annotations

from pathlib import Path
import re
import stat
from typing import ClassVar
import unittest


ROOT = Path(__file__).parents[1]
DRIVER = ROOT / "scripts" / "verify-full-0.7.1.sh"
PARENT_RUN_ID = "20260831T044446Z-9e6cd3cf"
PARENT_SOURCE_DIGEST = "16aa60c611c4cf8c327fe4174314091dcb8dae840dc22ce85f73dae9926fb00d"


class FullReleaseDriver071Tests(unittest.TestCase):
    source: ClassVar[str]

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = DRIVER.read_text(encoding="utf-8")

    def test_driver_is_fresh_strict_executable_and_non_overwriting(self) -> None:
        self.assertTrue(stat.S_IMODE(DRIVER.stat().st_mode) & stat.S_IXUSR)
        self.assertIn("set -euo pipefail", self.source)
        self.assertIn('nndv-071-full-${RUN_ID}-XXXXXX', self.source)
        self.assertIn('SNAPSHOT_DIR="$CONTROL_DIR/clean-source/NN_DaVinci_0.7.1"', self.source)
        self.assertIn('ARTIFACT_ROOT="$PROJECT_DIR/artifacts/v0.7.1"', self.source)
        self.assertIn('if [[ -e "$ARTIFACT_ROOT/$RUN_ID"', self.source)
        self.assertIn('"old_artifacts_used_as_current_output": False', self.source)
        self.assertIn("trap finish EXIT", self.source)

    def test_parent_is_the_pinned_read_only_070_source_and_artifact(self) -> None:
        self.assertIn(f'PARENT_RUN_ID="{PARENT_RUN_ID}"', self.source)
        self.assertIn('PARENT_SOURCE_FILES=356', self.source)
        self.assertIn(f'PARENT_SOURCE_DIGEST="{PARENT_SOURCE_DIGEST}"', self.source)
        self.assertIn('verification/source-allowlist-0.7.0.json', self.source)
        self.assertIn('scripts/verify_release_artifact_0_7.py', self.source)
        self.assertIn('reports/source/parent-0.7.0-artifact-verification.json', self.source)
        self.assertNotRegex(
            self.source,
            r"(?:cp|rsync|install)[^\n]*(?:AUTHORITATIVE_070_ARTIFACT|PARENT_SOURCE_DIR)",
        )

    def test_all_release_blockers_are_command_accounted(self) -> None:
        expected = {
            "clean-0.7.1-source-snapshot",
            "independent-parent-0.7.0-source-snapshot",
            "parent-0.7.0-source-identity",
            "npm-ci-offline",
            "authoritative-parent-0.7.0-artifact-read-only",
            "authoritative-parent-0.7.0-artifact-identity",
            "quick-0.7.1",
            "release-audit-0.7.1",
            "project-1.3-to-1.4-migration",
            "scene-studio-performance-three-repeats",
            "fresh-fourteen-case-scene-generation",
            "independent-scene-artifact-validation",
            "strict-fourteen-svg-chrome-oracle",
            "independent-pdf-tikz-publication-oracle",
            "fourteen-case-0.7.0-to-0.7.1-before-after-proof",
            "visual-oracle-positive-negative-mutations",
            "e2e-editor",
            "e2e-responsive",
            "e2e-semantic",
            "e2e-product",
            "e2e-trial",
            "e2e-figure-studio",
            "e2e-scene-studio",
            "independent-scene-visual-validation",
            "package-build",
            "wheel-sdist-install-0.7.1",
            "environment-manifest",
        }
        observed = set(re.findall(r"^run_logged ([a-zA-Z0-9._-]+) ", self.source, re.MULTILINE))
        self.assertEqual(expected, observed)
        self.assertIn('"failed": failed', self.source)

    def test_all_fourteen_visual_and_cross_format_gates_are_fresh(self) -> None:
        expected_fragments = (
            'scripts/generate_scene_artifacts_0_7_1.py',
            'scripts/validate_scene_artifacts_0_7_1.py',
            'scripts/scene_svg_oracle_0_7_1.mjs',
            'scripts/scene_publication_oracle_0_7_1.py',
            'scripts/generate_scene_before_after_0_7_1.py',
            'scripts/validate_visual_oracle_fixtures_0_7_1.mjs',
            '--input-root "$STAGING_DIR/exports/scene-corpus"',
            '--expected-cases 14',
        )
        for fragment in expected_fragments:
            self.assertIn(fragment, self.source)

    def test_performance_package_and_final_artifact_use_071_contracts(self) -> None:
        self.assertIn('--baseline-scene-report "$PARENT_SCENE_PERFORMANCE"', self.source)
        self.assertIn('--repeats 3', self.source)
        self.assertIn('--expected-version 0.7.1', self.source)
        self.assertIn('scripts/finalize_artifact_0_7_1.py', self.source)
        self.assertIn('scripts/verify_release_artifact_0_7_1.py', self.source)
        self.assertIn('NNDV_071_FULL_RESULT', self.source)
        self.assertIn("inherited_0_7_0", self.source)

    def test_seven_browser_suites_have_isolated_fresh_paths(self) -> None:
        self.assertEqual(self.source.count('TMPDIR="$BROWSER_TMP_ROOT/'), 7)
        for command in (
            "npm run e2e",
            "npm run e2e:responsive",
            "npm run e2e:semantic",
            "npm run e2e:product",
            "npm run e2e:trial",
            "npm run e2e:figure",
            "npm run e2e:scene",
        ):
            self.assertEqual(1, len(re.findall(rf"^  {re.escape(command)}$", self.source, re.MULTILINE)))


if __name__ == "__main__":
    unittest.main()
