from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Iterable

from .errors import ValidationError
from .ir import Annotation, Edge, GraphIR, LayoutConstraint, Node, Subgraph, stable_id


class GraphEditor:
    """Command-oriented Graph IR editor with bounded undo/redo history."""

    def __init__(self, graph: GraphIR, *, history_limit: int = 100):
        self.graph = graph.copy()
        self.history_limit = history_limit
        self._undo: list[dict] = []
        self._redo: list[dict] = []

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def _commit(self, operation: Callable[[GraphIR], None]) -> GraphIR:
        snapshot = self.graph.to_dict()
        operation(self.graph)
        self.graph.validate()
        self._undo.append(snapshot)
        del self._undo[:-self.history_limit]
        self._redo.clear()
        return self.graph

    def undo(self) -> GraphIR:
        if not self._undo:
            return self.graph
        self._redo.append(self.graph.to_dict())
        self.graph = GraphIR.from_dict(self._undo.pop())
        return self.graph

    def redo(self) -> GraphIR:
        if not self._redo:
            return self.graph
        self._undo.append(self.graph.to_dict())
        self.graph = GraphIR.from_dict(self._redo.pop())
        return self.graph

    def add_node(self, node: Node) -> GraphIR:
        return self._commit(lambda graph: graph.nodes.append(node))

    def update_node(self, node_id: str, **changes: Any) -> GraphIR:
        def operation(graph: GraphIR) -> None:
            node = graph.node_map().get(node_id)
            if node is None:
                raise ValidationError(f"Unknown node {node_id!r}")
            for key, value in changes.items():
                if key not in Node.__dataclass_fields__ or key == "id":
                    raise ValidationError(f"Node field {key!r} cannot be edited")
                setattr(node, key, value)
        return self._commit(operation)

    def remove_nodes(self, node_ids: Iterable[str]) -> GraphIR:
        selected = set(node_ids)
        def operation(graph: GraphIR) -> None:
            graph.nodes = [node for node in graph.nodes if node.id not in selected]
            graph.edges = [edge for edge in graph.edges if edge.source not in selected and edge.target not in selected]
            for group in graph.subgraphs:
                group.node_ids = [node_id for node_id in group.node_ids if node_id not in selected]
            graph.annotations = [item for item in graph.annotations if not selected.intersection(item.target_ids)]
            graph.constraints = [item for item in graph.constraints if not selected.intersection(item.target_ids)]
        return self._commit(operation)

    def duplicate_nodes(self, node_ids: Iterable[str]) -> list[str]:
        selected = set(node_ids)
        new_ids: dict[str, str] = {}
        def operation(graph: GraphIR) -> None:
            new_nodes: list[Node] = []
            port_ids: dict[str, str] = {}
            for node in list(graph.nodes):
                if node.id not in selected:
                    continue
                new_id = stable_id("node", f"copy:{node.id}:{len(graph.nodes) + len(new_nodes)}")
                new_ids[node.id] = new_id
                duplicate = deepcopy(node)
                duplicate.id = new_id
                duplicate.name = f"{node.name} copy"
                duplicate.path = f"{node.path}.copy"
                for direction in ("inputs", "outputs"):
                    for index, port in enumerate(getattr(duplicate, direction)):
                        old_port_id = port.id
                        port.id = f"{new_id}:{direction[:-1]}:{index}"
                        port_ids[old_port_id] = port.id
                new_nodes.append(duplicate)
            graph.nodes.extend(new_nodes)
            for edge in list(graph.edges):
                if edge.source in selected and edge.target in selected:
                    duplicate = deepcopy(edge)
                    duplicate.source = new_ids[edge.source]
                    duplicate.target = new_ids[edge.target]
                    duplicate.source_port = port_ids.get(edge.source_port, edge.source_port)
                    duplicate.target_port = port_ids.get(edge.target_port, edge.target_port)
                    duplicate.id = stable_id("edge", f"copy:{edge.id}:{duplicate.source}->{duplicate.target}")
                    graph.edges.append(duplicate)
        self._commit(operation)
        return list(new_ids.values())

    def connect(self, source: str, target: str, **attributes: Any) -> GraphIR:
        return self._commit(lambda graph: graph.edges.append(Edge.create(source, target, **attributes)))

    def disconnect(self, edge_ids: Iterable[str]) -> GraphIR:
        selected = set(edge_ids)
        return self._commit(lambda graph: setattr(graph, "edges", [edge for edge in graph.edges if edge.id not in selected]))

    def group(self, node_ids: Iterable[str], name: str, *, level: str = "module") -> str:
        group_id = stable_id("group", f"{name}:{len(self.graph.subgraphs)}")
        members = list(dict.fromkeys(node_ids))
        self._commit(lambda graph: graph.subgraphs.append(Subgraph(group_id, name, members, level=level)))
        return group_id

    def ungroup(self, group_id: str) -> GraphIR:
        return self._commit(lambda graph: setattr(graph, "subgraphs", [group for group in graph.subgraphs if group.id != group_id]))

    def set_collapsed(self, group_id: str, collapsed: bool) -> GraphIR:
        def operation(graph: GraphIR) -> None:
            for group in graph.subgraphs:
                if group.id == group_id:
                    group.collapsed = collapsed
                    return
            raise ValidationError(f"Unknown group {group_id!r}")
        return self._commit(operation)

    def set_positions(self, positions: dict[str, tuple[float, float]], *, locked: bool = True) -> GraphIR:
        selected = set(positions)
        def operation(graph: GraphIR) -> None:
            graph.constraints = [item for item in graph.constraints if not (item.kind == "position" and selected.intersection(item.target_ids))]
            graph.constraints.extend(LayoutConstraint([node_id], "position", {"x": value[0], "y": value[1]}, locked) for node_id, value in positions.items())
        return self._commit(operation)

    def align(self, node_ids: Iterable[str], axis: str, value: float) -> GraphIR:
        if axis not in {"x", "y"}:
            raise ValidationError("Alignment axis must be 'x' or 'y'")
        selected = list(node_ids)
        constraints = [LayoutConstraint(selected, f"align-{axis}", value, True)]
        return self._commit(lambda graph: graph.constraints.extend(constraints))

    def distribute(self, node_ids: Iterable[str], axis: str) -> GraphIR:
        """Evenly distribute three or more nodes along an axis at layout time."""
        if axis not in {"x", "y"}:
            raise ValidationError("Distribution axis must be 'x' or 'y'")
        selected = list(dict.fromkeys(node_ids))
        if len(selected) < 3:
            raise ValidationError("Distribution requires at least three nodes")
        return self._commit(
            lambda graph: graph.constraints.append(LayoutConstraint(selected, f"distribute-{axis}", locked=True))
        )

    def set_edge_route(self, edge_id: str, points: Iterable[tuple[float, float]]) -> GraphIR:
        waypoints = [[float(x), float(y)] for x, y in points]
        if edge_id not in self.graph.edge_map():
            raise ValidationError(f"Unknown edge {edge_id!r}")
        if len(waypoints) < 2:
            raise ValidationError("An edge route requires at least two points")
        def operation(graph: GraphIR) -> None:
            graph.constraints = [
                item for item in graph.constraints
                if not (item.kind == "edge-route" and edge_id in item.target_ids)
            ]
            graph.constraints.append(LayoutConstraint([edge_id], "edge-route", {"points": waypoints}, True))
        return self._commit(operation)

    def add_annotation(self, kind: str, text: str = "", **attributes: Any) -> str:
        annotation_id = stable_id("annotation", f"{kind}:{text}:{len(self.graph.annotations)}")
        annotation = Annotation(annotation_id, kind, text, **attributes)
        self._commit(lambda graph: graph.annotations.append(annotation))
        return annotation_id


__all__ = ["GraphEditor"]
