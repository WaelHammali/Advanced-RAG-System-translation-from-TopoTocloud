"""Readiness findings as (device, other device, message) triples.

The list is meant for a person or an assistant to act on. `list_issues` never
changes the architecture and does not decide what blocks translation: readiness
still does that. Same-address findings are reported here but never block, because
reusing addresses is a supported negative-lab case (see docs/edge-cases.md).

Devices are named by their `name` (falling back to `id`, then a position such
as devices[2]); links are named by their `id`.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from .readiness import check_readiness

Issue = tuple[str, str, str]  # (device, other device or "", message)

_DEVICE_PATH = re.compile(r"^/devices/(\d+)")
# Matches /links/N, /links/N/source and /links/N/network/source_ip (side captured).
_LINK_PATH = re.compile(r"^/links/(\d+)(?:/(?:network/)?(source|target)(?:_ip)?\b)?")

_DEVICE_MESSAGES = {
    "isolated_device": "not linked to any other device",
    "missing_device_id": "has no ID",
    "missing_device_name": "has no name",
    "missing_device_type": "has no type",
    "too_many_links": "is a pc with more than one link",
    "missing_device_network": "has no network information",
    "missing_ip_address": "no IP address",
    "missing_prefix_length": "IP address has no mask",
    "invalid_ip_address": "invalid IP address",
    "invalid_prefix_length": "invalid mask",
    "invalid_subnet_mask": "invalid subnet mask",
    "subnet_mask_mismatch": "subnet mask does not match the prefix length",
    "invalid_network_address": "invalid network address",
    "network_address_mismatch": "network address does not match the IP address and prefix",
    "device_ip_not_on_link": "IP address is not the one it uses on any of its links",
}
# Link endpoint-address problems are reported against the device at that end.
_ENDPOINT_MESSAGES = {
    "missing_link_ip": "no IP address on link {link}",
    "invalid_link_ip": "invalid IP address on link {link}",
    "link_ip_outside_network": "IP address on link {link} is outside the link's network",
}
_LINK_MESSAGES = {
    "missing_link_id": "has no ID",
    "missing_link_network": "has no network information",
    "missing_network_address": "network address is missing",
    "missing_prefix_length": "network prefix is missing",
    "missing_subnet_mask": "subnet mask is missing",
    "invalid_prefix_length": "invalid network prefix",
    "invalid_subnet_mask": "invalid subnet mask",
    "subnet_mask_mismatch": "subnet mask does not match the prefix length",
    "invalid_network_address": "invalid network address",
    "self_link": "connects a device to itself",
}


def _named(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _items(architecture: Any, key: str) -> list[Any]:
    items = architecture.get(key) if isinstance(architecture, dict) else None
    return items if isinstance(items, list) else []


def _at(items: list[Any], index: int) -> dict[str, Any]:
    item = items[index] if index < len(items) else None
    return item if isinstance(item, dict) else {}


def _device_name(architecture: Any, index: int) -> str:
    """The device's display name, else its ID, else a position such as devices[2]."""
    device = _at(_items(architecture, "devices"), index)
    for key in ("name", "id"):
        if _named(device.get(key)):
            return device[key]
    return f"devices[{index}]"


def _device_name_by_id(architecture: Any, device_id: Any) -> str:
    for index, device in enumerate(_items(architecture, "devices")):
        if isinstance(device, dict) and device.get("id") == device_id:
            return _device_name(architecture, index)
    return device_id if _named(device_id) else ""


def _link_name(architecture: Any, index: int) -> str:
    link = _at(_items(architecture, "links"), index)
    return link["id"] if _named(link.get("id")) else f"links[{index}]"


def _from_device_error(architecture: Any, index: int, error: dict[str, str]) -> Issue:
    name = _device_name(architecture, index)
    code = error["code"]
    if code == "duplicate_device_id":
        return name, name, "same ID as another device"
    return name, "", _DEVICE_MESSAGES.get(code) or f"{error['message']} ({error['path']})"


def _from_link_error(architecture: Any, match: re.Match[str], error: dict[str, str]) -> Issue:
    index = int(match.group(1))
    link_name = _link_name(architecture, index)
    code, side = error["code"], match.group(2)
    if code == "duplicate_link_id":
        return link_name, "", "same ID as another link"
    if code == "unknown_device" and side:
        link = _at(_items(architecture, "links"), index)
        return link_name, "", f"link {side} points to unknown device {link.get(side)!r}"
    if code in _ENDPOINT_MESSAGES and side:
        link = _at(_items(architecture, "links"), index)
        device_name = _device_name_by_id(architecture, link.get(side))
        if device_name:
            return device_name, "", _ENDPOINT_MESSAGES[code].format(link=link_name)
    return link_name, "", _LINK_MESSAGES.get(code) or f"{error['message']} ({error['path']})"


def _from_error(architecture: Any, error: dict[str, str]) -> Issue:
    path = error["path"]
    link = _LINK_PATH.match(path)
    if link:
        return _from_link_error(architecture, link, error)
    device = _DEVICE_PATH.match(path)
    if device:
        return _from_device_error(architecture, int(device.group(1)), error)
    located = path not in ("", "/devices", "/links")
    return "", "", f"{error['message']} ({path})" if located else error["message"]


def _address(value: Any) -> ipaddress.IPv4Address | None:
    try:
        return ipaddress.IPv4Address(value)
    except (TypeError, ValueError):
        return None


def _address_conflicts(architecture: Any) -> list[Issue]:
    """Two devices using the same IP (own or on a link) inside one connected group."""
    parent: dict[str, str] = {}

    def find(node: str) -> str:
        while parent.setdefault(node, node) != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    used: dict[str, set[ipaddress.IPv4Address]] = {}
    for link in _items(architecture, "links"):
        if not isinstance(link, dict):
            continue
        source, target = link.get("source"), link.get("target")
        if _named(source) and _named(target):
            parent[find(source)] = find(target)
        network = link.get("network")
        if not isinstance(network, dict):
            continue
        for side in ("source", "target"):
            node, address = link.get(side), _address(network.get(f"{side}_ip"))
            if _named(node) and address is not None:
                used.setdefault(node, set()).add(address)

    first_use: dict[tuple[str, ipaddress.IPv4Address], tuple[str, int]] = {}
    conflicts: list[Issue] = []
    for index, device in enumerate(_items(architecture, "devices")):
        if not isinstance(device, dict) or not _named(device.get("id")):
            continue
        device_id = device["id"]
        network = device.get("network")
        addresses = set(used.get(device_id, set()))
        own = _address(network.get("ip_address")) if isinstance(network, dict) else None
        if own is not None:
            addresses.add(own)
        name = _device_name(architecture, index)
        for address in sorted(addresses):
            owner = first_use.setdefault((find(device_id), address), (name, index))
            if owner[1] != index:
                conflicts.append((name, owner[0], f"same IP address as {owner[0]}"))
    return conflicts


def list_issues(architecture: Any) -> list[Issue]:
    """Every readiness problem plus same-address clashes, as (device, other, message).

    `other` is empty when the problem concerns one device; it names the second
    device for a shared ID or a shared IP address (`device` is the later one).
    Problems that belong to no device (such as a missing link list) have an
    empty device. Order follows the readiness report, then address clashes.
    """
    issues = [_from_error(architecture, e) for e in check_readiness(architecture)["errors"]]
    return issues + _address_conflicts(architecture)
