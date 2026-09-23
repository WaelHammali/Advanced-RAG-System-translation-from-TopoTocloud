"""Deterministic OCR semantic classification.

Every OCR region becomes one (rarely several) :class:`ParsedText` with exactly one of::

    device_name | ipv4 | ipv4_cidr | subnet_mask | host_suffix | unknown

Strategy, applied in this order to the whitespace-normalised text:

1. ``ipv4_cidr``   - strict ``a.b.c.d/n`` (octets 0-255, no leading zeros, n in 0..32).
2. dotted quad     - strict IPv4; then *mathematically* tested for a contiguous mask:
                       contiguous (and not 0.0.0.0) -> ``subnet_mask`` (+ prefix length)
                       otherwise                    -> ``ipv4``
3. ``host_suffix`` - ``.N`` with N in 0..255.
4. link/interface vocabulary ("Ethernet", "GigabitEthernet0/1", "Gi0/1", "Fa0/0", "Se0",
   "Vlan10", "Port-channel1", ...) is always ``unknown``, checked before ``device_name`` so
   it can never be mistaken for one. Interface names are explicitly out of scope for this
   phase (see the phase-1 spec); this keeps them from leaking in as a side effect of the
   device-name pattern instead of a deliberate decision. Vocabulary and pattern are
   configurable (``link_type_pattern``).
5. ``device_name`` - letters + optional ``-``/``_`` + digits (``R1``, ``PC1``, ``SW-2``,
                     ``Server10``). Pattern is configurable.
6. anything else   -> ``unknown`` (never forced).

Three conservative repairs, all flagged in ``notes`` and all lowering the semantic
confidence: (a) whitespace touching a ``.`` or ``/`` is removed ("192.168.1. 1"), (b) an OCR
region holding several tokens is split only if EVERY token classifies, and (c) a leading
label ("Subnet:", "GW:", "Gateway:", an OCR typo of one of these, ...) is stripped when what
follows it, on its own, is a complete and unambiguous address, mask or CIDR - never when the
label itself looks like a device name ("R1:" is left alone).

The original OCR string is always kept in ``raw_text``.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from ..config.thresholds import SemanticConfidence
from ..geometry import Point, Rect
from ..schemas.raw import OcrText
from .address_normalizer import (
    NormalizedAddress,
    ip_to_int,
    mask_to_prefix,
    normalize_cidr,
    normalize_ip_only,
    normalize_mask_only,
    parse_host_suffix,
)

SEMANTIC_TYPES = ("device_name", "ipv4", "ipv4_cidr", "subnet_mask", "host_suffix", "unknown")

DEFAULT_DEVICE_NAME_PATTERN = r"^[A-Za-z]{1,12}[-_]?\d{1,4}$"

#: link-type / interface vocabulary that must always be ignored (classified ``unknown``),
#: even though the abbreviated forms ("Gi0/1", "Fa0/0", "Se0", "Vl10", "Po1", "Lo0", "Tu5")
#: would otherwise match ``DEFAULT_DEVICE_NAME_PATTERN``. Full words (case-insensitive) are
#: matched with or without a trailing interface number, so bare "Ethernet" / "Gigabit" /
#: "Trunk" are also ignored, not just numbered interfaces.
DEFAULT_LINK_TYPE_PATTERN = (
    r"^(?:gigabitethernet|tengigabitethernet|hundredgigabitethernet|fastethernet|"
    r"tengige|hundredgige|gigabit|ethernet|fiber|copper|optical|serial|loopback|"
    r"tunnel|vlan|port-?channel|management|mgmt|trunk|uplink|downlink|duplex|"
    r"eth|gi|ge|gig|fa|fe|te|hu|se|lo|tu|po|vl)"
    r"[-_]?\d{0,4}(?:/\d{1,4}){0,3}(?:\.\d{1,4})?$"
)

_DOT_SLASH_WS = re.compile(r"\s*([./])\s*")

#: "<label>:<value>" with or without a space after the colon - the label is discarded (never
#: read as data) provided the value alone is a complete, unambiguous address/mask/CIDR and the
#: label itself is not something that could be a device name
_LABEL_PREFIX_RE = re.compile(r"^([A-Za-z][A-Za-z0-9 _-]{0,20}):\s*(.+)$")


@dataclass
class ParsedText:
    id: str
    source_id: str
    raw_text: str
    normalized_text: str
    semantic_type: str
    semantic_confidence: float | None
    ocr_confidence: float
    bbox: Rect
    #: 0 = horizontal text, pi/2 = vertical; from the polygon when available
    axis_angle: float = 0.0
    address: NormalizedAddress | None = None
    host_suffix: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def center(self) -> Point:
        return self.bbox.center

    @property
    def text_height(self) -> float:
        """Height of the glyph line: box height for horizontal text, box width for vertical."""
        vertical = math.pi / 4 < self.axis_angle < 3 * math.pi / 4
        return max(self.bbox.w if vertical else self.bbox.h, 1.0)

    @property
    def is_network_form(self) -> bool:
        return (
            self.semantic_type == "ipv4_cidr"
            and self.address is not None
            and self.address.is_network_form
        )

    @property
    def slot(self) -> str | None:
        """Grouping slot: which part of a device label this text can be."""
        return {
            "device_name": "device_name",
            "ipv4": "ip",
            "ipv4_cidr": "ip",
            "subnet_mask": "subnet_mask",
        }.get(self.semantic_type)

    def to_dict(self) -> dict[str, Any]:
        cx, cy = self.bbox.center
        return {
            "id": self.id,
            "source_text_id": self.source_id,
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
            "semantic_type": self.semantic_type,
            "semantic_confidence": None
            if self.semantic_confidence is None
            else round(self.semantic_confidence, 4),
            "ocr_confidence": round(self.ocr_confidence, 4),
            "bbox": self.bbox.to_list(),
            "center": [round(cx, 2), round(cy, 2)],
            "is_network_label_candidate": self.is_network_form,
            "address": self.address.to_dict() if self.address else None,
            "host_suffix": self.host_suffix,
            "notes": list(self.notes),
        }


@dataclass
class _Cls:
    semantic_type: str
    confidence: float | None
    address: NormalizedAddress | None = None
    host_suffix: str | None = None


class SemanticParser:
    def __init__(
        self,
        confidence: SemanticConfidence | None = None,
        device_name_pattern: str | None = None,
        link_type_pattern: str | None = None,
    ) -> None:
        self.conf = confidence or SemanticConfidence()
        self._name_re = re.compile(device_name_pattern or DEFAULT_DEVICE_NAME_PATTERN)
        self._link_type_re = re.compile(
            link_type_pattern or DEFAULT_LINK_TYPE_PATTERN, re.IGNORECASE
        )

    # ------------------------------------------------------------------ single token
    def classify_text(self, text: str) -> _Cls:
        """Classify one already-normalised token (no repairs, no splitting)."""
        cidr = normalize_cidr(text)
        if cidr is not None:
            return _Cls("ipv4_cidr", self.conf.ipv4_cidr, address=cidr)
        if ip_to_int(text) is not None:
            if text == "0.0.0.0":  # neither a usable host address nor a usable mask
                return _Cls("unknown", None)
            if mask_to_prefix(text) is not None:
                return _Cls("subnet_mask", self.conf.subnet_mask, address=normalize_mask_only(text))
            return _Cls("ipv4", self.conf.ipv4, address=normalize_ip_only(text))
        if parse_host_suffix(text) is not None:
            return _Cls("host_suffix", self.conf.host_suffix, host_suffix=text)
        if self._link_type_re.match(text):  # checked before device_name: never a device name
            return _Cls("unknown", None)
        if self._name_re.match(text):
            return _Cls("device_name", self.conf.device_name)
        return _Cls("unknown", None)

    def is_ignored_link_type(self, text: str) -> bool:
        return self._link_type_re.match(text) is not None

    # --------------------------------------------------------------------- OCR region
    def parse(self, item: OcrText) -> list[ParsedText]:
        norm = normalize_text(item.text)
        base = dict(
            source_id=item.id,
            raw_text=item.text,
            ocr_confidence=item.confidence,
            axis_angle=_axis_angle(item),
        )

        direct = self.classify_text(norm)
        if direct.semantic_type != "unknown":
            return [self._make(item.id, norm, direct, item.bbox, **base)]

        repaired = _DOT_SLASH_WS.sub(r"\1", norm)
        if repaired != norm:
            r = self.classify_text(repaired)
            if r.semantic_type in ("ipv4", "ipv4_cidr", "subnet_mask", "host_suffix"):
                r.confidence = (r.confidence or 0.0) * self.conf.whitespace_repaired_factor
                return [
                    self._make(
                        item.id,
                        repaired,
                        r,
                        item.bbox,
                        notes=["whitespace_removed_around_dot_or_slash"],
                        **base,
                    )
                ]

        tokens = norm.split()
        if len(tokens) >= 2:
            classes = [self.classify_text(t) for t in tokens]
            if all(c.semantic_type != "unknown" for c in classes):
                boxes = _split_bbox(item, norm, tokens)
                out = []
                for k, (tok, cls_, box) in enumerate(zip(tokens, classes, boxes), start=1):
                    cls_.confidence = (cls_.confidence or 0.0) * self.conf.split_token_factor
                    out.append(
                        self._make(
                            f"{item.id}.{k}",
                            tok,
                            cls_,
                            box,
                            notes=["split_from_multi_token_ocr_region"],
                            **base,
                        )
                    )
                return out

        m = _LABEL_PREFIX_RE.match(norm)
        if m:
            label, rest = m.group(1), m.group(2)
            rest_cls = self.classify_text(rest)
            if rest_cls.semantic_type in (
                "ipv4",
                "ipv4_cidr",
                "subnet_mask",
            ) and not self._name_re.match(label):
                rest_cls.confidence = (
                    rest_cls.confidence or 0.0
                ) * self.conf.label_prefix_stripped_factor
                return [
                    self._make(
                        item.id, rest, rest_cls, item.bbox, notes=["label_prefix_stripped"], **base
                    )
                ]

        notes = ["ignored_link_type_or_interface_term"] if self.is_ignored_link_type(norm) else []
        return [self._make(item.id, norm, direct, item.bbox, notes=notes, **base)]

    def parse_all(self, items: list[OcrText]) -> list[ParsedText]:
        out: list[ParsedText] = []
        for it in items:
            out.extend(self.parse(it))
        return out

    @staticmethod
    def _make(
        pid: str,
        norm: str,
        cls_: _Cls,
        bbox: Rect,
        *,
        source_id: str,
        raw_text: str,
        ocr_confidence: float,
        axis_angle: float,
        notes: list[str] | None = None,
    ) -> ParsedText:
        return ParsedText(
            id=pid,
            source_id=source_id,
            raw_text=raw_text,
            normalized_text=norm,
            semantic_type=cls_.semantic_type,
            semantic_confidence=cls_.confidence,
            ocr_confidence=ocr_confidence,
            bbox=bbox,
            axis_angle=axis_angle,
            address=cls_.address,
            host_suffix=cls_.host_suffix,
            notes=notes or [],
        )


# ------------------------------------------------------------------------------ helpers


def normalize_text(text: str) -> str:
    """NFKC (full-width digits/dots -> ASCII), trim, collapse whitespace. No other rewriting."""
    return " ".join(unicodedata.normalize("NFKC", text).split())


def _axis_angle(item: OcrText) -> float:
    if item.polygon and len(item.polygon) >= 2:
        (x0, y0), (x1, y1) = item.polygon[0], item.polygon[1]
        if abs(x1 - x0) + abs(y1 - y0) > 1e-6:
            return math.atan2(y1 - y0, x1 - x0) % math.pi
    return 0.0 if item.bbox.w >= item.bbox.h else math.pi / 2


def _split_bbox(item: OcrText, norm: str, tokens: list[str]) -> list[Rect]:
    """Approximate sub-boxes for tokens of one region, proportional to character offsets."""
    b = item.bbox
    vertical = "\n" in item.text or b.h > b.w * 1.5
    if "\n" in item.text:
        lines = [normalize_text(s) for s in item.text.split("\n") if s.strip()]
        if len(lines) == len(tokens):
            step = b.h / len(lines)
            return [
                Rect(b.x1, b.y1 + i * step, b.x2, b.y1 + (i + 1) * step) for i in range(len(lines))
            ]
    total = max(len(norm), 1)
    spans, cursor = [], 0
    for t in tokens:
        start = norm.index(t, cursor)
        spans.append((start, start + len(t)))
        cursor = start + len(t)
    if vertical:
        return [Rect(b.x1, b.y1 + b.h * s / total, b.x2, b.y1 + b.h * e / total) for s, e in spans]
    return [Rect(b.x1 + b.w * s / total, b.y1, b.x1 + b.w * e / total, b.y2) for s, e in spans]
