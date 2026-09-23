"""Reconstruct logical cable paths from merged segments (pure geometry, no cv2).

Cables drawn with bends are several segments. This module joins them into paths:

* segment endpoints closer than ``join_dist`` are one junction (unless both lie inside the
  same *barrier* region, e.g. the same device - so cables that all dock on one switch stay
  separate cables);
* an endpoint that lands on the *body* of another segment (T-junction) splits that segment.

Each connected component becomes a :class:`PathCandidate`:

``chain``     exactly two open ends           -> ``start`` / ``end`` are set
``single``    one segment                     -> ``start`` / ``end`` are set
``branched``  a junction with 3+ segments     -> ``start`` / ``end`` are ``None``
``cycle``     no open ends                    -> ``start`` / ``end`` are ``None``

Endpoints that cannot be determined are ``None``; they are never made up.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from ..geometry import Point, Rect, Seg, dist, point_seg_distance, project_param, seg_length


@dataclass
class PathCandidate:
    segments: list[Seg]
    polyline: list[Point]
    path_type: str
    start: Point | None
    end: Point | None
    endpoints: list[Point] = field(default_factory=list)
    #: a component that would otherwise be "branched" was recovered as a clean chain by
    #: dropping this many short leaf spurs (icon-detail noise, e.g. an arrow drawn on a device
    #: that YOLO missed) - only ever done when it fully resolves the branching, never partially
    pruned_spur_count: int = 0
    pruned_length_px: float = 0.0

    @property
    def length(self) -> float:
        return sum(seg_length(s) for s in self.segments)


class _DSU:
    def __init__(self, n: int = 0) -> None:
        self.p = list(range(n))

    def add(self) -> int:
        self.p.append(len(self.p))
        return len(self.p) - 1

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def reconstruct_paths(
    segments: Sequence[Seg],
    *,
    join_dist: float,
    barriers: Sequence[Rect] = (),
    min_path_length: float = 0.0,
    max_spur_px: float = 0.0,
) -> tuple[list[PathCandidate], int]:
    """Returns ``(paths, number_of_paths_dropped_for_being_too_short)``."""
    segs = [s for s in segments if seg_length(s) > 0]
    if not segs:
        return [], 0

    # ---- 1. T-junction splitting: which unjoined endpoints land on another segment's body
    ends = [(i, k, s[k]) for i, s in enumerate(segs) for k in (0, 1)]
    joined = [False] * len(ends)
    for a in range(len(ends)):
        for b in range(a + 1, len(ends)):
            if ends[a][0] != ends[b][0] and dist(ends[a][2], ends[b][2]) <= join_dist:
                joined[a] = joined[b] = True
    splits: dict[int, list[tuple[float, Point, int]]] = {}  # seg -> [(t, point, end_index)]
    for e, (i, _, p) in enumerate(ends):
        if joined[e] or _in_any(p, barriers):
            continue
        best: tuple[float, int, float] | None = None
        for j, s in enumerate(segs):
            if j == i:
                continue
            d = point_seg_distance(p, s)
            t = project_param(p, s)
            L = seg_length(s)
            if (
                d <= join_dist and join_dist / L < t < 1 - join_dist / L
            ):  # interior, not near an end
                if best is None or d < best[0]:
                    best = (d, j, t)
        if best is not None:
            _, j, t = best
            s = segs[j]
            splits.setdefault(j, []).append(
                (t, (s[0][0] + t * (s[1][0] - s[0][0]), s[0][1] + t * (s[1][1] - s[0][1])), e)
            )

    # ---- 2. pieces + terminals
    dsu = _DSU()
    terminals: list[Point] = []  # terminal index -> point
    pieces: list[tuple[int, int]] = []  # (terminal_a, terminal_b)

    def new_terminal(p: Point) -> int:
        terminals.append(p)
        return dsu.add()

    end_terminal: dict[int, int] = {}  # end index -> terminal index
    t_unions: list[tuple[int, int]] = []  # (split-node terminal, T-ing end index)
    for i, s in enumerate(segs):
        cuts = sorted(splits.get(i, []), key=lambda c: c[0])
        pts = [s[0]] + [c[1] for c in cuts] + [s[1]]
        first = len(pieces)
        prev_b: int | None = None
        for k in range(len(pts) - 1):
            ta, tb = new_terminal(pts[k]), new_terminal(pts[k + 1])
            if prev_b is not None:
                dsu.union(prev_b, ta)  # the two pieces meeting at a split point share a node
            pieces.append((ta, tb))
            prev_b = tb
        end_terminal[2 * i], end_terminal[2 * i + 1] = pieces[first][0], pieces[-1][1]
        t_unions.extend((pieces[first + n][1], c[2]) for n, c in enumerate(cuts))
    for split_terminal, e in t_unions:  # a T-ing endpoint joins the node it landed on
        dsu.union(split_terminal, end_terminal[e])

    # ---- 3. proximity joins between original endpoints
    term_list = [(ends[e][0], end_terminal[e]) for e in range(len(ends))]
    for a in range(len(term_list)):
        for b in range(a + 1, len(term_list)):
            (sa, ta), (sb, tb) = term_list[a], term_list[b]
            if sa == sb:
                continue
            pa, pb = terminals[ta], terminals[tb]
            if dist(pa, pb) <= join_dist and not _same_barrier(pa, pb, barriers):
                dsu.union(ta, tb)

    # ---- 4. components of pieces
    node_of = [dsu.find(t) for t in range(len(terminals))]
    node_pts: dict[int, list[Point]] = {}
    for t, n in enumerate(node_of):
        node_pts.setdefault(n, []).append(terminals[t])
    node_pos = {
        n: (sum(p[0] for p in ps) / len(ps), sum(p[1] for p in ps) / len(ps))
        for n, ps in node_pts.items()
    }
    adj: dict[int, list[int]] = {}  # node -> piece indices
    for pi, (ta, tb) in enumerate(pieces):
        adj.setdefault(node_of[ta], []).append(pi)
        adj.setdefault(node_of[tb], []).append(pi)

    seen = [False] * len(pieces)
    out: list[PathCandidate] = []
    dropped = 0
    for start_piece in range(len(pieces)):
        if seen[start_piece]:
            continue
        comp, stack = [], [start_piece]
        seen[start_piece] = True
        while stack:
            pi = stack.pop()
            comp.append(pi)
            for t in pieces[pi]:
                for nb in adj[node_of[t]]:
                    if not seen[nb]:
                        seen[nb] = True
                        stack.append(nb)
        cand = _build_candidate(sorted(comp), pieces, node_of, node_pos, adj, max_spur_px)
        if cand.length < min_path_length:
            dropped += 1
        else:
            out.append(cand)
    return out, dropped


def _degrees(
    members: set[int], pieces: list[tuple[int, int]], node_of: list[int]
) -> dict[int, int]:
    deg: dict[int, int] = {}
    for pi in members:
        a, b = node_of[pieces[pi][0]], node_of[pieces[pi][1]]
        deg[a] = deg.get(a, 0) + 1
        deg[b] = deg.get(b, 0) + 1
    return deg


def _prune_short_spurs(
    comp: list[int],
    pieces: list[tuple[int, int]],
    node_of: list[int],
    node_pos: dict[int, Point],
    max_spur_px: float,
) -> tuple[list[int], int, float] | None:
    """If dropping one or more short leaf pieces (icon-detail noise - e.g. an arrow drawn on a
    device YOLO missed, or a decorative shape crossing the cable) fully resolves a branched
    component into a clean 2-leaf chain, return the reduced membership plus how much was
    removed. Returns ``None`` if pruning does not FULLY resolve the branching - a partial,
    still-ambiguous result is never returned; nothing is guessed."""
    if max_spur_px <= 0:
        return None
    members = set(comp)
    removed_count, removed_len = 0, 0.0
    while True:
        deg = _degrees(members, pieces, node_of)
        # keep going while an actual branch point (degree >= 3) remains to resolve - a lone
        # leaf on an otherwise-cyclic component (e.g. a spur off a loop) must still be tried
        if len(members) < 2 or not any(d >= 3 for d in deg.values()):
            break
        shortest: tuple[int, float] | None = None
        for pi in members:
            a, b = node_of[pieces[pi][0]], node_of[pieces[pi][1]]
            if deg.get(a) == 1 or deg.get(b) == 1:
                length = dist(node_pos[a], node_pos[b])
                if length <= max_spur_px and (shortest is None or length < shortest[1]):
                    shortest = (pi, length)
        if shortest is None:
            break
        pi, length = shortest
        members.discard(pi)
        removed_count += 1
        removed_len += length
    if removed_count == 0 or not members:
        return None
    deg = _degrees(members, pieces, node_of)
    if sum(1 for d in deg.values() if d == 1) == 2 and all(d <= 2 for d in deg.values()):
        return sorted(members), removed_count, removed_len
    return None  # still branched (or collapsed to a cycle) after pruning - leave it alone


def _build_candidate(
    comp: list[int],
    pieces: list[tuple[int, int]],
    node_of: list[int],
    node_pos: dict[int, Point],
    adj: dict[int, list[int]],
    max_spur_px: float = 0.0,
) -> PathCandidate:
    pruned_count, pruned_len = 0, 0.0
    deg = _degrees(set(comp), pieces, node_of)
    if any(d >= 3 for d in deg.values()):
        recovered = _prune_short_spurs(comp, pieces, node_of, node_pos, max_spur_px)
        if recovered is not None:
            comp, pruned_count, pruned_len = recovered
            deg = _degrees(set(comp), pieces, node_of)

    members = set(comp)
    edges = [(node_of[pieces[pi][0]], node_of[pieces[pi][1]]) for pi in comp]
    segs = [(node_pos[a], node_pos[b]) for a, b in edges]
    nodes = set(deg)
    leaves = sorted(
        (n for n in nodes if deg[n] == 1), key=lambda n: (node_pos[n][0], node_pos[n][1])
    )
    if any(d >= 3 for d in deg.values()):
        return PathCandidate(segs, [], "branched", None, None, [node_pos[n] for n in leaves])
    if len(leaves) != 2:
        return PathCandidate(segs, [], "cycle", None, None, [node_pos[n] for n in leaves])

    # walk the chain from the first leaf
    order = [leaves[0]]
    used: set[int] = set()
    cur = leaves[0]
    while True:
        nxt = None
        for pi in adj[cur]:
            if pi in members and pi not in used:
                used.add(pi)
                a, b = node_of[pieces[pi][0]], node_of[pieces[pi][1]]
                nxt = b if a == cur else a
                break
        if nxt is None:
            break
        order.append(nxt)
        cur = nxt
    poly = [node_pos[n] for n in order]
    ptype = "single" if len(comp) == 1 else "chain"
    return PathCandidate(
        list(zip(poly[:-1], poly[1:])),
        poly,
        ptype,
        poly[0],
        poly[-1],
        [poly[0], poly[-1]],
        pruned_spur_count=pruned_count,
        pruned_length_px=pruned_len,
    )


def _in_any(p: Point, rects: Sequence[Rect]) -> bool:
    return any(r.contains_point(p) for r in rects)


def _same_barrier(a: Point, b: Point, rects: Sequence[Rect]) -> bool:
    return any(r.contains_point(a) and r.contains_point(b) for r in rects)
