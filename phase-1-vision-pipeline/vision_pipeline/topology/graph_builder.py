"""Pass 10 - graph reconstruction.

Turns the fusion state into a graph: nodes = devices, edges = physical links. This is the
semantic assembly step. It only reads what earlier passes decided; it never adds
information. Missing values are ``None``.

Device ``addresses`` holds EVERY address binding of the device (a router with two
subnets has two). The scalar ``network`` block mirrors the device's single address, and is
all-null when the device has none or several (a scalar cannot represent several addresses
without picking one, which would be a guess).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..fusion.confidence import combine
from ..fusion.models import AddressBinding, DeviceState, LinkState, SuffixBinding

if TYPE_CHECKING:  # avoid a runtime import cycle (fusion_engine imports nothing from here)
    from ..fusion.fusion_engine import FusionResult

NETWORK_KEYS = ("ip_address", "prefix_length", "subnet_mask", "network_address", "host_suffix")


def _r(v: float | None) -> float | None:
    return None if v is None else round(float(v), 4)


def build_graph(r: FusionResult) -> dict[str, Any]:
    penalty = r.thresholds.link.missing_endpoint_penalty
    nodes = [_node(r.devices[i]) for i in sorted(r.devices)]
    edges = [_edge(r, lk, penalty) for lk in r.links.values()]
    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------------- nodes


def _direct_entry(b: AddressBinding) -> dict[str, Any]:
    return {
        "link_id": None,
        **b.address.to_dict(),
        "host_suffix": None,
        "source": "ocr_direct",
        "confidence": _r(b.confidence),
        "flags": list(b.flags),
        "unresolved_reason": None,
        "provenance": b.provenance,
    }


def _suffix_entry(s: SuffixBinding) -> dict[str, Any]:
    ev_suffix = {
        "method": "ocr_direct",
        "sources": ["ocr", "fusion"],
        "evidence": {"text_id": s.text.id, "device_id": s.device_id},
    }
    if s.status == "resolved" and s.address is not None:
        prov: dict[str, Any] = {"host_suffix": ev_suffix}
        for fld, origin in s.address.field_origin.items():
            prov[fld] = {
                "method": origin,
                "sources": s.provenance["sources"],
                "evidence": s.provenance["evidence"],
            }
        return {
            "link_id": s.link_id,
            **s.address.to_dict(),
            "host_suffix": s.text.host_suffix,
            "source": "host_suffix_resolution",
            "confidence": _r(s.confidence),
            "flags": s.flags + s.resolution_flags,
            "unresolved_reason": None,
            "provenance": prov,
            "components": s.provenance.get("components"),
        }
    return {
        "link_id": s.link_id,
        "ip_address": None,
        "prefix_length": None,
        "subnet_mask": None,
        "network_address": None,
        "host_suffix": s.text.host_suffix,
        "source": "host_suffix_only",
        "confidence": _r(
            combine(s.text.ocr_confidence, s.text.semantic_confidence, s.device_confidence)
        ),
        "flags": list(s.flags),
        "unresolved_reason": s.reason,
        "provenance": {"host_suffix": ev_suffix},
    }


def _addresses(d: DeviceState) -> list[dict[str, Any]]:
    direct = [_direct_entry(b) for b in d.bindings]
    out: list[dict[str, Any]] = []
    for s in d.suffixes:
        e = _suffix_entry(s)
        if e["ip_address"] is not None:
            # the same address also read directly from text: one interface, keep the richer entry
            twin = next(
                (
                    x
                    for x in direct
                    if x["ip_address"] == e["ip_address"]
                    and x["prefix_length"] in (None, e["prefix_length"])
                ),
                None,
            )
            if twin is not None:
                direct.remove(twin)
                for fld in ("ip_address",):
                    e["provenance"][fld]["also_read_directly_from"] = (
                        twin["provenance"].get(fld, {}).get("evidence")
                    )
        out.append(e)
    return direct + out


def _node(d: DeviceState) -> dict[str, Any]:
    det = d.det
    addrs = _addresses(d)
    mirror = {k: None for k in NETWORK_KEYS}
    if len(addrs) == 1:
        mirror = {k: addrs[0][k] for k in NETWORK_KEYS}

    name = d.name.text.normalized_text if d.name else None
    name_conf = _r(d.name.confidence) if d.name else None
    net_conf = _r(
        min((a["confidence"] for a in addrs if a["confidence"] is not None), default=None)
    )
    overall = _r(combine(det.confidence, name_conf, net_conf))

    prov: dict[str, Any] = {
        "type": {
            "method": "yolo_detection",
            "sources": ["yolo"],
            "evidence": {"detection_id": det.id, "class": det.cls},
        }
    }
    flags: list[str] = []
    if d.name:
        t = d.name.text
        prov["name"] = {
            "method": "ocr_spatial_association",
            "sources": ["ocr", "fusion"],
            "evidence": {
                "text_id": t.id,
                "source_text_id": t.source_id,
                "group_id": d.name.via_group,
            },
            "components": {
                "ocr": _r(t.ocr_confidence),
                "semantic": _r(t.semantic_confidence),
                "text_to_device": _r(d.name.confidence),
            },
        }
        flags += [f"name:{f}" for f in d.name.flags]
    for a in addrs:
        flags += [f"address:{f}" for f in a["flags"]]
    return {
        "id": det.id,
        "type": det.cls,
        "name": name,
        "network": mirror,
        "addresses": addrs,
        "confidence": {
            "device_detection": _r(det.confidence),
            "name": name_conf,
            "network_information": net_conf,
            "overall": overall,
        },
        "flags": sorted(set(flags)),
        "provenance": prov,
        "bbox": det.bbox.to_list(),
    }


# ---------------------------------------------------------------------------------- edges


def _edge(r: FusionResult, lk: LinkState, penalty: float) -> dict[str, Any]:
    src = lk.endpoint_for(lk.source) if lk.source else None
    tgt = lk.endpoint_for(lk.target) if lk.target else None
    cable = lk.candidate.confidence
    base = combine(cable, src.confidence if src else None, tgt.confidence if tgt else None)
    overall = _r(None if base is None else base * (penalty**lk.n_missing_endpoints))

    net = r.networks.get(lk.id)
    network = {"network_address": None, "prefix_length": None, "subnet_mask": None}
    prov: dict[str, Any] = {
        "link": {
            "method": "opencv_link_detection+endpoint_association",
            "sources": ["opencv", "fusion"],
            "evidence": {
                "candidate_id": lk.candidate.id,
                "source_endpoint": src.to_dict() if src else None,
                "target_endpoint": tgt.to_dict() if tgt else None,
            },
        }
    }
    flags = list(lk.flags)
    if net is not None:
        a = net.address
        network = {
            "network_address": a.network_address,
            "prefix_length": a.prefix_length,
            "subnet_mask": a.subnet_mask,
        }
        for fld, origin in a.field_origin.items():
            prov[fld] = {
                "method": "ocr_direct" if origin == "ocr" else origin,
                "sources": ["ocr", "opencv", "fusion"]
                if origin == "ocr"
                else ["ocr", "fusion", "address_normalizer"],
                "evidence": {"text_id": net.label_id, "link_id": lk.id},
            }
        flags += [f"network:{f}" for f in net.flags]
    return {
        "id": lk.id,
        "source": lk.source,
        "target": lk.target,
        "network": network,
        "confidence": {
            "cable_detection": _r(cable),
            "source_endpoint": _r(src.confidence) if src else None,
            "target_endpoint": _r(tgt.confidence) if tgt else None,
            "network_label": _r(net.confidence) if net else None,
            "overall": overall,
        },
        "flags": sorted(set(flags)),
        "provenance": prov,
        "geometry": {
            "start": _pt(lk.candidate.start),
            "end": _pt(lk.candidate.end),
            "polyline": [_pt(p) for p in lk.candidate.polyline],
        },
    }


def _pt(p: tuple[float, float] | None) -> list[float] | None:
    return None if p is None else [round(p[0], 2), round(p[1], 2)]
