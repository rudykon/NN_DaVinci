from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

from nn_davinci.errors import ExportError
from nn_davinci.scene_export import (
    PNG_EXPORT_DPI,
    export_scene,
    export_scene_png,
    export_scene_pptx,
    render_scene_eps,
    render_scene_html,
    render_scene_pdf,
    render_scene_svg,
    render_scene_tikz,
    scene_export_policy,
)
from nn_davinci.scene_gltf import (
    export_scene_json,
    render_scene_glb,
    render_scene_gltf,
    validate_glb,
)
from nn_davinci.scene_ir import Material3D, Object3D, Scene, SceneProvenance, Transform3D, new_scene


def _export_scene() -> Scene:
    scene = new_scene("Scene export proof")
    camera = scene.cameras[0]
    camera.position = [7.0, 6.0, 10.0]
    camera.target = [0.0, 0.0, 0.0]
    camera.ortho_height = 10.0
    provenance = SceneProvenance(
        "semantic_view",
        source_id="semantic:stage:encoder",
        graph_ir_ids=["graph:conv1"],
        semantic_view_ids=["semantic:stage:encoder"],
        figure_ir_ids=["figure:encoder"],
        evidence={"source": "unit-test"},
    )
    tensor = Object3D.create(
        "tensor-volume",
        "Feature map",
        {"size": [3.0, 2.0, 1.4], "center": [0.0, 0.0, 0.2]},
        provenance,
        transform=Transform3D(position=[0.5, 0.0, 0.7], rotation=[8.0, 15.0, 0.0]),
        material=Material3D(base_color="#60a5fa", face_colors={"top": "#bfdbfe"}, opacity=0.96),
        identity="export:tensor",
    )
    arrow = Object3D.create(
        "arrow",
        "Data flow",
        {"points": [[-3.0, -1.0, -0.5], [3.0, -1.0, 1.2]]},
        provenance,
        identity="export:arrow",
    )
    bezier = Object3D.create(
        "bezier-route",
        "Residual skip",
        {"points": [[-2.5, 0.0, 0.0], [-1.5, 2.5, 1.5], [1.5, 2.5, 1.5], [2.5, 0.0, 0.0]]},
        provenance,
        identity="export:bezier",
    )
    annotation = Object3D.create(
        "annotation",
        "Annotation",
        {"text": "Editable 3D projection"},
        SceneProvenance.author(),
        transform=Transform3D(position=[0.0, -2.0, 0.0]),
        identity="export:annotation",
    )
    scene.layers[0].objects = [tensor, arrow, bezier, annotation]
    scene.validate()
    return scene


def _position_values(document: dict, payload: bytes) -> list[float]:
    values: list[float] = []
    for accessor in document["accessors"]:
        if accessor["type"] != "VEC3" or accessor["componentType"] != 5126:
            continue
        view = document["bufferViews"][accessor["bufferView"]]
        offset = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
        count = int(accessor["count"])
        values.extend(struct.unpack_from(f"<{count * 3}f", payload, offset))
    return values


class SceneExports070Tests(unittest.TestCase):
    def test_svg_pdf_tikz_and_eps_are_native_vectors(self) -> None:
        scene = _export_scene()
        svg = render_scene_svg(scene)
        root = ET.fromstring(svg)
        tags = {item.tag.rsplit("}", 1)[-1] for item in root.iter()}
        self.assertIn("polygon", tags)
        self.assertIn("polyline", tags)
        self.assertIn("path", tags)
        self.assertNotIn("image", tags)
        self.assertNotIn("foreignObject", tags)
        label = next(item for item in root.iter() if item.attrib.get("data-kind") == "label")
        self.assertAlmostEqual(7.0, float(label.attrib["data-font-size-pt"]))
        self.assertAlmostEqual(7.0 * 25.4 / 72.0, float(label.attrib["font-size"]), places=5)
        pdf = render_scene_pdf(scene)
        self.assertTrue(pdf.startswith(b"%PDF-1.4"))
        self.assertNotIn(b"/Subtype /Image", pdf)
        self.assertIn(b" c S", pdf)
        tikz = render_scene_tikz(scene)
        self.assertIn(r"\begin{tikzpicture}", tikz)
        self.assertIn(".. controls", tikz)
        self.assertNotIn(r"\includegraphics", tikz)
        eps = render_scene_eps(scene)
        self.assertTrue(eps.startswith(b"%!PS-Adobe-3.0 EPSF-3.0"))
        self.assertIn(b"curveto", eps)
        self.assertNotIn(b"colorimage", eps.lower())

    def test_offline_html_embeds_interactive_svg_and_escapes_text(self) -> None:
        scene = _export_scene()
        scene.layers[0].objects[-1].geometry["text"] = "safe </script><script>alert(1)</script> label"
        scene.validate()
        payload = render_scene_html(scene)
        lowered = payload.lower()
        self.assertIn("content-security-policy", lowered)
        self.assertIn("nndv-scene-projection", lowered)
        self.assertIn("addeventlistener('wheel'", lowered)
        self.assertNotIn("fetch(", lowered)
        self.assertNotIn("https://", lowered)
        self.assertNotIn("safe </script><script>", lowered)

    def test_png_is_a_real_300_dpi_cpu_proof(self) -> None:
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is not installed")
        scene = _export_scene()
        with tempfile.TemporaryDirectory() as directory:
            path = export_scene_png(scene, Path(directory) / "scene.png")
            with Image.open(path) as image:
                self.assertEqual(image.format, "PNG")
                self.assertGreater(image.width, 1000)
                self.assertGreater(image.height, 1000)
                self.assertGreaterEqual(min(image.info["dpi"]), 299.0)
                metadata = json.loads(image.info["nndv.scene_export"])
                self.assertEqual(metadata["dpi"], PNG_EXPORT_DPI)
                self.assertEqual(metadata["source"], "cpu-vector-projection")

    @unittest.skipUnless(importlib.util.find_spec("pptx"), "python-pptx is not installed")
    def test_powerpoint_contains_editable_shapes_and_no_flattened_media(self) -> None:
        scene = _export_scene()
        with tempfile.TemporaryDirectory() as directory:
            path = export_scene_pptx(scene, Path(directory) / "scene.pptx")
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                slide = archive.read("ppt/slides/slide1.xml")
            self.assertIn(b"NNDV editable face", slide)
            self.assertFalse(any(name.startswith("ppt/media/") for name in names))

    def test_scene_json_is_source_preserving_and_reloadable(self) -> None:
        scene = _export_scene()
        with tempfile.TemporaryDirectory() as directory:
            path = export_scene_json(scene, Path(directory) / "scene.scene.json")
            document = json.loads(path.read_text(encoding="utf-8"))
            restored = Scene.from_dict(document)
        self.assertEqual(restored.digest(), scene.digest())
        object_record = document["layers"][0]["objects"][0]
        self.assertIn("material", object_record)
        self.assertIn("provenance", object_record)
        self.assertIn("world", object_record)

    def test_gltf_embeds_real_3d_coordinates_cameras_materials_and_provenance(self) -> None:
        scene = _export_scene()
        encoded = render_scene_gltf(scene)
        document = json.loads(encoded)
        uri = document["buffers"][0]["uri"]
        self.assertTrue(uri.startswith("data:application/octet-stream;base64,"))
        payload = base64.b64decode(uri.split(",", 1)[1], validate=True)
        coordinates = _position_values(document, payload)
        z_values = coordinates[2::3]
        self.assertTrue(any(abs(value) > 1.0e-6 for value in z_values))
        self.assertEqual(document["asset"]["version"], "2.0")
        self.assertTrue(document["cameras"])
        self.assertGreaterEqual(len(document["materials"]), 3)
        mesh_nodes = [node for node in document["nodes"] if "mesh" in node]
        self.assertTrue(mesh_nodes)
        self.assertTrue(all(node["extras"]["objectId"] for node in mesh_nodes))
        self.assertTrue(all("provenance" in node["extras"] for node in mesh_nodes))
        self.assertTrue(any(any(abs(value) > 1.0e-6 for value in node["matrix"][12:15]) for node in mesh_nodes))
        arrow_id = next(item.id for item in scene.iter_objects() if item.kind == "arrow")
        arrow_node = next(node for node in mesh_nodes if node["extras"]["objectId"] == arrow_id)
        arrow_modes = {item["mode"] for item in document["meshes"][arrow_node["mesh"]]["primitives"]}
        self.assertEqual({3, 4}, arrow_modes)
        self.assertNotIn("http://", uri)
        self.assertEqual(encoded, render_scene_gltf(scene))

    def test_glb_parses_and_retains_nonzero_z_buffer_data(self) -> None:
        scene = _export_scene()
        payload = render_scene_glb(scene)
        document = validate_glb(payload)
        json_length = struct.unpack_from("<I", payload, 12)[0]
        binary_offset = 20 + json_length
        binary_length = struct.unpack_from("<I", payload, binary_offset)[0]
        declared = document["buffers"][0]["byteLength"]
        binary = payload[binary_offset + 8 : binary_offset + 8 + min(binary_length, declared)]
        coordinates = _position_values(document, binary)
        self.assertTrue(any(abs(value) > 1.0e-6 for value in coordinates[2::3]))
        self.assertEqual(payload, render_scene_glb(scene))
        with self.assertRaises(ExportError):
            validate_glb(payload[:-1])

    def test_all_nonoptional_formats_export_and_validate(self) -> None:
        scene = _export_scene()
        requested = ("svg", "pdf", "tikz", "png", "eps", "html", "json", "gltf", "glb")
        with tempfile.TemporaryDirectory() as directory:
            outputs = export_scene(scene, Path(directory) / "network", formats=requested)
            names = [path.name for path in outputs]
            self.assertEqual(
                names,
                [
                    "network.svg",
                    "network.pdf",
                    "network.tex",
                    "network.png",
                    "network.eps",
                    "network.html",
                    "network.scene.json",
                    "network.gltf",
                    "network.glb",
                ],
            )
            self.assertTrue(all(path.is_file() and path.stat().st_size > 0 for path in outputs))

    def test_export_policy_makes_physical_and_vector_claims_explicit(self) -> None:
        policy = scene_export_policy(_export_scene())
        self.assertEqual(policy["minimum_label_pt"], 7.0)
        self.assertGreater(policy["stroke_width_pt"], 0.0)
        self.assertIn("no Image XObjects", policy["formats"]["pdf"])
        self.assertIn("no flattened media", policy["formats"]["pptx"])
        self.assertIn("binary glTF 2.0", policy["formats"]["glb"])

    def test_external_and_executable_asset_uris_are_rejected(self) -> None:
        for value in ("https://evil.example/texture.png", "javascript:alert(1)", "data:image/svg+xml,<svg onload=alert(1)>"):
            scene = _export_scene()
            scene.metadata["asset"] = {"href": value}
            scene.validate()
            with self.subTest(value=value), self.assertRaises(ExportError):
                render_scene_svg(scene)


if __name__ == "__main__":
    unittest.main()
