from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Any, ClassVar
import unittest

from nn_davinci.figure_templates import TEMPLATE_SPECS, instantiate_template
from nn_davinci.project import PROJECT_VERSION, Project
from nn_davinci.scene_export import export_scene
from nn_davinci.scene_ir import SCENE_IR_VERSION, Scene
from nn_davinci.model_scene import scene_template
from scripts.generate_scene_artifacts_0_7 import (
    FORMATS,
    REAL_MODEL_CASES,
    TEMPLATE_CASES,
    _eps_has_image_operator as generator_eps_has_image_operator,
    build_report,
    corpus_jobs,
    generate_one,
    write_comparison_png,
    write_comparison_svg,
)
from scripts.validate_scene_artifacts_0_7 import (
    _eps_has_image_operator as validator_eps_has_image_operator,
    _inspect_comparison,
    expected_cases,
    validate_case,
)


class SceneArtifactCorpus070Tests(unittest.TestCase):
    temporary: ClassVar[tempfile.TemporaryDirectory[str]]
    case_dir: ClassVar[Path]
    generated: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="nndv-scene-corpus-test-")
        cls.case_dir = Path(cls.temporary.name) / "templates" / "moe"
        cls.generated = generate_one("template", "moe", cls.case_dir)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_exact_case_plan_has_seven_templates_and_seven_real_models(self) -> None:
        jobs = corpus_jobs()
        self.assertEqual(jobs, expected_cases())
        self.assertEqual(14, len(jobs))
        self.assertEqual(7, len(TEMPLATE_CASES))
        self.assertEqual(7, len(REAL_MODEL_CASES))
        self.assertEqual(len(jobs), len(set(jobs)))
        self.assertEqual(
            {
                "cnn",
                "resnet",
                "unet",
                "transformer",
                "moe",
                "multimodal-fusion",
                "diffusion-unet",
            },
            set(TEMPLATE_CASES),
        )

    def test_one_template_generates_all_formats_and_revalidates_independently(self) -> None:
        self.assertEqual("PASS", self.generated["status"], self.generated["failures"])
        self.assertEqual(set(FORMATS), set(self.generated["format_accounting"]))
        self.assertTrue(all(len(paths) == 1 for paths in self.generated["format_accounting"].values()))
        self.assertEqual(11, len(self.generated["files"]))
        validated = validate_case(self.case_dir, "template", "moe")
        self.assertEqual("PASS", validated["status"], validated["failures"])
        self.assertTrue(validated["project_roundtrip"])
        self.assertTrue(validated["projection_validation"]["passed"])
        self.assertTrue(validated["true_3d_validation"]["passed"])
        self.assertTrue(all(validated["native_vector_validation"].values()))
        self.assertTrue(validated["editable_pptx_validation"]["passed"])
        self.assertTrue(validated["png_300dpi_validation"]["passed"])
        self.assertTrue(validated["offline_html_validation"]["passed"])

    def test_project_is_explicit_project_1_4_with_reloadable_scene_1_0(self) -> None:
        project = Project.load(self.case_dir / "scene.nndv.json")
        scene = Scene.from_dict(json.loads((self.case_dir / "scene.scene.json").read_text(encoding="utf-8")))
        self.assertEqual("1.4", PROJECT_VERSION)
        self.assertEqual(PROJECT_VERSION, project.project_version)
        self.assertEqual("1.0", SCENE_IR_VERSION)
        self.assertEqual(SCENE_IR_VERSION, scene.schema_version)
        self.assertEqual(scene.digest(), project.persisted_scene().digest())
        self.assertEqual("scene", project.export["workspace"])
        self.assertEqual(list(FORMATS), project.export["formats"])

    def test_validator_rejects_svg_raster_substitution(self) -> None:
        path = self.case_dir / "scene.svg"
        original = path.read_text(encoding="utf-8")
        try:
            path.write_text(
                '<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><image href="data:image/png;base64,AA=="/></svg>',
                encoding="utf-8",
            )
            result = validate_case(self.case_dir, "template", "moe")
        finally:
            path.write_text(original, encoding="utf-8")
        self.assertEqual("FAIL", result["status"])
        self.assertFalse(result["native_vector_validation"]["svg_native"])
        self.assertTrue(any("svg_native" in failure for failure in result["failures"]))

    def test_validator_rejects_remote_html_dependency(self) -> None:
        path = self.case_dir / "scene.html"
        original = path.read_text(encoding="utf-8")
        try:
            path.write_text(original.replace("</body>", '<img src="https://example.invalid/proof.png"></body>'), encoding="utf-8")
            result = validate_case(self.case_dir, "template", "moe")
        finally:
            path.write_text(original, encoding="utf-8")
        self.assertEqual("FAIL", result["status"])
        self.assertFalse(result["offline_html_validation"]["passed"])

    def test_eps_operator_scanner_ignores_label_strings_but_rejects_raster_code(self) -> None:
        labelled_vector = b"%!PS-Adobe-3.0 EPSF-3.0\n% image is a label\n0 0 moveto (Input image) show\n"
        raster_operator = b"%!PS-Adobe-3.0 EPSF-3.0\n100 100 8 [100 0 0 -100 0 100] image\n"
        for scanner in (generator_eps_has_image_operator, validator_eps_has_image_operator):
            self.assertFalse(scanner(labelled_vector))
            self.assertTrue(scanner(raster_operator))

    def test_comparison_outputs_pair_native_svg_and_300dpi_png(self) -> None:
        with tempfile.TemporaryDirectory(prefix="nndv-scene-comparison-test-") as directory:
            root = Path(directory)
            scene = scene_template("cnn")
            export_scene(scene, root / "scene", formats=("svg", "png"))
            _graph, figure = instantiate_template(TEMPLATE_SPECS[0].slug)
            write_comparison_svg(figure, scene, root / "comparison.svg")
            write_comparison_png(figure, root / "scene.png", root / "comparison.png")
            inspection, failures = _inspect_comparison(root)
        self.assertFalse(failures)
        self.assertTrue(inspection["passed"])
        self.assertTrue(inspection["svg_native"])
        self.assertEqual(["figure-ir-2d", "scene-ir-3d"], inspection["svg_roles"])
        self.assertTrue(inspection["png"]["passed"])

    def test_report_gate_requires_the_complete_168_file_tree(self) -> None:
        fake_results = [
            {
                "kind": kind,
                "key": key,
                "status": "PASS",
                "failures": [],
                "format_accounting": {name: [f"scene.{name}"] for name in FORMATS},
                "comparison_accounting": ["comparison.svg", "comparison.png"] if kind == "real-model" else [],
                "files": {"scene.nndv.json": {"bytes": 1, "sha256": "0" * 64}},
            }
            for kind, key in corpus_jobs()
        ]
        with tempfile.TemporaryDirectory(prefix="nndv-scene-empty-report-") as directory:
            report = build_report(fake_results, Path(directory))
        self.assertEqual("FAIL", report["status"])
        self.assertEqual(0, report["counts"]["regular_files"])
        self.assertTrue(any(item["key"] == "regular_files" for item in report["failures"]))


if __name__ == "__main__":
    unittest.main()
