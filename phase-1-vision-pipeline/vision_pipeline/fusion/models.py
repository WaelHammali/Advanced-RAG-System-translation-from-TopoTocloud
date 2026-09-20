"""State objects shared by the fusion passes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..ocr.address_normalizer import NormalizedAddress
from ..ocr.semantic_parser import ParsedText
from ..schemas.raw import LinkCandidate, YoloDetection
from .confidence import Decision
from .endpoint_matcher import EndpointMatch


@dataclass
class NameAssignment:
    text: ParsedText
    device_id: str
    confidence: float  # text -> device association confidence
    via_group: str | None = None
    flags: list[str] = field(default_factory=list)


@dataclass
class AddressBinding:
    """A full address (or mask) read directly from OCR and attached to a device."""

    device_id: str
    address: NormalizedAddress
    text_ids: list[str]
    #: OCR x classification x association confidence
    confidence: float
    via_group: str | None = None
    flags: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class SuffixBinding:
    """A host suffix (".2") attached to a device; resolved to an address in pass 9."""

    text: ParsedText
    device_id: str
    device_confidence: float  # suffix -> device association confidence
    flags: list[str] = field(default_factory=list)
    # ---- filled by the address resolver
    link_id: str | None = None
    link_decision: Decision | None = None
    link_confidence: float | None = None
    status: str = "unresolved"  # resolved | unresolved | ambiguous
    reason: str | None = None
    address: NormalizedAddress | None = None
    confidence: float | None = None  # combined confidence of the resolved address
    provenance: dict[str, Any] = field(default_factory=dict)
    resolution_flags: list[str] = field(default_factory=list)


@dataclass
class DeviceState:
    det: YoloDetection
    name: NameAssignment | None = None
    bindings: list[AddressBinding] = field(default_factory=list)
    suffixes: list[SuffixBinding] = field(default_factory=list)


@dataclass
class LinkState:
    id: str
    candidate: LinkCandidate
    source: str | None
    target: str | None
    start_match: EndpointMatch
    end_match: EndpointMatch
    flags: list[str] = field(default_factory=list)

    def endpoint_for(self, device_id: str) -> EndpointMatch | None:
        for m in (self.start_match, self.end_match):
            if m.device_id == device_id:
                return m
        return None

    def endpoint_confidences(self) -> list[float]:
        return [
            m.confidence for m in (self.start_match, self.end_match) if m.confidence is not None
        ]

    @property
    def n_missing_endpoints(self) -> int:
        return int(self.source is None) + int(self.target is None)
