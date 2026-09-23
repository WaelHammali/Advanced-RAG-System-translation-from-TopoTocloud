"""Every fusion / parser threshold and scoring weight lives here.

No other module may contain a tunable number. Each group is a dataclass so it can be
overridden from a YAML/JSON file (see :mod:`vision_pipeline.config.settings`) without code
changes.

Confidence tiers (used for every inferred relationship):

    score >= high                 -> ACCEPTED    (stored)
    medium <= score < high        -> FLAGGED     (stored, marked low_confidence)
    score < medium                -> UNRESOLVED  (field stays null, evidence preserved)

If the runner-up candidate is within ``ambiguity_margin`` of the winner (and is itself at
least ``medium``), the association is AMBIGUOUS and is not made.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any


@dataclass
class TierThresholds:
    high: float = 0.75
    medium: float = 0.55
    ambiguity_margin: float = 0.08


# ------------------------------------------------------------------------------- parser


@dataclass
class SemanticConfidence:
    """Confidence in the *classification* itself (deterministic rules, so mostly 1.0)."""

    ipv4: float = 1.0
    ipv4_cidr: float = 1.0
    subnet_mask: float = 1.0
    ipv6: float = 1.0
    ipv6_cidr: float = 1.0
    host_suffix: float = 0.95
    device_name: float = 0.90
    #: multiplier when whitespace inside a dotted/slashed token had to be removed
    whitespace_repaired_factor: float = 0.90
    #: multiplier when one OCR region held several tokens and was split
    split_token_factor: float = 0.90
    #: multiplier when a leading, unclassifiable label ("Subnet:", "GW:", "Gateway:", a typo of
    #: one of these, ...) had to be stripped before the address behind it would classify
    label_prefix_stripped_factor: float = 0.85


# ------------------------------------------------------------------------------ grouping


@dataclass
class GroupingThresholds:
    #: texts further apart than this many text-heights are never grouped
    max_gap_in_text_heights: float = 2.0
    #: alignment offset tolerated, as a fraction of the larger text extent
    alignment_tolerance: float = 0.6
    weight_distance: float = 0.40
    weight_alignment: float = 0.30
    weight_order: float = 0.10
    weight_semantic: float = 0.20
    #: minimum pair score to merge two texts into one group
    link_threshold: float = 0.60
    #: if a competing partner of the same kind is this close in score, do not group
    ambiguity_margin: float = 0.08
    #: semantic compatibility of two slots (order-insensitive keys "a|b")
    semantic_compat: dict[str, float] = field(
        default_factory=lambda: {
            "device_name|ip": 1.0,
            "ip|subnet_mask": 1.0,
            "device_name|subnet_mask": 0.6,
        }
    )
    #: penalty applied when reading order is unusual (e.g. mask above IP)
    unusual_order_score: float = 0.6


# ------------------------------------------------------------------- text <-> device


@dataclass
class TextDeviceScoring:
    #: a text further than ``max_gap_factor`` x device size (bbox gap) is not a candidate
    max_gap_factor: float = 0.6
    #: centre distance that maps to score 0, in device sizes
    center_factor: float = 2.0
    weight_gap: float = 0.35
    weight_center: float = 0.10
    weight_location: float = 0.10
    weight_alignment: float = 0.20
    weight_ocr: float = 0.15
    weight_yolo: float = 0.10
    location_preference: dict[str, float] = field(
        default_factory=lambda: {
            "below": 1.0,
            "above": 0.9,
            "right": 0.85,
            "left": 0.85,
            "inside": 0.7,
            "diagonal": 0.6,
        }
    )
    tier: TierThresholds = field(default_factory=TierThresholds)


# ------------------------------------------------------------------ endpoint <-> device


@dataclass
class EndpointScoring:
    #: an endpoint further than ``max_gap_factor`` x device size from a bbox is not a candidate
    max_gap_factor: float = 0.6
    #: how far (in device sizes) the cable's extension may travel to still "point at" a device
    ray_factor: float = 1.0
    weight_proximity: float = 0.45
    weight_direction: float = 0.30
    weight_intersection: float = 0.10
    weight_yolo: float = 0.15
    tier: TierThresholds = field(default_factory=TierThresholds)


# --------------------------------------------------------------- network label <-> link


@dataclass
class NetworkLabelScoring:
    #: label further than this many text-heights from the cable is not a candidate
    max_dist_in_text_heights: float = 3.0
    weight_distance: float = 0.40
    weight_alignment: float = 0.15
    weight_midpoint: float = 0.15
    weight_device_relative: float = 0.15
    weight_ocr: float = 0.15
    #: inside "alignment": share of extent alignment vs. label/cable parallelism
    extent_share: float = 0.70
    tier: TierThresholds = field(default_factory=TierThresholds)


@dataclass
class SuffixLinkScoring:
    """Which of a device's links does a host suffix (".2") belong to."""

    max_dist_in_text_heights: float = 4.0
    #: weight of "suffix is close to the cable path" vs "close to the cable's end at the device"
    weight_path: float = 0.60
    weight_endpoint: float = 0.40
    #: suffix centre further than this many device sizes from the cable's end at the device scores 0
    max_endpoint_dist_factor: float = 1.5
    tier: TierThresholds = field(default_factory=TierThresholds)


# ------------------------------------------------------------------------ link / device


@dataclass
class LinkThresholds:
    #: link candidates below this geometric confidence are not turned into links
    min_candidate_confidence: float = 0.30
    #: multiplier on the final link confidence for each unresolved endpoint
    missing_endpoint_penalty: float = 0.60
    tier: TierThresholds = field(default_factory=TierThresholds)


@dataclass
class ResolverThresholds:
    """Gate on the *combined* confidence of a resolved host address."""

    tier: TierThresholds = field(default_factory=lambda: TierThresholds(high=0.75, medium=0.55))
    #: smallest / largest prefix for which a ".N" suffix means "final octet"
    min_prefix_for_final_octet: int = 24
    max_prefix_for_final_octet: int = 31


@dataclass
class Thresholds:
    semantic: SemanticConfidence = field(default_factory=SemanticConfidence)
    grouping: GroupingThresholds = field(default_factory=GroupingThresholds)
    #: a whole OCR group -> device
    group_to_device: TextDeviceScoring = field(
        default_factory=lambda: TextDeviceScoring(max_gap_factor=0.8)
    )
    name_to_device: TextDeviceScoring = field(default_factory=TextDeviceScoring)
    address_to_device: TextDeviceScoring = field(
        default_factory=lambda: TextDeviceScoring(max_gap_factor=0.9)
    )
    suffix_to_device: TextDeviceScoring = field(
        default_factory=lambda: TextDeviceScoring(max_gap_factor=0.9)
    )
    endpoint_to_device: EndpointScoring = field(default_factory=EndpointScoring)
    network_label_to_link: NetworkLabelScoring = field(default_factory=NetworkLabelScoring)
    suffix_to_link: SuffixLinkScoring = field(default_factory=SuffixLinkScoring)
    link: LinkThresholds = field(default_factory=LinkThresholds)
    resolver: ResolverThresholds = field(default_factory=ResolverThresholds)
    #: coordinates may exceed the image by this many pixels before a warning is raised
    bbox_out_of_bounds_tolerance_px: float = 4.0
    #: two YOLO detections at or above this box IoU are treated as one physical device
    #: detected twice (e.g. once as "router", once as "switch"); the lower-confidence one is
    #: dropped in pass 1, before any text association, so it never leaves both duplicates
    #: with a null name/address as "ambiguous"
    duplicate_detection_iou: float = 0.7


# ------------------------------------------------------------------------ (de)serialise


def to_dict(obj: Any) -> Any:
    if is_dataclass(obj):
        return {f.name: to_dict(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    return obj


def apply_overrides(obj: Any, overrides: dict[str, Any], path: str = "") -> None:
    """Recursively apply a nested dict onto a dataclass instance. Unknown keys are an error."""
    names = {f.name for f in fields(obj)}
    for key, value in overrides.items():
        if key not in names:
            raise KeyError(f"unknown config key: {path}{key}")
        current = getattr(obj, key)
        if is_dataclass(current) and isinstance(value, dict):
            apply_overrides(current, value, f"{path}{key}.")
        elif isinstance(current, dict) and isinstance(value, dict):
            current.update(value)
        else:
            setattr(obj, key, value)
