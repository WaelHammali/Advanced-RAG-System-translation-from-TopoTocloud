"""Pass 8 - network label -> link association.

A value such as ``192.168.1.0/24`` (host bits zero, prefix <= 30: mathematically a NETWORK,
never a host) is a candidate link/subnet attribute. Each (label, link) pair gets a weighted
score (weights in ``NetworkLabelScoring``):

* distance         label box to the cable path, in text heights
* alignment        (a) the label lies beside the cable body, not beyond one of its ends, and
                   (b) label text direction vs. cable direction (parallel labels score higher)
* midpoint         label centre to the cable's arc-length midpoint, relative to cable length
* device-relative  a label nearer to a device than to the cable is probably not a cable label
* ocr              OCR confidence

The winner per label comes from :func:`confidence.decide`. If two different labels claim
the same link with comparable confidence, NEITHER is applied (ambiguous).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ..config.thresholds import NetworkLabelScoring
from ..geometry import (
    angle_diff,
    clamp01,
    dist,
    polyline_midpoint,
    project_param,
    rect_polyline_distance,
    seg_angle,
    seg_length,
)
from ..ocr.address_normalizer import NormalizedAddress
from ..ocr.semantic_parser import ParsedText
from ..schemas.raw import LinkCandidate, YoloDetection
from .confidence import AMBIGUOUS, Decision, decide


@dataclass
class LabelMatch:
    label_id: str
    decision: Decision
    link_id: str | None = None  # set only when applied to a link
    confidence: float | None = None
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "label_id": self.label_id,
            "link_id": self.link_id,
            "status": self.decision.status,
            "confidence": None if self.confidence is None else round(self.confidence, 4),
            "flags": list(self.flags),
            "spatial": self.decision.to_dict(),
        }


@dataclass
class LinkNetwork:
    label_id: str
    address: NormalizedAddress  # network_address / prefix_length / subnet_mask
    confidence: float
    flags: list[str] = field(default_factory=list)


def link_midpoint(cand: LinkCandidate):
    if cand.polyline:
        return polyline_midpoint(cand.polyline)
    if cand.start is not None and cand.end is not None:
        return ((cand.start[0] + cand.end[0]) / 2, (cand.start[1] + cand.end[1]) / 2)
    pts = [((s[0][0] + s[1][0]) / 2, (s[0][1] + s[1][1]) / 2) for s in cand.segments]
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def score_label_link(
    label: ParsedText, cand: LinkCandidate, devices: list[YoloDetection], p: NetworkLabelScoring
) -> tuple[float, dict[str, float]] | None:
    if not cand.segments:
        return None
    th = label.text_height
    d_link, idx = rect_polyline_distance(label.bbox, cand.segments)
    limit = p.max_dist_in_text_heights * th
    if d_link > limit:
        return None
    s_dist = 1.0 - d_link / limit

    seg = cand.segments[idx]
    L = max(seg_length(seg), 1.0)
    t = project_param(label.center, seg)
    overshoot = max(0.0, -t, t - 1.0) * L
    s_extent = 1.0 - clamp01(overshoot / (0.25 * L))
    s_parallel = abs(math.cos(angle_diff(seg_angle(seg), label.axis_angle)))
    s_align = p.extent_share * s_extent + (1.0 - p.extent_share) * s_parallel

    total_len = max(sum(seg_length(s) for s in cand.segments), 1.0)
    s_mid = clamp01(1.0 - dist(label.center, link_midpoint(cand)) / (0.5 * total_len))

    if devices:
        d_dev = min(label.bbox.gap_to(d.bbox) for d in devices)
        rel = 0.5 if d_link + d_dev == 0 else d_link / (d_link + d_dev)
        s_dev = clamp01(1.0 - 2.0 * rel)
    else:
        s_dev = 1.0
    parts = {
        "distance": s_dist,
        "alignment": s_align,
        "midpoint": s_mid,
        "device_relative": s_dev,
        "ocr": clamp01(label.ocr_confidence),
    }
    total = (
        p.weight_distance * s_dist
        + p.weight_alignment * s_align
        + p.weight_midpoint * s_mid
        + p.weight_device_relative * s_dev
        + p.weight_ocr * parts["ocr"]
    )
    return clamp01(total), parts


def match_labels(
    labels: list[ParsedText],
    links: dict[str, LinkCandidate],
    devices: list[YoloDetection],
    p: NetworkLabelScoring,
) -> tuple[list[LabelMatch], dict[str, LinkNetwork]]:
    matches: list[LabelMatch] = []
    for lab in labels:
        scored = []
        for lid, cand in links.items():
            r = score_label_link(lab, cand, devices, p)
            if r is not None:
                scored.append((lid, r[0], r[1]))
        d = decide(scored, p.tier)
        flags = ["low_confidence"] if d.status == "flagged" else []
        matches.append(
            LabelMatch(lab.id, d, d.key if d.stored else None, d.score if d.stored else None, flags)
        )

    by_link: dict[str, list[LabelMatch]] = {}
    for m in matches:
        if m.link_id is not None:
            by_link.setdefault(m.link_id, []).append(m)
    label_of = {lab.id: lab for lab in labels}
    networks: dict[str, LinkNetwork] = {}
    for lid, ms in by_link.items():
        ms.sort(key=lambda m: (-(m.confidence or 0), m.label_id))
        values = {
            (
                label_of[m.label_id].address.network_address,
                label_of[m.label_id].address.prefix_length,
            )
            for m in ms
        }
        if len(values) > 1:
            for m in ms:  # conflicting labels on one link: apply none, keep the evidence
                m.decision = Decision(
                    AMBIGUOUS,
                    None,
                    m.decision.score,
                    best_key=lid,
                    best_score=m.decision.score,
                    breakdown=m.decision.breakdown,
                )
                m.link_id, m.confidence = None, None
                m.flags.append("conflicting_labels_on_same_link")
            continue
        top = ms[0]
        addr = label_of[top.label_id].address
        net = NormalizedAddress(
            network_address=addr.network_address,
            prefix_length=addr.prefix_length,
            subnet_mask=addr.subnet_mask,
            field_origin={
                "network_address": "ocr",
                "prefix_length": "ocr",
                "subnet_mask": "derived_from_prefix_length",
            },
        )
        networks[lid] = LinkNetwork(top.label_id, net, top.confidence or 0.0, list(top.flags))
    return matches, networks
