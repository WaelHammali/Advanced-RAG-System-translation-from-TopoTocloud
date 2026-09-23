"""Deterministic architecture completeness checks before retrieval or translation.

Readiness checks a devices/links topology JSON: names, addressing and graph
references. It does not predict reachability, repair settings or certify
implementation support.

A device's own `network` object holds its main address. Switch/bridge/hub
devices may leave every `network` field null. Every other device must have a
complete, internally consistent `network` object. Every link has its own
complete, internally consistent `network` object, plus `source_ip` and
`target_ip`: the address each end uses on that link (null only at a
switch/bridge/hub end). A router that joins two subnets therefore uses a
different endpoint IP on each link; its own `ip_address` must be one of them.
"""

from __future__ import annotations

import ipaddress
import math
from typing import Any

from .contracts import JSONObject

LAYER2_TYPES = {"switch", "bridge", "hub"}
DEVICE_NETWORK_FIELDS = ("ip_address", "prefix_length", "subnet_mask", "network_address")
LINK_NETWORK_FIELDS = ("network_address", "prefix_length", "subnet_mask")


class ArchitectureNotReady(ValueError):
    """Translation is blocked; report contains all detected input issues."""

    def __init__(self, report: JSONObject) -> None:
        self.report = report
        super().__init__(f"Architecture is not ready: {len(report['errors'])} issue(s).")


def _json_errors(value: Any) -> list[dict[str, str]]:
    """Bound nesting and reject Python-only values at the direct API boundary."""
    errors = []
    pending = [(value, "", frozenset())]
    while pending:
        item, path, ancestors = pending.pop()
        if len(ancestors) > 64 or (isinstance(item, (dict, list)) and id(item) in ancestors):
            errors.append(
                {
                    "code": "json_nesting_limit",
                    "path": path,
                    "message": "JSON nesting must not exceed 64 levels; cycles are invalid.",
                }
            )
        elif isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    errors.append(
                        {
                            "code": "invalid_json_key",
                            "path": path,
                            "message": "JSON object keys must be strings.",
                        }
                    )
                else:
                    escaped = key.replace("~", "~0").replace("/", "~1")
                    pending.append((child, path + "/" + escaped, ancestors | {id(item)}))
        elif isinstance(item, list):
            pending.extend(
                (child, f"{path}/{index}", ancestors | {id(item)})
                for index, child in enumerate(item)
            )
        elif not (
            item is None
            or type(item) in (str, bool, int)
            or (type(item) is float and math.isfinite(item))
        ):
            errors.append(
                {
                    "code": "invalid_json_value",
                    "path": path,
                    "message": "Use JSON values with finite numbers only.",
                }
            )
    return errors


def _parse_prefix(value: Any, path: str, error) -> int | None:
    if type(value) is not int or not 0 <= value <= 32:
        error("invalid_prefix_length", path, "Provide an integer prefix length from 0 to 32.")
        return None
    return value


def _parse_ipv4(value: Any, path: str, code: str, error) -> ipaddress.IPv4Address | None:
    if not isinstance(value, str):
        error(code, path, "Provide an IPv4 address string.")
        return None
    try:
        return ipaddress.IPv4Address(value)
    except ValueError:
        error(code, path, "The IPv4 address is invalid.")
        return None


def _check_mask(mask_value: Any, prefix: int | None, path: str, error) -> None:
    if not isinstance(mask_value, str):
        error("invalid_subnet_mask", path, "Provide the subnet mask as a dotted IPv4 string.")
        return
    try:
        mask = ipaddress.IPv4Address(mask_value)
    except ValueError:
        error("invalid_subnet_mask", path, "The subnet mask is not a valid IPv4 address.")
        return
    if prefix is not None and str(mask) != str(ipaddress.IPv4Network((0, prefix)).netmask):
        error(
            "subnet_mask_mismatch",
            path,
            f"subnet_mask does not match prefix_length /{prefix}.",
        )


def _check_device_network(
    network: dict, path: str, error, *, optional: bool
) -> tuple[ipaddress.IPv4Address, int] | None:
    values = {field: network.get(field) for field in DEVICE_NETWORK_FIELDS}
    if optional and all(value is None for value in values.values()):
        return None
    missing = [field for field in DEVICE_NETWORK_FIELDS if values[field] is None]
    for field in missing:
        error("missing_" + field, f"{path}/{field}", f"Provide {field}.")
    if missing:
        return None
    ip = _parse_ipv4(values["ip_address"], f"{path}/ip_address", "invalid_ip_address", error)
    prefix = _parse_prefix(values["prefix_length"], f"{path}/prefix_length", error)
    _check_mask(values["subnet_mask"], prefix, f"{path}/subnet_mask", error)
    network_address = _parse_ipv4(
        values["network_address"], f"{path}/network_address", "invalid_network_address", error
    )
    if ip is not None and prefix is not None:
        expected = ipaddress.IPv4Network(f"{ip}/{prefix}", strict=False).network_address
        if network_address is not None and network_address != expected:
            error(
                "network_address_mismatch",
                f"{path}/network_address",
                f"network_address should be {expected} for {ip}/{prefix}.",
            )
        return ip, prefix
    return None


def _check_link_network(network: dict, path: str, error) -> ipaddress.IPv4Network | None:
    values = {field: network.get(field) for field in LINK_NETWORK_FIELDS}
    missing = [field for field in LINK_NETWORK_FIELDS if values[field] is None]
    for field in missing:
        error("missing_" + field, f"{path}/{field}", f"Provide {field}.")
    if missing:
        return None
    prefix = _parse_prefix(values["prefix_length"], f"{path}/prefix_length", error)
    _check_mask(values["subnet_mask"], prefix, f"{path}/subnet_mask", error)
    if not isinstance(values["network_address"], str):
        error(
            "invalid_network_address",
            f"{path}/network_address",
            "Provide an IPv4 network address string.",
        )
        return None
    if prefix is None:
        return None
    try:
        return ipaddress.IPv4Network(f"{values['network_address']}/{prefix}", strict=True)
    except ValueError:
        error(
            "invalid_network_address",
            f"{path}/network_address",
            "network_address must be the canonical network base for this prefix (no host bits set).",
        )
        return None


def check_readiness(architecture: Any) -> JSONObject:
    """Return a machine-readable report without changing the supplied JSON."""
    errors: list[dict[str, str]] = []

    def error(code: str, path: str, message: str) -> None:
        errors.append({"code": code, "path": path, "message": message})

    def result() -> JSONObject:
        return {"ready": not errors, "status": "not_ready" if errors else "ready", "errors": errors}

    def named(value: Any) -> bool:
        return isinstance(value, str) and bool(value.strip())

    if not isinstance(architecture, dict):
        error("invalid_architecture", "", "The architecture must be a JSON object.")
        return result()
    errors.extend(_json_errors(architecture))
    if errors:
        return result()

    devices = architecture.get("devices")
    if not isinstance(devices, list) or not devices:
        error("missing_devices", "/devices", "Provide a nonempty list of devices.")
        devices = []
    device_paths: dict[str, str] = {}
    device_types: dict[str, str] = {}
    device_addresses: dict[str, tuple[ipaddress.IPv4Address, int]] = {}
    for index, device in enumerate(devices):
        path = f"/devices/{index}"
        if not isinstance(device, dict):
            error("invalid_device", path, "Each device must be an object.")
            continue
        identifier = device.get("id")
        valid_id = named(identifier)
        if not valid_id:
            error(
                "missing_device_id",
                path + "/id",
                "Give this device a nonempty unique ID, such as device_1.",
            )
        elif identifier in device_paths:
            error("duplicate_device_id", path + "/id", f"Device ID {identifier!r} is already used.")
            valid_id = False
        else:
            device_paths[identifier] = path
        if not named(device.get("name")):
            error(
                "missing_device_name",
                path + "/name",
                "Give this device a nonempty display name, such as R1.",
            )
        role = device.get("type")
        if not named(role):
            error(
                "missing_device_type",
                path + "/type",
                "Specify the device type, such as pc, router, server or switch.",
            )
        layer2 = isinstance(role, str) and role.lower() in LAYER2_TYPES
        network = device.get("network")
        address = None
        if not isinstance(network, dict):
            error(
                "missing_device_network",
                path + "/network",
                "Provide a network object; use null values for fields that do not apply.",
            )
        else:
            address = _check_device_network(network, path + "/network", error, optional=layer2)
        if valid_id:
            device_types[identifier] = role if isinstance(role, str) else ""
            if address is not None:
                device_addresses[identifier] = address

    links = architecture.get("links")
    if not isinstance(links, list) or not links:
        error("missing_links", "/links", "Provide links connecting the devices.")
        links = []
    connected: set[str] = set()
    link_ids: set[str] = set()
    link_counts: dict[str, int] = {identifier: 0 for identifier in device_paths}
    endpoint_ips: dict[str, set[ipaddress.IPv4Address]] = {}
    for index, link in enumerate(links):
        path = f"/links/{index}"
        if not isinstance(link, dict):
            error("invalid_link", path, "Each link must be an object.")
            continue
        identifier = link.get("id")
        valid_link_id = named(identifier)
        if not valid_link_id:
            error("missing_link_id", path + "/id", "Give this link a nonempty ID.")
        elif identifier in link_ids:
            error("duplicate_link_id", path + "/id", f"Link ID {identifier!r} is already used.")
            valid_link_id = False
        else:
            link_ids.add(identifier)
        # Structural validity gates connectivity; an addressing mismatch on an
        # otherwise-real cable must not make a device look isolated.
        edge_ok = valid_link_id
        ends: list[tuple[str, str]] = []  # (side, node_id)
        for side in ("source", "target"):
            node_id = link.get(side)
            if not named(node_id) or node_id not in device_types:
                error(
                    "unknown_device",
                    path + "/" + side,
                    f"This link's {side} must reference an existing device ID.",
                )
                edge_ok = False
                continue
            ends.append((side, node_id))
        if len(ends) == 2 and ends[0][1] == ends[1][1]:
            error("self_link", path, "Connect this link to another device, not itself.")
            edge_ok = False
        network = link.get("network")
        link_network = None
        if not isinstance(network, dict):
            error(
                "missing_link_network",
                path + "/network",
                "Provide this link's network object.",
            )
        else:
            link_network = _check_link_network(network, path + "/network", error)
            for side, node_id in ends:
                ip_path = f"{path}/network/{side}_ip"
                value = network.get(f"{side}_ip")
                if value is None:
                    if device_types[node_id].lower() not in LAYER2_TYPES:
                        error(
                            "missing_link_ip",
                            ip_path,
                            f"Provide the address {node_id!r} uses on this link.",
                        )
                    continue
                ip = _parse_ipv4(value, ip_path, "invalid_link_ip", error)
                if ip is None:
                    continue
                endpoint_ips.setdefault(node_id, set()).add(ip)
                if link_network is not None and ip not in link_network:
                    error(
                        "link_ip_outside_network",
                        ip_path,
                        f"{node_id!r}'s address on this link is not inside the link's network.",
                    )
        if edge_ok:
            connected.update(node_id for _, node_id in ends)
            for _, node_id in ends:
                link_counts[node_id] = link_counts.get(node_id, 0) + 1

    for identifier, path in device_paths.items():
        if identifier not in connected:
            error(
                "isolated_device",
                path,
                f"Device {identifier!r} has no valid link to another device.",
            )
        elif device_types[identifier].lower() == "pc" and link_counts[identifier] > 1:
            error(
                "too_many_links",
                path,
                f"Device {identifier!r} is a pc; a pc may have only one link.",
            )
        address = device_addresses.get(identifier)
        used = endpoint_ips.get(identifier)
        if address is not None and used and address[0] not in used:
            error(
                "device_ip_not_on_link",
                path + "/network/ip_address",
                f"Device {identifier!r}'s ip_address is not the address it uses on any link.",
            )
    return result()


def require_ready(architecture: Any) -> None:
    report = check_readiness(architecture)
    if not report["ready"]:
        raise ArchitectureNotReady(report)
