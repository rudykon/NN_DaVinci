from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from typing import Any

from scripts.finalize_artifact_0_7 import (
    EXPECTED_COMMAND_IDS,
    PARENT_RUN_ID,
    PARENT_SOURCE_DIGEST,
    RELEASE,
    REPORTS,
    canonical_inventory_digest,
    inventory,
    payload_failures,
    report_failures,
)
from scripts.validate_scene_visual_evidence_0_7 import validate_scene_visual_evidence
from tests.test_scene_visual_evidence_070 import SceneVisualEvidenceFixture


ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class ReleaseArtifact070Tests(unittest.TestCase):
    def reports(self, staging: Path, run_id: str) -> dict[str, dict[str, Any]]:
        corpus_root = staging / "exports" / "scene-corpus"
        for case_index in range(14):
            for file_index in range(12):
                path = corpus_root / f"case-{case_index:02d}" / f"file-{file_index:02d}.bin"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(f"{case_index}:{file_index}\n".encode())
        corpus_files = inventory(corpus_root)

        ids_path = staging / "reports" / "quick" / "collected-test-ids.txt"
        ids_path.parent.mkdir(parents=True, exist_ok=True)
        ids_path.write_text("".join(f"test_fixture_{index:03d}\n" for index in range(300)), encoding="utf-8")

        distributions = staging / "distributions"
        distributions.mkdir(parents=True)
        wheel_path = distributions / "nn_davinci-0.7.0-py3-none-any.whl"
        sdist_path = distributions / "nn_davinci-0.7.0.tar.gz"
        wheel_path.write_bytes(b"fixture wheel payload\n")
        sdist_path.write_bytes(b"fixture sdist payload\n")

        command_records: list[dict[str, object]] = []
        for sequence, identifier in enumerate(EXPECTED_COMMAND_IDS, 1):
            relative = f"logs/{identifier}.log"
            log = staging / relative
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text("fixture command PASS\n", encoding="utf-8")
            command_records.append({
                "id": identifier,
                "sequence": sequence,
                "argv": [identifier],
                "working_directory": "/fresh/source",
                "exit_code": 0,
                "log": relative,
            })

        responsive_root = staging / "screenshots" / "responsive"
        responsive_root.mkdir(parents=True)
        responsive_names = {
            *(f"toolbar-{width}.png" for width in (1440, 1024, 800, 768, 568, 390, 320)),
            "paper-menu-1440.png",
            "view-menu-390.png",
        }
        for name in responsive_names:
            (responsive_root / name).write_bytes(b"\x89PNG\r\n\x1a\nfixture")

        source_files = {
            f"src/fixture-{index:03d}.py": {
                "bytes": index + 1,
                "mode": "0644",
                "sha256": hashlib.sha256(f"source-{index}".encode()).hexdigest(),
            }
            for index in range(300)
        }
        parent_files = {
            f"parent/fixture-{index:03d}.py": {
                "bytes": index + 1,
                "mode": "0644",
                "sha256": hashlib.sha256(f"parent-{index}".encode()).hexdigest(),
            }
            for index in range(294)
        }
        python = {
            "collected": 300,
            "passed": 300,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "deselected": 0,
            "inherited_0_6_1_tests": 246,
            "baseline_0_6_1_missing": [],
            "test_ids_sha256": hashlib.sha256(ids_path.read_bytes()).hexdigest(),
        }
        gates = {
            "old_core_passed": True,
            "expanded_core_passed": True,
            "all_package_passed": True,
            "scene_core_80_percent": True,
        }
        counts = {
            "cases": 14,
            "templates": 7,
            "real_models": 7,
            "passing_cases": 14,
            "scene_exports": 140,
            "projects": 14,
            "comparison_files": 14,
            "regular_files": 168,
            "failures": 0,
        }
        evidence_root = staging / "evidence" / "scene-studio" / "scene-studio-artifacts"
        evidence_root.mkdir(parents=True)
        scene_fixture = SceneVisualEvidenceFixture(evidence_root)
        scene_report = scene_fixture.report
        scene_report["required_workflows"]["scene_templates_7"] = True
        scene_report["quality_checks"]["label"] = True
        scene_report_path = staging / REPORTS["scene"]
        write_json(scene_report_path, scene_report)
        scene_fixture.report_path.unlink()
        write_json(
            evidence_root / "pre-reload-project.json",
            {"project_version": "1.4", "scene_ir": {"schema_version": "1.0"}},
        )
        visual_report = validate_scene_visual_evidence(scene_report_path, evidence_root)
        return {
            "quick": {
                "schema_version": "nndv-0.7.0-quick-verification-1",
                "release": RELEASE,
                "status": "PASS",
                "python": python,
                "coverage": {"gates": gates},
            },
            "scene_corpus": {
                "schema_version": "nndv-0.7.0-scene-artifact-corpus-1",
                "release": RELEASE,
                "status": "PASS",
                "fresh_outputs": True,
                "offline_generation": True,
                "weights_downloaded": False,
                "counts": counts,
                "format_counts": {
                    name: 14
                    for name in ("svg", "pdf", "tikz", "pptx", "png", "eps", "html", "json", "gltf", "glb")
                },
                "output_file_count": 168,
                "output_tree_digest": canonical_inventory_digest(corpus_files),
                "failures": [],
            },
            "scene_corpus_validation": {
                "schema_version": "nndv-0.7.0-scene-artifact-validation-1",
                "status": "PASS",
                "validator_is_independent_of_generator": True,
                "counts": {"passing_cases": 14},
                "failures": [],
            },
            "performance": {
                "schema_version": "nndv-0.7.0-scene-studio-performance-1",
                "status": "PASS",
                "repeats": 3,
                "failures": [],
            },
            "audit": {
                "schema_version": "nndv-0.7.0-release-audit-1",
                "release": RELEASE,
                "status": "PASS",
                "failures": [],
                "human_participants": 0,
            },
            "migration": {
                "schema_version": "nndv-0.7.0-project-scene-migration-1",
                "release": RELEASE,
                "status": "PASS",
                "counts": {"expected": 7, "checked": 7, "passed": 7, "failed": 0},
                "migration_contract": {
                    "graph_ir_mutated": False,
                    "figure_ir_mutated": False,
                    "scene_geometry_inferred": False,
                    "model_semantics_inferred": False,
                    "provenance_inferred": False,
                },
                "failures": [],
            },
            "editor": {
                "schema_version": "1.0",
                "counts": {"e2e_scenarios": 11, "passed": 11, "failed": 0, "skipped": 0, "assertions": 71},
                "scenarios": [
                    {"id": f"scenario-{index}", "status": "passed", "console_errors": []}
                    for index in range(11)
                ],
            },
            "responsive": {
                "schema_version": "0.5.2-responsive-workspace-e2e-1",
                "status": "passed",
                "assertion_count": 168,
            },
            "semantic": {
                "schema_version": "0.3.0-semantic-workflow-1",
                "status": "passed",
                "assertion_count": 28,
            },
            "product": {
                "schema_version": "0.5.1-product-workflow-1",
                "status": "passed",
                "assertion_count": 32,
            },
            "trial": {
                "schema_version": "0.5.1-trial-workflow-e2e-1",
                "status": "passed",
                "assertion_count": 65,
                "human_participants": 0,
            },
            "figure": {
                "schema_version": "nndv-0.6.1-figure-studio-e2e-1",
                "status": "PASS",
                "counts": {
                    "scenarios": 1,
                    "passed": 1,
                    "failed": 0,
                    "skipped": 0,
                    "assertions": 75,
                    "console_page_request_errors": 0,
                },
                "errors": [],
            },
            "scene": scene_report,
            "visual": visual_report,
            "packaging": {
                "checks": 16,
                "passed": True,
                "wheel_installed_with_dependencies": True,
                "sdist_installed_with_dependencies": True,
                "pip_check_passed": True,
                "web_assets": True,
                "figure_templates": True,
                "scene_templates": True,
                "cli_smoke": True,
                "lock_matches": True,
                "wheel": {
                    "name": wheel_path.name,
                    "bytes": wheel_path.stat().st_size,
                    "sha256": hashlib.sha256(wheel_path.read_bytes()).hexdigest(),
                },
                "sdist": {
                    "name": sdist_path.name,
                    "bytes": sdist_path.stat().st_size,
                    "sha256": hashlib.sha256(sdist_path.read_bytes()).hexdigest(),
                },
                "wheel_install": {"version": "0.7.0", "passed": True},
                "sdist_install": {"version": "0.7.0", "passed": True},
            },
            "source": {
                "schema_version": "nndv-clean-source-snapshot-2",
                "passed": True,
                "release": "0.7.0",
                "file_count": 300,
                "source_tree_digest": "1" * 64,
                "allowlist_sha256": "2" * 64,
                "files": source_files,
                "forbidden_paths": [],
            },
            "parent_source": {
                "schema_version": "nndv-clean-source-snapshot-2",
                "passed": True,
                "file_count": 294,
                "source_tree_digest": PARENT_SOURCE_DIGEST,
                "files": parent_files,
                "forbidden_paths": [],
            },
            "parent_artifact": {
                "status": "PASS",
                "run_id": PARENT_RUN_ID,
                "source_file_count": 294,
                "source_digest": PARENT_SOURCE_DIGEST,
                "failures": [],
            },
            "commands": {
                "schema_version": "nndv-0.7.0-full-command-report-1",
                "release": RELEASE,
                "run_id": run_id,
                "fresh_control_root": True,
                "old_artifacts_used_as_current_output": False,
                "command_count": len(EXPECTED_COMMAND_IDS),
                "completed": len(EXPECTED_COMMAND_IDS),
                "failed": 0,
                "commands": command_records,
            },
            "environment": {
                "project_version": "0.7.0",
                "git_repository": False,
                "python": sys.version,
                "hardware": {},
                "tools": {"browser": "Chrome", "node": "Node", "npm": "npm"},
                "sources": {name: value["sha256"] for name, value in source_files.items()},
            },
        }

    def test_release_gates_reject_skeletal_claims_and_missing_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            staging = Path(temporary) / "staging"
            reports = self.reports(staging, "fixture-run")
            self.assertEqual([], report_failures(reports))
            self.assertEqual([], payload_failures(staging, reports))

            mutations: list[tuple[str, dict[str, dict[str, Any]]]] = []
            zero_tests = deepcopy(reports)
            zero_tests["quick"]["python"]["collected"] = 0
            zero_tests["quick"]["python"]["passed"] = 0
            mutations.append(("zero tests", zero_tests))
            empty_commands = deepcopy(reports)
            empty_commands["commands"]["commands"] = []
            empty_commands["commands"]["command_count"] = 0
            empty_commands["commands"]["completed"] = 0
            mutations.append(("empty commands", empty_commands))
            skeletal_audit = deepcopy(reports)
            skeletal_audit["audit"] = {"status": "PASS"}
            mutations.append(("skeletal audit", skeletal_audit))
            skeletal_package = deepcopy(reports)
            skeletal_package["packaging"] = {"passed": True}
            mutations.append(("skeletal package", skeletal_package))
            missing_scene_identity = deepcopy(reports)
            missing_scene_identity["scene"].pop("schema_version")
            mutations.append(("unidentified Scene E2E", missing_scene_identity))
            skeletal_visual = deepcopy(reports)
            skeletal_visual["visual"] = {"status": "PASS"}
            mutations.append(("skeletal independent visual evidence", skeletal_visual))
            unbound_svg_oracle = deepcopy(reports)
            unbound_svg_oracle["visual"]["svg_visual_oracle"]["source"]["sha256"] = "0" * 64
            mutations.append(("unbound SVG visual oracle", unbound_svg_oracle))
            arbitrary_environment = deepcopy(reports)
            arbitrary_environment["environment"] = {"python": sys.version}
            mutations.append(("arbitrary environment", arbitrary_environment))
            for label, mutated in mutations:
                with self.subTest(label=label):
                    self.assertTrue(report_failures(mutated))

            missing = staging / "exports" / "scene-corpus" / "case-00" / "file-00.bin"
            missing.unlink()
            self.assertTrue(payload_failures(staging, reports))

    def test_finalize_verify_and_detect_payload_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "staging"
            run_id = "20990101T000000Z-release-test"
            reports = self.reports(staging, run_id)
            for name, relative in REPORTS.items():
                write_json(staging / relative, reports[name])
            (staging / "exports").mkdir(parents=True, exist_ok=True)
            (staging / "exports" / "proof.txt").write_text("sealed payload\n", encoding="utf-8")

            artifact_root = root / "artifacts"
            started_epoch = int(time.time())
            started_utc = datetime.fromtimestamp(started_epoch, timezone.utc).isoformat()
            finalized = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "finalize_artifact_0_7.py"),
                    "--staging",
                    str(staging),
                    "--artifact-root",
                    str(artifact_root),
                    "--run-id",
                    run_id,
                    "--started-utc",
                    started_utc,
                    "--started-epoch",
                    str(started_epoch),
                    "--project-root",
                    str(ROOT),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, finalized.returncode, finalized.stderr or finalized.stdout)
            artifact = artifact_root / run_id
            output = root / "verification-pass.json"
            verified = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "verify_release_artifact_0_7.py"),
                    str(artifact),
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, verified.returncode, verified.stderr or verified.stdout)
            self.assertEqual("PASS", json.loads(output.read_text(encoding="utf-8"))["status"])

            verification_path = artifact / "verification.json"
            manifest_path = artifact / "MANIFEST.json"
            checksums_path = artifact / "SHA256SUMS"
            original_controls = {
                path: path.read_bytes()
                for path in (verification_path, manifest_path, checksums_path)
            }
            verification_payload = json.loads(verification_path.read_text(encoding="utf-8"))
            verification_payload["visual_evidence"]["screenshots"] += 1
            write_json(verification_path, verification_payload)
            manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_payload["entries"]["verification.json"] = {
                "bytes": verification_path.stat().st_size,
                "sha256": hashlib.sha256(verification_path.read_bytes()).hexdigest(),
            }
            write_json(manifest_path, manifest_payload)
            checksums_payload = json.loads(checksums_path.read_text(encoding="utf-8"))
            for item in checksums_payload["entries"]:
                candidate = artifact / item["path"]
                item["size"] = candidate.stat().st_size
                item["sha256"] = hashlib.sha256(candidate.read_bytes()).hexdigest()
            write_json(checksums_path, checksums_payload)
            summary_output = root / "verification-summary-tampered.json"
            summary_tampered = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "verify_release_artifact_0_7.py"),
                    str(artifact),
                    "--output",
                    str(summary_output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(1, summary_tampered.returncode)
            summary_report = json.loads(summary_output.read_text(encoding="utf-8"))
            self.assertTrue(
                any("visual-evidence summary" in failure for failure in summary_report["failures"]),
            )
            for path, payload in original_controls.items():
                path.write_bytes(payload)

            manifest_before = (artifact / "MANIFEST.json").read_bytes()
            unsafe_output = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "verify_release_artifact_0_7.py"),
                    str(artifact),
                    "--output",
                    str(artifact / "MANIFEST.json"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(0, unsafe_output.returncode)
            self.assertEqual(manifest_before, (artifact / "MANIFEST.json").read_bytes())

            (artifact / "exports" / "proof.txt").write_text("tampered payload\n", encoding="utf-8")
            tampered_output = root / "verification-tampered.json"
            tampered = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "verify_release_artifact_0_7.py"),
                    str(artifact),
                    "--output",
                    str(tampered_output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(1, tampered.returncode)
            report = json.loads(tampered_output.read_text(encoding="utf-8"))
            self.assertEqual("FAIL", report["status"])
            self.assertTrue(any("proof.txt" in failure for failure in report["failures"]))


if __name__ == "__main__":
    unittest.main()
