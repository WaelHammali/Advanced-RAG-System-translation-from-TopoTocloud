"""Pure geometry helpers shared by every stage.

Nothing here knows about YOLO, OCR, links or networks. All coordinates are pixels in the
ORIGINAL image coordinate system, x to the right, y downwards.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

Point = tuple[float, float]
Seg = tuple[Point, Point]

EPS = 1e-9


def clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


@dataclass(frozen=True, slots=True)
class Rect:
    x1: float
    y1: float
    x2: float
    y2: float

    @classmethod
    def from_list(cls, box: Sequence[float]) -> Rect:
        if len(box) != 4:
            raise ValueError(f"bbox must have 4 numbers, got {box!r}")
        x1, y1, x2, y2 = (float(v) for v in box)
        return cls(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))

    @classmethod
    def from_points(cls, points: Iterable[Point]) -> Rect:
        pts = list(points)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return cls(min(xs), min(ys), max(xs), max(ys))

    def to_list(self) -> list[float]:
        return [round(self.x1, 2), round(self.y1, 2), round(self.x2, 2), round(self.y2, 2)]

    @property
    def w(self) -> float:
        return self.x2 - self.x1

    @property
    def h(self) -> float:
        return self.y2 - self.y1

    @property
    def center(self) -> Point:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)

    @property
    def size(self) -> float:
        """Characteristic size used to make distances scale-invariant."""
        return max(self.w, self.h, 1.0)

    def union(self, other: Rect) -> Rect:
        return Rect(
            min(self.x1, other.x1),
            min(self.y1, other.y1),
            max(self.x2, other.x2),
            max(self.y2, other.y2),
        )

    def expand(self, margin: float) -> Rect:
        return Rect(self.x1 - margin, self.y1 - margin, self.x2 + margin, self.y2 + margin)

    def shrink_ratio(self, ratio: float, min_border: float = 0.0) -> Rect | None:
        """Shrink each side by ``ratio`` of the corresponding extent (at least ``min_border``).

        Returns ``None`` when nothing is left.
        """
        dx = max(self.w * ratio, min_border)
        dy = max(self.h * ratio, min_border)
        r = Rect(self.x1 + dx, self.y1 + dy, self.x2 - dx, self.y2 - dy)
        return r if r.w > 0 and r.h > 0 else None

    def contains_point(self, p: Point, tol: float = 0.0) -> bool:
        return (self.x1 - tol <= p[0] <= self.x2 + tol) and (self.y1 - tol <= p[1] <= self.y2 + tol)

    def contains_rect(self, other: Rect, tol: float = 0.0) -> bool:
        return (
            other.x1 >= self.x1 - tol
            and other.y1 >= self.y1 - tol
            and other.x2 <= self.x2 + tol
            and other.y2 <= self.y2 + tol
        )

    def clip(self, width: float, height: float) -> Rect:
        return Rect(max(0.0, self.x1), max(0.0, self.y1), min(width, self.x2), min(height, self.y2))

    def gap_to(self, other: Rect) -> float:
        """Euclidean gap between two rectangles (0 when they touch or overlap)."""
        dx = max(0.0, other.x1 - self.x2, self.x1 - other.x2)
        dy = max(0.0, other.y1 - self.y2, self.y1 - other.y2)
        return math.hypot(dx, dy)

    def separations(self, other: Rect) -> tuple[float, float]:
        """Axis separations (dx, dy), each 0 if the projections overlap."""
        dx = max(0.0, other.x1 - self.x2, self.x1 - other.x2)
        dy = max(0.0, other.y1 - self.y2, self.y1 - other.y2)
        return dx, dy

    def point_distance(self, p: Point) -> float:
        dx = max(self.x1 - p[0], 0.0, p[0] - self.x2)
        dy = max(self.y1 - p[1], 0.0, p[1] - self.y2)
        return math.hypot(dx, dy)


# ----------------------------------------------------------------------------- vectors


def dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def seg_length(s: Seg) -> float:
    return dist(s[0], s[1])


def seg_angle(s: Seg) -> float:
    """Undirected angle in [0, pi)."""
    a = math.atan2(s[1][1] - s[0][1], s[1][0] - s[0][0])
    return a % math.pi


def angle_diff(a: float, b: float) -> float:
    """Smallest difference between two undirected angles (radians, result in [0, pi/2])."""
    d = abs(a - b) % math.pi
    return min(d, math.pi - d)


def unit(a: Point, b: Point) -> Point:
    d = dist(a, b)
    if d < EPS:
        return (0.0, 0.0)
    return ((b[0] - a[0]) / d, (b[1] - a[1]) / d)


def project_param(p: Point, s: Seg) -> float:
    """Unclamped parameter of p's projection on segment s (0 at s[0], 1 at s[1])."""
    vx, vy = s[1][0] - s[0][0], s[1][1] - s[0][1]
    L2 = vx * vx + vy * vy
    if L2 < EPS:
        return 0.0
    return ((p[0] - s[0][0]) * vx + (p[1] - s[0][1]) * vy) / L2


def point_seg_distance(p: Point, s: Seg) -> float:
    t = min(1.0, max(0.0, project_param(p, s)))
    q = (s[0][0] + t * (s[1][0] - s[0][0]), s[0][1] + t * (s[1][1] - s[0][1]))
    return dist(p, q)


def point_line_distance(p: Point, s: Seg) -> float:
    """Perpendicular distance from p to the infinite line through s."""
    vx, vy = s[1][0] - s[0][0], s[1][1] - s[0][1]
    L = math.hypot(vx, vy)
    if L < EPS:
        return dist(p, s[0])
    return abs((p[0] - s[0][0]) * vy - (p[1] - s[0][1]) * vx) / L


def _ccw(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def segments_intersect(s: Seg, t: Seg) -> bool:
    d1, d2 = _ccw(t[0], t[1], s[0]), _ccw(t[0], t[1], s[1])
    d3, d4 = _ccw(s[0], s[1], t[0]), _ccw(s[0], s[1], t[1])
    return (d1 * d2 < 0) and (d3 * d4 < 0)


def clip_segment_to_rect(s: Seg, r: Rect) -> Seg | None:
    """Liang-Barsky. Returns the part of ``s`` inside ``r`` or ``None``."""
    x0, y0 = s[0]
    dx, dy = s[1][0] - x0, s[1][1] - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - r.x1), (dx, r.x2 - x0), (-dy, y0 - r.y1), (dy, r.y2 - y0)):
        if abs(p) < EPS:
            if q < 0:
                return None
            continue
        t = q / p
        if p < 0:
            if t > t1:
                return None
            t0 = max(t0, t)
        else:
            if t < t0:
                return None
            t1 = min(t1, t)
    return ((x0 + t0 * dx, y0 + t0 * dy), (x0 + t1 * dx, y0 + t1 * dy))


def seg_rect_distance(s: Seg, r: Rect) -> float:
    """Minimum distance between a segment and a rectangle (0 when they intersect)."""
    if clip_segment_to_rect(s, r) is not None:
        return 0.0
    corners = [(r.x1, r.y1), (r.x2, r.y1), (r.x2, r.y2), (r.x1, r.y2)]
    best = min(r.point_distance(s[0]), r.point_distance(s[1]))
    for c in corners:
        best = min(best, point_seg_distance(c, s))
    return best


def ray_rect_entry(origin: Point, direction: Point, r: Rect) -> float | None:
    """Distance along a ray until it first enters ``r``; 0 if origin is inside; None if it misses."""
    if r.contains_point(origin):
        return 0.0
    dx, dy = direction
    if abs(dx) < EPS and abs(dy) < EPS:
        return None
    tmin, tmax = 0.0, float("inf")
    for o, d, lo, hi in ((origin[0], dx, r.x1, r.x2), (origin[1], dy, r.y1, r.y2)):
        if abs(d) < EPS:
            if o < lo or o > hi:
                return None
            continue
        t1, t2 = (lo - o) / d, (hi - o) / d
        if t1 > t2:
            t1, t2 = t2, t1
        tmin, tmax = max(tmin, t1), min(tmax, t2)
        if tmin > tmax:
            return None
    return tmin if tmax >= 0 else None


# -------------------------------------------------------------------------- polylines


def polyline_segments(poly: Sequence[Point]) -> list[Seg]:
    return [(tuple(poly[i]), tuple(poly[i + 1])) for i in range(len(poly) - 1)]  # type: ignore[misc]


def polyline_length(poly: Sequence[Point]) -> float:
    return sum(seg_length(s) for s in polyline_segments(poly))


def polyline_midpoint(poly: Sequence[Point]) -> Point:
    """Point at half the arc length."""
    segs = polyline_segments(poly)
    total = sum(seg_length(s) for s in segs)
    if not segs or total < EPS:
        return tuple(poly[0]) if poly else (0.0, 0.0)  # type: ignore[return-value]
    half, acc = total / 2.0, 0.0
    for s in segs:
        L = seg_length(s)
        if acc + L >= half:
            t = (half - acc) / L if L > EPS else 0.0
            return (s[0][0] + t * (s[1][0] - s[0][0]), s[0][1] + t * (s[1][1] - s[0][1]))
        acc += L
    return tuple(poly[-1])  # type: ignore[return-value]


def rect_polyline_distance(r: Rect, segs: Sequence[Seg]) -> tuple[float, int]:
    """(minimum distance, index of the nearest segment). ``(inf, -1)`` for no segments."""
    best, idx = float("inf"), -1
    for i, s in enumerate(segs):
        d = seg_rect_distance(s, r)
        if d < best:
            best, idx = d, i
    return best, idx


def reading_order_key(
    items: Sequence[tuple[str, Rect]], band_ratio: float = 0.5, min_band_px: float = 8.0
) -> list[str]:
    """Deterministic top-to-bottom, left-to-right ordering with row banding.

    Items whose vertical centres are within ``max(band_ratio x median height, min_band_px)``
    of each other are one row, so small vertical jitter never reorders a visual row (the
    floor matters for near-zero-height items such as horizontal cables).
    """
    if not items:
        return []
    heights = sorted(r.h for _, r in items)
    band = max(min_band_px, heights[len(heights) // 2] * band_ratio)
    ordered = sorted(items, key=lambda it: (it[1].center[1], it[1].center[0], it[0]))
    rows: list[list[tuple[str, Rect]]] = []
    for it in ordered:
        if rows and abs(it[1].center[1] - rows[-1][0][1].center[1]) <= band:
            rows[-1].append(it)
        else:
            rows.append([it])
    out: list[str] = []
    for row in rows:
        out.extend(k for k, _ in sorted(row, key=lambda it: (it[1].center[0], it[0])))
    return out
