from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from heapq import heappop, heappush
from math import cos, pi, sin
from typing import Any

from ..ir import Edge, GraphIR, Node, Port, Subgraph, stable_id
from ..spatial import DEFAULT_MAX_PAIRS, RectanglePairQuery, query_rectangle_pairs, rectangles_overlap


@dataclass(slots=True)
class NodePlacement:
    x: float
    y: float
    width: float
    height: float
    rank: int = 0
    order: int = 0
    locked: bool = False
    panel: str | None = None


@dataclass(slots=True)
class EdgeRoute:
    points: list[tuple[float, float]]
    back_edge: bool = False


@dataclass(slots=True)
class LayoutResult:
    engine: str
    direction: str
    nodes: dict[str, NodePlacement] = field(default_factory=dict)
    edges: dict[str, EdgeRoute] = field(default_factory=dict)
    groups: dict[str, dict[str, float]] = field(default_factory=dict)
    width: float = 0
    height: float = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LayoutResult":
        payload = dict(data)
        payload["nodes"] = {key: NodePlacement(**value) for key, value in payload.get("nodes", {}).items()}
        payload["edges"] = {key: EdgeRoute(points=[tuple(point) for point in value["points"]], back_edge=value.get("back_edge", False)) for key, value in payload.get("edges", {}).items()}
        return cls(**payload)


class LayoutEngine:
    """Deterministic layered/domain layout with constraint preservation."""

    DOMAIN_ENGINES = {"generic", "cnn", "resnet", "unet", "transformer", "rnn", "moe", "multimodal", "diffusion", "radial"}
    PLUGIN_ENGINES: dict[str, Any] = {}
    PAPER_PAGES: dict[str, dict[str, Any]] = {
        "single-column": {"width": 420.0, "height": 620.0, "margin": 24.0},
        "double-column": {"width": 840.0, "height": 620.0, "margin": 28.0},
        "widescreen": {"width": 1280.0, "height": 720.0, "margin": 42.0},
        "slide": {"width": 1280.0, "height": 720.0, "margin": 42.0},
        "wide-two-column": {"width": 1020.0, "height": 620.0, "margin": 30.0},
        "multi-panel": {"width": 1020.0, "height": 760.0, "margin": 32.0},
        "fit-content": {"width": None, "height": None, "margin": 34.0},
    }

    @classmethod
    def register(cls, name: str, engine: Any, *, replace: bool = False) -> None:
        if (name in cls.DOMAIN_ENGINES or name in cls.PLUGIN_ENGINES) and not replace:
            raise ValueError(f"Layout engine {name!r} is already registered")
        cls.PLUGIN_ENGINES[name] = engine

    @classmethod
    def available(cls) -> set[str]:
        return cls.DOMAIN_ENGINES | set(cls.PLUGIN_ENGINES)

    def layout(
        self,
        graph: GraphIR,
        *,
        algorithm: str = "auto",
        direction: str = "LR",
        node_width: float = 154,
        node_height: float = 66,
        rank_gap: float = 88,
        node_gap: float = 34,
        previous: LayoutResult | dict | None = None,
        page: dict[str, Any] | None = None,
        page_preset: str | None = None,
        font_size: float = 12,
        minimum_font_pt: float = 7,
        label_density: str = "paper",
    ) -> LayoutResult:
        if isinstance(previous, dict):
            previous = LayoutResult.from_dict(previous)
        selected = self.detect_domain(graph) if algorithm == "auto" else algorithm.lower()
        if label_density not in {"compact", "paper", "detailed"}:
            raise ValueError("label_density must be compact, paper, or detailed")
        if label_density == "paper":
            node_height = max(node_height, 88.0)
        elif label_density == "detailed":
            analysis_lines = max((len(node.analysis) for node in graph.nodes), default=0)
            node_height = max(node_height, 58.0 + 14.0 * max(3, analysis_lines))
        if selected not in self.available():
            raise ValueError(f"Unknown layout algorithm {selected!r}")
        if selected in self.PLUGIN_ENGINES:
            plugin_result = self.PLUGIN_ENGINES[selected](
                graph,
                direction=direction,
                node_width=node_width,
                node_height=node_height,
                rank_gap=rank_gap,
                node_gap=node_gap,
            )
            result = LayoutResult.from_dict(plugin_result) if isinstance(plugin_result, dict) else plugin_result
            if not isinstance(result, LayoutResult):
                raise TypeError(f"Layout plugin {selected!r} must return LayoutResult or a compatible dictionary")
        elif selected == "radial":
            result = self._radial(graph, node_width, node_height, node_gap)
        else:
            result = self._layered(graph, selected, direction, node_width, node_height, rank_gap, node_gap)
        self._apply_domain_geometry(graph, result, selected, node_gap)
        self._apply_constraints(graph, result, previous)
        self._arrange_panels(result)
        if not result.edges:
            self._route_edges(graph, result)
        self._place_groups(graph, result)
        self._normalize(result)
        if self._restore_absolute_positions(graph, result, previous):
            result.edges.clear()
            self._route_edges(graph, result)
            result.groups.clear()
            self._place_groups(graph, result)
            self._refresh_panel_boxes(result)
        if page_preset:
            self._adapt_to_paper(
                graph,
                result,
                requested=page_preset,
                page=page,
                font_size=font_size,
                minimum_font_pt=minimum_font_pt,
                node_gap=node_gap,
                previous=previous,
                label_density=label_density,
            )
        self._apply_edge_constraints(graph, result)
        self._measure(result)
        if "paper" in result.metadata:
            prior = result.metadata["paper"]
            refreshed = self._paper_metrics(
                result,
                prior["selected_page"],
                prior["page"],
                body_font_px=float(prior["body_font_px"]),
                minimum_font_pt=float(prior["minimum_body_font_pt"]),
            )
            refreshed.update({
                key: prior[key]
                for key in ("requested_page", "selection_reason")
                if key in prior
            })
            if refreshed["readable"]:
                refreshed["warnings"] = []
            else:
                refreshed["warnings"] = [
                    "锁定位置或手工路由使最终正文预计为 "
                    f"{refreshed['final_body_font_pt']:.2f} pt；请缩短路由、解除远距离锁定，"
                    "或改用 fit-content/widescreen。"
                ]
            result.metadata["paper"] = refreshed
        result.metadata.update({
            "stable": True,
            "algorithm": selected,
            "node_count": len(result.nodes),
            "label_density": label_density,
        })
        return result

    def _adapt_to_paper(
        self,
        graph: GraphIR,
        result: LayoutResult,
        *,
        requested: str,
        page: dict[str, Any] | None,
        font_size: float,
        minimum_font_pt: float,
        node_gap: float,
        previous: LayoutResult | None,
        label_density: str,
    ) -> None:
        """Wrap layered graphs before page scaling and record measurable readability.

        CSS/SVG user units are pixels, so one unit is 0.75 pt.  The smallest
        body text emitted by the renderers is 10 px; page adaptation therefore
        budgets against that size instead of the larger node-title size.
        """
        smallest_scale = 0.78 if label_density == "detailed" else 0.84
        body_font_px = max(10.0, float(font_size)) * smallest_scale
        natural_aspect = result.width / max(result.height, 1.0)
        if requested == "auto":
            if natural_aspect >= 1.8:
                candidates = ["widescreen", "double-column", "single-column"]
            elif natural_aspect <= 0.78:
                candidates = ["single-column", "double-column", "widescreen"]
            else:
                candidates = ["double-column", "single-column", "widescreen"]
            candidates.append("fit-content")
        else:
            candidates = [requested]

        evaluated: list[tuple[LayoutResult, dict[str, Any]]] = []
        for preset in candidates:
            config = dict(self.PAPER_PAGES.get(preset, page or {}))
            if preset == requested and page:
                config.update(page)
            candidate = deepcopy(result)
            if preset != "fit-content":
                self._wrap_ranks(
                    graph,
                    candidate,
                    config,
                    body_font_px=body_font_px,
                    minimum_font_pt=minimum_font_pt,
                    node_gap=node_gap,
                )
            candidate.edges.clear()
            candidate.groups.clear()
            self._route_edges_for_paper(graph, candidate)
            self._place_groups(graph, candidate)
            self._normalize(candidate)
            if self._restore_absolute_positions(graph, candidate, previous):
                candidate.edges.clear()
                self._route_edges_for_paper(graph, candidate)
                candidate.groups.clear()
                self._place_groups(graph, candidate)
                self._refresh_panel_boxes(candidate)
            self._measure(candidate)
            metrics = self._paper_metrics(
                candidate,
                preset,
                config,
                body_font_px=body_font_px,
                minimum_font_pt=minimum_font_pt,
            )
            evaluated.append((candidate, metrics))
            if requested != "auto" or (
                metrics["readable"] and metrics["node_overlap_count"] == 0
                and metrics["content_occupancy"] >= 0.18
            ):
                break

        chosen, metrics = evaluated[-1]
        result.nodes = chosen.nodes
        result.edges = chosen.edges
        result.groups = chosen.groups
        result.width = chosen.width
        result.height = chosen.height
        result.metadata.update(chosen.metadata)
        metrics["requested_page"] = requested
        metrics["selection_reason"] = self._page_selection_reason(requested, metrics, natural_aspect)
        if not metrics["readable"]:
            metrics["warnings"] = [
                "最终正文预计为 "
                f"{metrics['final_body_font_pt']:.2f} pt，低于 {minimum_font_pt:g} pt；"
                "请改用 fit-content/widescreen、折叠重复块，或解除相距过远的锁定节点。"
            ]
        else:
            metrics["warnings"] = []
        result.metadata["paper"] = metrics

    @staticmethod
    def _page_selection_reason(requested: str, metrics: dict[str, Any], natural_aspect: float) -> str:
        if requested != "auto":
            return f"用户锁定 {metrics['selected_page']}；布局在缩放前执行分段换行。"
        if metrics["selected_page"] == "fit-content":
            return "固定论文页面均无法满足字号或占用率约束，回退到内容裁切页面。"
        shape = "横向超宽" if natural_aspect >= 1.8 else "纵向" if natural_aspect <= 0.78 else "常规"
        return f"自然布局为{shape}结构；选择 {metrics['selected_page']} 以兼顾 7 pt 正文和页面占用率。"

    @staticmethod
    def _wrap_ranks(
        graph: GraphIR,
        result: LayoutResult,
        page: dict[str, Any],
        *,
        body_font_px: float,
        minimum_font_pt: float,
        node_gap: float,
    ) -> None:
        width = float(page["width"])
        height = float(page["height"])
        margin = float(page.get("margin", 24))
        minimum_scale = min(1.0, minimum_font_pt / max(body_font_px * 0.75, 0.01))
        target_width = max(220.0, (width - 2 * margin) / minimum_scale - 68)
        target_height = max(160.0, (height - 2 * margin) / minimum_scale - 68)
        buckets: dict[int, list[tuple[str, NodePlacement]]] = defaultdict(list)
        locked: list[NodePlacement] = []
        for node_id, placement in result.nodes.items():
            if placement.locked:
                locked.append(placement)
            else:
                buckets[placement.rank].append((node_id, placement))
        if not buckets:
            return
        for items in buckets.values():
            items.sort(key=lambda item: (item[1].order, item[0]))
        # Paper nodes contain several short label lines.  The generic canvas
        # spacing is intentionally generous, but retaining its 34 px vertical
        # gap makes branched ranks unnecessarily tall on a fixed paper page.
        # Eighteen pixels still gives a visible separation and keeps the
        # Transformer authority fixture above the 7 pt floor.
        paper_node_gap = min(node_gap, 18.0)
        column_gap = max(34.0, min(52.0, node_gap + 14.0))
        row_gap = max(30.0, paper_node_gap + 14.0)
        rows: list[list[int]] = []
        current: list[int] = []
        used = 0.0
        for rank in sorted(buckets):
            column_width = max(item.width for _, item in buckets[rank])
            required = column_width if not current else column_gap + column_width
            if current and used + required > target_width:
                rows.append(current)
                current, used = [], 0.0
                required = column_width
            current.append(rank)
            used += required
        if current:
            rows.append(current)

        cursor_y = 0.0
        segments: list[dict[str, Any]] = []
        group_names = {
            rank: sorted({
                group.name
                for group in graph.subgraphs
                if any(node_id in group.node_ids for node_id, _ in buckets[rank])
            })
            for rank in buckets
        }
        for row_index, ranks in enumerate(rows):
            heights = {
                rank: sum(item.height for _, item in buckets[rank])
                + max(0, len(buckets[rank]) - 1) * paper_node_gap
                for rank in ranks
            }
            row_height = max(heights.values(), default=0.0)
            if cursor_y + row_height > target_height and row_index:
                row_gap = max(34.0, row_gap * 0.72)
            ordered = ranks if row_index % 2 == 0 else list(reversed(ranks))
            cursor_x = 0.0
            for rank in ordered:
                column = buckets[rank]
                column_width = max(item.width for _, item in column)
                column_y = cursor_y + (row_height - heights[rank]) / 2
                for order, (_, placement) in enumerate(column):
                    placement.x = cursor_x + (column_width - placement.width) / 2
                    placement.y = column_y
                    placement.order = order
                    column_y += placement.height + paper_node_gap
                cursor_x += column_width + column_gap
            segments.append({
                "row": row_index,
                "ranks": ranks,
                "stages": sorted({name for rank in ranks for name in group_names.get(rank, [])}),
                "direction": "LR" if row_index % 2 == 0 else "RL",
            })
            cursor_y += row_height + row_gap

        if locked:
            for placement in result.nodes.values():
                if placement.locked:
                    continue
                while any(_boxes_overlap(placement, fixed, padding=8.0) for fixed in locked):
                    placement.y += placement.height + node_gap
        result.direction = "LR"
        result.metadata["paper_segments"] = segments
        result.metadata["stage_aware"] = any(segment["stages"] for segment in segments)

    @staticmethod
    def _route_edges_for_paper(graph: GraphIR, result: LayoutResult) -> None:
        critical: list[dict[str, str]] = []
        node_map = graph.node_map()
        routed: list[tuple[Edge, list[tuple[float, float]]]] = []
        visible_edges = [edge for edge in graph.edges if edge.visible and edge.source in result.nodes and edge.target in result.nodes]
        # The visibility-grid router is deliberately bounded: synchronous full
        # rendering is already rejected above the scale policy, while the 1k
        # benchmark must not allocate a quadratic routing grid.  Large focused
        # views use the deterministic linear fallback.
        # Exact visibility routing grows sharply with both obstacles and edge
        # count.  Reserve it for small paper diagrams; larger semantic views
        # use the deterministic linear router and remain interactively fast.
        use_visibility_grid = len(result.nodes) <= 12 and len(visible_edges) <= 18
        for edge_index, edge in enumerate(visible_edges):
            source = result.nodes.get(edge.source)
            target = result.nodes.get(edge.target)
            assert source is not None and target is not None
            semantic = _edge_semantic(edge, node_map.get(edge.source), node_map.get(edge.target))
            if semantic != "data":
                critical.append({"edge_id": edge.id, "semantic": semantic})
            if edge.source == edge.target:
                padding = 7.0 + edge_index * 0.25
                points = [
                    (source.x + source.width, source.y + source.height / 2),
                    (source.x + source.width + padding, source.y + source.height / 2),
                    (source.x + source.width + padding, source.y - padding),
                    (source.x - padding, source.y - padding),
                    (source.x - padding, source.y + source.height / 2),
                    (source.x, source.y + source.height / 2),
                ]
            elif use_visibility_grid:
                points = _visibility_route(edge, result.nodes, routed, edge_index)
            else:
                points = _simple_paper_route(source, target, edge_index)
            points = _remove_redundant_points(points)
            result.edges[edge.id] = EdgeRoute(points, target.rank <= source.rank)
            routed.append((edge, points))
        result.metadata["critical_edges"] = critical

    @staticmethod
    def _paper_metrics(
        result: LayoutResult,
        preset: str,
        page: dict[str, Any],
        *,
        body_font_px: float,
        minimum_font_pt: float,
    ) -> dict[str, Any]:
        bbox = _content_bbox(result)
        content_width = max(1.0, bbox[2] - bbox[0])
        content_height = max(1.0, bbox[3] - bbox[1])
        if preset == "fit-content":
            margin = float(page.get("margin", 34.0))
            page_width = content_width + 2 * margin
            page_height = content_height + 2 * margin
            scale = 1.0
            occupancy = content_width * content_height / max(page_width * page_height, 1.0)
        else:
            page_width = float(page["width"])
            page_height = float(page["height"])
            margin = float(page.get("margin", 24.0))
            available_width = max(1.0, page_width - 2 * margin)
            available_height = max(1.0, page_height - 2 * margin)
            scale = min(1.0, available_width / content_width, available_height / content_height)
            occupancy = (content_width * scale) * (content_height * scale) / (available_width * available_height)
        overlaps = _node_overlap_pairs(result)
        final_font = body_font_px * 0.75 * scale
        return {
            "selected_page": preset,
            "page": {"width": page_width, "height": page_height, "margin": margin},
            "content_bbox": list(bbox),
            "content_width": content_width,
            "content_height": content_height,
            "diagram_scale": scale,
            "body_font_px": body_font_px,
            "final_body_font_pt": final_font,
            "minimum_body_font_pt": minimum_font_pt,
            "readable": final_font + 1e-9 >= minimum_font_pt,
            "content_occupancy": occupancy,
            "node_overlap_count": len(overlaps),
            "node_overlap_pairs": overlaps,
            "cropped": False,
        }

    def detect_domain(self, graph: GraphIR) -> str:
        text = " ".join([
            graph.name,
            *(f"{node.name} {node.op_type} {' '.join(node.tags)}" for node in graph.nodes),
            *(f"{group.name} {group.level}" for group in graph.subgraphs),
        ]).lower()
        scores = {
            "unet": sum(token in text for token in ("unet", "encoder", "decoder", "upsample", "skip")),
            "transformer": sum(token in text for token in ("attention", "transformer", "qkv", "layernorm", "embedding")),
            "resnet": 2 * any(token in text for token in ("resnet", "residual", "shortcut")) + sum(token in text for token in ("bottleneck", "skip")),
            "rnn": 2 * any(token in text for token in ("rnn", "lstm", "gru", "recurrent")),
            "moe": sum(token in text for token in ("moe", "expert", "router", "gating")),
            "diffusion": sum(token in text for token in ("diffusion", "timestep", "noise", "denoise")),
            "multimodal": sum(token in text for token in ("vision", "text", "audio", "fusion", "multimodal")),
            "cnn": sum(token in text for token in ("conv", "pool", "batchnorm", "feature")),
        }
        specific = {key: value for key, value in scores.items() if key != "cnn"}
        domain, score = max(specific.items(), key=lambda item: (item[1], item[0]))
        if score >= 2:
            return domain
        return "cnn" if scores["cnn"] >= 2 else "generic"

    def _layered(self, graph: GraphIR, algorithm: str, direction: str, width: float, height: float, rank_gap: float, node_gap: float) -> LayoutResult:
        visible = sorted((node for node in graph.nodes if node.visible), key=lambda item: item.id)
        node_ids = {node.id for node in visible}
        incoming: dict[str, set[str]] = {node.id: set() for node in visible}
        outgoing: dict[str, set[str]] = {node.id: set() for node in visible}
        for edge in graph.edges:
            if edge.visible and edge.source in node_ids and edge.target in node_ids and edge.source != edge.target:
                incoming[edge.target].add(edge.source)
                outgoing[edge.source].add(edge.target)
        rank = _component_ranks(node_ids, outgoing)

        by_rank: dict[int, list[str]] = defaultdict(list)
        nodes = graph.node_map()
        for node_id, value in rank.items():
            by_rank[value].append(node_id)
        for items in by_rank.values():
            items.sort(key=lambda node_id: self._domain_order(nodes[node_id], algorithm))
        for _ in range(4):
            for value in sorted(by_rank):
                previous_order = {item: index for index, item in enumerate(by_rank.get(value - 1, []))}
                by_rank[value].sort(key=lambda item: (
                    sum(previous_order.get(parent, 0) for parent in incoming[item]) / max(1, len(incoming[item])),
                    self._domain_order(nodes[item], algorithm), item,
                ))
            for value in sorted(by_rank, reverse=True):
                next_order = {item: index for index, item in enumerate(by_rank.get(value + 1, []))}
                by_rank[value].sort(key=lambda item: (
                    sum(next_order.get(child, 0) for child in outgoing[item]) / max(1, len(outgoing[item])),
                    self._domain_order(nodes[item], algorithm), item,
                ))

        placements: dict[str, NodePlacement] = {}
        horizontal = direction.upper() in {"LR", "RL"}
        max_rank = max(by_rank, default=0)
        for rank_value, items in sorted(by_rank.items()):
            span = (len(items) - 1) * (height + node_gap)
            for order, node_id in enumerate(items):
                main = rank_value * (width + rank_gap)
                cross = order * (height + node_gap) - span / 2
                if horizontal:
                    x, y = main, cross
                    if direction.upper() == "RL":
                        x = (max_rank * (width + rank_gap)) - x
                else:
                    x, y = cross, main
                    if direction.upper() == "BT":
                        y = (max_rank * (height + rank_gap)) - y
                placements[node_id] = NodePlacement(x, y, width, height, rank_value, order)
        return LayoutResult(engine=algorithm, direction=direction.upper(), nodes=placements)

    @staticmethod
    def _domain_order(node: Node, algorithm: str) -> tuple:
        text = f"{node.path} {node.name} {node.op_type}".lower()
        if algorithm == "unet":
            lane = 0 if "encoder" in text or "down" in text else 2 if "decoder" in text or "up" in text else 1
            return lane, text
        if algorithm == "transformer":
            order = next((index for index, token in enumerate(("input", "embed", "norm", "q", "k", "v", "attention", "add", "mlp", "output")) if token in text), 5)
            return order, text
        if algorithm == "moe":
            order = 0 if "router" in text or "gate" in text else 1 if "expert" in text else 2
            return order, text
        if algorithm == "multimodal":
            order = 0 if "vision" in text or "image" in text else 1 if "text" in text else 2 if "audio" in text else 3
            return order, text
        return 0, text

    @staticmethod
    def _apply_domain_geometry(graph: GraphIR, result: LayoutResult, algorithm: str, gap: float) -> None:
        nodes = graph.node_map()
        horizontal = result.direction in {"LR", "RL", "RADIAL"}
        cross_axis = "y" if horizontal else "x"
        cross_size = "height" if horizontal else "width"

        def set_cross(placement: NodePlacement, value: float) -> None:
            setattr(placement, cross_axis, value)

        if algorithm == "unet":
            encoders, decoders, bottlenecks = [], [], []
            for node_id, placement in result.nodes.items():
                text = f"{nodes[node_id].path} {nodes[node_id].name} {nodes[node_id].op_type}".lower()
                if any(token in text for token in ("encoder", "down", "contract")):
                    encoders.append((placement.rank, node_id, placement))
                elif any(token in text for token in ("decoder", "up", "expand")):
                    decoders.append((placement.rank, node_id, placement))
                elif any(token in text for token in ("bottleneck", "bridge", "middle")):
                    bottlenecks.append(placement)
            step = (next(iter(result.nodes.values())).height if result.nodes else 66) + gap
            for index, (_, _, placement) in enumerate(sorted(encoders, key=lambda item: (item[0], item[1]))):
                set_cross(placement, index * step)
            for index, (_, _, placement) in enumerate(
                sorted(decoders, key=lambda item: (item[0], item[1]), reverse=True)
            ):
                set_cross(placement, index * step)
            bottom = max(len(encoders), len(decoders)) * step
            for placement in bottlenecks:
                set_cross(placement, bottom)
        elif algorithm == "multimodal":
            lanes = {"vision": -1, "image": -1, "text": 0, "language": 0, "audio": 1, "speech": 1}
            step = (next(iter(result.nodes.values())).height if result.nodes else 66) + gap * 2
            for node_id, placement in result.nodes.items():
                text = f"{nodes[node_id].path} {nodes[node_id].name}".lower()
                lane = next((value for token, value in lanes.items() if token in text), None)
                if lane is not None and not any(token in text for token in ("fusion", "merge", "project")):
                    set_cross(placement, lane * step)
        elif algorithm == "moe":
            experts = [(node_id, placement) for node_id, placement in result.nodes.items() if "expert" in f"{nodes[node_id].name} {nodes[node_id].op_type}".lower()]
            experts.sort(key=lambda item: item[0])
            if experts:
                step = getattr(experts[0][1], cross_size) + gap
                start = -(len(experts) - 1) * step / 2
                for index, (_, placement) in enumerate(experts):
                    set_cross(placement, start + index * step)

    def _radial(self, graph: GraphIR, width: float, height: float, gap: float) -> LayoutResult:
        nodes = sorted((node for node in graph.nodes if node.visible), key=lambda item: item.id)
        radius = max(140.0, len(nodes) * (max(width, height) + gap) / (2 * pi))
        placements = {}
        for index, node in enumerate(nodes):
            angle = -pi / 2 + 2 * pi * index / max(1, len(nodes))
            placements[node.id] = NodePlacement(radius + cos(angle) * radius, radius + sin(angle) * radius, width, height, 0, index)
        return LayoutResult(engine="radial", direction="RADIAL", nodes=placements)

    @staticmethod
    def _apply_constraints(graph: GraphIR, result: LayoutResult, previous: LayoutResult | None) -> None:
        for constraint in graph.constraints:
            placements = [result.nodes[node_id] for node_id in constraint.target_ids if node_id in result.nodes]
            if constraint.kind in {"align-x", "align-y"} and placements:
                axis = constraint.kind[-1]
                value = float(constraint.value) if constraint.value is not None else sum(getattr(item, axis) for item in placements) / len(placements)
                for item in placements:
                    setattr(item, axis, value)
                    item.locked = constraint.locked
                continue
            if constraint.kind in {"distribute-x", "distribute-y"} and len(placements) > 2:
                axis = constraint.kind[-1]
                ordered = sorted(placements, key=lambda item: getattr(item, axis))
                low, high = getattr(ordered[0], axis), getattr(ordered[-1], axis)
                for index, item in enumerate(ordered):
                    setattr(item, axis, low + (high - low) * index / (len(ordered) - 1))
                    item.locked = constraint.locked
                continue
            if constraint.kind == "same-rank" and placements:
                rank = int(constraint.value) if constraint.value is not None else min(item.rank for item in placements)
                for item in placements:
                    item.rank = rank
                continue
            for node_id in constraint.target_ids:
                placement = result.nodes.get(node_id)
                if placement is None:
                    continue
                if constraint.kind == "position" and isinstance(constraint.value, dict):
                    placement.x = float(constraint.value.get("x", placement.x))
                    placement.y = float(constraint.value.get("y", placement.y))
                    placement.locked = constraint.locked
                elif constraint.kind == "panel":
                    placement.panel = str(constraint.value)
        if previous:
            for node_id, old in previous.nodes.items():
                if old.locked and node_id in result.nodes:
                    current = result.nodes[node_id]
                    current.x, current.y, current.locked = old.x, old.y, True

    @staticmethod
    def _route_edges(graph: GraphIR, result: LayoutResult) -> None:
        for edge in graph.edges:
            source, target = result.nodes.get(edge.source), result.nodes.get(edge.target)
            if source is None or target is None or not edge.visible:
                continue
            horizontal = result.direction in {"LR", "RL"}
            back_edge = target.rank <= source.rank
            long_skip = abs(target.rank - source.rank) > 1
            if horizontal:
                sx = source.x + (0 if result.direction == "RL" else source.width)
                tx = target.x + (target.width if result.direction == "RL" else 0)
                sy, ty = source.y + source.height / 2, target.y + target.height / 2
                if back_edge or long_skip:
                    bend = min(source.y, target.y) - 42 - abs(target.rank - source.rank) * 9 - abs(target.order - source.order) * 10
                    points = [(sx, sy), (sx + (12 if tx >= sx else -12), bend), (tx - (12 if tx >= sx else -12), bend), (tx, ty)]
                else:
                    middle = (sx + tx) / 2
                    points = [(sx, sy), (middle, sy), (middle, ty), (tx, ty)]
            else:
                sx, tx = source.x + source.width / 2, target.x + target.width / 2
                sy = source.y + (0 if result.direction == "BT" else source.height)
                ty = target.y + (target.height if result.direction == "BT" else 0)
                if back_edge or long_skip:
                    bend = min(source.x, target.x) - 42 - abs(target.rank - source.rank) * 9 - abs(target.order - source.order) * 10
                    points = [(sx, sy), (bend, sy), (bend, ty), (tx, ty)]
                else:
                    middle = (sy + ty) / 2
                    points = [(sx, sy), (sx, middle), (tx, middle), (tx, ty)]
            result.edges[edge.id] = EdgeRoute(points, back_edge)

    @staticmethod
    def _apply_edge_constraints(graph: GraphIR, result: LayoutResult) -> None:
        """Restore user-edited waypoints after normalization while keeping endpoints attached."""
        for constraint in graph.constraints:
            if constraint.kind != "edge-route":
                continue
            raw = constraint.value.get("points") if isinstance(constraint.value, dict) else constraint.value
            if not isinstance(raw, list) or len(raw) < 2:
                continue
            for edge_id in constraint.target_ids:
                route = result.edges.get(edge_id)
                if route is None:
                    continue
                try:
                    points = [(float(point[0]), float(point[1])) for point in raw]
                except (TypeError, ValueError, IndexError):
                    continue
                route.points = [route.points[0], *points[1:-1], route.points[-1]]
    @staticmethod
    def _restore_absolute_positions(graph: GraphIR, result: LayoutResult, previous: LayoutResult | None) -> bool:
        """Treat persisted manual coordinates as final canvas coordinates, not pre-margin hints."""
        changed = False
        for constraint in graph.constraints:
            placements = [result.nodes[node_id] for node_id in constraint.target_ids if node_id in result.nodes]
            if constraint.kind == "position" and isinstance(constraint.value, dict):
                for placement in placements:
                    placement.x = float(constraint.value.get("x", placement.x))
                    placement.y = float(constraint.value.get("y", placement.y))
                    placement.locked = constraint.locked
                    changed = True
            elif constraint.kind in {"align-x", "align-y"} and constraint.value is not None:
                axis = constraint.kind[-1]
                for placement in placements:
                    setattr(placement, axis, float(constraint.value))
                    placement.locked = constraint.locked
                    changed = True
        if previous:
            for node_id, old in previous.nodes.items():
                if old.locked and node_id in result.nodes:
                    placement = result.nodes[node_id]
                    placement.x, placement.y, placement.locked = old.x, old.y, True
                    changed = True
        return changed

    @staticmethod
    def _refresh_panel_boxes(result: LayoutResult) -> None:
        panels: dict[str, list[NodePlacement]] = defaultdict(list)
        for placement in result.nodes.values():
            if placement.panel:
                panels[placement.panel].append(placement)
        result.metadata["panels"] = {
            name: {
                "x": min(item.x for item in placements) - 18,
                "y": min(item.y for item in placements) - 30,
                "width": max(item.x + item.width for item in placements) - min(item.x for item in placements) + 36,
                "height": max(item.y + item.height for item in placements) - min(item.y for item in placements) + 48,
            }
            for name, placements in sorted(panels.items())
        }

    @staticmethod
    def _measure(result: LayoutResult) -> None:
        right = [item.x + item.width for item in result.nodes.values()]
        bottom = [item.y + item.height for item in result.nodes.values()]
        right.extend(item["x"] + item["width"] for item in result.groups.values())
        bottom.extend(item["y"] + item["height"] for item in result.groups.values())
        right.extend(x for route in result.edges.values() for x, _ in route.points)
        bottom.extend(y for route in result.edges.values() for _, y in route.points)
        result.width = max(right, default=0) + 34
        result.height = max(bottom, default=0) + 34

    @staticmethod
    def _arrange_panels(result: LayoutResult) -> None:
        panels: dict[str, list[NodePlacement]] = defaultdict(list)
        for placement in result.nodes.values():
            if placement.panel:
                panels[placement.panel].append(placement)
        if not panels:
            return
        cursor = 0.0
        panel_boxes: dict[str, dict[str, float]] = {}
        for name in sorted(panels):
            placements = panels[name]
            min_x = min(item.x for item in placements)
            min_y = min(item.y for item in placements)
            max_x = max(item.x + item.width for item in placements)
            max_y = max(item.y + item.height for item in placements)
            dx, dy = cursor - min_x, 0 - min_y
            for item in placements:
                item.x += dx
                item.y += dy
            width, height = max_x - min_x, max_y - min_y
            panel_boxes[name] = {"x": cursor - 18, "y": -30, "width": width + 36, "height": height + 48}
            cursor += width + 92
        result.metadata["panels"] = panel_boxes

    @staticmethod
    def _place_groups(graph: GraphIR, result: LayoutResult) -> None:
        for group in graph.subgraphs:
            members = [result.nodes[item] for item in group.node_ids if item in result.nodes]
            if not members:
                continue
            margin = 20
            x1 = min(item.x for item in members) - margin
            y1 = min(item.y for item in members) - margin - 14
            x2 = max(item.x + item.width for item in members) + margin
            y2 = max(item.y + item.height for item in members) + margin
            result.groups[group.id] = {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1}

    @staticmethod
    def _normalize(result: LayoutResult) -> None:
        boxes = [(item.x, item.y, item.x + item.width, item.y + item.height) for item in result.nodes.values()]
        boxes += [(item["x"], item["y"], item["x"] + item["width"], item["y"] + item["height"]) for item in result.groups.values()]
        boxes += [(x, y, x, y) for route in result.edges.values() for x, y in route.points]
        if not boxes:
            return
        min_x, min_y = min(item[0] for item in boxes), min(item[1] for item in boxes)
        dx, dy = 34 - min_x, 46 - min_y
        for placement in result.nodes.values():
            placement.x += dx
            placement.y += dy
        for group_box in result.groups.values():
            group_box["x"] += dx
            group_box["y"] += dy
        for route in result.edges.values():
            route.points = [(x + dx, y + dy) for x, y in route.points]
        for panel_box in result.metadata.get("panels", {}).values():
            panel_box["x"] += dx
            panel_box["y"] += dy
        result.width = max(
            max((item.x + item.width for item in result.nodes.values()), default=0),
            max((x for route in result.edges.values() for x, _ in route.points), default=0),
        ) + 34
        result.height = max(
            max((item.y + item.height for item in result.nodes.values()), default=0),
            max((y for route in result.edges.values() for _, y in route.points), default=0),
        ) + 34


def collapse_graph(graph: GraphIR, collapsed: set[str] | None = None) -> GraphIR:
    collapsed = collapsed or {group.id for group in graph.subgraphs if group.collapsed}
    result = graph.copy()
    groups = {group.id: group for group in result.subgraphs if group.id in collapsed}
    if not groups:
        return result
    hidden_to_proxy: dict[str, str] = {}
    hidden_to_group: dict[str, str] = {}
    proxies_by_id: dict[str, Node] = {}
    proxies: list[Node] = []
    edge_target_mapping: dict[str, str] = {}
    for group_id, group in sorted(groups.items()):
        proxy_id = stable_id("node", f"collapsed:{group_id}")
        members = [node for node in result.nodes if node.id in group.node_ids]
        proxy = Node(
            proxy_id, group.name, "CollapsedModule", "operation", path=group.name, level=group.level,
            parameters=sum(node.parameters for node in members),
            trainable_parameters=sum(node.trainable_parameters for node in members),
            attributes={"collapsed_group": group_id, "member_count": len(members)}, tags=["collapsed"],
        )
        proxies.append(proxy)
        proxies_by_id[proxy_id] = proxy
        for node in members:
            hidden_to_proxy[node.id] = proxy_id
            hidden_to_group[node.id] = group_id
    kept_nodes = [node for node in result.nodes if node.id not in hidden_to_proxy] + proxies
    dedup: dict[tuple[str, str, str, str, str | None, str | None], Edge] = {}
    for edge in result.edges:
        source = hidden_to_proxy.get(edge.source, edge.source)
        target = hidden_to_proxy.get(edge.target, edge.target)
        if source == target:
            continue
        source_port = edge.source_port
        target_port = edge.target_port
        if edge.source in hidden_to_proxy:
            proxy = proxies_by_id[source]
            source_port = f"{source}:output:{len(proxy.outputs)}"
            proxy.outputs.append(Port(source_port, edge.label or f"output_{len(proxy.outputs)}", "output", edge.tensor))
        if edge.target in hidden_to_proxy:
            proxy = proxies_by_id[target]
            target_port = f"{target}:input:{len(proxy.inputs)}"
            proxy.inputs.append(Port(target_port, edge.label or f"input_{len(proxy.inputs)}", "input", edge.tensor))
        key = (source, target, edge.kind, edge.label, source_port, target_port)
        if key not in dedup:
            collapsed_edge = Edge.create(source, target, source_port=source_port, target_port=target_port, kind=edge.kind, tensor=edge.tensor, label=edge.label)
            collapsed_edge.attributes = {**deepcopy(edge.attributes), "source_edges": [edge.id]}
            dedup[key] = collapsed_edge
        elif edge.id not in dedup[key].attributes["source_edges"]:
            dedup[key].attributes["source_edges"].append(edge.id)
        edge_target_mapping[edge.id] = dedup[key].id
    result.nodes = kept_nodes
    result.edges = list(dedup.values())
    result.subgraphs = [group for group in result.subgraphs if group.id not in collapsed]
    target_mapping = {**hidden_to_proxy, **edge_target_mapping, **{group_id: stable_id("node", f"collapsed:{group_id}") for group_id in groups}}
    valid_targets = {node.id for node in result.nodes} | {edge.id for edge in result.edges} | {group.id for group in result.subgraphs}
    for annotation in result.annotations:
        annotation.target_ids = list(dict.fromkeys(target_mapping.get(target, target) for target in annotation.target_ids if target_mapping.get(target, target) in valid_targets))
    result.annotations = [item for item in result.annotations if not item.target_ids or item.kind in {"text", "title", "formula", "region", "panel", "panel-label"}]
    for constraint in result.constraints:
        constraint.target_ids = list(dict.fromkeys(target_mapping.get(target, target) for target in constraint.target_ids if target_mapping.get(target, target) in valid_targets))
    result.constraints = [item for item in result.constraints if item.target_ids]
    return result.validate()


def aggregate_repeated_blocks(graph: GraphIR, *, minimum_repeats: int = 2) -> GraphIR:
    """Collapse verified repeated groups/parallel operators into editable ``×N`` proxies.

    Groups containing position constraints are deliberately excluded: automatic
    paper adaptation must never hide or relocate content the user explicitly
    locked.  External data/control edges remain graph edges rather than being
    flattened into a bitmap decoration.
    """
    result = graph.copy()
    locked_ids = {
        target
        for constraint in result.constraints
        if constraint.locked and constraint.kind in {"position", "align-x", "align-y", "panel"}
        for target in constraint.target_ids
    }
    aggregations: list[dict[str, Any]] = []

    incoming: dict[str, set[str]] = defaultdict(set)
    outgoing: dict[str, set[str]] = defaultdict(set)
    for edge in result.edges:
        incoming[edge.target].add(edge.source)
        outgoing[edge.source].add(edge.target)
    parallel: dict[tuple[Any, ...], list[str]] = defaultdict(list)
    for node in result.nodes:
        text = f"{node.name} {node.op_type}".lower()
        if node.id in locked_ids or node.category in {"input", "output", "merge"}:
            continue
        if "router" in text or "gate" in text:
            continue
        parallel_signature = (
            node.name.lower().rstrip(" 0123456789"),
            node.op_type,
            node.category,
            tuple(sorted(incoming[node.id])),
            tuple(sorted(outgoing[node.id])),
        )
        parallel[parallel_signature].append(node.id)
    for member_ids in sorted(parallel.values(), key=lambda values: values[0]):
        if len(member_ids) < max(3, minimum_repeats):
            continue
        _replace_repetition(result, member_ids, [], aggregations, kind="parallel")

    node_map = result.node_map()
    group_candidates: dict[tuple[Any, ...], list[Subgraph]] = defaultdict(list)
    for group in result.subgraphs:
        members = [node_map[node_id] for node_id in group.node_ids if node_id in node_map]
        if len(members) < 2 or any(node.id in locked_ids for node in members):
            continue
        namespaces = [node.namespace for node in members if node.namespace]
        common = _common_namespace(namespaces)
        parent_namespace = common.rsplit(".", 1)[0] if "." in common else ""
        group_signature = (
            parent_namespace,
            group.level,
            tuple(sorted(node.op_type for node in members)),
            tuple(sorted(node.category for node in members)),
            len(members),
        )
        group_candidates[group_signature].append(group)
    consumed: set[str] = set()
    for groups in sorted(group_candidates.values(), key=lambda values: values[0].id):
        available = [group for group in groups if not consumed.intersection(group.node_ids)]
        if len(available) < minimum_repeats:
            continue
        member_ids = [node_id for group in available for node_id in group.node_ids if node_id in result.node_map()]
        if len(member_ids) < 2:
            continue
        _replace_repetition(result, member_ids, [group.id for group in available], aggregations, kind="sequential-block")
        consumed.update(member_ids)

    if aggregations:
        result.metadata["paper_aggregations"] = aggregations
    return result.validate()


def _replace_repetition(
    graph: GraphIR,
    member_ids: list[str],
    group_ids: list[str],
    records: list[dict[str, Any]],
    *,
    kind: str,
) -> None:
    members = [graph.node_map()[node_id] for node_id in member_ids if node_id in graph.node_map()]
    if len(members) < 2:
        return
    member_set = {node.id for node in members}
    repeat_count = len(group_ids) if group_ids else len(members)
    base_name = members[0].name.rstrip(" 0123456789") or members[0].op_type
    if kind == "sequential-block":
        base_name = "Residual block" if any("residual" in f"{node.name} {' '.join(node.tags)}".lower() for node in members) else "Repeated block"
    proxy_id = stable_id("node", f"aggregate:{kind}:{':'.join(sorted(member_set))}")
    proxy = Node(
        id=proxy_id,
        name=f"{base_name} ×{repeat_count}",
        op_type="RepeatedBlock" if kind == "sequential-block" else members[0].op_type,
        category=members[0].category,
        path=f"paper.aggregate.{proxy_id}",
        level="block",
        parameters=sum(node.parameters for node in members),
        trainable_parameters=sum(node.trainable_parameters for node in members),
        buffers=sum(node.buffers for node in members),
        attributes={
            "repeat_count": repeat_count,
            "member_count": len(members),
            "aggregated_node_ids": sorted(member_set),
            "aggregation_kind": kind,
        },
        tags=list(dict.fromkeys(["collapsed", "repeated", *(tag for node in members for tag in node.tags)])),
    )
    replacement_edges: dict[tuple[str, str, str, str], Edge] = {}
    internal_semantics: set[str] = set()
    original_map = graph.node_map()
    for edge in graph.edges:
        source_inside = edge.source in member_set
        target_inside = edge.target in member_set
        if source_inside and target_inside:
            semantic = _edge_semantic(edge, original_map.get(edge.source), original_map.get(edge.target))
            if semantic != "data":
                internal_semantics.add(semantic)
            continue
        source = proxy_id if source_inside else edge.source
        target = proxy_id if target_inside else edge.target
        copied = deepcopy(edge)
        if source_inside or target_inside:
            copied.id = stable_id("edge", f"aggregate:{edge.id}:{source}->{target}")
        copied.source, copied.target = source, target
        copied.attributes = {**copied.attributes, "source_edges": [edge.id]}
        if source_inside:
            copied.source_port = None
        if target_inside:
            copied.target_port = None
        key = (source, target, copied.kind, copied.label)
        if key not in replacement_edges:
            replacement_edges[key] = copied
        elif edge.id not in replacement_edges[key].attributes["source_edges"]:
            replacement_edges[key].attributes["source_edges"].append(edge.id)
    for semantic in sorted(internal_semantics):
        loop = Edge.create(proxy_id, proxy_id, kind=semantic, label=f"{semantic} ×{repeat_count}")
        loop.attributes["semantic"] = semantic
        replacement_edges[(proxy_id, proxy_id, semantic, loop.label)] = loop
    graph.nodes = [node for node in graph.nodes if node.id not in member_set] + [proxy]
    graph.edges = list(replacement_edges.values())
    removed_groups = set(group_ids)
    updated_groups: list[Subgraph] = []
    for group in graph.subgraphs:
        if group.id in removed_groups:
            continue
        mapped = [proxy_id if node_id in member_set else node_id for node_id in group.node_ids]
        group.node_ids = list(dict.fromkeys(mapped))
        if group.node_ids:
            updated_groups.append(group)
    graph.subgraphs = updated_groups
    for collection in (graph.annotations, graph.constraints):
        for item in collection:
            item.target_ids = list(dict.fromkeys(proxy_id if target in member_set else target for target in item.target_ids))
    records.append({
        "proxy_id": proxy_id,
        "label": proxy.name,
        "repeat_count": repeat_count,
        "member_count": len(members),
        "kind": kind,
    })


def _common_namespace(values: list[str]) -> str:
    if not values:
        return ""
    split = [value.split(".") for value in values]
    common: list[str] = []
    for parts in zip(*split):
        if len(set(parts)) != 1:
            break
        common.append(parts[0])
    return ".".join(common)


def focus_graph(graph: GraphIR, focus_ids: set[str], *, hops: int = 1) -> GraphIR:
    """Create a bounded neighborhood with proxy nodes for connections outside the view."""
    if not focus_ids:
        return graph.copy()
    groups = {group.id: group for group in graph.subgraphs}
    selected = {item for item in focus_ids if item in graph.node_map()}
    for group_id in focus_ids:
        if group_id in groups:
            selected.update(groups[group_id].node_ids)
    if not selected:
        return graph.copy()
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in graph.edges:
        adjacency[edge.source].add(edge.target)
        adjacency[edge.target].add(edge.source)
    frontier = set(selected)
    for _ in range(max(0, int(hops))):
        frontier = {neighbor for node_id in frontier for neighbor in adjacency[node_id]} - selected
        selected.update(frontier)

    result = graph.induced(selected, name=f"{graph.name} · focused")
    result.metadata["focus"] = {"node_ids": sorted(focus_ids), "hops": max(0, int(hops)), "total_nodes": len(graph.nodes)}
    source_nodes = graph.node_map()
    proxy_ids: dict[str, str] = {}
    for edge in graph.edges:
        source_inside, target_inside = edge.source in selected, edge.target in selected
        if source_inside == target_inside:
            continue
        outside_id = edge.target if source_inside else edge.source
        outside = source_nodes[outside_id]
        proxy_id = proxy_ids.setdefault(outside_id, stable_id("node", f"focus-boundary:{outside_id}"))
        if proxy_id not in result.node_map():
            result.nodes.append(Node(
                proxy_id, outside.name, "BoundaryProxy", outside.category,
                path=outside.path, level=outside.level, parameters=outside.parameters,
                trainable_parameters=outside.trainable_parameters,
                attributes={"boundary_for": outside_id}, tags=["boundary", "collapsed"],
            ))
        if source_inside:
            result.edges.append(Edge.create(edge.source, proxy_id, kind=edge.kind, tensor=edge.tensor, label=edge.label))
        else:
            result.edges.append(Edge.create(proxy_id, edge.target, kind=edge.kind, tensor=edge.tensor, label=edge.label))
    return result.validate()


def unroll_recurrent_graph(graph: GraphIR, *, steps: int = 3, recurrent_ids: set[str] | None = None) -> GraphIR:
    """Expand recurrent nodes into deterministic, editable time-step copies."""
    steps = int(steps)
    if steps < 2:
        return graph.copy()
    selected = recurrent_ids or {
        node.id for node in graph.nodes
        if any(token in f"{node.name} {node.op_type} {' '.join(node.tags)}".lower() for token in ("rnn", "lstm", "gru", "recurrent"))
        or int(node.attributes.get("num_passes", 1) or 1) > 1
    }
    selected &= set(graph.node_map())
    if not selected:
        return graph.copy()
    copies: dict[tuple[str, int], Node] = {}
    for node_id in sorted(selected):
        original = graph.node_map()[node_id]
        for time_step in range(steps):
            node = deepcopy(original)
            node.id = stable_id("node", f"unroll:{node_id}:t{time_step}")
            node.name = f"{original.name} [t={time_step}]"
            node.path = f"{original.path}.time_{time_step}"
            node.tags = list(dict.fromkeys([*node.tags, "recurrent", "time-step"]))
            node.attributes.update({"unrolled_from": node_id, "time_step": time_step, "time_steps": steps})
            for direction in ("inputs", "outputs"):
                for index, port in enumerate(getattr(node, direction)):
                    port.id = f"{node.id}:{direction[:-1]}:{index}"
            copies[node_id, time_step] = node
    result = graph.copy()
    result.name = f"{graph.name} · {steps} time steps"
    result.nodes = [node for node in result.nodes if node.id not in selected] + list(copies.values())
    result.edges = []
    for edge in graph.edges:
        source_recurrent, target_recurrent = edge.source in selected, edge.target in selected
        if not source_recurrent and not target_recurrent:
            result.edges.append(deepcopy(edge))
            continue
        if source_recurrent and target_recurrent:
            if edge.source == edge.target:
                continue
            pairs = [(copies[edge.source, step].id, copies[edge.target, step].id, step) for step in range(steps)]
        elif source_recurrent:
            pairs = [(copies[edge.source, steps - 1].id, edge.target, steps - 1)]
        else:
            pairs = [(edge.source, copies[edge.target, 0].id, 0)]
        for source, target, time_step in pairs:
            unrolled = Edge.create(source, target, kind=edge.kind, tensor=edge.tensor, label=edge.label)
            unrolled.id = stable_id("edge", f"unroll:{edge.id}:t{time_step}:{source}->{target}")
            unrolled.attributes = {**edge.attributes, "unrolled_from": edge.id, "time_step": time_step}
            result.edges.append(unrolled)
    for node_id in sorted(selected):
        for time_step in range(steps - 1):
            recurrent = Edge.create(copies[node_id, time_step].id, copies[node_id, time_step + 1].id, kind="recurrent", label=f"t{time_step}→t{time_step + 1}")
            recurrent.attributes.update({
                "time_unrolled": True,
                "unrolled_from_node": node_id,
                "source_time_step": time_step,
                "target_time_step": time_step + 1,
            })
            result.edges.append(recurrent)
    for group in result.subgraphs:
        members: list[str] = []
        for node_id in group.node_ids:
            if node_id in selected:
                members.extend(copies[node_id, step].id for step in range(steps))
            else:
                members.append(node_id)
        group.node_ids = members
    valid_targets = {node.id for node in result.nodes} | {edge.id for edge in result.edges} | {group.id for group in result.subgraphs}
    for collection in (result.annotations, result.constraints):
        for item in collection:
            expanded: list[str] = []
            for target in item.target_ids:
                if target in selected:
                    expanded.extend(copies[target, step].id for step in range(steps))
                elif target in valid_targets:
                    expanded.append(target)
            item.target_ids = list(dict.fromkeys(expanded))
    result.metadata["time_unroll"] = {"steps": steps, "source_nodes": sorted(selected)}
    return result.validate()


def _remove_redundant_points(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    compact: list[tuple[float, float]] = []
    for point in points:
        point = (round(float(point[0]), 6), round(float(point[1]), 6))
        if compact and point == compact[-1]:
            continue
        if len(compact) >= 2:
            a, b = compact[-2], compact[-1]
            if (a[0] == b[0] == point[0]) or (a[1] == b[1] == point[1]):
                compact[-1] = point
                continue
        compact.append(point)
    return compact


def _simple_paper_route(source: NodePlacement, target: NodePlacement, lane_index: int) -> list[tuple[float, float]]:
    """Linear-memory fallback used by large focus views."""
    sx, sy = source.x + source.width / 2, source.y + source.height / 2
    tx, ty = target.x + target.width / 2, target.y + target.height / 2
    if abs(tx - sx) >= abs(ty - sy):
        forward = tx >= sx
        start = (source.x + (source.width if forward else 0), sy)
        end = (target.x + (0 if forward else target.width), ty)
        lane = (start[0] + end[0]) / 2 + (lane_index % 3 - 1) * 4
        return [start, (lane, start[1]), (lane, end[1]), end]
    down = ty >= sy
    start = (sx, source.y + (source.height if down else 0))
    end = (tx, target.y + (0 if down else target.height))
    lane = (start[1] + end[1]) / 2 + (lane_index % 3 - 1) * 4
    return [start, (start[0], lane), (end[0], lane), end]


def _placement_ports(item: NodePlacement, padding: float) -> list[tuple[tuple[float, float], tuple[float, float], str]]:
    center_x, center_y = item.x + item.width / 2, item.y + item.height / 2
    return [
        ((item.x, center_y), (item.x - padding, center_y), "L"),
        ((item.x + item.width, center_y), (item.x + item.width + padding, center_y), "R"),
        ((center_x, item.y), (center_x, item.y - padding), "T"),
        ((center_x, item.y + item.height), (center_x, item.y + item.height + padding), "B"),
    ]


def _axis_segment_blocked(first: tuple[float, float], second: tuple[float, float], nodes: dict[str, NodePlacement], *, padding: float) -> bool:
    x1, y1 = first
    x2, y2 = second
    for item in nodes.values():
        left, right = item.x - padding, item.x + item.width + padding
        top, bottom = item.y - padding, item.y + item.height + padding
        if y1 == y2 and top < y1 < bottom and min(x1, x2) < right and max(x1, x2) > left:
            return True
        if x1 == x2 and left < x1 < right and min(y1, y2) < bottom and max(y1, y2) > top:
            return True
    return False


def _point_inside_expanded(point: tuple[float, float], nodes: dict[str, NodePlacement], padding: float) -> bool:
    x, y = point
    return any(item.x - padding < x < item.x + item.width + padding and item.y - padding < y < item.y + item.height + padding for item in nodes.values())


def _segment_intersects(first: tuple[float, float], second: tuple[float, float], third: tuple[float, float], fourth: tuple[float, float]) -> bool:
    def orientation(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def on_segment(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> bool:
        return min(a[0], c[0]) <= b[0] <= max(a[0], c[0]) and min(a[1], c[1]) <= b[1] <= max(a[1], c[1])

    values = (orientation(first, second, third), orientation(first, second, fourth), orientation(third, fourth, first), orientation(third, fourth, second))
    if values[0] * values[1] < 0 and values[2] * values[3] < 0:
        return True
    return any(abs(value) < 1e-9 and on_segment(a, b, c) for value, a, b, c in (
        (values[0], first, third, second), (values[1], first, fourth, second),
        (values[2], third, first, fourth), (values[3], third, second, fourth),
    ))


def _segment_conflicts_with_routes(first: tuple[float, float], second: tuple[float, float], edge: Edge, routed: list[tuple[Edge, list[tuple[float, float]]]]) -> bool:
    for other, points in routed:
        if {edge.source, edge.target} & {other.source, other.target}:
            continue
        if any(_segment_intersects(first, second, start, end) for start, end in zip(points, points[1:])):
            return True
    return False


def _visibility_route(edge: Edge, nodes: dict[str, NodePlacement], routed: list[tuple[Edge, list[tuple[float, float]]]], edge_index: int) -> list[tuple[float, float]]:
    """Route one small-graph edge on an obstacle-aware orthogonal grid."""
    padding = 6.0
    source, target = nodes[edge.source], nodes[edge.target]
    source_ports, target_ports = _placement_ports(source, padding), _placement_ports(target, padding)
    xs: set[float] = set()
    ys: set[float] = set()
    for item in nodes.values():
        xs.update((item.x - padding, item.x, item.x + item.width / 2, item.x + item.width, item.x + item.width + padding))
        ys.update((item.y - padding, item.y, item.y + item.height / 2, item.y + item.height, item.y + item.height + padding))
    xs.update((min(item.x for item in nodes.values()) - 18.0 - edge_index * 2.0, max(item.x + item.width for item in nodes.values()) + 18.0 + edge_index * 2.0))
    ys.update((min(item.y for item in nodes.values()) - 18.0 - edge_index * 2.0, max(item.y + item.height for item in nodes.values()) + 18.0 + edge_index * 2.0))
    ordered_x, ordered_y = sorted(xs), sorted(ys)
    x_index, y_index = {value: index for index, value in enumerate(ordered_x)}, {value: index for index, value in enumerate(ordered_y)}
    pairs = sorted(((start, end) for start in source_ports for end in target_ports), key=lambda pair: (abs(pair[0][1][0] - pair[1][1][0]) + abs(pair[0][1][1] - pair[1][1][1]), pair[0][2], pair[1][2]))
    for (source_boundary, start, _), (target_boundary, goal, _) in pairs:
        start_key, goal_key = (x_index[start[0]], y_index[start[1]]), (x_index[goal[0]], y_index[goal[1]])
        queue: list[tuple[float, float, int, int, str]] = []
        heappush(queue, (abs(start[0] - goal[0]) + abs(start[1] - goal[1]), 0.0, start_key[0], start_key[1], ""))
        best: dict[tuple[int, int, str], float] = {(start_key[0], start_key[1], ""): 0.0}
        previous: dict[tuple[int, int, str], tuple[int, int, str]] = {}
        found: tuple[int, int, str] | None = None
        while queue:
            _, cost, ix, iy, direction = heappop(queue)
            state = (ix, iy, direction)
            if cost != best.get(state):
                continue
            if (ix, iy) == goal_key:
                found = state
                break
            for next_ix, next_iy, next_direction in ((ix - 1, iy, "H"), (ix + 1, iy, "H"), (ix, iy - 1, "V"), (ix, iy + 1, "V")):
                if not (0 <= next_ix < len(ordered_x) and 0 <= next_iy < len(ordered_y)):
                    continue
                first, second = (ordered_x[ix], ordered_y[iy]), (ordered_x[next_ix], ordered_y[next_iy])
                if _point_inside_expanded(second, nodes, padding) or _axis_segment_blocked(first, second, nodes, padding=padding) or _segment_conflicts_with_routes(first, second, edge, routed):
                    continue
                step = abs(first[0] - second[0]) + abs(first[1] - second[1])
                next_cost = cost + step + (10.0 if direction and direction != next_direction else 0.0)
                next_state = (next_ix, next_iy, next_direction)
                if next_cost + 1e-9 < best.get(next_state, float("inf")):
                    best[next_state] = next_cost
                    previous[next_state] = state
                    heuristic = abs(second[0] - goal[0]) + abs(second[1] - goal[1])
                    heappush(queue, (next_cost + heuristic, next_cost, next_ix, next_iy, next_direction))
        if found is None:
            continue
        grid_points: list[tuple[float, float]] = []
        cursor = found
        while True:
            grid_points.append((ordered_x[cursor[0]], ordered_y[cursor[1]]))
            if (cursor[0], cursor[1]) == start_key:
                break
            cursor = previous[cursor]
        grid_points.reverse()
        candidate = _remove_redundant_points([source_boundary, *grid_points, target_boundary])
        if not any(_segment_conflicts_with_routes(a, b, edge, routed) for a, b in zip(candidate, candidate[1:])):
            return candidate
    return _simple_paper_route(source, target, edge_index)


def _strongly_connected_components(node_ids: set[str], outgoing: dict[str, set[str]]) -> list[list[str]]:
    """Return a deterministic SCC partition using iterative Kosaraju passes."""
    reverse: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    for source in node_ids:
        for target in outgoing[source]:
            if target in reverse:
                reverse[target].add(source)

    visited: set[str] = set()
    finish_order: list[str] = []
    for root in sorted(node_ids):
        if root in visited:
            continue
        visited.add(root)
        stack: list[tuple[str, int, list[str]]] = [(root, 0, sorted(outgoing[root]))]
        while stack:
            node_id, index, neighbors = stack[-1]
            if index < len(neighbors):
                target = neighbors[index]
                stack[-1] = (node_id, index + 1, neighbors)
                if target in node_ids and target not in visited:
                    visited.add(target)
                    stack.append((target, 0, sorted(outgoing[target])))
                continue
            finish_order.append(node_id)
            stack.pop()

    components: list[list[str]] = []
    assigned: set[str] = set()
    for root in reversed(finish_order):
        if root in assigned:
            continue
        component: list[str] = []
        component_stack = [root]
        assigned.add(root)
        while component_stack:
            node_id = component_stack.pop()
            component.append(node_id)
            for source in sorted(reverse[node_id], reverse=True):
                if source not in assigned:
                    assigned.add(source)
                    component_stack.append(source)
        components.append(sorted(component))
    return components


def _component_ranks(node_ids: set[str], outgoing: dict[str, set[str]]) -> dict[str, int]:
    """Rank the SCC condensation DAG without consuming Python call frames."""
    components = _strongly_connected_components(node_ids, outgoing)
    component_of = {node_id: index for index, component in enumerate(components) for node_id in component}
    component_outgoing: dict[int, set[int]] = {index: set() for index in range(len(components))}
    indegree = {index: 0 for index in range(len(components))}
    for source in sorted(node_ids):
        source_component = component_of[source]
        for target in sorted(outgoing[source]):
            target_component = component_of[target]
            if source_component != target_component and target_component not in component_outgoing[source_component]:
                component_outgoing[source_component].add(target_component)
                indegree[target_component] += 1
    component_rank = {index: 0 for index in range(len(components))}
    queue = deque(sorted((index for index, value in indegree.items() if value == 0), key=lambda index: components[index]))
    while queue:
        current = queue.popleft()
        for component_target in sorted(component_outgoing[current], key=lambda index: components[index]):
            component_rank[component_target] = max(component_rank[component_target], component_rank[current] + 1)
            indegree[component_target] -= 1
            if indegree[component_target] == 0:
                queue.append(component_target)
    return {node_id: component_rank[component_of[node_id]] for node_id in node_ids}


def _boxes_overlap(first: NodePlacement, second: NodePlacement, *, padding: float = 0.0) -> bool:
    return rectangles_overlap(first, second, padding=padding)


def _node_overlap_query(
    result: LayoutResult,
    *,
    max_pairs: int | None = DEFAULT_MAX_PAIRS,
    count_only: bool = False,
) -> RectanglePairQuery:
    return query_rectangle_pairs(result.nodes, max_pairs=max_pairs, count_only=count_only)


def _node_overlap_pairs(result: LayoutResult, *, max_pairs: int | None = DEFAULT_MAX_PAIRS) -> list[list[str]]:
    """Return a complete deterministic pair list or reject dense truncation."""
    query = _node_overlap_query(result, max_pairs=max_pairs)
    if not query.complete:
        raise ValueError(
            "node-overlap query exceeded pair budget; full geometry is incomplete "
            f"(lower_bound={query.lower_bound:,}, max_pairs={query.max_pairs:,})"
        )
    return query.pair_lists()


def _content_bbox(result: LayoutResult) -> tuple[float, float, float, float]:
    boxes = [
        (item.x, item.y, item.x + item.width, item.y + item.height)
        for item in result.nodes.values()
    ]
    boxes.extend(
        (item["x"], item["y"], item["x"] + item["width"], item["y"] + item["height"])
        for item in result.groups.values()
    )
    boxes.extend((x, y, x, y) for route in result.edges.values() for x, y in route.points)
    if not boxes:
        return 0.0, 0.0, 1.0, 1.0
    return (
        min(item[0] for item in boxes),
        min(item[1] for item in boxes),
        max(item[2] for item in boxes),
        max(item[3] for item in boxes),
    )


def _edge_semantic(edge: Edge, source: Node | None, target: Node | None) -> str:
    declared = str(edge.attributes.get("semantic", edge.kind or "data")).lower()
    if declared not in {"", "data"}:
        return declared
    source_text = f"{source.name} {source.op_type} {' '.join(source.tags)}".lower() if source else ""
    target_text = f"{target.name} {target.op_type} {' '.join(target.tags)}".lower() if target else ""
    combined = f"{source_text} {target_text}"
    if any(token in combined for token in ("router", "expert", "gating", "sparsecombine")):
        return "routing"
    if any(token in combined for token in ("attention", " q ", " k ", " v ", "qkv")):
        return "attention"
    if "skip" in combined or ("encoder" in source_text and "decoder" in target_text):
        return "skip"
    if any(token in combined for token in ("residual", "shortcut")):
        return "residual"
    if "scheduler" in source_text and any(token in target_text for token in ("denois", "unet")):
        return "diffusion-loop"
    if edge.kind in {"recurrent", "control"}:
        return edge.kind
    return "data"
