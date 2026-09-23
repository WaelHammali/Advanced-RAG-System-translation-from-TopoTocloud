"""Apply explicit clarification tuples transactionally, then recheck readiness."""

from __future__ import annotations

import ipaddress
from copy import deepcopy
from typing import Any

from .issues import issue_entity
from .readiness import _json_errors, check_readiness


class CorrectionError(ValueError):
    """A correction batch is ambiguous, stale or outside the topology contract."""


def _target(architecture: dict, path: str):
    parts = path.split("/")[1:]
    allowed = {
        "devices": {"id", "name", "type"},
        "links": {"id", "source", "target"},
    }
    if len(parts) == 1 and parts[0] in allowed:
        return architecture, parts[0]
    if len(parts) not in (3, 4) or parts[0] not in allowed:
        raise CorrectionError(f"Unsupported correction path: {path}")
    try:
        if str(int(parts[1])) != parts[1] or int(parts[1]) < 0:
            raise ValueError
        item = architecture[parts[0]][int(parts[1])]
        if not isinstance(item, dict):
            raise ValueError
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise CorrectionError(f"Correction target does not exist: {path}") from exc
    if len(parts) == 3 and parts[2] in allowed[parts[0]] | {"network"}:
        return item, parts[2]
    fields = {"network_address", "prefix_length", "subnet_mask"}
    fields |= {"ip_address"} if parts[0] == "devices" else {"source_ip", "target_ip"}
    if len(parts) == 4 and parts[2] == "network" and parts[3] in fields:
        if item.get("network") is None:
            item["network"] = {}
        if isinstance(item["network"], dict):
            return item["network"], parts[3]
    raise CorrectionError(f"Unsupported correction path: {path}")


def _derive_network(network: dict, changed: set[str]) -> None:
    """Recompute redundant mask/base fields, without inventing endpoint addresses."""
    try:
        prefix = network.get("prefix_length")
        if "subnet_mask" in changed and "prefix_length" not in changed:
            mask = network["subnet_mask"]
            if not isinstance(mask, str):
                return
            parsed = ipaddress.IPv4Network("0.0.0.0/" + mask)
            if str(parsed.netmask) != mask:  # host masks are not subnet masks
                return
            prefix = network["prefix_length"] = parsed.prefixlen
        if type(prefix) is not int or not 0 <= prefix <= 32:
            return
        address = network.get("ip_address", network.get("network_address"))
        if not isinstance(address, str):
            return
        subnet = ipaddress.IPv4Network(f"{address}/{prefix}", strict=False)
        if "subnet_mask" not in changed:
            network["subnet_mask"] = str(subnet.netmask)
        if "network_address" not in changed:
            network["network_address"] = str(subnet.network_address)
    except (ValueError, KeyError):
        return  # The readiness report describes invalid user-supplied values.


def apply_corrections(architecture: Any, corrections: list, *, expected_revision: str) -> dict:
    """Return {architecture, validation}; never mutate input or call a model.

    Corrections are (entity_id, JSON_pointer, replacement_value). Whole devices/links
    lists use an empty entity ID. A batch may remain not_ready after partial repair.
    """
    report = check_readiness(architecture)
    if not report["revision"] or expected_revision != report["revision"]:
        raise CorrectionError("Stale or unavailable revision; request a fresh readiness report.")
    if not isinstance(corrections, list):
        raise CorrectionError("Corrections must be a list of triples.")
    normalized = []
    for item in corrections:
        if not isinstance(item, (tuple, list)) or len(item) != 3:
            raise CorrectionError("Each correction must be (entity_id, path, value).")
        entity, path, value = item
        if not isinstance(entity, str) or not isinstance(path, str) or _json_errors(value):
            raise CorrectionError("Correction IDs/paths must be strings and values must be JSON.")
        if entity != issue_entity(architecture, path):
            raise CorrectionError(f"Entity ID does not match correction path: {path}")
        normalized.append((path, value))
    paths = [path for path, _ in normalized]
    for index, path in enumerate(paths):
        if any(
            path == other or path.startswith(other + "/") or other.startswith(path + "/")
            for other in paths[:index]
        ):
            raise CorrectionError("Correction paths must not overlap or repeat.")
    updated = deepcopy(architecture)
    for path, value in normalized:
        target, key = _target(updated, path)
        target[key] = deepcopy(value)

    if any(path in {"/devices", "/links"} for path in paths):
        return {"architecture": updated, "validation": check_readiness(updated)}

    devices = updated.get("devices")
    links = updated.get("links")
    original_devices = architecture.get("devices", [])
    if isinstance(devices, list) and isinstance(links, list):
        # Resolve simultaneous renames against the original graph. Sequential
        # replacement would miswire links when two IDs are swapped.
        renames = {}
        for index, device in enumerate(devices):
            original = original_devices[index]
            if not isinstance(device, dict) or not isinstance(original, dict):
                continue
            old_id = original.get("id")
            if (
                f"/devices/{index}/id" in paths
                and isinstance(old_id, str)
                and old_id
                and sum(isinstance(d, dict) and d.get("id") == old_id for d in original_devices)
                == 1
            ):
                renames[old_id] = device.get("id")
        for li, link in enumerate(links):
            if not isinstance(link, dict):
                continue
            original = architecture["links"][li]
            for side in ("source", "target"):
                old_id = original.get(side) if isinstance(original, dict) else None
                if (
                    isinstance(old_id, str)
                    and old_id in renames
                    and f"/links/{li}/{side}" not in paths
                ):
                    link[side] = renames[old_id]
        for index, device in enumerate(devices):
            if not isinstance(device, dict) or index >= len(original_devices):
                continue
            original = original_devices[index]
            if not isinstance(original, dict):
                continue
            ip_path = f"/devices/{index}/network/ip_address"
            if ip_path in paths and isinstance(device.get("network"), dict):
                old_network = original.get("network")
                old_ip = old_network.get("ip_address") if isinstance(old_network, dict) else None
                endpoints = [
                    (li, side, link)
                    for li, link in enumerate(links)
                    if isinstance(link, dict)
                    for side in ("source", "target")
                    if link.get(side) == device.get("id")
                ]
                for li, side, link in endpoints:
                    network = link.get("network")
                    endpoint_path = f"/links/{li}/network/{side}_ip"
                    if isinstance(network, dict) and endpoint_path not in paths:
                        if (
                            old_ip is not None
                            and network.get(side + "_ip") == old_ip
                            or old_ip is None
                            and len(endpoints) == 1
                        ):
                            network[side + "_ip"] = device["network"].get("ip_address")
        # Mirror an explicitly corrected link endpoint back to a matching main address.
        for path, value in normalized:
            parts = path.split("/")
            if (
                len(parts) != 5
                or parts[1] != "links"
                or parts[3] != "network"
                or parts[4] not in {"source_ip", "target_ip"}
            ):
                continue
            li, side = int(parts[2]), parts[4].removesuffix("_ip")
            old = architecture.get("links", [])[li]
            old_network = old.get("network") if isinstance(old, dict) else None
            old_ip = old_network.get(parts[4]) if isinstance(old_network, dict) else None
            for di, device in enumerate(devices):
                if not isinstance(device, dict) or device.get("id") != links[li].get(side):
                    continue
                network = device.get("network")
                main_path = f"/devices/{di}/network/ip_address"
                if (
                    isinstance(network, dict)
                    and old_ip is not None
                    and network.get("ip_address") == old_ip
                    and main_path not in paths
                ):
                    network["ip_address"] = value
                    device_prefix = f"/devices/{di}/network/"
                    explicit = {
                        p[len(device_prefix) :] for p in paths if p.startswith(device_prefix)
                    }
                    _derive_network(network, {"ip_address", *explicit})
    for group in ("devices", "links"):
        items = updated.get(group, [])
        if not isinstance(items, list):
            continue
        for index, item in enumerate(items):
            prefix = f"/{group}/{index}/network/"
            changed = {p[len(prefix) :] for p in paths if p.startswith(prefix)}
            if isinstance(item, dict) and isinstance(item.get("network"), dict) and changed:
                _derive_network(item["network"], changed)
    return {"architecture": updated, "validation": check_readiness(updated)}
