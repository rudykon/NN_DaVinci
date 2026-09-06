from __future__ import annotations

from pathlib import Path
import re
import stat
from typing import ClassVar
import unittest


ROOT = Path(__file__).parents[1]
DRIVER = ROOT / "scripts" / "verify-full-0.7.0.sh"
PARENT_RUN_ID = "20260830T122225Z-0f6f36c2"
PARENT_SOURCE_DIGEST = "26469ab2eb7fd2d10a4d058ec7061017f8de005d714ca2760e2412a414d7ad7f"


class FullReleaseDriver070Tests(unittest.TestCase):
    source: ClassVar[str]

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = DRIVER.read_text(encoding="utf-8")

    def test_driver_is_strict_executable_and_uses_a_new_controller(self) -> None:
        self.assertTrue(stat.S_IMODE(DRIVER.stat().st_mode) & stat.S_IXUSR)
        self.assertIn("set -euo pipefail", self.source)
        self.assertRegex(
            self.source,
            r'CONTROL_DIR="\$\(mktemp -d "\$TEMPORARY_ROOT/nndv-070-full-\$\{RUN_ID\}-XXXXXX"\)"',
        )
        self.assertIn('SNAPSHOT_DIR="$CONTROL_DIR/clean-source/NN_DaVinci_0.7.0"', self.source)
        self.assertIn('STAGING_DIR="$CONTROL_DIR/artifact-staging"', self.source)
        self.assertIn('WORK_DIR="$CONTROL_DIR/work"', self.source)
        self.assertIn('BROWSER_TMP_ROOT="$(mktemp -d "/tmp/n7b-XXXXXX")"', self.source)
        self.assertEqual(self.source.count('TMPDIR="$BROWSER_TMP_ROOT/'), 7)
        self.assertIn("trap finish EXIT", self.source)
        self.assertIn('echo "0.7.0 full diagnostics retained: $CONTROL_DIR"', self.source)
        self.assertIn('not resolved.name.startswith("nndv-070-full-")', self.source)
        self.assertIn("shutil.rmtree(resolved)", self.source)
        self.assertIn("SUCCESS=1", self.source)

    def test_both_sources_are_fresh_allowlisted_snapshots(self) -> None:
        self.assertEqual(self.source.count("scripts/create_clean_snapshot.py"), 2)
        self.assertIn("--allowlist verification/source-allowlist-0.7.0.json", self.source)
        self.assertIn("--allowlist verification/source-allowlist-0.6.1.json", self.source)
        self.assertEqual(self.source.count("--reject-symlinks"), 2)
        self.assertIn("PARENT_SOURCE_FILES=294", self.source)
        self.assertIn(f'PARENT_SOURCE_DIGEST="{PARENT_SOURCE_DIGEST}"', self.source)
        self.assertIn('report.get("file_count") == expected_files', self.source)
        self.assertIn('report.get("source_tree_digest") == expected_digest', self.source)
        self.assertIn('SOURCE_REPORT="$STAGING_DIR/reports/source/snapshot.json"', self.source)
        self.assertIn(
            'PARENT_SOURCE_REPORT="$STAGING_DIR/reports/source/parent-0.6.1-snapshot.json"',
            self.source,
        )

    def test_bytecode_cache_is_fresh_reusable_and_outside_the_snapshot(self) -> None:
        self.assertIn('export PYTHONPYCACHEPREFIX="$WORK_DIR/pycache"', self.source)
        self.assertIn("unset PYTHONDONTWRITEBYTECODE", self.source)
        self.assertNotIn("export PYTHONDONTWRITEBYTECODE=1", self.source)

    def test_parent_artifact_is_only_a_verified_read_only_baseline(self) -> None:
        self.assertIn(f'PARENT_RUN_ID="{PARENT_RUN_ID}"', self.source)
        self.assertIn("scripts/verify_release_artifact_0_6_1.py", self.source)
        self.assertIn(
            'PARENT_ARTIFACT_REPORT="$STAGING_DIR/reports/source/parent-0.6.1-artifact-verification.json"',
            self.source,
        )
        self.assertIn('--baseline-figure-report "$PARENT_FIGURE_PERFORMANCE"', self.source)
        self.assertNotRegex(
            self.source,
            r"(?:cp|rsync|install)[^\n]*(?:AUTHORITATIVE_061_ARTIFACT|PARENT_SOURCE_DIR)",
        )
        self.assertNotIn("artifacts/v0.6.1/$RUN_ID", self.source)
        self.assertNotIn("finalize_artifact_0_6_1.py", self.source)
        self.assertIn('ARTIFACT_ROOT="$PROJECT_DIR/artifacts/v0.7.0"', self.source)
        self.assertIn('"old_artifacts_used_as_current_output": False', self.source)

    def test_absent_artifact_root_is_created_safely_before_outputs(self) -> None:
        create = self.source.index('mkdir -p "$ARTIFACT_ROOT"')
        overwrite_guard = self.source.index('if [[ -e "$ARTIFACT_ROOT/$RUN_ID"')
        finalize_redirect = self.source.index('> "$ARTIFACT_ROOT/$RUN_ID.finalize.log"')
        self.assertLess(create, overwrite_guard)
        self.assertLess(create, finalize_redirect)
        self.assertIn('-L "$PROJECT_DIR/artifacts"', self.source)
        self.assertIn('-L "$ARTIFACT_ROOT"', self.source)
        self.assertIn('! -d "$ARTIFACT_ROOT"', self.source)

    def test_every_required_fresh_command_is_accounted_for(self) -> None:
        required_ids = {
            "clean-0.7.0-source-snapshot",
            "independent-parent-0.6.1-source-snapshot",
            "parent-0.6.1-source-identity",
            "authoritative-parent-0.6.1-artifact-read-only",
            "authoritative-parent-0.6.1-artifact-identity",
            "npm-ci-offline",
            "quick-0.7.0",
            "release-audit-0.7.0",
            "project-1.3-to-1.4-migration",
            "scene-studio-performance-three-repeats",
            "fresh-fourteen-case-scene-generation",
            "independent-scene-artifact-validation",
            "e2e-editor",
            "e2e-responsive",
            "e2e-semantic",
            "e2e-product",
            "e2e-trial",
            "e2e-figure-studio",
            "e2e-scene-studio",
            "independent-scene-visual-validation",
            "package-build",
            "wheel-sdist-install-0.7.0",
            "environment-manifest",
        }
        observed = set(re.findall(r"^run_logged ([a-zA-Z0-9._-]+) ", self.source, re.MULTILINE))
        self.assertEqual(observed, required_ids)
        self.assertIn('"argv": argv', self.source)
        self.assertIn('"working_directory": working_directory', self.source)
        self.assertIn('"exit_code": exit_code', self.source)
        self.assertIn('"log": log', self.source)
        self.assertIn('"failed": failed', self.source)

    def test_scene_outputs_performance_and_package_install_are_fresh(self) -> None:
        self.assertIn("scripts/audit_release_0_7.py", self.source)
        self.assertIn("scripts/benchmark_scene_studio_0_7.py", self.source)
        self.assertIn("--repeats 3", self.source)
        self.assertIn("scripts/generate_scene_artifacts_0_7.py", self.source)
        self.assertIn("scripts/validate_scene_artifacts_0_7.py", self.source)
        self.assertIn("scripts/validate_scene_visual_evidence_0_7.py", self.source)
        self.assertIn('--output-dir "$STAGING_DIR/exports/scene-corpus"', self.source)
        self.assertIn(
            '--artifact-root "$STAGING_DIR/evidence/scene-studio/scene-studio-artifacts"',
            self.source,
        )
        self.assertIn('--output "$STAGING_DIR/reports/visual/scene-studio.json"', self.source)
        self.assertIn('--expected-version 0.7.0', self.source)
        self.assertIn("scripts/write_environment_manifest.py", self.source)
        self.assertIn("scripts/finalize_artifact_0_7.py", self.source)
        self.assertIn("scripts/verify_release_artifact_0_7.py", self.source)
        self.assertIn("NNDV_070_FULL_RESULT", self.source)
        setup_prefix = self.source.split("cd \"$PROJECT_DIR\"", 1)[0]
        self.assertNotIn('"$WORK_DIR/package-install/venvs"', setup_prefix)

    def test_project_scene_migration_report_is_fresh_and_release_blocking(self) -> None:
        self.assertIn("project-1.3-to-1.4-migration", self.source)
        self.assertIn("scripts/verify_scene_migration_0_7.py", self.source)
        self.assertIn('reports/migration/project-1.3-to-1.4.json', self.source)

    def test_all_seven_browser_suites_have_explicit_fresh_paths(self) -> None:
        expected_commands = (
            "npm run e2e",
            "npm run e2e:responsive",
            "npm run e2e:semantic",
            "npm run e2e:product",
            "npm run e2e:trial",
            "npm run e2e:figure",
            "npm run e2e:scene",
        )
        for command in expected_commands:
            self.assertEqual(
                len(re.findall(rf"^  {re.escape(command)}$", self.source, re.MULTILINE)),
                1,
                command,
            )
        expected_paths = (
            'NNDV_E2E_DIR="$WORK_DIR/editor/runtime"',
            'NNDV_E2E_REPORT="$STAGING_DIR/reports/e2e/editor.json"',
            'TMPDIR="$BROWSER_TMP_ROOT/responsive"',
            'NNDV_RESPONSIVE_SCREENSHOT_DIR="$STAGING_DIR/screenshots/responsive"',
            'NNDV_RESPONSIVE_E2E_REPORT="$STAGING_DIR/reports/e2e/responsive.json"',
            'NNDV_SEMANTIC_E2E_DIR="$WORK_DIR/semantic/runtime"',
            'NNDV_SEMANTIC_E2E_REPORT="$STAGING_DIR/reports/e2e/semantic.json"',
            'NNDV_PRODUCT_E2E_DIR="$WORK_DIR/product/runtime"',
            'NNDV_PRODUCT_E2E_REPORT="$STAGING_DIR/reports/e2e/product.json"',
            'NNDV_TRIAL_E2E_DIR="$WORK_DIR/trial/runtime"',
            'NNDV_TRIAL_E2E_REPORT="$STAGING_DIR/reports/e2e/trial.json"',
            'NNDV_FIGURE_E2E_DIR="$WORK_DIR/figure/runtime"',
            'NNDV_FIGURE_E2E_REPORT="$STAGING_DIR/reports/e2e/figure-studio.json"',
            'NNDV_SCENE_E2E_DIR="$STAGING_DIR/evidence/scene-studio"',
            'NNDV_SCENE_E2E_REPORT="$STAGING_DIR/reports/e2e/scene-studio.json"',
        )
        for path in expected_paths:
            self.assertIn(path, self.source)


if __name__ == "__main__":
    unittest.main()
