from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import math
import unittest

from nn_davinci.architecture_role_graph import build_architecture_role_graph
from nn_davinci.architecture_evidence import _json_semantic_value
from nn_davinci.errors import ValidationError
from nn_davinci.ir import Annotation, LayoutConstraint
from nn_davinci.metamorphic_corpus import metamorphic_graph
from nn_davinci.real_models import import_real_model
from nn_davinci.scene_projection import (
    ProjectedPrimitive,
    ProjectedScene,
    ProjectionOptions,
    _number,
    _plain,
    _vec3,
    identity_matrix,
    look_at_matrix,
    mat4_multiply,
    orthographic_matrix,
    perspective_matrix,
    project_point,
    transform_point,
)
from nn_davinci.semantic import derive_semantic_view
from nn_davinci.server import create_app


class ArchitectureRoleGraphContract073Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.graph = import_real_model("resnet50", view="module")
        cls.evidence = derive_semantic_view(cls.graph).architecture_evidence
        cls.role_graph = build_architecture_role_graph(cls.graph, cls.evidence)

    def _errors(self, candidate: object, *, bind_graph: bool = True, bind_evidence: bool = True) -> list[str]:
        with self.assertRaises(ValidationError) as caught:
            candidate.validate(
                self.graph if bind_graph else None,
                self.evidence if bind_evidence else None,
            )
        return caught.exception.details["errors"]

    def test_digest_and_evidence_binding_reject_stale_or_mismatched_claims(self) -> None:
        candidate = deepcopy(self.role_graph)
        candidate.family = "transformer"
        candidate.source_digest = "0" * 64
        candidate.evidence_provenance_digest = "1" * 64
        candidate.nodes = [*candidate.nodes, candidate.nodes[0]]
        candidate.edges = [edge for edge in candidate.edges if not edge.critical]
        errors = self._errors(candidate, bind_graph=False)
        self.assertIn("role graph node IDs must be unique", errors)
        self.assertIn("role graph digest is stale or tampered", errors)
        self.assertIn("role graph family disagrees with Architecture Evidence", errors)
        self.assertIn("role graph source digest disagrees with Architecture Evidence", errors)
        self.assertIn("role graph evidence digest is stale", errors)
        self.assertIn("role graph critical-route set disagrees with Architecture Evidence", errors)

        missing_role = deepcopy(self.role_graph)
        missing_role.nodes.pop()
        missing_role.seal()
        self.assertIn(
            "role graph role set disagrees with Architecture Evidence",
            self._errors(missing_role, bind_graph=False),
        )

    def test_edge_integrity_rejects_duplicates_unknown_endpoints_and_lost_direction(self) -> None:
        candidate = deepcopy(self.role_graph)
        original = candidate.edges[0]
        candidate.edges = [
            replace(
                original,
                source_role_id="missing-source",
                target_role_id="missing-target",
                direction="target-to-source",
                supporting_edge_ids=[],
                critical=True,
                critical_route_id="wrong-route",
            ),
            original,
            original,
        ]
        candidate.seal()
        errors = self._errors(candidate, bind_graph=False, bind_evidence=False)
        self.assertIn("role graph edge IDs must be unique", errors)
        self.assertTrue(any("unknown endpoint" in item for item in errors))
        self.assertTrue(any("no forward direction evidence" in item for item in errors))
        self.assertTrue(any("no Graph IR edge evidence" in item for item in errors))
        self.assertTrue(any("lost its route ID" in item for item in errors))

    def test_every_graph_ir_provenance_kind_is_validated_for_nodes_and_edges(self) -> None:
        candidate = deepcopy(self.role_graph)
        candidate.nodes[0] = replace(
            candidate.nodes[0],
            supporting_node_ids=["missing-node"],
            supporting_edge_ids=["missing-edge"],
            supporting_port_ids=["missing-port"],
        )
        candidate.edges[0] = replace(
            candidate.edges[0],
            supporting_node_ids=["missing-node"],
            supporting_edge_ids=["missing-edge"],
            supporting_port_ids=["missing-port"],
        )
        candidate.seal()
        errors = self._errors(candidate, bind_evidence=False)
        self.assertEqual(2, sum("unknown Graph nodes" in item for item in errors))
        self.assertEqual(2, sum("unknown Graph edges" in item for item in errors))
        self.assertEqual(2, sum("unknown Graph ports" in item for item in errors))

    def test_architecture_evidence_rejects_incomplete_unbound_or_tampered_claims(self) -> None:
        candidate = deepcopy(self.evidence)
        bad_role = replace(
            candidate.detected_roles[0],
            role="",
            label="",
            reasons=[],
            repeat_count=0,
            supporting_node_ids=["missing-node"],
            supporting_edge_ids=["missing-edge"],
            supporting_port_ids=["missing-port"],
        )
        bad_route = replace(
            candidate.critical_routes[0],
            source_role_id="missing-role",
            target_role_id="missing-role",
            reasons=[],
            supporting_node_ids=["missing-node"],
            supporting_edge_ids=[],
            supporting_port_ids=["missing-port"],
            protected=False,
        )
        candidate.evidence_version = "2.0"
        candidate.family = "invented-family"
        candidate.confidence = True
        candidate.reasons = []
        candidate.unknown_reason = "not allowed on a claimed family"
        candidate.supporting_node_ids = ["missing-node"]
        candidate.supporting_edge_ids = ["missing-edge"]
        candidate.supporting_port_ids = ["missing-port"]
        candidate.detected_roles = [bad_role, bad_role]
        candidate.critical_routes = [bad_route, bad_route]
        with self.assertRaises(ValidationError) as caught:
            candidate.validate(self.graph, source_digest="2" * 64)
        errors = caught.exception.details["errors"]
        expected_fragments = (
            "unsupported Architecture Evidence version",
            "unsupported architecture family",
            "architecture confidence",
            "at least one reason",
            "cannot carry unknown_reason",
            "role IDs must be unique",
            "route IDs must be unique",
            "is incomplete",
            "invalid repeat_count",
            "missing role endpoint",
            "lacks source-edge evidence",
            "is not protected",
            "source digest does not match",
            "provenance digest is stale",
            "unknown Graph nodes",
            "unknown Graph edges",
            "unknown Graph ports",
        )
        for fragment in expected_fragments:
            with self.subTest(fragment=fragment):
                self.assertTrue(any(fragment in item for item in errors), errors)

        unknown = deepcopy(self.evidence)
        unknown.family = "unknown"
        unknown.unknown_reason = None
        unknown.seal()
        with self.assertRaises(ValidationError) as caught_unknown:
            unknown.validate()
        self.assertIn(
            "unknown architecture evidence needs an explicit unknown_reason",
            caught_unknown.exception.details["errors"],
        )
        marker = object()
        self.assertIs(marker, _json_semantic_value(marker))

    def test_metamorphic_graph_rebinds_nested_groups_annotations_and_constraints(self) -> None:
        source = deepcopy(self.graph)
        self.assertGreaterEqual(len(source.subgraphs), 2)
        parent, child = source.subgraphs[:2]
        child.parent = parent.id
        source.nodes[0].parent = parent.id
        target_ids = [source.nodes[0].id, source.edges[0].id, child.id]
        source.annotations.append(Annotation("note", "text", "reader note", target_ids=target_ids))
        source.constraints.append(LayoutConstraint(target_ids, "align"))
        source.validate()

        transformed = metamorphic_graph(source, seed=730073)
        transformed_ids = {
            *(node.id for node in transformed.nodes),
            *(edge.id for edge in transformed.edges),
            *(group.id for group in transformed.subgraphs),
        }
        transformed_groups = {group.id: group for group in transformed.subgraphs}
        nested = next(group for group in transformed.subgraphs if group.parent)
        self.assertIn(nested.parent, transformed_groups)
        self.assertIn(next(node for node in transformed.nodes if node.parent).parent, transformed_groups)
        self.assertTrue(set(transformed.annotations[0].target_ids).issubset(transformed_ids))
        self.assertTrue(set(transformed.constraints[0].target_ids).issubset(transformed_ids))


@dataclass
class _PlainDataclass:
    value: int


class _PlainObject:
    def to_dict(self) -> dict[str, float]:
        return {"value": math.inf}


class _StringObject:
    def __str__(self) -> str:
        return "sentinel"


class SceneProjectionContract073Tests(unittest.TestCase):
    def test_plain_numeric_and_vector_coercion_are_deterministic_and_finite(self) -> None:
        self.assertEqual({"value": 3}, _plain(_PlainDataclass(3)))
        self.assertEqual({"value": None}, _plain(_PlainObject()))
        self.assertEqual("sentinel", _plain(_StringObject()))
        self.assertEqual(2.5, _number("2.5"))
        self.assertEqual(7.0, _number("invalid", 7.0))
        with self.assertRaises(ValidationError):
            _number(math.inf)
        self.assertEqual((1.0, 2.0, 3.0), _vec3({"x": 1, "y": 2, "z": 3}))

        class Vector:
            x, y, z = 4, 5, 6

        self.assertEqual((4.0, 5.0, 6.0), _vec3(Vector()))
        self.assertEqual((9.0, 8.0, 7.0), _vec3(None, (9.0, 8.0, 7.0)))
        self.assertEqual((9.0, 8.0, 7.0), _vec3(4, (9.0, 8.0, 7.0)))
        self.assertEqual((9.0, 8.0, 7.0), _vec3([1, 2], (9.0, 8.0, 7.0)))

    def test_matrix_camera_and_page_guards_reject_degenerate_geometry(self) -> None:
        matrix = identity_matrix()
        self.assertEqual(matrix, mat4_multiply(matrix, matrix))
        with self.assertRaises(ValidationError):
            mat4_multiply(((1.0,),), matrix)
        self.assertEqual((1.0, 2.0, 3.0), transform_point(matrix, (1, 2, 3)))
        scaled_w = (
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 1.0, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.0),
            (0.0, 0.0, 0.0, 2.0),
        )
        self.assertEqual((0.5, 1.0, 1.5), transform_point(scaled_w, (1, 2, 3)))
        with self.assertRaises(ValidationError):
            look_at_matrix((0, 0, 0), (0, 0, 0))
        with self.assertRaises(ValidationError):
            look_at_matrix((0, 0, 1), (0, 0, 0), (0, 0, 1))
        for values in ((0, 1, 0.1, 100), (180, 1, 0.1, 100), (45, 0, 0.1, 100), (45, 1, 1, 1)):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                perspective_matrix(*values)
        with self.assertRaises(ValidationError):
            orthographic_matrix(1, 1, -1, 1, 0, 10)

        view = look_at_matrix((0, 0, 5), (0, 0, 0))
        perspective = perspective_matrix(45, 1.5, 0.1, 100)
        self.assertIsNotNone(project_point((0, 0, 0), view, perspective))
        with self.assertRaises(ValidationError):
            project_point((0, 0, 0), view, perspective, width_mm=10, margin_mm=6)
        self.assertIsNone(project_point((0, 0, 6), view, perspective))
        zero_w = tuple(tuple(0.0 for _ in range(4)) for _ in range(4))
        self.assertIsNone(project_point((0, 0, 0), view, zero_w))
        narrow = perspective_matrix(45, 1, 0.1, 1)
        self.assertIsNone(project_point((0, 0, -100), identity_matrix(), narrow))

    def test_projection_options_reject_every_unsafe_publication_setting(self) -> None:
        invalid = [
            {"width_mm": -1},
            {"width_mm": 10, "margin_mm": 6},
            {"stroke_width_pt": 0},
            {"min_label_pt": 6.99},
            {"occlusion_samples": 3},
            {"density": "poster"},
            {"auto_frame": 1},
            {"target_occupancy": 0.5},
            {"label_budget": True},
            {"max_leader_mm": 81},
        ]
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                ProjectionOptions(**values)
        default = ProjectionOptions.coerce(None)
        self.assertIs(default, ProjectionOptions.coerce(default))
        self.assertEqual("detailed", ProjectionOptions.coerce({"density": "detailed"}).density)
        with self.assertRaises(ValidationError):
            ProjectionOptions.coerce({"unknown": True})
        with self.assertRaises(ValidationError):
            ProjectionOptions.coerce("paper")  # type: ignore[arg-type]

    def test_projected_scene_validation_guards_visible_vector_contract(self) -> None:
        options = ProjectionOptions()

        def scene(primitive: ProjectedPrimitive, **overrides: object) -> ProjectedScene:
            values = {
                "scene_id": "scene",
                "camera_id": "camera",
                "width_mm": 180.0,
                "height_mm": 120.0,
                "view_matrix": identity_matrix(),
                "projection_matrix": identity_matrix(),
                "primitives": [primitive],
                "options": options,
                "source_digest": "a" * 64,
            }
            values.update(overrides)
            return ProjectedScene(**values)  # type: ignore[arg-type]

        label = ProjectedPrimitive(
            kind="label",
            object_id="label",
            depth=1.0,
            points=[(1.0, 2.0)],
            style={"font_size_pt": 7.0, "stroke_width_pt": 0.75},
            text="Visible role",
        )
        self.assertEqual("Visible role", scene(label).to_dict()["primitives"][0]["text"])
        invalid = [
            scene(label, width_mm=0),
            scene(label, camera_id=""),
            scene(replace(label, kind="raster")),
            scene(replace(label, object_id="")),
            scene(replace(label, style={"font_size_pt": 6.9})),
            scene(replace(label, style={"font_size_pt": 7.0, "stroke_width_pt": 0})),
            scene(replace(label, points=[(math.nan, 2.0)])),
        ]
        for candidate in invalid:
            with self.subTest(candidate=candidate), self.assertRaises(ValidationError):
                candidate.validate()


class ServerContract073Tests(unittest.TestCase):
    def test_project_boundary_and_unexpected_error_return_machine_readable_failures(self) -> None:
        app = create_app()
        def unexpected() -> None:
            raise RuntimeError("contract sentinel")

        app.add_url_rule("/contract-unexpected", "contract-unexpected", unexpected)
        client = app.test_client()
        top_level = client.post("/api/project", json=[])
        self.assertEqual(400, top_level.status_code)
        self.assertEqual("validation_error", top_level.get_json()["error"])
        nested = client.post("/api/project", json={"project": []})
        self.assertEqual(400, nested.status_code)
        self.assertEqual("validation_error", nested.get_json()["error"])
        response = client.get("/contract-unexpected")
        self.assertEqual(500, response.status_code)
        self.assertEqual("RuntimeError", response.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
