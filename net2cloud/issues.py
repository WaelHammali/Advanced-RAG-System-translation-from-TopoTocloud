"""Stable clarification tuples and advisory topology findings; no conversation agent."""

from __future__ import annotations

import ipaddress
from typing import Any

Issue = tuple[str, str, str]  # (entity ID or "", exact JSON Pointer, message)


def issue_entity(architecture: Any, path: str) -> str:
    """Resolve an issue's owner without relying on non-unique display names."""
    parts = path.split("/")
    if not isinstance(architecture, dict) or len(parts) < 3:
        return ""
    items = architecture.get(parts[1])
    if parts[1] not in {"devices", "links"} or not isinstance(items, list):
        return ""
    try:
        item = items[int(parts[2])]
    except (ValueError, IndexError):
        return ""
    identifier = item.get("id") if isinstance(item, dict) else None
    return identifier if isinstance(identifier, str) and identifier.strip() else ""


def issue_tuple(architecture: Any, finding: dict) -> Issue:
    return issue_entity(architecture, finding["path"]), finding["path"], finding["message"]


def address_warnings(architecture: dict) -> list[dict[str, str]]:
    """Detect duplicate endpoint IPs on the same L2 segment, without joining routers."""
    devices = {d["id"]: d for d in architecture["devices"]}
    parent: dict[tuple[int, str], tuple[int, str]] = {}

    def find(key):
        parent.setdefault(key, key)
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def join(a, b):
        parent[find(a)] = find(b)

    bridge_port = {}
    for index, link in enumerate(architecture["links"]):
        join((index, "source"), (index, "target"))
        for side in ("source", "target"):
            device = devices[link[side]]
            if device["type"].lower() in {"switch", "bridge", "hub"}:
                first = bridge_port.setdefault(device["id"], (index, side))
                join(first, (index, side))
    owners = {}
    warnings = []
    for index, link in enumerate(architecture["links"]):
        for side in ("source", "target"):
            value = link["network"].get(side + "_ip")
            if value is None:
                continue
            key = (find((index, side)), ipaddress.IPv4Address(value))
            owner = owners.setdefault(key, link[side])
            if owner != link[side]:
                warnings.append(
                    {
                        "code": "duplicate_lan_ip",
                        "path": f"/links/{index}/network/{side}_ip",
                        "message": f"Address {value} is also used by device {owner!r} on this LAN; preserve only if intentional.",
                    }
                )
    return warnings


def list_issues(architecture: Any) -> list[Issue]:
    """Return blocking issues only; advisory findings are in report.warning_issues."""
    from .readiness import check_readiness

    return check_readiness(architecture)["issues"]
