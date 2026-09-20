"""Text -> device spatial scoring (used by passes 4, 5 and 6).

This is deliberately not "nearest neighbour". A candidate (text rectangle, device) gets a
weighted score in [0, 1] from six independent factors (weights: ``TextDeviceScoring``):

* gap        bbox-to-bbox gap, normalised by the device size (0 gap = 1.0; gap beyond
             ``max_gap_factor`` x size disqualifies the candidate)
* center     centre-to-centre distance, normalised by the device size
* location   where the text sits relative to the device (below/above/right/left/inside/diagonal)
* alignment  how well the text is centred on the device along the axis perpendicular to
             its side (a label under an icon is centred on it)
* ocr        OCR confidence of the text
* yolo       YOLO confidence of the device

Distances are divided by the device size, so scores do not depend on image resolution.
The winner is chosen by :func:`confidence.decide`, which refuses ambiguous cases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config.thresholds import TextDeviceScoring, TierThresholds
from ..geometry import Rect, clamp01
from ..schemas.raw import YoloDetection
from .confidence import ACCEPTED, FLAGGED, STORED, UNRESOLVED, Decision, decide, tier_of


@dataclass
class Association:
    """One text/group -> device association, kept for traceability."""

    kind: str  # "device_name" | "address" | "host_suffix" | "group_placement"
    subject_id: str  # text id (or group id)
    decision: Decision  # the raw spatial decision
    #: final status after the combined confidence was tier-checked
    status: str
    device_id: str | None  # set only when the association is stored
    via_group: str | None = None
    #: final confidence of the association (spatial score combined with semantic / group confidence)
    confidence: float | None = None
    flags: list[str] = field(default_factory=list)

    @property
    def stored(self) -> bool:
        return self.status in STORED

    @classmethod
    def build(
        cls,
        kind: str,
        subject_id: str,
        decision: Decision,
        confidence: float | None,
        tier: TierThresholds,
        via_group: str | None = None,
    ) -> Association:
        """Store the association only if the spatial decision AND the combined confidence allow it."""
        status, flags = decision.status, []
        if decision.stored:
            final = tier_of(confidence, tier)
            if final == UNRESOLVED:
                status = UNRESOLVED
            else:
                status = FLAGGED if FLAGGED in (final, decision.status) else ACCEPTED
        if status == FLAGGED:
            flags.append("low_confidence")
        stored = status in STORED
        return cls(
            kind,
            subject_id,
            decision,
            status,
            decision.key if stored else None,
            via_group,
            confidence if stored else None,
            flags,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "subject_id": self.subject_id,
            "device_id": self.device_id,
            "status": self.status,
            "confidence": None if self.confidence is None else round(self.confidence, 4),
            "via_group": self.via_group,
            "flags": list(self.flags),
            "spatial": self.decision.to_dict(),
        }


def relative_location(text: Rect, dev: Rect) -> str:
    dx, dy = text.separations(dev)
    if dx == 0 and dy == 0:
        return "inside"
    if dx > 0 and dy > 0:
        return "diagonal"
    if dy > 0:
        return "below" if text.center[1] > dev.center[1] else "above"
    return "right" if text.center[0] > dev.center[0] else "left"


def score_text_device(
    text: Rect, ocr_conf: float, dev: YoloDetection, p: TextDeviceScoring
) -> tuple[float, dict[str, float]] | None:
    """``None`` when the text is too far from the device to be a candidate at all."""
    size = dev.bbox.size
    limit = p.max_gap_factor * size
    gap = text.gap_to(dev.bbox)
    if gap > limit:
        return None
    s_gap = 1.0 - gap / limit
    (tx, ty), (dx_, dy_) = text.center, dev.bbox.center
    s_center = clamp01(1.0 - ((tx - dx_) ** 2 + (ty - dy_) ** 2) ** 0.5 / (p.center_factor * size))
    loc = relative_location(text, dev.bbox)
    s_loc = p.location_preference.get(loc, 0.0)
    if loc in ("above", "below", "inside"):
        s_align = clamp01(1.0 - abs(tx - dx_) / (dev.bbox.w / 2 + text.w / 2))
    elif loc in ("left", "right"):
        s_align = clamp01(1.0 - abs(ty - dy_) / (dev.bbox.h / 2 + text.h / 2))
    else:
        s_align = 0.0
    parts = {
        "gap": s_gap,
        "center": s_center,
        "location": s_loc,
        "alignment": s_align,
        "ocr": clamp01(ocr_conf),
        "yolo": clamp01(dev.confidence),
    }
    total = (
        p.weight_gap * s_gap
        + p.weight_center * s_center
        + p.weight_location * s_loc
        + p.weight_alignment * s_align
        + p.weight_ocr * parts["ocr"]
        + p.weight_yolo * parts["yolo"]
    )
    return clamp01(total), parts


def match_text_to_device(
    text: Rect, ocr_conf: float, devices: list[YoloDetection], p: TextDeviceScoring
) -> Decision:
    scored = []
    for d in devices:
        r = score_text_device(text, ocr_conf, d, p)
        if r is not None:
            scored.append((d.id, r[0], r[1]))
    return decide(scored, p.tier)
