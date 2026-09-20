"""Topology Builder - the ONLY component that creates ``topology.json``.

Input : the fusion document (``fusion.json`` content). It never sees YOLO / OCR / OpenCV
        objects, so any of them can be replaced without touching this module.
Output: the canonical, network-oriented topology (devices, links, unresolved). No pixel
        geometry, no detection ids other than those already used as device ids.

It reshapes and *validates*; it never adds information. Every violated invariant raises
:class:`TopologyValidationError` rather than being silently repaired.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import __version__
from ..ocr.address_normalizer import ip_to_int, network_of, parse_host_suffix, prefix_to_mask
from ..schemas.raw import write_json

TOPOLOGY_SCHEMA_VERSION = "1.0"
NETWORK_KEYS = ("ip_address", "prefix_length", "subnet_mask", "network_address", "host_suffix")
LINK_NETWORK_KEYS = ("network_address", "prefix_length", "subnet_mask")

#: unresolved kinds that are not network information (stray labels, titles...) and stay in fusion.json only
_FUSION_ONLY_KINDS = {"text"}


class TopologyValidationError(ValueError):
    pass


class TopologyBuilder:
    def build(self, fusion: dict[str, Any]) -> dict[str, Any]:
        graph = fusion.get("graph")
        if graph is None:
            raise TopologyValidationError("fusion document has no 'graph' (was pass 10 run?)")
        image = fusion["image"]
        devices = [self._device(n) for n in graph["nodes"]]
        links = [self._link(e) for e in graph["edges"]]
        unresolved = [
            self._unresolved(u)
            for u in fusion.get("unresolved", [])
            if u.get("kind") not in _FUSION_ONLY_KINDS
        ]
        topology = {
            "schema_version": TOPOLOGY_SCHEMA_VERSION,
            "metadata": {
                "image": Path(image.get("path") or "").name or None,
                "width": image["width"],
                "height": image["height"],
                "pipeline_version": __version__,
                "source": "fusion.json",
            },
            "devices": devices,
            "links": links,
            "unresolved": unresolved,
        }
        validate_topology(topology)
        return topology

    def write(self, topology: dict[str, Any], path: str | Path) -> Path:
        validate_topology(topology)
        return write_json(path, topology)

    # ------------------------------------------------------------------------- shaping
    @staticmethod
    def _device(n: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": n["id"],
            "type": n["type"],
            "name": n.get("name"),
            "network": {k: n["network"].get(k) for k in NETWORK_KEYS},
            "addresses": [
                {
                    k: a.get(k)
                    for k in (
                        "link_id",
                        *NETWORK_KEYS,
                        "source",
                        "confidence",
                        "flags",
                        "unresolved_reason",
                        "provenance",
                    )
                }
                for a in n.get("addresses", [])
            ],
            "confidence": dict(n["confidence"]),
            "flags": list(n.get("flags", [])),
            "provenance": n.get("provenance", {}),
        }

    @staticmethod
    def _link(e: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": e["id"],
            "source": e.get("source"),
            "target": e.get("target"),
            "network": {k: e["network"].get(k) for k in LINK_NETWORK_KEYS},
            "confidence": dict(e["confidence"]),
            "flags": list(e.get("flags", [])),
            "provenance": e.get("provenance", {}),
        }

    @staticmethod
    def _unresolved(u: dict[str, Any]) -> dict[str, Any]:
        return dict(u)


# ------------------------------------------------------------------------------ validation


def validate_topology(t: dict[str, Any]) -> None:
    """Structural and arithmetic invariants of the canonical topology."""
    ids = [d["id"] for d in t["devices"]]
    if len(ids) != len(set(ids)):
        raise TopologyValidationError("duplicate device ids")
    lids = [lk["id"] for lk in t["links"]]
    if len(lids) != len(set(lids)):
        raise TopologyValidationError("duplicate link ids")
    known = set(ids)
    for lk in t["links"]:
        for end in ("source", "target"):
            if lk[end] is not None and lk[end] not in known:
                raise TopologyValidationError(f"link {lk['id']}: {end} {lk[end]!r} is not a device")
        if lk["source"] is None:
            raise TopologyValidationError(
                f"link {lk['id']}: source is null (a link needs at least one reliable endpoint)"
            )
        if lk["source"] == lk["target"]:
            raise TopologyValidationError(f"link {lk['id']}: source equals target")
        _check_addr(lk["network"], f"link {lk['id']}", host=False)
    for d in t["devices"]:
        _check_addr(d["network"], f"device {d['id']}", host=True)
        for a in d["addresses"]:
            _check_addr(a, f"device {d['id']} address", host=True)
            if a.get("ip_address") is not None and not a.get("provenance", {}).get("ip_address"):
                raise TopologyValidationError(f"device {d['id']}: ip_address without provenance")
            if a.get("link_id") is not None and a["link_id"] not in set(lids):
                raise TopologyValidationError(
                    f"device {d['id']}: address references unknown link {a['link_id']!r}"
                )


def _check_addr(a: dict[str, Any], where: str, host: bool) -> None:
    ip, prefix = a.get("ip_address"), a.get("prefix_length")
    mask, net, suffix = a.get("subnet_mask"), a.get("network_address"), a.get("host_suffix")
    if ip is not None and ip_to_int(ip) is None:
        raise TopologyValidationError(f"{where}: invalid ip_address {ip!r}")
    if prefix is not None:
        if mask is not None and prefix_to_mask(prefix) != mask:
            raise TopologyValidationError(
                f"{where}: subnet_mask {mask!r} does not match prefix /{prefix}"
            )
        if net is not None and ip is not None and network_of(ip, prefix) != net:
            raise TopologyValidationError(
                f"{where}: network_address {net!r} does not match {ip}/{prefix}"
            )
    if net is not None and ip_to_int(net) is None:
        raise TopologyValidationError(f"{where}: invalid network_address {net!r}")
    if host and suffix is not None and parse_host_suffix(suffix) is None:
        raise TopologyValidationError(f"{where}: invalid host_suffix {suffix!r}")
