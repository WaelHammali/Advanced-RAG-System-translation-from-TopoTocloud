"""Auto-addressing: give the whole topology a clean VLSM plan (IPv4 and IPv6).

The user's alternative to fixing addresses one by one. Every address, mask and network is
recomputed from the graph alone:

1. segments - the links a switch joins are one broadcast segment (:mod:`.segments`); each
   segment needs one address per device on it (routers, PCs, servers, a switch's
   management IP, a layer-3 switch's interface).
2. size     - IPv4: the smallest block that fits (hosts + network + broadcast, at least a
   /30); IPv6: a /64 per segment (the standard LAN size), or - with ``ipv6_prefix=None`` - the
   smallest block that fits, like IPv4.
3. VLSM     - the largest segments are placed first, each block aligned to its own size, one
   after the other inside the base network, so blocks never overlap and no space is wasted
   between them. A base too small for the plan is an error (never a silent overlap).
4. hosts    - in each segment the first usable address goes to the gateway (routers first,
   then firewalls, servers, switches, then the rest, in document order).

Names, types, ids and links are kept; only ``network`` / ``network6`` blocks are rewritten.
The result is validated like any other topology.
"""

from __future__ import annotations

import copy
import ipaddress
from typing import Any

from .addressing import BLOCK, DEVICE_FIELDS, MAX_PREFIX, prefix_mask, smallest_prefix, usable_hosts
from .segments import Segment, find_segments
from .validator import validate

DEFAULT_IPV4_BASE = "192.168.0.0/16"
#: the IPv6 documentation prefix (RFC 3849), 65536 /64 segments
DEFAULT_IPV6_BASE = "2001:db8::/48"
_ROLE_ORDER = {"router": 0, "firewall": 1, "server": 2, "switch": 3, "bridge": 3, "hub": 3}


class AutoAddressError(ValueError):
    pass


def autoaddress(
    doc: dict[str, Any],
    *,
    ipv4_base: str | None = DEFAULT_IPV4_BASE,
    ipv6_base: str | None = None,
    ipv6_prefix: int | None = 64,
    require_ipv4: bool = True,
) -> dict[str, Any]:
    """Returns ``{"topology", "plan", "report"}``; ``doc`` itself is not changed.

    ``ipv4_base`` / ``ipv6_base`` = the address space to carve (``None`` = leave that family
    alone). IPv6 is addressed when ``ipv6_base`` is given, or - with the default base - when the
    topology already carries IPv6 (``network6`` blocks).
    """
    work = copy.deepcopy(doc)
    devices = [
        d for d in work.get("devices", []) if isinstance(d, dict) and isinstance(d.get("id"), str)
    ]
    by_id = {d["id"]: d for d in devices}
    links = [
        lk
        for lk in work.get("links", [])
        if isinstance(lk, dict)
        and lk.get("source") in by_id
        and lk.get("target") in by_id
        and lk["source"] != lk["target"]
        and isinstance(lk.get("id"), str)
    ]
    if ipv6_base is None and any("network6" in x for x in devices + links):
        ipv6_base = DEFAULT_IPV6_BASE
    order = {d["id"]: i for i, d in enumerate(devices)}
    segs = find_segments(devices, links)

    plan: dict[str, Any] = {"segments": []}
    assigned: dict[int, dict[tuple[str, str], str]] = {}
    nets: dict[int, dict[str, Any]] = {}
    for fam, base in ((4, ipv4_base), (6, ipv6_base)):
        if base is None:
            continue
        space = _base_network(base, fam)
        nets[fam] = _vlsm(segs, space, fam, ipv6_prefix)
        assigned[fam] = {}
        for s in segs:
            net = nets[fam][s.id]
            hosts = sorted(
                s.hosts,
                key=lambda dev: (
                    _ROLE_ORDER.get(str(by_id[dev].get("type")).lower(), 4),
                    order[dev],
                ),
            )
            for n, dev in enumerate(hosts, start=1):
                assigned[fam][(s.id, dev)] = str(net.network_address + n)
        plan[f"ipv{fam}_base"] = str(space)

    seg_of = {lid: s for s in segs for lid in s.link_ids}
    for fam in nets:
        block = BLOCK[fam]
        for lk in links:
            s = seg_of[lk["id"]]
            net = nets[fam][s.id]
            values: dict[str, Any] = {
                "network_address": str(net.network_address),
                "prefix_length": net.prefixlen,
            }
            if fam == 4:
                values["subnet_mask"] = prefix_mask(net.prefixlen)
            for side in ("source", "target"):
                values[f"{side}_ip"] = assigned[fam].get((s.id, lk[side]))
            lk[block] = values
        for d in devices:
            mine = [lk for lk in links if d["id"] in (lk["source"], lk["target"])]
            first = next(
                (
                    seg_of[lk["id"]]
                    for lk in mine
                    if (seg_of[lk["id"]].id, d["id"]) in assigned[fam]
                ),
                None,
            )
            if first is None:
                if fam == 4 or block in d:
                    d[block] = dict.fromkeys(DEVICE_FIELDS[fam])
                continue
            net = nets[fam][first.id]
            values = {
                "ip_address": assigned[fam][(first.id, d["id"])],
                "prefix_length": net.prefixlen,
            }
            if fam == 4:
                values["subnet_mask"] = prefix_mask(net.prefixlen)
            values["network_address"] = str(net.network_address)
            d[block] = values

    for s in segs:
        entry: dict[str, Any] = {"id": s.id, "links": s.link_ids, "hosts": len(s.hosts)}
        for fam in nets:
            net = nets[fam][s.id]
            entry[f"ipv{fam}"] = {
                "network": str(net),
                "usable": usable_hosts(net.prefixlen, fam),
                "addresses": {dev: assigned[fam][(s.id, dev)] for dev in s.hosts},
            }
            if fam == 4:
                entry["ipv4"]["mask"] = prefix_mask(net.prefixlen)
        plan["segments"].append(entry)
    return {"topology": work, "plan": plan, "report": validate(work, require_ipv4=require_ipv4)}


def _base_network(text: str, fam: int):
    try:
        net = ipaddress.ip_network(text, strict=True)
    except ValueError as exc:
        raise AutoAddressError(f"{text!r} is not a network like 192.168.0.0/16 ({exc}).") from None
    if net.version != fam:
        raise AutoAddressError(f"{text!r} is not an IPv{fam} network.")
    return net


def _segment_prefix(hosts: int, fam: int, ipv6_prefix: int | None) -> int:
    if fam == 4:
        return smallest_prefix(hosts, 4)
    if ipv6_prefix is not None:
        if not 0 < ipv6_prefix <= 126:
            raise AutoAddressError("ipv6_prefix must be between 1 and 126.")
        if usable_hosts(ipv6_prefix, 6) < hosts:
            raise AutoAddressError(f"/{ipv6_prefix} cannot hold {hosts} devices.")
        return ipv6_prefix
    for prefix in range(126, 0, -1):  # tight VLSM, like IPv4
        if usable_hosts(prefix, 6) >= max(hosts, 1):
            return prefix
    raise AutoAddressError("segment too large")  # pragma: no cover - 2**126 devices


def _vlsm(segs: list[Segment], space, fam: int, ipv6_prefix: int | None) -> dict[str, Any]:
    """Largest first, each block aligned to its size, packed from the start of ``space``."""
    need = {s.id: _segment_prefix(len(s.hosts), fam, ipv6_prefix) for s in segs}
    total = sum(2 ** (MAX_PREFIX[fam] - p) for p in need.values())
    if total > space.num_addresses:
        raise AutoAddressError(
            f"{space} has {space.num_addresses} addresses but the plan needs {total}; "
            "give a bigger base network."
        )
    out: dict[str, Any] = {}
    cursor = int(space.network_address)
    for s in sorted(segs, key=lambda s: (need[s.id], [x.id for x in segs].index(s.id))):
        size = 2 ** (MAX_PREFIX[fam] - need[s.id])
        cursor = -(-cursor // size) * size  # align (already aligned when sorted largest first)
        out[s.id] = (ipaddress.IPv4Network if fam == 4 else ipaddress.IPv6Network)(
            (cursor, need[s.id])
        )
        cursor += size
    return out
