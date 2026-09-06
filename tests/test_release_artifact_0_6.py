from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from scripts.verify_release_artifact_0_6 import verify


ROOT = Path(__file__).parents[1]


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class ReleaseArtifact060Tests(unittest.TestCase):
    def reports(self, root: Path) -> None:
        quick = {
            "status": "PASS",
            "python": {
                "collected": 170, "passed": 170, "failed": 0, "errors": 0,
                "skipped": 0, "deselected": 0, "inherited_0_5_2_tests": 149,
            },
            "coverage": {},
        }
        editor = {"counts": {"passed": 10, "failed": 0, "assertions": 63}}
        responsive = {"status": "passed", "viewport_count": 7}
        semantic = {"status": "passed", "assertion_count": 27}
        product = {"status": "passed", "assertion_count": 31}
        trial = {
            "status": "passed", "assertion_count": 65,
            "human_participants": 0, "human_usability_claim": False,
        }
        figure = {
            "status": "PASS", "tested_viewports": [1440, 800, 390],
            "median_interaction_ms": 16,
            "counts": {"passed": 1, "failed": 0, "assertions": 44, "console_page_request_errors": 0},
        }
        exports = {"status": "PASS", "counts": {"formats": 28, "failures": 0}}
        performance = {"status": "PASS", "figure_objects": 1_000}
        packaging = {"passed": True, "checks": 12, "wheel": {}, "sdist": {}}
        audit = {"status": "PASS"}
        values = {
            "reports/quick/quick-verification.json": quick,
            "reports/e2e/editor.json": editor,
            "reports/e2e/responsive.json": responsive,
            "reports/e2e/semantic.json": semantic,
            "reports/e2e/product.json": product,
            "reports/e2e/trial.json": trial,
            "reports/e2e/figure-studio.json": figure,
            "reports/exports/figure-export-report.json": exports,
            "reports/performance/figure-studio.json": performance,
            "reports/packaging/package-install.json": packaging,
            "reports/docs/release-audit.json": audit,
        }
        for relative, value in values.items():
            write_json(root / relative, value)

    def test_finalizer_creates_exact_inventory_and_verifier_rejects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            staging = temporary / "staging"
            staging.mkdir()
            self.reports(staging)
            source = temporary / "source"
            source.mkdir()
            source_file = source / "README.md"
            source_file.write_text("release fixture\n", encoding="utf-8")
            digest = hashlib.sha256(source_file.read_bytes()).hexdigest()
            source_tree_digest = hashlib.sha256(
                f"README.md\0{digest}\0{source_file.stat().st_size}\n".encode()
            ).hexdigest()
            source_report = temporary / "source.json"
            write_json(source_report, {
                "schema_version": "nndv-clean-source-snapshot-2",
                "release": "0.6.0",
                "passed": True,
                "file_count": 1,
                "source_tree_digest": source_tree_digest,
                "allowlist": "verification/source-allowlist-0.6.0.json",
                "allowlist_sha256": "a" * 64,
                "source": str(source),
                "snapshot": str(source),
                "forbidden_paths": [],
                "files": {
                    "README.md": {
                        "bytes": source_file.stat().st_size,
                        "sha256": digest,
                        "mode": f"{source_file.stat().st_mode & 0o7777:04o}",
                    }
                },
            })
            artifact_root = temporary / "artifacts"
            run_id = "20260830T000000Z-fixture"
            command = [
                sys.executable, str(ROOT / "scripts" / "finalize_artifact_0_6.py"),
                "--staging", str(staging), "--source-root", str(source),
                "--source-report", str(source_report), "--artifact-root", str(artifact_root),
                "--run-id", run_id,
                "--started-utc", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "--started-epoch", str(time.time()),
            ]
            environment = {**os.environ, "PYTHONPATH": f"{ROOT}:{ROOT / 'src'}"}
            completed = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, check=False)
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            artifact = artifact_root / run_id
            report = verify(artifact)
            self.assertEqual("PASS", report["status"], report["failures"])
            self.assertEqual(1, report["source_file_count"])

            (artifact / "source" / "replay-source" / "README.md").write_text("tampered\n", encoding="utf-8")
            tampered = verify(artifact)
            self.assertEqual("FAIL", tampered["status"])
            self.assertTrue(any("mismatch" in failure for failure in tampered["failures"]))

    def test_verifier_rejects_symlink_and_special_inventory_objects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "target").write_text("target", encoding="utf-8")
            (root / "link").symlink_to("target")
            write_json(root / "MANIFEST.json", {
                "schema_version": "nndv-0.6.0-artifact-manifest-1",
                "release": "0.6.0 Beta — Scientific Figure Studio",
                "run_id": "fixture",
                "source": {"file_count": 0, "digest": hashlib.sha256(b"").hexdigest()},
                "entries": {},
            })
            (root / "SHA256SUMS").write_text("", encoding="utf-8")
            result = verify(root)
            self.assertEqual("FAIL", result["status"])
            self.assertIn("symlink:link", result["unsafe_objects"])


if __name__ == "__main__":
    unittest.main()
