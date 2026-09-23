"""Topology Builder - the ONLY component that creates ``topology.json``.

Input : the fusion document (``fusion.json`` content). It never sees YOLO / OCR / OpenCV
        objects, so any of them can be replaced without touching this module.
Output: the canonical, network-oriented topology (devices, links, unresolved). No pixel
        geometry, no detection ids other than those already used as device ids.

It reshapes and *validates*; it never adds information. Every violated invariant raises
:class:`TopologyValidationError` rather than being silently repaired.
"""

from __future__ import annotations

import re
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


_ID_RE = re.compile(r"^(?P<prefix>[A-Za-z]+)_0*(?P<num>\d+)$")
SIMPLE_NETWORK_KEYS = ("ip_address", "prefix_length", "subnet_mask", "network_address")
#: the RAG input contract: a link's network also names the address each end uses on it
SIMPLE_LINK_NETWORK_KEYS = (
    "network_address",
    "prefix_length",
    "subnet_mask",
    "source_ip",
    "target_ip",
)


def _short_id(ident: str) -> str:
    """``device_001`` -> ``device_1`` (ids that do not follow the pattern are kept)."""
    m = _ID_RE.match(ident)
    return f"{m['prefix']}_{int(m['num'])}" if m else ident


class TopologyBuilder:
    def __init__(self, type_aliases: dict[str, str] | None = None) -> None:
        self.type_aliases = dict(type_aliases or {})

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

    # ------------------------------------------------------------- minimal RAG form
    def build_simple(self, topology: dict[str, Any]) -> dict[str, Any]:
        """Project the canonical topology onto the minimal form handed to the RAG.

        Devices (id, type, name, 4-key network) and links (id, source, target, network with
        the address each end uses on that link: ``source_ip`` / ``target_ip``), matching the
        RAG input contract. Nothing is invented; every value comes from ``topology.json``:

        * a link end's address is the device address bound to that link, or the device's
          address that lies inside the link's network, or - for a device with a single link
          only - its one address. Anything ambiguous stays null.
        * a link with no network label takes the network its known end addresses agree on
          (a cable is one network); if they disagree or carry no prefix, it stays null.
        * a device's own ``network`` is its single address, or - for a device on several
          links (a router joining subnets) - the address it uses on its first link, since the
          contract requires one main address that is one of its link addresses.
        """
        ids = [d["id"] for d in topology["devices"]] + [lk["id"] for lk in topology["links"]]
        short = {i: _short_id(i) for i in ids}
        if len(set(short.values())) != len(short):  # renumbering would collide: keep original ids
            short = {i: i for i in ids}
        by_id = {d["id"]: d for d in topology["devices"]}
        links_of: dict[str, list[str]] = {}
        for lk in topology["links"]:
            for end in ("source", "target"):
                if lk[end] is not None:
                    links_of.setdefault(lk[end], []).append(lk["id"])

        link_net = {lk["id"]: _link_network(lk["network"]) for lk in topology["links"]}
        ends: dict[tuple[str, str], dict[str, Any] | None] = {}
        for lk in topology["links"]:
            for end in ("source", "target"):
                if lk[end] is not None:
                    ends[(lk["id"], lk[end])] = _endpoint_address(
                        by_id[lk[end]], lk["id"], link_net[lk["id"]], len(links_of[lk[end]])
                    )
        for lk in topology["links"]:  # an unlabelled cable is the one network its ends agree on
            if link_net[lk["id"]] is None:
                known = {
                    (a["network_address"], a["prefix_length"])
                    for end in ("source", "target")
                    if lk[end] is not None
                    for a in [ends[(lk["id"], lk[end])]]
                    if a and a["prefix_length"] is not None
                }
                if len(known) == 1:
                    net, prefix = known.pop()
                    link_net[lk["id"]] = {
                        "network_address": net,
                        "prefix_length": prefix,
                        "subnet_mask": prefix_to_mask(prefix),
                    }

        devices = []
        for d in topology["devices"]:
            network = {k: d["network"][k] for k in SIMPLE_NETWORK_KEYS}
            if network["ip_address"] is None:
                used = [ends[(lid, d["id"])] for lid in links_of.get(d["id"], [])]
                first = next((a for a in used if a is not None), None)
                if first is not None:
                    network = {k: first[k] for k in SIMPLE_NETWORK_KEYS}
            devices.append(
                {
                    "id": short[d["id"]],
                    "type": self.type_aliases.get(d["type"], d["type"]),
                    "name": d["name"],
                    "network": network,
                }
            )
        links = []
        for lk in topology["links"]:
            net = link_net[lk["id"]] or dict.fromkeys(LINK_NETWORK_KEYS)
            end_ip = {
                end: None
                if lk[end] is None or ends[(lk["id"], lk[end])] is None
                else ends[(lk["id"], lk[end])]["ip_address"]
                for end in ("source", "target")
            }
            links.append(
                {
                    "id": short[lk["id"]],
                    "source": short[lk["source"]],
                    "target": None if lk["target"] is None else short[lk["target"]],
                    "network": {
                        **{k: net[k] for k in LINK_NETWORK_KEYS},
                        "source_ip": end_ip["source"],
                        "target_ip": end_ip["target"],
                    },
                }
            )
        simple = {"devices": devices, "links": links}
        validate_simple(simple)
        return simple

    def write_simple(self, simple: dict[str, Any], path: str | Path) -> Path:
        validate_simple(simple)
        return write_json(path, simple)

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


# ------------------------------------------------------------------ minimal-form helpers


def _link_network(network: dict[str, Any]) -> dict[str, Any] | None:
    if network.get("network_address") is None or network.get("prefix_length") is None:
        return None
    return {k: network.get(k) for k in LINK_NETWORK_KEYS}


def _endpoint_address(
    device: dict[str, Any], link_id: str, link_net: dict[str, Any] | None, n_links: int
) -> dict[str, Any] | None:
    """The address ``device`` uses on ``link_id``, or ``None`` if that is not certain."""
    known = [a for a in device.get("addresses", []) if a.get("ip_address") is not None]

    def unique(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
        distinct = {a["ip_address"] for a in entries}
        return entries[0] if len(distinct) == 1 else None

    bound = [a for a in known if a.get("link_id") == link_id]
    if bound:
        return unique(bound)
    unbound = [a for a in known if a.get("link_id") is None]
    if not unbound:
        return None
    if link_net is not None:
        inside = [
            a
            for a in unbound
            if network_of(a["ip_address"], link_net["prefix_length"]) == link_net["network_address"]
        ]
        return unique(inside) if inside else None
    return unique(unbound) if n_links == 1 else None  # a single-link device uses it there


# ------------------------------------------------------------------------------ validation


def validate_topology(t: dict[str, Any]) -> None:
    """Structural and arithmetic invariants of the canonical topology."""
    ids = [d["id"] for d in t["devices"]]
    if len(ids) != len(set(ids)):
        raise TopologyValidationError("duplicate device ids")
    lids = [lk["id"] for lk in t["links"]]
    if len(lids) != len(set(lids)):
        raise TopologyValidationError("duplicate link ids")
    names = [d["name"] for d in t["devices"] if d["name"] is not None]
    if len(names) != len(set(names)):
        raise TopologyValidationError(
            "duplicate device name (graph_builder should have deduplicated it)"
        )
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


def validate_simple(t: dict[str, Any]) -> None:
    if set(t) != {"devices", "links"}:
        raise TopologyValidationError("minimal topology must contain exactly 'devices' and 'links'")
    ids = [d["id"] for d in t["devices"]]
    if len(ids) != len(set(ids)) or len({lk["id"] for lk in t["links"]}) != len(t["links"]):
        raise TopologyValidationError("duplicate ids in minimal topology")
    for d in t["devices"]:
        if set(d) != {"id", "type", "name", "network"} or set(d["network"]) != set(
            SIMPLE_NETWORK_KEYS
        ):
            raise TopologyValidationError(f"device {d.get('id')}: unexpected shape")
        _check_addr(d["network"], f"device {d['id']}", host=False)
    for lk in t["links"]:
        if set(lk) != {"id", "source", "target", "network"} or set(lk["network"]) != set(
            SIMPLE_LINK_NETWORK_KEYS
        ):
            raise TopologyValidationError(f"link {lk.get('id')}: unexpected shape")
        for end in ("source", "target"):
            if lk[end] is not None and lk[end] not in set(ids):
                raise TopologyValidationError(f"link {lk['id']}: {end} {lk[end]!r} is not a device")
            ip = lk["network"][f"{end}_ip"]
            if ip is not None and (lk[end] is None or ip_to_int(ip) is None):
                raise TopologyValidationError(f"link {lk['id']}: invalid {end}_ip {ip!r}")
        _check_addr(
            {k: lk["network"][k] for k in LINK_NETWORK_KEYS}, f"link {lk['id']}", host=False
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
