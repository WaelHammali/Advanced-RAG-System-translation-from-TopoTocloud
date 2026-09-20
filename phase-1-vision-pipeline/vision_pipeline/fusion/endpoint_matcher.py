"""Pass 7 - cable endpoint -> device association.

For each endpoint of a link candidate and each device, a weighted score (weights in
``EndpointScoring``) combines:

* proximity     point-to-bbox distance, normalised by the device size (0 = touching/inside)
* direction     does the cable, extended past its endpoint along its final direction, run into
                the device within ``ray_factor`` x device size? (geometric continuity: a cable
                that stops slightly short still "points at" its device, one that passes beside
                a neighbouring device does not)
* intersection  does the cable's terminal segment actually enter the device bbox?
* yolo          YOLO confidence of the device

Devices further than ``max_gap_factor`` x size are not candidates. The winner is picked by
:func:`confidence.decide` (ambiguous -> refuse). An endpoint that is ``None`` in the raw
OpenCV output is never matched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config.thresholds import EndpointScoring
from ..geometry import Point, Seg, clamp01, clip_segment_to_rect, dist, ray_rect_entry, unit
from ..schemas.raw import LinkCandidate, YoloDetection
from .confidence import Decision, decide


@dataclass
class EndpointMatch:
    end: str  # "start" | "end"
    point: Point | None
    decision: Decision | None  # None when the endpoint itself is unknown
    device_id: str | None
    confidence: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "end": self.end,
            "point": None
            if self.point is None
            else [round(self.point[0], 2), round(self.point[1], 2)],
            "device_id": self.device_id,
            "confidence": None if self.confidence is None else round(self.confidence, 4),
            "status": self.decision.status if self.decision else "endpoint_unknown",
            "spatial": self.decision.to_dict() if self.decision else None,
        }


def terminal_segment(cand: LinkCandidate, point: Point) -> tuple[Seg, Point] | None:
    """(segment, outward unit direction) of the segment end nearest to ``point``."""
    best: tuple[float, Seg, Point] | None = None
    for s in cand.segments:
        for own, other in ((s[0], s[1]), (s[1], s[0])):
            d = dist(own, point)
            if best is None or d < best[0]:
                best = (d, (other, own), unit(other, own))
    return None if best is None else (best[1], best[2])


def score_endpoint(
    point: Point, direction: Point, seg: Seg, dev: YoloDetection, p: EndpointScoring
) -> tuple[float, dict[str, float]] | None:
    size = dev.bbox.size
    limit = p.max_gap_factor * size
    d = dev.bbox.point_distance(point)
    if d > limit:
        return None
    s_prox = 1.0 - d / limit
    t = ray_rect_entry(point, direction, dev.bbox)
    s_dir = 0.0 if t is None else clamp01(1.0 - t / (p.ray_factor * size))
    s_int = 1.0 if clip_segment_to_rect(seg, dev.bbox) is not None else 0.0
    parts = {
        "proximity": s_prox,
        "direction": s_dir,
        "intersection": s_int,
        "yolo": clamp01(dev.confidence),
    }
    total = (
        p.weight_proximity * s_prox
        + p.weight_direction * s_dir
        + p.weight_intersection * s_int
        + p.weight_yolo * parts["yolo"]
    )
    return clamp01(total), parts


def match_endpoint(
    cand: LinkCandidate, which: str, devices: list[YoloDetection], p: EndpointScoring
) -> EndpointMatch:
    point = cand.start if which == "start" else cand.end
    if point is None:
        return EndpointMatch(which, None, None, None, None)
    term = terminal_segment(cand, point)
    scored = []
    if term is not None:
        seg, direction = term
        for dev in devices:
            r = score_endpoint(point, direction, seg, dev, p)
            if r is not None:
                scored.append((dev.id, r[0], r[1]))
    decision = decide(scored, p.tier)
    return EndpointMatch(
        which,
        point,
        decision,
        decision.key if decision.stored else None,
        decision.score if decision.stored else None,
    )
