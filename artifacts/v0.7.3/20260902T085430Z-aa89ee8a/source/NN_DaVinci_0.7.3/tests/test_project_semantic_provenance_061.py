from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from nn_davinci.errors import ValidationError
from nn_davinci.figure_ir import FigureObject, FigureProvenance, new_figure
from nn_davinci.ir import Edge, GraphIR, Node, Port, TensorSpec
from nn_davinci.model_figure import model_figure_from_graph
from nn_davinci.project import Project
from nn_davinci.semantic import derive_semantic_view


def evidence_graph() -> GraphIR:
    tensor = TensorSpec("features", [1, "T", 8], "float32")
    source = Node(
        "source",
        "Input",
        "Input",
        category="input",
        outputs=[Port("source:out", "features", "output", tensor)],
    )
    projection = Node(
        "projection",
        "Projection",
        "Linear",
        inputs=[Port("projection:in", "features", "input", tensor)],
        outputs=[Port("projection:out", "projected", "output", tensor)],
    )
    return GraphIR(
        "Persisted semantic evidence",
        [source, projection],
        [Edge("source-projection", source.id, projection.id, "source:out", "projection:in", tensor)],
        metadata={"source_format": "project-semantic-fixture"},
    ).validate()


class ProjectSemanticProvenance061Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.graph = evidence_graph()
        self.semantic = derive_semantic_view(self.graph)
        self.figure = model_figure_from_graph(
            self.graph,
            semantic_view=self.semantic,
            level="operation",
            view="faithful",
            mode="mixed",
        )
        self.envelope = {
            "version": "1.0",
            "level": "operation",
            "view": "faithful",
            "document": self.semantic.to_dict(),
        }

    def project_payload(self) -> dict:
        return Project(
            "Persisted provenance",
            self.graph,
            semantic_view=deepcopy(self.envelope),
            figure_ir=self.figure.to_dict(),
        ).to_dict()

    def load_payload(self, payload: dict) -> Project:
        with tempfile.TemporaryDirectory(prefix="nndv-project-semantic-") as directory:
            source = Path(directory) / "figure.nndv.json"
            source.write_text(json.dumps(payload), encoding="utf-8")
            return Project.load(source)

    def test_roundtrip_persists_exact_semantic_document_used_by_figure(self) -> None:
        restored = self.load_payload(self.project_payload())
        persisted = restored.persisted_semantic_view()
        self.assertIsNotNone(persisted)
        assert persisted is not None
        self.assertEqual(self.semantic.to_dict(), persisted.to_dict())
        semantic_ids = {entity.id for entity in persisted.entities}
        self.assertTrue(all(
            item.provenance.source_id in semantic_ids
            for item in self.figure.iter_objects()
            if item.provenance.kind == "semantic_view"
        ))

    def test_model_derived_figure_requires_semantic_document(self) -> None:
        with self.assertRaisesRegex(ValidationError, "requires its persisted Semantic View"):
            Project(
                "Missing semantic evidence",
                self.graph,
                semantic_view={"version": "1.0", "level": "operation", "view": "faithful"},
                figure_ir=self.figure.to_dict(),
            )

        with self.assertRaisesRegex(ValidationError, "missing required fields"):
            Project(
                "Incomplete semantic evidence",
                self.graph,
                semantic_view={
                    "version": "1.0",
                    "level": "operation",
                    "view": "faithful",
                    "document": {},
                },
                figure_ir=self.figure.to_dict(),
            )

        legacy = Project(
            "Compatible Graph-only 1.x project",
            self.graph,
            semantic_view={"version": "1.0", "level": "block", "view": "paper"},
        )
        self.assertIsNone(legacy.persisted_semantic_view())

    def test_loading_rejects_orphan_figure_semantic_id_and_reverse_index_tampering(self) -> None:
        payload = self.project_payload()
        semantic_object = next(
            item for item in self.figure.iter_objects()
            if item.provenance.kind == "semantic_view"
        )
        for page in payload["figure_ir"]["pages"]:
            for panel in page["panels"]:
                for layer in panel["layers"]:
                    for item in layer["objects"]:
                        if item["id"] == semantic_object.id:
                            item["provenance"]["source_id"] = "orphan-semantic-entity"
        with self.assertRaisesRegex(ValidationError, "provenance disagree"):
            self.load_payload(payload)

        payload = self.project_payload()
        payload["figure_ir"]["metadata"]["provenance_index"]["figure_to_source"][
            semantic_object.id
        ]["semantic_id"] = "tampered-semantic-entity"
        with self.assertRaisesRegex(ValidationError, "provenance disagree"):
            self.load_payload(payload)

    def test_loading_rejects_semantic_to_graph_digest_tampering(self) -> None:
        payload = self.project_payload()
        payload["graph"]["nodes"][0]["name"] = "Tampered input"
        with self.assertRaisesRegex(ValidationError, "source digest"):
            self.load_payload(payload)

    def test_prerelease_flat_semantic_document_is_canonicalized_without_losing_evidence(self) -> None:
        flattened = {
            **self.semantic.to_dict(),
            "version": "1.0",
            "level": "operation",
            "view": "faithful",
        }
        restored = Project(
            "Flat prerelease",
            self.graph,
            semantic_view=flattened,
            figure_ir=self.figure.to_dict(),
        )
        self.assertEqual(
            {"version", "level", "view", "document"},
            set(restored.semantic_view),
        )
        self.assertEqual(self.semantic.to_dict(), restored.semantic_view["document"])

    def test_graph_only_figure_claims_require_exact_bidirectional_index(self) -> None:
        figure = new_figure("Graph-only Structure Lens evidence")
        layer = next(figure.iter_panels()).layers[0]
        source_id = self.graph.nodes[0].id
        item = FigureObject.create(
            "node-glyph",
            "Exact Graph evidence",
            {"x": 10, "y": 10, "width": 20, "height": 10},
            FigureProvenance(
                "graph_ir",
                source_id=source_id,
                graph_ir_ids=[source_id],
                evidence={"structure_lens_graph_evidence": True},
            ),
            identity="graph-only-project-evidence",
        )
        layer.objects.append(item)
        figure.metadata["provenance_index"] = {
            "graph_to_figure": {source_id: [item.id]},
            "semantic_to_figure": {},
            "figure_to_source": {
                item.id: {"graph_ir_ids": [source_id], "graph_port_ids": []},
            },
        }
        valid = Project(
            "Graph-only evidence",
            self.graph,
            semantic_view={"version": "1.0", "level": None, "view": "faithful"},
            figure_ir=figure.to_dict(),
        )
        self.assertIsNone(valid.persisted_semantic_view())
        self.assertEqual(
            [item.id],
            valid.figure_ir["metadata"]["provenance_index"]["graph_to_figure"][source_id],
        )

        orphaned = deepcopy(figure.to_dict())
        orphaned["pages"][0]["panels"][0]["layers"][0]["objects"][0][
            "provenance"
        ]["graph_ir_ids"] = ["orphan-graph-id"]
        with self.assertRaisesRegex(ValidationError, "Graph IR and Figure IR provenance disagree"):
            Project("Orphan Graph evidence", self.graph, figure_ir=orphaned)

        missing_index = deepcopy(figure.to_dict())
        missing_index["metadata"].pop("provenance_index")
        with self.assertRaisesRegex(ValidationError, "Graph IR and Figure IR provenance disagree"):
            Project("Missing Graph index", self.graph, figure_ir=missing_index)


if __name__ == "__main__":
    unittest.main()
