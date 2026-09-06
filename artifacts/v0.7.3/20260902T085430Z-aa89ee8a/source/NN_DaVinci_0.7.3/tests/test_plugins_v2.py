from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from nn_davinci.api import load_graph
from nn_davinci.errors import PluginError
from nn_davinci.plugins import CAPABILITY_VERSIONS, PLUGIN_API_VERSION, PluginManager, PluginManifest
from nn_davinci.semantic import SEMANTIC_RECOGNIZERS, derive_semantic_view


class PluginApiV2Tests(unittest.TestCase):
    def test_six_stable_interfaces_negotiate(self) -> None:
        self.assertEqual("2.0", PLUGIN_API_VERSION)
        self.assertTrue({"adapter", "semantic-recognizer", "layout", "analyzer", "theme", "exporter"}.issubset(CAPABILITY_VERSIONS))
        manifest = PluginManifest.from_dict({
            "name": "all-capabilities",
            "version": "1.0",
            "api_version": "2.0",
            "capabilities": ["adapter", "semantic-recognizer", "layout", "analyzer", "theme", "exporter"],
            "capability_versions": {key: "2.0" for key in ("adapter", "semantic-recognizer", "layout", "analyzer", "theme", "exporter")},
            "entry_point": "plugin:create",
        })
        manager = PluginManager()
        manager.manifests[manifest.name] = manifest
        self.assertTrue(manager.negotiate(manifest.name)["accepted"])
        self.assertFalse(manager.negotiate(manifest.name, ["operator"])["accepted"])

    def test_api_1_receives_actionable_migration_error(self) -> None:
        with self.assertRaises(PluginError) as caught:
            PluginManifest.from_dict({
                "name": "legacy", "version": "1", "api_version": "1.0",
                "capabilities": ["theme"], "entry_point": "legacy:create",
            })
        self.assertIn("capability negotiation", caught.exception.hint)

    def test_broken_local_plugin_isolated_and_semantic_failure_becomes_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "broken"
            root.mkdir()
            (root / "nn-davinci-plugin.json").write_text(json.dumps({
                "name": "broken", "version": "1", "api_version": "2.0",
                "capabilities": ["theme"], "capability_versions": {"theme": "2.0"},
                "entry_point": "plugin:create",
            }), encoding="utf-8")
            (root / "plugin.py").write_text("def create(context):\n    raise RuntimeError('boom')\n", encoding="utf-8")
            manager = PluginManager()
            manager.discover([directory])
            result = manager.load_safely("broken", allow_local_code=True)
            self.assertFalse(result["loaded"])
            self.assertTrue(result["editor_survived"])

        SEMANTIC_RECOGNIZERS["broken-test"] = lambda graph: (_ for _ in ()).throw(RuntimeError("recognizer boom"))
        try:
            graph = load_graph({"name": "x", "layers": [{"name": "x", "type": "Opaque"}]})
            semantic = derive_semantic_view(graph)
            failure = next(item for item in semantic.detections if item.get("plugin_error"))
            self.assertTrue(failure["unknown"])
            self.assertIn("recognizer boom", failure["reasons"][0])
        finally:
            SEMANTIC_RECOGNIZERS.pop("broken-test", None)


if __name__ == "__main__":
    unittest.main()
