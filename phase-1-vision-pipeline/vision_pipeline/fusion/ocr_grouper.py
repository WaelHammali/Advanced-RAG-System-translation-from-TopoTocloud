"""Pass 3 - OCR grouping.

Nearby texts that form one device label ("R1" / "192.168.1.1" / "255.255.255.0") are
grouped BEFORE any device association, so a name and its address are judged together.

Groupable texts are those with a slot: ``device_name``, ``ip`` (ipv4 / host-form CIDR) and
``subnet_mask``. Host suffixes, unknown texts and network-form CIDR labels (a value such as
``192.168.1.0/24`` is a network, never a host, so it cannot belong to a device label) are
never grouped.

Pair score = weighted sum of (all weights in ``GroupingThresholds``)

* distance     1 - gap / (max_gap_in_text_heights x text height)
* alignment    stacked texts: best of centre/left/right offset; same-line texts: vertical offset
* reading order  name -> ip -> mask, top-to-bottom / left-to-right (else ``unusual_order_score``)
* semantic compatibility of the two slots

A pair merges only if its score >= ``link_threshold``, the merged group stays legal (one
name, one ip, one mask; a CIDR excludes a separate mask), and no competing partner of the
same kind scores within ``ambiguity_margin`` - in which case both stay independent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config.thresholds import GroupingThresholds
from ..geometry import Rect, clamp01, reading_order_key
from ..ocr.semantic_parser import ParsedText

_RANK = {"device_name": 0, "ip": 1, "subnet_mask": 2}


@dataclass
class TextGroup:
    id: str
    members: list[ParsedText]
    confidence: float
    edges: list[dict[str, Any]] = field(default_factory=list)

    @property
    def bbox(self) -> Rect:
        box = self.members[0].bbox
        for m in self.members[1:]:
            box = box.union(m.bbox)
        return box

    @property
    def ocr_confidence(self) -> float:
        return sum(m.ocr_confidence for m in self.members) / len(self.members)

    def by_slot(self, slot: str) -> ParsedText | None:
        return next((m for m in self.members if m.slot == slot), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "member_ids": [m.id for m in self.members],
            "slots": {m.id: m.slot for m in self.members},
            "bbox": self.bbox.to_list(),
            "grouping_confidence": round(self.confidence, 4),
            "edges": self.edges,
        }


def _before(a: ParsedText, b: ParsedText, ref: float) -> bool:
    ay, by = a.center[1], b.center[1]
    if abs(ay - by) > 0.5 * ref:
        return ay < by
    return a.center[0] <= b.center[0]


def pair_score(
    a: ParsedText, b: ParsedText, cfg: GroupingThresholds
) -> tuple[float, dict[str, float]] | None:
    if a.slot is None or b.slot is None:
        return None
    compat = cfg.semantic_compat.get("|".join(sorted((a.slot, b.slot))), 0.0)
    if compat <= 0:
        return None
    ref = (a.text_height + b.text_height) / 2.0
    gap = a.bbox.gap_to(b.bbox)
    limit = cfg.max_gap_in_text_heights * ref
    if gap > limit:
        return None
    s_dist = 1.0 - gap / limit

    dx, dy = a.bbox.separations(b.bbox)
    if dy >= dx:  # stacked vertically
        offset = min(
            abs(a.center[0] - b.center[0]), abs(a.bbox.x1 - b.bbox.x1), abs(a.bbox.x2 - b.bbox.x2)
        )
        span = max(a.bbox.w, b.bbox.w)
    else:  # side by side on one line
        offset = abs(a.center[1] - b.center[1])
        span = max(a.bbox.h, b.bbox.h)
    s_align = clamp01(1.0 - offset / max(cfg.alignment_tolerance * span, 1.0))

    first, second = (a, b) if _RANK[a.slot] <= _RANK[b.slot] else (b, a)
    s_order = 1.0 if _before(first, second, ref) else cfg.unusual_order_score

    score = (
        cfg.weight_distance * s_dist
        + cfg.weight_alignment * s_align
        + cfg.weight_order * s_order
        + cfg.weight_semantic * compat
    )
    parts = {"distance": s_dist, "alignment": s_align, "reading_order": s_order, "semantic": compat}
    return score, parts


def _legal(members: list[ParsedText]) -> bool:
    slots = [m.slot for m in members]
    if len(slots) != len(set(slots)):
        return False
    has_cidr = any(m.semantic_type == "ipv4_cidr" for m in members)
    return not (has_cidr and "subnet_mask" in slots)


def group_texts(parsed: list[ParsedText], cfg: GroupingThresholds) -> list[TextGroup]:
    """Multi-member groups only; texts not in any returned group are independent."""
    items = [p for p in parsed if p.slot is not None and not p.is_network_form]
    edges = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            r = pair_score(items[i], items[j], cfg)
            if r and r[0] >= cfg.link_threshold:
                edges.append((r[0], items[i], items[j], r[1]))
    edges.sort(key=lambda e: (-e[0], e[1].id, e[2].id))

    def competitor(score: float, a: ParsedText, b: ParsedText) -> bool:
        """Does another edge, sharing one end with (a, b), offer a same-kind partner that
        scores within the ambiguity margin?"""
        for s2, x, y, _ in edges:
            if s2 < score - cfg.ambiguity_margin:
                break
            for shared, partner in ((a, b), (b, a)):
                if x is shared:
                    other = y
                elif y is shared:
                    other = x
                else:
                    continue
                if other is not partner and other.slot == partner.slot:
                    return True
        return False

    group_of: dict[str, list[ParsedText]] = {p.id: [p] for p in items}
    used: dict[int, list[dict[str, Any]]] = {}
    for score, a, b, parts in edges:
        ga, gb = group_of[a.id], group_of[b.id]
        if ga is gb or not _legal(ga + gb) or competitor(score, a, b):
            continue
        merged = ga + gb
        for m in merged:
            group_of[m.id] = merged
        used[id(merged)] = (
            used.pop(id(ga), [])
            + used.pop(id(gb), [])
            + [
                {
                    "a": a.id,
                    "b": b.id,
                    "score": round(score, 4),
                    "parts": {k: round(v, 4) for k, v in parts.items()},
                }
            ]
        )

    seen: set[int] = set()
    raw_groups: list[tuple[list[ParsedText], list[dict[str, Any]]]] = []
    for p in items:
        g = group_of[p.id]
        if len(g) > 1 and id(g) not in seen:
            seen.add(id(g))
            raw_groups.append((g, used[id(g)]))

    boxes = [(str(i), TextGroup("", g, 0.0).bbox) for i, (g, _) in enumerate(raw_groups)]
    groups = []
    for n, key in enumerate(reading_order_key(boxes), start=1):
        members, es = raw_groups[int(key)]
        order = reading_order_key([(m.id, m.bbox) for m in members])
        members = sorted(members, key=lambda m: order.index(m.id))
        conf = sum(e["score"] for e in es) / len(es)
        groups.append(TextGroup(f"group_{n:03d}", members, conf, es))
    return groups
