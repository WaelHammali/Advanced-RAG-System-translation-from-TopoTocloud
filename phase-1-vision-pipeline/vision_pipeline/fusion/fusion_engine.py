"""Spatial-Semantic Fusion Engine.

Consumes the three standardised raw documents and reconstructs the semantic relationships
between devices, text, addresses, masks, host suffixes and links. It does NOT concatenate
the inputs and does NOT write ``topology.json`` (that is the Topology Builder's job).

Passes (each writes only its own results; later passes read earlier ones):

 1  coordinate normalisation      fusion.coordinate_normalizer
 2  OCR semantic classification   ocr.semantic_parser
 3  OCR grouping                  fusion.ocr_grouper
 4  device-name association       fusion.spatial_matcher   (group placement, then names)
 5  direct address association    fusion.spatial_matcher   (ip / cidr / mask + normalisation)
 6  host-suffix association       fusion.spatial_matcher
 7  cable endpoint -> device      fusion.endpoint_matcher
 8  network label -> link         fusion.network_label_matcher
 9  address resolution            fusion.address_resolver
10  graph reconstruction          injected ``graph_builder`` (topology.graph_builder)

Nothing is guessed: every association passes through :func:`confidence.decide`; the losers,
the ambiguous cases and everything below threshold are preserved in ``unresolved`` /
``ambiguous`` instead of being dropped or forced.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .. import __version__
from ..config.thresholds import Thresholds, to_dict
from ..ocr.address_normalizer import NormalizedAddress, normalize_ip_and_mask
from ..ocr.semantic_parser import ParsedText, SemanticParser
from ..schemas.raw import RawOcr, RawOpenCV, RawYolo
from .address_resolver import resolve_addresses
from .confidence import AMBIGUOUS, FLAGGED, combine, tier_of
from .coordinate_normalizer import NormalizedInputs, normalize_coordinates
from .endpoint_matcher import match_endpoint
from .models import AddressBinding, DeviceState, LinkState, NameAssignment, SuffixBinding
from .network_label_matcher import LabelMatch, LinkNetwork, match_labels
from .ocr_grouper import TextGroup, group_texts
from .spatial_matcher import Association, match_text_to_device

FUSION_SCHEMA_VERSION = "1.0"
ADDRESS_TYPES = ("ipv4", "ipv4_cidr", "subnet_mask")


@dataclass
class FusionResult:
    inputs: NormalizedInputs
    thresholds: Thresholds
    parsed: list[ParsedText] = field(default_factory=list)
    groups: list[TextGroup] = field(default_factory=list)
    group_placements: dict[str, Association] = field(default_factory=dict)
    devices: dict[str, DeviceState] = field(default_factory=dict)
    name_associations: list[Association] = field(default_factory=list)
    address_associations: list[Association] = field(default_factory=list)
    suffix_associations: list[Association] = field(default_factory=list)
    cable_reviews: list[dict[str, Any]] = field(default_factory=list)
    links: dict[str, LinkState] = field(default_factory=dict)
    label_matches: list[LabelMatch] = field(default_factory=list)
    networks: dict[str, LinkNetwork] = field(default_factory=dict)
    suffix_bindings: list[SuffixBinding] = field(default_factory=list)
    ambiguous: list[dict[str, Any]] = field(default_factory=list)
    unresolved: list[dict[str, Any]] = field(default_factory=list)
    graph: dict[str, Any] | None = None
    raw_counts: dict[str, int] = field(default_factory=dict)

    # ------------------------------------------------------------------ serialisation
    def to_document(self) -> dict[str, Any]:
        inp = self.inputs
        return {
            "schema_version": FUSION_SCHEMA_VERSION,
            "pipeline_version": __version__,
            "purpose": "debugging / traceability; the canonical output is topology.json",
            "image": inp.image.to_dict(),
            "warnings": inp.warnings,
            "raw_references": {
                "raw_yolo": {
                    "count": self.raw_counts.get("devices", 0),
                    "ids": [d.id for d in inp.devices],
                },
                "raw_ocr": {
                    "count": self.raw_counts.get("texts", 0),
                    "ids": [t.id for t in inp.texts],
                },
                "raw_opencv": {
                    "count": self.raw_counts.get("link_candidates", 0),
                    "ids": [c.id for c in inp.candidates],
                },
            },
            "ocr_classifications": [p.to_dict() for p in self.parsed],
            "ocr_groups": [g.to_dict() for g in self.groups],
            "ocr_group_placements": [a.to_dict() for a in self.group_placements.values()],
            "device_name_associations": [a.to_dict() for a in self.name_associations],
            "address_associations": [a.to_dict() for a in self.address_associations],
            "direct_address_bindings": [
                {
                    "device_id": b.device_id,
                    "text_ids": b.text_ids,
                    "address": b.address.to_dict(),
                    "confidence": round(b.confidence, 4),
                    "via_group": b.via_group,
                    "flags": b.flags,
                    "provenance": b.provenance,
                }
                for d in self.devices.values()
                for b in d.bindings
            ],
            "host_suffix_associations": [a.to_dict() for a in self.suffix_associations],
            "cable_candidates": self.cable_reviews,
            "cable_endpoint_associations": [
                {
                    "link_id": lk.id,
                    "candidate_id": lk.candidate.id,
                    "start": lk.start_match.to_dict(),
                    "end": lk.end_match.to_dict(),
                    "source": lk.source,
                    "target": lk.target,
                    "flags": lk.flags,
                }
                for lk in self.links.values()
            ],
            "network_label_associations": [m.to_dict() for m in self.label_matches],
            "resolved_addresses": [_suffix_to_dict(b) for b in self.suffix_bindings],
            "ambiguous": self.ambiguous,
            "unresolved": self.unresolved,
            "graph": self.graph,
            "config": {"thresholds": to_dict(self.thresholds)},
        }


def _suffix_to_dict(b: SuffixBinding) -> dict[str, Any]:
    return {
        "host_suffix_text_id": b.text.id,
        "host_suffix": b.text.host_suffix,
        "device_id": b.device_id,
        "link_id": b.link_id,
        "status": b.status,
        "reason": b.reason,
        "address": b.address.to_dict() if b.address else None,
        "confidence": None if b.confidence is None else round(b.confidence, 4),
        "flags": b.resolution_flags,
        "suffix_to_link": b.link_decision.to_dict() if b.link_decision else None,
        "provenance": b.provenance,
    }


class FusionEngine:
    def __init__(
        self,
        thresholds: Thresholds | None = None,
        parser: SemanticParser | None = None,
        graph_builder: Callable[[FusionResult], dict[str, Any]] | None = None,
        device_name_pattern: str | None = None,
    ) -> None:
        self.thr = thresholds or Thresholds()
        self.parser = parser or SemanticParser(self.thr.semantic, device_name_pattern)
        self.graph_builder = graph_builder

    # ===================================================================== entry point
    def run(self, yolo: RawYolo, ocr: RawOcr, cv: RawOpenCV) -> FusionResult:
        inp = normalize_coordinates(yolo, ocr, cv, self.thr)  # pass 1
        r = FusionResult(
            inputs=inp,
            thresholds=self.thr,
            raw_counts={
                "devices": len(yolo.detections),
                "texts": len(ocr.texts),
                "link_candidates": len(cv.candidates),
            },
        )
        r.devices = {d.id: DeviceState(d) for d in inp.devices}
        r.parsed = self.parser.parse_all(inp.texts)  # pass 2
        r.groups = group_texts(r.parsed, self.thr.grouping)  # pass 3

        self._place_groups(r)
        self._pass4_names(r)  # pass 4
        self._pass5_addresses(r)  # pass 5
        self._pass6_suffixes(r)  # pass 6
        self._pass7_links(r)  # pass 7
        self._pass8_labels(r)  # pass 8
        r.suffix_bindings = resolve_addresses(r.devices, r.links, r.networks, self.thr)  # pass 9
        self._collect_unresolved(r)
        if self.graph_builder is not None:  # pass 10
            r.graph = self.graph_builder(r)
        return r

    # ================================================================ group placement
    def _place_groups(self, r: FusionResult) -> None:
        """Decide, per multi-text group, which device the whole group belongs to."""
        dets = [d.det for d in r.devices.values()]
        p = self.thr.group_to_device
        for g in r.groups:
            decision = match_text_to_device(g.bbox, g.ocr_confidence, dets, p)
            conf = combine(decision.score, g.confidence)
            r.group_placements[g.id] = Association.build(
                "group_placement", g.id, decision, conf, p.tier
            )

    def _group_of(self, r: FusionResult) -> dict[str, TextGroup]:
        return {m.id: g for g in r.groups for m in g.members}

    # ======================================================================= pass 4
    def _pass4_names(self, r: FusionResult) -> None:
        dets = [d.det for d in r.devices.values()]
        p = self.thr.name_to_device
        group_of = self._group_of(r)
        claims: dict[str, list[tuple[Association, ParsedText]]] = defaultdict(list)
        for item in r.parsed:
            if item.semantic_type != "device_name":
                continue
            g = group_of.get(item.id)
            pl = r.group_placements.get(g.id) if g else None
            if pl is not None and pl.stored:
                conf = combine(pl.confidence, item.semantic_confidence)
                assoc = Association.build(
                    "device_name", item.id, pl.decision, conf, p.tier, via_group=g.id
                )
            else:
                d = match_text_to_device(item.bbox, item.ocr_confidence, dets, p)
                assoc = Association.build(
                    "device_name", item.id, d, combine(d.score, item.semantic_confidence), p.tier
                )
            r.name_associations.append(assoc)
            if assoc.stored:
                claims[assoc.device_id].append((assoc, item))

        for dev_id, lst in claims.items():
            lst.sort(key=lambda x: (-(x[0].confidence or 0.0), x[1].id))
            top = lst[0]
            if (
                len(lst) > 1
                and (top[0].confidence - lst[1][0].confidence) < p.tier.ambiguity_margin
            ):
                for assoc, item in lst:
                    _demote(assoc, AMBIGUOUS, "device_claimed_by_several_names_of_similar_score")
                continue
            for assoc, item in lst[1:]:
                _demote(assoc, "unresolved", "device_already_named_by_higher_scoring_text")
            assoc, item = top
            r.devices[dev_id].name = NameAssignment(
                item, dev_id, assoc.confidence, assoc.via_group, list(assoc.flags)
            )

    # ======================================================================= pass 5
    def _pass5_addresses(self, r: FusionResult) -> None:
        dets = [d.det for d in r.devices.values()]
        p = self.thr.address_to_device
        handled: set[str] = set()

        # ---- (a) texts placed via a group: ip + mask read together
        for g in r.groups:
            pl = r.group_placements.get(g.id)
            ip, mask = g.by_slot("ip"), g.by_slot("subnet_mask")
            if pl is None or not pl.stored or (ip is None and mask is None):
                continue
            members = [m for m in (ip, mask) if m is not None]
            conf = combine(pl.confidence, *[m.semantic_confidence for m in members])
            assocs = [
                Association.build("address", m.id, pl.decision, conf, p.tier, via_group=g.id)
                for m in members
            ]
            r.address_associations.extend(assocs)
            handled.update(m.id for m in members)
            if assocs[0].stored:
                addr = _address_from(ip, mask)
                self._attach_binding(
                    r,
                    pl.device_id,
                    addr,
                    [m.id for m in members],
                    assocs[0].confidence,
                    g.id,
                    list(assocs[0].flags),
                )

        # ---- (b) remaining address texts: each scored on its own
        for item in r.parsed:
            if (
                item.semantic_type not in ADDRESS_TYPES
                or item.is_network_form
                or item.id in handled
            ):
                continue
            d = match_text_to_device(item.bbox, item.ocr_confidence, dets, p)
            assoc = Association.build(
                "address", item.id, d, combine(d.score, item.semantic_confidence), p.tier
            )
            r.address_associations.append(assoc)
            if assoc.stored:
                self._attach_binding(
                    r,
                    assoc.device_id,
                    item.address,
                    [item.id],
                    assoc.confidence,
                    None,
                    list(assoc.flags),
                )

        # ---- (c) a stray mask and a prefix-less IP on the same device belong together
        for dev in r.devices.values():
            ip_only = [
                b for b in dev.bindings if b.address.ip_address and b.address.prefix_length is None
            ]
            mask_only = [
                b for b in dev.bindings if b.address.ip_address is None and b.address.subnet_mask
            ]
            if len(ip_only) == 1 and len(mask_only) == 1:
                a, m = ip_only[0], mask_only[0]
                merged = normalize_ip_and_mask(a.address.ip_address, m.address.subnet_mask)
                if merged is not None:
                    ids = a.text_ids + m.text_ids
                    self._replace_bindings(
                        dev,
                        [a, m],
                        AddressBinding(
                            dev.det.id,
                            merged,
                            ids,
                            combine(a.confidence, m.confidence),
                            a.via_group or m.via_group,
                            sorted(set(a.flags + m.flags)),
                            _direct_provenance(
                                merged,
                                ids,
                                a.via_group or m.via_group,
                                dev.det.id,
                                extra="ip_and_mask_paired_on_same_device",
                            ),
                        ),
                    )
            elif len(ip_only) + len(mask_only) > 2 and mask_only and ip_only:
                r.ambiguous.append(
                    {
                        "kind": "mask_pairing",
                        "device_id": dev.det.id,
                        "reason": "several_ip_or_mask_candidates_on_one_device",
                        "text_ids": [t for b in ip_only + mask_only for t in b.text_ids],
                    }
                )

    def _attach_binding(
        self,
        r: FusionResult,
        device_id: str,
        addr: NormalizedAddress,
        text_ids: list[str],
        conf: float | None,
        group_id: str | None,
        flags: list[str],
    ) -> None:
        r.devices[device_id].bindings.append(
            AddressBinding(
                device_id,
                addr,
                text_ids,
                conf if conf is not None else 0.0,
                group_id,
                flags,
                _direct_provenance(addr, text_ids, group_id, device_id),
            )
        )

    @staticmethod
    def _replace_bindings(dev: DeviceState, old: list[AddressBinding], new: AddressBinding) -> None:
        dev.bindings = [b for b in dev.bindings if all(b is not o for o in old)] + [new]

    # ======================================================================= pass 6
    def _pass6_suffixes(self, r: FusionResult) -> None:
        dets = [d.det for d in r.devices.values()]
        p = self.thr.suffix_to_device
        for item in r.parsed:
            if item.semantic_type != "host_suffix":
                continue
            d = match_text_to_device(item.bbox, item.ocr_confidence, dets, p)
            assoc = Association.build(
                "host_suffix", item.id, d, combine(d.score, item.semantic_confidence), p.tier
            )
            r.suffix_associations.append(assoc)
            if assoc.stored:
                r.devices[assoc.device_id].suffixes.append(
                    SuffixBinding(item, assoc.device_id, assoc.confidence, list(assoc.flags))
                )

    # ======================================================================= pass 7
    def _pass7_links(self, r: FusionResult) -> None:
        dets = [d.det for d in r.devices.values()]
        p = self.thr.endpoint_to_device
        lt = self.thr.link
        for cand in r.inputs.candidates:
            review: dict[str, Any] = {
                "candidate_id": cand.id,
                "geometric_confidence": round(cand.confidence, 4),
                "path_type": cand.path_type,
                "decision": "unresolved",
                "reason": None,
                "link_id": None,
            }
            r.cable_reviews.append(review)
            if cand.confidence < lt.min_candidate_confidence:
                review["reason"] = "low_geometric_confidence"
                r.unresolved.append(_link_unresolved(cand, review["reason"]))
                continue
            if cand.path_type in ("branched", "cycle") or (cand.start is None and cand.end is None):
                review["reason"] = "path_endpoints_undetermined"
                r.unresolved.append(_link_unresolved(cand, review["reason"]))
                continue
            sm, em = (match_endpoint(cand, "start", dets, p), match_endpoint(cand, "end", dets, p))
            review["start"], review["end"] = sm.to_dict(), em.to_dict()
            for m in (sm, em):
                if m.decision is not None and m.decision.status == AMBIGUOUS:
                    r.ambiguous.append(
                        {
                            "kind": "cable_endpoint",
                            "subject_id": cand.id,
                            "end": m.end,
                            "candidates": [m.decision.best_key, m.decision.runner_up_key],
                            "scores": [m.decision.best_score, m.decision.runner_up_score],
                        }
                    )
            matched = [m for m in (sm, em) if m.device_id]
            if not matched:
                review["reason"] = "no_device_at_either_endpoint"
                r.unresolved.append(_link_unresolved(cand, review["reason"]))
                continue
            if sm.device_id and sm.device_id == em.device_id:
                review["reason"] = "both_endpoints_on_same_device"
                r.unresolved.append(_link_unresolved(cand, review["reason"]))
                continue
            if sm.device_id and em.device_id:
                source, target = sorted((sm.device_id, em.device_id))
            else:
                source, target = matched[0].device_id, None
            lid = f"link_{len(r.links) + 1:03d}"
            flags = []
            if (
                any(m.decision is not None and m.decision.status == FLAGGED for m in matched)
                or tier_of(cand.confidence, lt.tier) == FLAGGED
            ):
                flags.append("low_confidence")
            if target is None:
                flags.append("unresolved_endpoint")
            r.links[lid] = LinkState(lid, cand, source, target, sm, em, flags)
            review.update(decision="kept", reason=None, link_id=lid)

        pairs: dict[tuple[str | None, str | None], list[str]] = defaultdict(list)
        for lk in r.links.values():
            if lk.source and lk.target:
                pairs[(lk.source, lk.target)].append(lk.id)
        for (a, b), ids in pairs.items():
            if len(ids) > 1:
                for i in ids:
                    r.links[i].flags.append("parallel_link_between_same_devices")

    # ======================================================================= pass 8
    def _pass8_labels(self, r: FusionResult) -> None:
        labels = [p for p in r.parsed if p.is_network_form]
        if not labels:
            return
        r.label_matches, r.networks = match_labels(
            labels,
            {lid: lk.candidate for lid, lk in r.links.items()},
            [d.det for d in r.devices.values()],
            self.thr.network_label_to_link,
        )

    # ============================================================== unresolved / ambiguous
    def _collect_unresolved(self, r: FusionResult) -> None:
        stored_name = {a.subject_id: a for a in r.name_associations}
        stored_addr = {a.subject_id: a for a in r.address_associations}
        stored_suffix = {a.subject_id: a for a in r.suffix_associations}
        label_match = {m.label_id: m for m in r.label_matches}
        consumed_by_binding = {
            t for d in r.devices.values() for b in d.bindings for t in b.text_ids
        }

        def add(item: ParsedText, kind: str, reason: str, decision=None, extra=None) -> None:
            entry: dict[str, Any] = {
                "kind": kind,
                "text_id": item.id,
                "raw_text": item.raw_text,
                "normalized_text": item.normalized_text,
                "semantic_type": item.semantic_type,
                "bbox": item.bbox.to_list(),
                "reason": reason,
            }
            if decision is not None and decision.best_key is not None:
                entry["best_candidate"] = decision.best_key
                entry["best_score"] = (
                    None if decision.best_score is None else round(decision.best_score, 4)
                )
                if decision.runner_up_key is not None:
                    entry["runner_up"] = decision.runner_up_key
            if extra:
                entry.update(extra)
            r.unresolved.append(entry)
            if reason.startswith("ambiguous") or reason.startswith("device_claimed"):
                r.ambiguous.append({k: v for k, v in entry.items() if k != "bbox"})

        for item in r.parsed:
            t = item.semantic_type
            if t == "device_name":
                a = stored_name.get(item.id)
                if a is None or not a.stored:
                    add(item, "device_name", _why(a), a.decision if a else None)
            elif t in ADDRESS_TYPES and not item.is_network_form:
                a = stored_addr.get(item.id)
                if item.id not in consumed_by_binding:
                    add(
                        item,
                        "address" if t != "subnet_mask" else "subnet_mask",
                        _why(a),
                        a.decision if a else None,
                    )
            elif item.is_network_form:
                m = label_match.get(item.id)
                if m is None or m.link_id is None:
                    reason = (
                        "no_link_candidate"
                        if m is None
                        else (
                            "ambiguous_link_association"
                            if m.decision.status == AMBIGUOUS
                            else "conflicting_labels_on_same_link"
                            if "conflicting_labels_on_same_link" in m.flags
                            else "association_confidence_below_threshold"
                            if m.decision.status == "unresolved"
                            else "no_link_nearby"
                        )
                    )
                    add(item, "network_label", reason, m.decision if m else None)
            elif t == "host_suffix":
                a = stored_suffix.get(item.id)
                if a is None or not a.stored:
                    add(item, "host_suffix", _why(a), a.decision if a else None)
            else:
                add(item, "text", "unclassified_text")

    # ------------------------------------------------------------------------------


def _why(a: Association | None) -> str:
    if a is None:
        return "no_association_attempted"
    return {
        "ambiguous": "ambiguous_device_association",
        "unresolved": "association_confidence_below_threshold",
        "no_candidates": "no_device_nearby",
    }.get(a.status, a.flags[-1] if a.flags else a.status)


def _demote(assoc: Association, status: str, reason: str) -> None:
    assoc.status, assoc.device_id, assoc.confidence = status, None, None
    assoc.flags.append(reason)


def _link_unresolved(cand, reason: str) -> dict[str, Any]:
    p = lambda v: None if v is None else [round(v[0], 2), round(v[1], 2)]  # noqa: E731
    return {
        "kind": "link_candidate",
        "candidate_id": cand.id,
        "reason": reason,
        "geometric_confidence": round(cand.confidence, 4),
        "path_type": cand.path_type,
        "start": p(cand.start),
        "end": p(cand.end),
        "endpoints": [p(q) for q in cand.endpoints],
    }


def _address_from(ip: ParsedText | None, mask: ParsedText | None) -> NormalizedAddress:
    """Case A/B/C/D from the texts of one group. Nothing is assumed."""
    if ip is not None and mask is not None:
        return normalize_ip_and_mask(
            ip.address.ip_address, mask.address.subnet_mask
        )  # validated types
    return (ip or mask).address


def _direct_provenance(
    addr: NormalizedAddress,
    text_ids: list[str],
    group_id: str | None,
    device_id: str,
    extra: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for fld, origin in addr.field_origin.items():
        direct = origin == "ocr"
        out[fld] = {
            "method": "ocr_direct" if direct else origin,
            "sources": ["ocr", "fusion"] if direct else ["ocr", "fusion", "address_normalizer"],
            "evidence": {"text_ids": text_ids, "device_id": device_id, "group_id": group_id},
        }
        if extra:
            out[fld]["note"] = extra
    return out
