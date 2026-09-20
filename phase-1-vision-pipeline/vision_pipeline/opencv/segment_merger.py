"""Collinear segment merging (pure numpy, no cv2).

Hough/LSD return many short, overlapping, parallel fragments per physical line (a thick line
even yields two parallel edge lines). This module fuses fragments that are:

* nearly parallel                (``angle_tol_deg``)
* on (almost) the same line      (``perp_tol_px``)
* touching, overlapping or separated by a small gap (``gap_tol_px``) - or separated by a
  larger gap that is (almost) entirely inside a *bridge region* (masked text, e.g. a network
  label printed on top of the cable), up to ``max_bridge_px``.

The merged segment lies on the length-weighted principal axis of its members.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from ..geometry import Rect, Seg, dist


def merge_collinear(
    segments: Sequence[Seg],
    *,
    angle_tol_deg: float,
    perp_tol_px: float,
    gap_tol_px: float,
    bridge_rects: Sequence[Rect] = (),
    bridge_coverage: float = 0.8,
    max_bridge_px: float = 0.0,
    max_passes: int = 8,
) -> list[Seg]:
    segs = [
        ((float(a[0]), float(a[1])), (float(b[0]), float(b[1])))
        for a, b in segments
        if dist(a, b) > 0
    ]
    for _ in range(max_passes):
        n = len(segs)
        if n < 2:
            break
        compat = _compat_matrix(
            segs,
            math.radians(angle_tol_deg),
            perp_tol_px,
            gap_tol_px,
            bridge_rects,
            bridge_coverage,
            max_bridge_px,
        )
        groups = _components(compat)
        if len(groups) == n:
            break
        segs = [_fuse([segs[i] for i in g]) if len(g) > 1 else segs[g[0]] for g in groups]
    return segs


def _compat_matrix(
    segs: list[Seg],
    angle_tol: float,
    perp_tol: float,
    gap_tol: float,
    bridge_rects: Sequence[Rect],
    bridge_coverage: float,
    max_bridge: float,
) -> np.ndarray:
    P = np.array([s[0] for s in segs])
    Q = np.array([s[1] for s in segs])
    V = Q - P
    L = np.hypot(V[:, 0], V[:, 1])
    U = V / L[:, None]
    ang = np.arctan2(V[:, 1], V[:, 0]) % math.pi
    d_ang = np.abs(ang[:, None] - ang[None, :])
    d_ang = np.minimum(d_ang, math.pi - d_ang)

    def perp(
        pts: np.ndarray,
    ) -> np.ndarray:  # distance of pts[j] to the line of segment i -> (i, j)
        rel = pts[None, :, :] - P[:, None, :]
        return np.abs(rel[..., 0] * U[:, None, 1] - rel[..., 1] * U[:, None, 0])

    perp_ok = np.maximum.reduce([perp(P), perp(Q)])
    perp_sym = np.maximum(perp_ok, perp_ok.T)

    def along(pts: np.ndarray) -> np.ndarray:  # projection of pts[j] on segment i's axis
        rel = pts[None, :, :] - P[:, None, :]
        return rel[..., 0] * U[:, None, 0] + rel[..., 1] * U[:, None, 1]

    a, b = along(P), along(Q)
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    gap_i = np.maximum(0.0, np.maximum(lo - L[:, None], -hi))
    gap = np.maximum(gap_i, gap_i.T)

    base = (d_ang <= angle_tol) & (perp_sym <= perp_tol)
    np.fill_diagonal(base, False)
    ok = base & (gap <= gap_tol)

    if bridge_rects and max_bridge > gap_tol:
        cand = np.argwhere(np.triu(base & (gap > gap_tol) & (gap <= max_bridge), k=1))
        for i, j in cand:
            if _bridged(segs[i], segs[j], bridge_rects, bridge_coverage):
                ok[i, j] = ok[j, i] = True
    return ok


def _bridged(s: Seg, t: Seg, rects: Sequence[Rect], coverage: float) -> bool:
    """True when the shortest connection between two segments lies mostly inside ``rects``."""
    best = min(((dist(p, q), p, q) for p in s for q in t), key=lambda x: x[0])
    d, p, q = best
    if d <= 0:
        return True
    steps = max(2, int(d // 2))
    inside = 0
    for k in range(steps + 1):
        u = k / steps
        pt = (p[0] + u * (q[0] - p[0]), p[1] + u * (q[1] - p[1]))
        if any(r.contains_point(pt, tol=1.0) for r in rects):
            inside += 1
    return inside / (steps + 1) >= coverage


def _components(ok: np.ndarray) -> list[list[int]]:
    n = ok.shape[0]
    seen = [False] * n
    groups: list[list[int]] = []
    for s in range(n):
        if seen[s]:
            continue
        stack, comp = [s], []
        seen[s] = True
        while stack:
            i = stack.pop()
            comp.append(i)
            for j in np.flatnonzero(ok[i]):
                if not seen[j]:
                    seen[j] = True
                    stack.append(int(j))
        groups.append(sorted(comp))
    return groups


def _fuse(members: list[Seg]) -> Seg:
    """One segment on the length-weighted principal axis covering every member endpoint."""
    pts = np.array([p for s in members for p in s], dtype=float)
    w = np.repeat([dist(*s) for s in members], 2)
    mean = np.average(pts, axis=0, weights=w)
    cov = np.cov((pts - mean).T, aweights=w)
    vals, vecs = np.linalg.eigh(cov)
    d = vecs[:, int(np.argmax(vals))]
    t = (pts - mean) @ d
    p, q = mean + t.min() * d, mean + t.max() * d
    return ((float(p[0]), float(p[1])), (float(q[0]), float(q[1])))
