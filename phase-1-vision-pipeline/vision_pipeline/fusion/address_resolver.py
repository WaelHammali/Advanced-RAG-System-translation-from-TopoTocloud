"""Pass 9 - Address Resolver.

Reconstructs full device addresses from three independent pieces of evidence:

    host suffix (".2", read by OCR, attached to a device)
  + the physical link that suffix belongs to (OpenCV + endpoint matching)
  + that link's network label ("192.168.1.0/24", OCR + label matching)

It runs strictly AFTER text classification, grouping, device association, endpoint
association and network-label association.

Step 1 - which link does the suffix belong to?  The suffix already belongs to a device; among
the links that end at that device, score each by (a) distance from the suffix to the cable
path and (b) distance from the suffix to the cable's end at the device
(``SuffixLinkScoring``). The winner comes from :func:`confidence.decide`; a tie is
"ambiguous" and nothing is resolved. The best link is chosen among ALL of the device's links
(also those without a network label) so a suffix is never silently moved to a different
cable just because that one has a label.

Step 2 - arithmetic (``ocr.address_normalizer.resolve_host_suffix``): the suffix is the final
octet, only for prefixes /24../31, verified to lie inside the network and not to be its
network/broadcast address. Anything else stays unresolved (never guessed).

Step 3 - confidence: geometric mean of every link in the evidence chain; below the
``resolver.tier.medium`` threshold the address is NOT stored.

Step 4 - consistency: two suffixes producing the same address on one link, or two different
suffixes on the same (device, link), cancel each other (unresolved, evidence kept).
"""

from __future__ import annotations

from collections import defaultdict

from ..config.thresholds import Thresholds
from ..geometry import clamp01, dist, rect_polyline_distance
from ..ocr.address_normalizer import resolve_host_suffix
from ..schemas.raw import YoloDetection
from .confidence import AMBIGUOUS, FLAGGED, UNRESOLVED, combine, decide, tier_of
from .models import DeviceState, LinkState, SuffixBinding
from .network_label_matcher import LinkNetwork


def resolve_addresses(
    devices: dict[str, DeviceState],
    links: dict[str, LinkState],
    networks: dict[str, LinkNetwork],
    thr: Thresholds,
) -> list[SuffixBinding]:
    bindings = [b for d in devices.values() for b in d.suffixes]
    for b in bindings:
        _resolve_one(b, devices[b.device_id].det, links, networks, thr)
    _enforce_consistency(bindings)
    return bindings


def _score_link(b: SuffixBinding, dev: YoloDetection, link: LinkState, thr: Thresholds):
    p = thr.suffix_to_link
    th = b.text.text_height
    d_path, _ = rect_polyline_distance(b.text.bbox, link.candidate.segments)
    limit = p.max_dist_in_text_heights * th
    if d_path > limit:
        return None
    s_path = 1.0 - d_path / limit
    end = link.endpoint_for(dev.id)
    s_end = 0.0
    if end is not None and end.point is not None:
        s_end = clamp01(
            1.0 - dist(b.text.center, end.point) / (p.max_endpoint_dist_factor * dev.bbox.size)
        )
    parts = {"path_distance": s_path, "endpoint_distance": s_end}
    return clamp01(p.weight_path * s_path + p.weight_endpoint * s_end), parts


def _resolve_one(
    b: SuffixBinding,
    dev: YoloDetection,
    links: dict[str, LinkState],
    networks: dict[str, LinkNetwork],
    thr: Thresholds,
) -> None:
    device_links = [lk for lk in links.values() if dev.id in (lk.source, lk.target)]
    if not device_links:
        b.reason = "device_has_no_link"
        return
    scored = []
    for lk in device_links:
        r = _score_link(b, dev, lk, thr)
        if r is not None:
            scored.append((lk.id, r[0], r[1]))
    d = decide(scored, thr.suffix_to_link.tier)
    b.link_decision = d
    if d.status == AMBIGUOUS:
        b.status, b.reason = "ambiguous", "suffix_link_ambiguous"
        return
    if not d.stored:
        b.reason = "suffix_not_close_enough_to_any_link_of_device"
        return
    b.link_id, b.link_confidence = d.key, d.score
    link = links[b.link_id]

    net = networks.get(b.link_id)
    if net is None:
        b.reason = "link_has_no_network_label"
        return
    res = resolve_host_suffix(
        net.address.network_address,
        net.address.prefix_length,
        b.text.host_suffix,
        min_prefix=thr.resolver.min_prefix_for_final_octet,
        max_prefix=thr.resolver.max_prefix_for_final_octet,
    )
    if res.address is None:
        b.reason = res.reason
        return

    end = link.endpoint_for(dev.id)
    conf = combine(
        b.text.ocr_confidence,
        b.text.semantic_confidence,
        b.device_confidence,
        b.link_confidence,
        end.confidence if end else None,
        net.confidence,
        link.candidate.confidence,
    )
    tier = tier_of(conf, thr.resolver.tier)
    if tier == UNRESOLVED:
        b.reason = "combined_confidence_below_threshold"
        b.confidence = conf  # kept for traceability only; the address is NOT stored
        return
    b.address, b.confidence, b.status, b.reason = res.address, conf, "resolved", "resolved"
    if tier == FLAGGED:
        b.resolution_flags.append("low_confidence")
    b.provenance = {
        "method": "host_suffix_resolution",
        "sources": ["ocr", "opencv", "fusion", "address_resolver"],
        "evidence": {
            "host_suffix_text_id": b.text.id,
            "device_id": dev.id,
            "link_id": link.id,
            "link_candidate_id": link.candidate.id,
            "network_label_text_id": net.label_id,
        },
        "components": {
            "ocr": b.text.ocr_confidence,
            "semantic": b.text.semantic_confidence,
            "suffix_to_device": b.device_confidence,
            "suffix_to_link": b.link_confidence,
            "endpoint_to_device": end.confidence if end else None,
            "network_label_to_link": net.confidence,
            "cable_detection": link.candidate.confidence,
        },
    }


def _enforce_consistency(bindings: list[SuffixBinding]) -> None:
    resolved = [b for b in bindings if b.status == "resolved"]
    by_device_link: dict[tuple[str, str], list[SuffixBinding]] = defaultdict(list)
    by_link_ip: dict[tuple[str, str], list[SuffixBinding]] = defaultdict(list)
    for b in resolved:
        by_device_link[(b.device_id, b.link_id)].append(b)
        by_link_ip[(b.link_id, b.address.ip_address)].append(b)

    def cancel(group: list[SuffixBinding], reason: str) -> None:
        for b in group:
            b.status, b.reason = "ambiguous", reason
            b.address = None
            b.provenance = {}

    for group in by_device_link.values():
        if len({b.text.host_suffix for b in group}) > 1:
            cancel(group, "multiple_different_suffixes_for_same_device_and_link")
    for group in by_link_ip.values():
        live = [b for b in group if b.status == "resolved"]
        if len({b.device_id for b in live}) > 1:
            cancel(live, "same_address_resolved_for_different_devices_on_link")
