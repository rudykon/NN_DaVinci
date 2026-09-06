"""Deterministic, output-bounded two-dimensional rectangle queries.

The primary x sweep is paired with an AVL interval tree over y.  AVL balance
gives a deterministic logarithmic height bound; correctness and stack safety
do not depend on hash priorities or probabilistic treap shape.  Dense output
is explicitly bounded so callers cannot mistake a partial pair list for a
complete geometry result.
"""

from __future__ import annotations

from dataclasses import dataclass
import heapq
from typing import Iterable, Protocol


DEFAULT_MAX_PAIRS = 1_000_000


class Rectangle(Protocol):
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True, slots=True)
class RectanglePairQuery:
    pairs: tuple[tuple[str, str], ...]
    pair_count: int
    complete: bool
    truncated: bool
    lower_bound: int
    max_pairs: int | None
    algorithm: str = "x-sweep+y-avl-interval-v2"

    def pair_lists(self) -> list[list[str]]:
        return [list(pair) for pair in self.pairs]


@dataclass(slots=True)
class _IntervalNode:
    key: tuple[float, str]
    high: float
    rectangle_id: str
    maximum_high: float
    height: int = 1
    left: _IntervalNode | None = None
    right: _IntervalNode | None = None


def _maximum(node: _IntervalNode | None) -> float:
    return float("-inf") if node is None else node.maximum_high


def _refresh(node: _IntervalNode) -> _IntervalNode:
    node.maximum_high = max(node.high, _maximum(node.left), _maximum(node.right))
    node.height = 1 + max(0 if node.left is None else node.left.height, 0 if node.right is None else node.right.height)
    return node


def _balance_factor(node: _IntervalNode) -> int:
    return (0 if node.left is None else node.left.height) - (0 if node.right is None else node.right.height)


def _rotate_left(node: _IntervalNode) -> _IntervalNode:
    child = node.right
    assert child is not None
    node.right = child.left
    child.left = _refresh(node)
    return _refresh(child)


def _rotate_right(node: _IntervalNode) -> _IntervalNode:
    child = node.left
    assert child is not None
    node.left = child.right
    child.right = _refresh(node)
    return _refresh(child)


def _rebalance(node: _IntervalNode) -> _IntervalNode:
    _refresh(node)
    balance = _balance_factor(node)
    if balance > 1:
        assert node.left is not None
        if _balance_factor(node.left) < 0:
            node.left = _rotate_left(node.left)
        return _rotate_right(node)
    if balance < -1:
        assert node.right is not None
        if _balance_factor(node.right) > 0:
            node.right = _rotate_right(node.right)
        return _rotate_left(node)
    return node


def _insert(node: _IntervalNode | None, item: _IntervalNode) -> _IntervalNode:
    if node is None:
        return item
    if item.key < node.key:
        node.left = _insert(node.left, item)
    else:
        node.right = _insert(node.right, item)
    return _rebalance(node)


def _delete(node: _IntervalNode | None, key: tuple[float, str]) -> _IntervalNode | None:
    if node is None:
        return None
    if key < node.key:
        node.left = _delete(node.left, key)
    elif key > node.key:
        node.right = _delete(node.right, key)
    elif node.left is None:
        return node.right
    elif node.right is None:
        return node.left
    else:
        successor = node.right
        while successor.left is not None:
            successor = successor.left
        node.key = successor.key
        node.high = successor.high
        node.rectangle_id = successor.rectangle_id
        node.right = _delete(node.right, successor.key)
    return _rebalance(node)


def _query(node: _IntervalNode | None, low: float, high: float, matches: list[str]) -> None:
    """Iterative interval query; tree mutation remains AVL-height bounded."""
    stack = [] if node is None else [node]
    while stack:
        current = stack.pop()
        if current.maximum_high <= low:
            continue
        if current.right is not None and current.key[0] < high and current.right.maximum_high > low:
            stack.append(current.right)
        if current.key[0] < high and current.high > low:
            matches.append(current.rectangle_id)
        if current.left is not None and current.left.maximum_high > low:
            stack.append(current.left)


def rectangles_overlap(first: Rectangle, second: Rectangle, *, padding: float = 0.0) -> bool:
    """Match NN_DaVinci's strict-area overlap and boundary-touch semantics."""
    return (
        first.x < second.x + second.width + padding
        and first.x + first.width + padding > second.x
        and first.y < second.y + second.height + padding
        and first.y + first.height + padding > second.y
    )


def query_rectangle_pairs(
    rectangles: dict[str, Rectangle] | Iterable[tuple[str, Rectangle]],
    *,
    padding: float = 0.0,
    max_pairs: int | None = DEFAULT_MAX_PAIRS,
    count_only: bool = False,
) -> RectanglePairQuery:
    """Return exact pairs unless the explicit output budget is exceeded.

    When the query is truncated, ``lower_bound`` is at least
    ``max_pairs + 1`` and ``complete`` is false.  The retained pair tuple is
    deterministic and never presented as the full result.
    """
    if max_pairs is not None and max_pairs < 0:
        raise ValueError("max_pairs must be non-negative or None")
    items = list(rectangles.items() if isinstance(rectangles, dict) else rectangles)
    items.sort(key=lambda item: (item[1].x, item[0]))
    by_id = dict(items)
    root: _IntervalNode | None = None
    expiry: list[tuple[float, str]] = []
    active_keys: dict[str, tuple[float, str]] = {}
    pairs: list[tuple[str, str]] = []
    pair_count = 0
    for current_id, current in items:
        while expiry and expiry[0][0] <= current.x:
            _, expired_id = heapq.heappop(expiry)
            key = active_keys.pop(expired_id, None)
            if key is not None:
                root = _delete(root, key)
        candidates: list[str] = []
        _query(root, current.y - padding, current.y + current.height + padding, candidates)
        for other_id in sorted(candidates):
            if not rectangles_overlap(by_id[other_id], current, padding=padding):
                continue
            pair_count += 1
            if max_pairs is not None and pair_count > max_pairs:
                return RectanglePairQuery(
                    pairs=tuple(sorted(pairs)),
                    pair_count=len(pairs) if not count_only else 0,
                    complete=False,
                    truncated=True,
                    lower_bound=pair_count,
                    max_pairs=max_pairs,
                )
            if not count_only:
                pairs.append(tuple(sorted((other_id, current_id))))
        key = (current.y, current_id)
        root = _insert(
            root,
            _IntervalNode(key, current.y + current.height, current_id, current.y + current.height),
        )
        active_keys[current_id] = key
        heapq.heappush(expiry, (current.x + current.width, current_id))
    return RectanglePairQuery(
        pairs=tuple(sorted(pairs)),
        pair_count=pair_count,
        complete=True,
        truncated=False,
        lower_bound=pair_count,
        max_pairs=max_pairs,
    )


__all__ = [
    "DEFAULT_MAX_PAIRS",
    "RectanglePairQuery",
    "query_rectangle_pairs",
    "rectangles_overlap",
]
