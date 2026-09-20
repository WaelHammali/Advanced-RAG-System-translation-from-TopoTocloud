"""Readiness findings as (component, other component, message) triples.

The list is meant for a person or an assistant to act on. `list_issues` never
changes the architecture and does not decide what blocks translation: readiness
still does that. Same-address findings are reported here but never block, because
reusing addresses is a supported negative-lab case (see docs/edge-cases.md).

Components are named by their ID (or display name); the input is expected to give
every component a unique name, so a missing one falls back to `components[i]`.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from .readiness import check_readiness

Issue = tuple[str, str, str]  # (component, other component or "", message)

_COMPONENT_PATH = re.compile(r"^/components/(\d+)(?:/interfaces/(\d+))?")
_EDGE_PATH = re.compile(r"^/edges/(\d+)(?:/(source|target))?")
_UNKNOWN_REFERENCE = {"unknown_component": "component", "unknown_interface": "interface"}


def _named(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _items(architecture: Any, key: str) -> list[Any]:
    items = architecture.get(key) if isinstance(architecture, dict) else None
    return items if isinstance(items, list) else []


def _at(items: list[Any], index: int) -> dict[str, Any]:
    item = items[index] if index < len(items) else None
    return item if isinstance(item, dict) else {}


def _name(architecture: Any, index: int) -> str:
    """The component's ID, else its display name, else a position such as components[2]."""
    component = _at(_items(architecture, "components"), index)
    for key in ("id", "name"):
        if _named(component.get(key)):
            return component[key]
    return f"components[{index}]"


def _invalid_part(value: Any) -> str:
    """Say whether the address or the mask is wrong; a bad mask is negative, above 32 or not a number."""
    try:
        ipaddress.IPv4Address(str(value).partition("/")[0].strip())
    except ValueError:
        return "invalid IP address"
    return "invalid mask"


def _interface(architecture: Any, index: int, port_index: int) -> tuple[str, Any]:
    """An interface's label and its ipv4 value."""
    port = _at(_at(_items(architecture, "components"), index).get("interfaces") or [], port_index)
    label = port["id"] if _named(port.get("id")) else f"interfaces[{port_index}]"
    return label, port.get("ipv4")


def _edge_issue(architecture: Any, match: re.Match[str], error: dict[str, str]) -> Issue:
    edge = _at(_items(architecture, "edges"), int(match.group(1)))
    name = edge["id"] if _named(edge.get("id")) else f"edges[{match.group(1)}]"
    side, what = match.group(2), _UNKNOWN_REFERENCE.get(error["code"])
    end = edge.get(side) if side else None
    if what and isinstance(end, dict):
        return name, "", f"link {side} points to unknown {what} {end.get(what)!r}"
    return name, "", error["message"]


def _from_error(architecture: Any, error: dict[str, str]) -> Issue:
    code, path = error["code"], error["path"]
    edge = _EDGE_PATH.match(path)
    if edge:
        return _edge_issue(architecture, edge, error)
    match = _COMPONENT_PATH.match(path)
    if not match:
        located = path not in ("", "/components", "/edges")
        return "", "", f"{error['message']} ({path})" if located else error["message"]
    index = int(match.group(1))
    name = _name(architecture, index)
    port, value = "", None
    if match.group(2):
        port, value = _interface(architecture, index, int(match.group(2)))
    messages = {
        "missing_ip_address": "no IP address",
        "missing_ip_prefix": "IP address has no mask",
        "invalid_ip_address": _invalid_part(value),
        "isolated_component": "not linked to any other component",
        "missing_component_id": "has no name",
        "missing_component_type": "has no type",
        "missing_interfaces": "has no interfaces",
        "missing_interface_id": f"interface {port} has no name",
        "duplicate_interface_id": f"interface {port} is defined twice",
    }
    if code == "duplicate_component_id":
        return name, name, "same name as another component"
    return name, "", messages.get(code) or f"{error['message']} ({path})"


def _address_conflicts(architecture: Any) -> list[Issue]:
    """Two enabled interfaces with the same IP inside one connected group."""
    parent: dict[str, str] = {}

    def find(node: str) -> str:
        while parent.setdefault(node, node) != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for edge in _items(architecture, "edges"):
        ends = [edge.get(side) for side in ("source", "target")] if isinstance(edge, dict) else []
        linked = [
            e["component"] for e in ends if isinstance(e, dict) and _named(e.get("component"))
        ]
        if len(linked) == 2:
            parent[find(linked[0])] = find(linked[1])
    first_use: dict[tuple[str, ipaddress.IPv4Address], tuple[str, int, int]] = {}
    conflicts: list[Issue] = []
    for index, component in enumerate(_items(architecture, "components")):
        if not isinstance(component, dict):
            continue
        name = _name(architecture, index)
        for port_index, port in enumerate(_items(component, "interfaces")):
            if not isinstance(port, dict) or port.get("enabled") is False:
                continue
            try:
                address = ipaddress.IPv4Address(port["ipv4"].partition("/")[0].strip())
            except (AttributeError, KeyError, ValueError):
                continue
            owner = first_use.setdefault((find(name), address), (name, index, port_index))
            if owner[1:] != (index, port_index):
                conflicts.append((name, owner[0], f"same IP address as {owner[0]}"))
    return conflicts


def list_issues(architecture: Any) -> list[Issue]:
    """Every readiness problem plus same-address clashes, as (component, other, message).

    `other` is empty when the problem concerns one component; it names the second
    component for a shared IP address (`component` is the later one). Problems that belong to no
    component (such as a missing link list) have an empty component. Order follows
    the readiness report, then address clashes.
    """
    issues = [_from_error(architecture, e) for e in check_readiness(architecture)["errors"]]
    return issues + _address_conflicts(architecture)
