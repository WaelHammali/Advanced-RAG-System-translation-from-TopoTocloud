"""Broadcast segments: the links a switch (or bridge / hub) joins into one network.

``R1 -- SW1 -- PC1`` plus ``SW1 -- PC2`` is ONE segment of three hosts (R1, PC1, PC2): all
of its links must share one network, big enough for its hosts. A cable between two routers
is a segment on its own.

A switch normally holds no address on the segment. If it does (a management IP), it is a host
of that segment too. A switch whose own addresses lie in TWO OR MORE different networks is
routing between them (a layer-3 switch): it then joins only its links that carry the same
network (the ports of one VLAN) and separates the others, like a router does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .addressing import BLOCK, is_layer2


@dataclass
class Segment:
    id: str
    link_ids: list[str]
    layer2_ids: list[str]
    #: devices that need one address on the segment (non-L2, or L2 with a management IP)
    hosts: list[str]


def _end_ip(lk: dict[str, Any], side: str, fam: int) -> Any:
    block = lk.get(BLOCK[fam])
    return block.get(f"{side}_ip") if isinstance(block, dict) else None


def _network_key(lk: dict[str, Any]) -> tuple[Any, ...] | None:
    for fam in (4, 6):
        block = lk.get(BLOCK[fam])
        if isinstance(block, dict) and block.get("network_address") is not None:
            return (fam, block["network_address"], block.get("prefix_length"))
    return None


def routing_layer2(devices: list[dict[str, Any]], links: list[dict[str, Any]]) -> set[str]:
    """Switch-type devices whose own link addresses span several networks (layer-3 switches)."""
    nets: dict[tuple[str, int], set[Any]] = {}
    for lk in links:
        for side in ("source", "target"):
            for fam in (4, 6):
                block = lk.get(BLOCK[fam])
                if _end_ip(lk, side, fam) is not None and isinstance(block, dict):
                    nets.setdefault((lk.get(side), fam), set()).add(
                        (block.get("network_address"), block.get("prefix_length"))
                    )
    l2 = {d["id"] for d in devices if is_layer2(d)}
    return {dev for (dev, _), seen in nets.items() if dev in l2 and len(seen) > 1}


def find_segments(devices: list[dict[str, Any]], links: list[dict[str, Any]]) -> list[Segment]:
    """``links`` must reference existing devices; deterministic order (first link first)."""
    by_id = {d["id"]: d for d in devices}
    routed = routing_layer2(devices, links)
    parent = list(range(len(links)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    first_link_at: dict[tuple[Any, ...], int] = {}
    for i, lk in enumerate(links):
        for side in ("source", "target"):
            dev = lk.get(side)
            if dev not in by_id or not is_layer2(by_id[dev]):
                continue
            key: tuple[Any, ...] = (dev,)
            if dev in routed:  # a layer-3 switch joins a link only to others of the same network
                net = _network_key(lk)
                if net is None:
                    continue
                key = (dev, net)
            if key in first_link_at:
                parent[root(i)] = root(first_link_at[key])
            else:
                first_link_at[key] = i

    groups: dict[int, list[int]] = {}
    for i in range(len(links)):
        groups.setdefault(root(i), []).append(i)
    segs = []
    for n, members in enumerate(sorted(groups.values(), key=min), start=1):
        link_ids, l2, hosts = [], [], []
        for i in members:
            lk = links[i]
            link_ids.append(lk["id"])
            for side in ("source", "target"):
                dev = lk.get(side)
                transparent = is_layer2(by_id[dev]) and dev not in routed
                if transparent and dev not in l2:
                    l2.append(dev)
                addressed = any(_end_ip(lk, side, fam) is not None for fam in (4, 6))
                if (not transparent or addressed) and dev not in hosts:
                    hosts.append(dev)
        segs.append(Segment(f"segment_{n}", link_ids, l2, hosts))
    return segs
