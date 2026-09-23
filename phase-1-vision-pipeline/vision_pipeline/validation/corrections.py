"""User corrections to ``topology.simple.json``, strictly checked before they are applied.

The agent / UI sends a list of small changes; each one is checked on its own and either
applied or rejected with a reason (nothing half-applied). The corrected topology is then
validated again, so the loop is: validate -> show errors -> user corrects -> validate ... until
the report is valid (or the user picks auto-addressing instead, see :mod:`.autoaddress`).

A correction is one JSON object. The family (IPv4 / IPv6) always follows from the value::

    {"device": "device_3", "ip": "192.168.1.12/24"}              device address (CIDR form)
    {"device": "device_3", "ip": "192.168.1.12", "mask": "255.255.255.0"}
    {"device": "R1", "link": "link_2", "ip": "10.0.0.1/30"}      its address on ONE link
    {"device": "device_3", "ip": "2001:db8:1::12/64"}            IPv6 goes to network6
    {"link": "link_2", "network": "192.168.1.0/24"}              a link's network
    {"device": "device_3", "name": "PC3"}                        rename
    {"device": "device_3", "type": "server"}                     fix the detected type

``device`` may be a device id or its (unique) name. The prefix may be written in the address,
given as ``prefix`` or as a ``mask`` (IPv4); if it is left out, the prefix of the link the
address is on is used. A device address replaces the old one everywhere it was used (its own
``network`` block and the link ends that carried it); a device on several links must say which
``link`` when that is not clear.

Rejected (never applied): unknown device / link, malformed address, mask that is not a mask
or disagrees with the prefix, a mask on IPv6, prefix out of range, an address no device may
use (a mask, reserved, network or broadcast address), an address another device already
uses, an address outside the link's network, a network address with host bits set, an empty
or duplicate name.
"""

from __future__ import annotations

import copy
import ipaddress
from typing import Any

from .addressing import (
    BLOCK,
    LINK_FIELDS,
    MAX_PREFIX,
    host_problem,
    mask_prefix,
    network,
    prefix_mask,
)
from .validator import validate

FAMILY_NAME = {4: "IPv4", 6: "IPv6"}


class CorrectionError(ValueError):
    def __init__(self, code: str, message: str, hint: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code, self.hint = code, hint


def apply_corrections(
    doc: dict[str, Any], corrections: list[dict[str, Any]], *, require_ipv4: bool = True
) -> dict[str, Any]:
    """Returns ``{"topology", "applied", "rejected", "report"}``; ``doc`` itself is not changed."""
    if not isinstance(corrections, list):
        raise CorrectionError("invalid_corrections", "Corrections must be a JSON list of objects.")
    work = copy.deepcopy(doc)
    applied, rejected = [], []
    for index, corr in enumerate(corrections):
        try:
            changes = _apply_one(work, corr)
        except CorrectionError as exc:
            entry = {"index": index, "correction": corr, "code": exc.code, "message": str(exc)}
            if exc.hint:
                entry["hint"] = exc.hint
            rejected.append(entry)
        else:
            applied.append({"index": index, "correction": corr, "changes": changes})
    return {
        "topology": work,
        "applied": applied,
        "rejected": rejected,
        "report": validate(work, require_ipv4=require_ipv4),
    }


# ------------------------------------------------------------------------ dispatch


def _apply_one(doc: dict[str, Any], corr: Any) -> list[str]:
    if not isinstance(corr, dict):
        raise CorrectionError("invalid_correction", "Each correction must be a JSON object.")
    keys = set(corr)
    if "device" in corr:
        dev = _find_device(doc, corr["device"])
        if keys <= {"device", "name"} and "name" in keys:
            return _rename(doc, dev, corr["name"])
        if keys <= {"device", "type"} and "type" in keys:
            return _retype(dev, corr["type"])
        if "ip" in keys and keys <= {"device", "link", "ip", "prefix", "mask"}:
            link = _find_link(doc, corr["link"]) if "link" in corr else None
            return _set_device_ip(doc, dev, link, corr["ip"], corr.get("prefix"), corr.get("mask"))
    elif "link" in corr and "network" in keys and keys <= {"link", "network", "prefix", "mask"}:
        return _set_link_network(
            _find_link(doc, corr["link"]), corr["network"], corr.get("prefix"), corr.get("mask")
        )
    raise CorrectionError(
        "invalid_correction",
        "Unknown correction; use device+ip, device+name, device+type or link+network "
        "(see vision_pipeline.validation.corrections).",
    )


def _find_device(doc: dict[str, Any], ref: Any) -> dict[str, Any]:
    if not isinstance(ref, str) or not ref.strip():
        raise CorrectionError("unknown_device", "Give the device id or name.")
    devices = [d for d in doc.get("devices", []) if isinstance(d, dict)]
    by_id = [d for d in devices if d.get("id") == ref]
    if by_id:
        return by_id[0]
    by_name = [
        d
        for d in devices
        if isinstance(d.get("name"), str) and d["name"].strip().lower() == ref.strip().lower()
    ]
    if len(by_name) == 1:
        return by_name[0]
    if len(by_name) > 1:
        raise CorrectionError(
            "ambiguous_device",
            f"{len(by_name)} devices are named {ref!r}; use the device id.",
            {"ids": [d["id"] for d in by_name]},
        )
    raise CorrectionError("unknown_device", f"No device has the id or name {ref!r}.")


def _find_link(doc: dict[str, Any], ref: Any) -> dict[str, Any]:
    for lk in doc.get("links", []):
        if isinstance(lk, dict) and lk.get("id") == ref:
            return lk
    raise CorrectionError("unknown_link", f"No link has the id {ref!r}.")


# ------------------------------------------------------------------ name / type


def _rename(doc: dict[str, Any], dev: dict[str, Any], name: Any) -> list[str]:
    if not isinstance(name, str) or not name.strip():
        raise CorrectionError("invalid_name", "A device name must be a nonempty string.")
    name = name.strip()
    clash = [
        d["id"]
        for d in doc["devices"]
        if d is not dev
        and isinstance(d.get("name"), str)
        and d["name"].strip().lower() == name.lower()
    ]
    if clash:
        raise CorrectionError(
            "duplicate_device_name",
            f"{name!r} is already the name of {clash[0]}.",
            {"device": clash[0]},
        )
    old, dev["name"] = dev.get("name"), name
    return [f"{dev['id']}.name: {old!r} -> {name!r}"]


def _retype(dev: dict[str, Any], role: Any) -> list[str]:
    if not isinstance(role, str) or not role.strip():
        raise CorrectionError(
            "invalid_type", "A device type must be a nonempty string, such as pc or router."
        )
    old, dev["type"] = dev.get("type"), role.strip().lower()
    return [f"{dev['id']}.type: {old!r} -> {dev['type']!r}"]


# ----------------------------------------------------------------------- parsing


def parse_address(text: Any, prefix: Any = None, mask: Any = None, *, host: bool = True):
    """``text`` [+ ``prefix`` | ``mask``] -> (ip, prefix or None). Raises :class:`CorrectionError`."""
    if not isinstance(text, str) or not text.strip():
        raise CorrectionError(
            "invalid_ip", "Give the address as text, like 192.168.1.10/24 or 2001:db8::10/64."
        )
    raw = text.strip()
    written = None
    if "/" in raw:
        raw, _, p = raw.partition("/")
        written = _prefix_value(p)
    if "%" in raw:
        raise CorrectionError("invalid_ip", f"{text!r}: zone ids (%...) are not allowed.")
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        raise CorrectionError(
            "invalid_ip", f"{text!r} is not a valid IPv4 or IPv6 address."
        ) from None
    fam = ip.version
    given = [
        x for x in (written, None if prefix is None else _prefix_value(prefix)) if x is not None
    ]
    if mask is not None:
        if fam == 6:
            raise CorrectionError(
                "unexpected_subnet_mask", "IPv6 has no subnet mask; give a prefix length like /64."
            )
        as_prefix = mask_prefix(mask)
        if as_prefix is None:
            raise CorrectionError(
                "invalid_subnet_mask",
                f"{mask!r} is not a subnet mask (its 1-bits must be contiguous, like 255.255.255.0).",
            )
        given.append(as_prefix)
    if len(set(given)) > 1:
        raise CorrectionError(
            "prefix_mismatch", f"The prefix lengths given do not agree: {sorted(set(given))}."
        )
    p = given[0] if given else None
    if p is not None and not 0 <= p <= MAX_PREFIX[fam]:
        raise CorrectionError(
            "invalid_prefix_length",
            f"An {FAMILY_NAME[fam]} prefix length is 0 to {MAX_PREFIX[fam]}.",
        )
    if host:
        problem = host_problem(ip, p)
        if problem is not None and problem[1] == "error":
            raise CorrectionError(problem[0], problem[2])
    return ip, p


def _prefix_value(value: Any) -> int:
    if type(value) is int:
        return value
    if isinstance(value, str) and value.strip().lstrip("/").isdigit():
        digits = value.strip().lstrip("/")
        if digits == "0" or not digits.startswith("0"):
            return int(digits)
    raise CorrectionError(
        "invalid_prefix_length", f"{value!r} is not a prefix length (a whole number like 24)."
    )


# ------------------------------------------------------------------ device address


def _set_device_ip(
    doc: dict[str, Any],
    dev: dict[str, Any],
    link: dict[str, Any] | None,
    text: Any,
    prefix: Any,
    mask: Any,
) -> list[str]:
    ip, p = parse_address(text, prefix, mask)
    fam, block = ip.version, BLOCK[ip.version]
    links = [lk for lk in doc["links"] if dev["id"] in (lk.get("source"), lk.get("target"))]
    if link is not None and link not in links:
        raise CorrectionError(
            "link_not_on_device",
            f"{link['id']} does not end at {dev['id']}.",
            {"links": [lk["id"] for lk in links]},
        )
    old = (dev.get(block) or {}).get("ip_address")
    if link is not None:
        targets = [link]
    else:
        targets = [lk for lk in links if old is not None and _end(lk, dev, fam) == old]
        if not targets and len(links) == 1:
            targets = links
        if not targets and len(links) > 1:
            raise CorrectionError(
                "link_required",
                f'{dev["id"]} is on {len(links)} links; say which one ("link").',
                {"links": [lk["id"] for lk in links]},
            )
    for lk in targets:  # the prefix comes from the address, else from the link it is on
        net = lk.get(block) or {}
        if p is None and net.get("prefix_length") is not None:
            p = net["prefix_length"]
    if p is None:
        raise CorrectionError(
            "prefix_required", f"Give the prefix length for {ip} (like {ip}/24 or a mask)."
        )
    problem = host_problem(ip, p)
    if problem is not None and problem[1] == "error":
        raise CorrectionError(problem[0], problem[2])
    subnet = network(ip, p)
    for lk in targets:
        net = lk.get(block) or {}
        if net.get("network_address") is not None and net.get("prefix_length") is not None:
            link_net = network(net["network_address"], net["prefix_length"])
            if ip not in link_net or link_net.prefixlen != p:
                raise CorrectionError(
                    "ip_outside_link_network",
                    f"{ip}/{p} is not in {lk['id']}'s network {link_net}; correct the link's "
                    "network first, or use an address inside it.",
                    {"link": lk["id"], "network": str(link_net)},
                )
    owner = _owner(doc, ip, dev)
    if owner is not None:
        raise CorrectionError(
            "duplicate_ip", f"{ip} is already used by {owner}.", {"device": owner}
        )

    old_ends = {lk["id"]: _end(lk, dev, fam) for lk in targets}
    changes = []
    for lk in targets:
        side = "source" if lk.get("source") == dev["id"] else "target"
        net = lk.setdefault(block, _empty_link_block(fam))
        if net.get("network_address") is None:
            other = net.get("target_ip" if side == "source" else "source_ip")
            if other is None or ipaddress.ip_address(other) in subnet:
                net.update(_link_values(subnet))
                changes.append(f"{lk['id']}.{block}: network set to {subnet}")
        before, net[f"{side}_ip"] = net.get(f"{side}_ip"), str(ip)
        changes.append(f"{lk['id']}.{block}.{side}_ip: {before} -> {ip}")
    # the device's main address follows, unless only another link's address was corrected
    if link is None or old is None or old_ends[link["id"]] == old:
        dev[block] = _device_values(ip, subnet, fam)
        changes.append(f"{dev['id']}.{block}: {old} -> {ip}/{p}")
    return changes


def _set_link_network(lk: dict[str, Any], text: Any, prefix: Any, mask: Any) -> list[str]:
    ip, p = parse_address(text, prefix, mask, host=False)
    if p is None:
        raise CorrectionError(
            "prefix_required", f"Give the prefix length of the network (like {ip}/24)."
        )
    net = network(ip, p)
    if net.network_address != ip:
        raise CorrectionError(
            "invalid_network_address",
            f"{ip} has host bits set for /{p}; the network is {net}.",
            {"expected": str(net)},
        )
    block = BLOCK[ip.version]
    values = lk.setdefault(block, _empty_link_block(ip.version))
    before = values.get("network_address"), values.get("prefix_length")
    values.update(_link_values(net))
    return [f"{lk['id']}.{block}: {before[0]}/{before[1]} -> {net}"]


# ----------------------------------------------------------------------- helpers


def _end(lk: dict[str, Any] | None, dev: dict[str, Any], fam: int) -> Any:
    if lk is None:
        return None
    side = "source" if lk.get("source") == dev["id"] else "target"
    return (lk.get(BLOCK[fam]) or {}).get(f"{side}_ip")


def _owner(doc: dict[str, Any], ip, me: dict[str, Any]) -> str | None:
    """Another device already using ``ip`` (in its own block or on a link end)."""
    text = str(ip)
    block = BLOCK[ip.version]
    for d in doc["devices"]:
        if d is not me and (d.get(block) or {}).get("ip_address") == text:
            return d["id"]
    for lk in doc["links"]:
        net = lk.get(block) or {}
        for side in ("source", "target"):
            if net.get(f"{side}_ip") == text and lk.get(side) != me["id"]:
                return lk.get(side)
    return None


def _device_values(ip, subnet, fam: int) -> dict[str, Any]:
    out = {"ip_address": str(ip), "prefix_length": subnet.prefixlen}
    if fam == 4:
        out["subnet_mask"] = prefix_mask(subnet.prefixlen)
    out["network_address"] = str(subnet.network_address)
    return out


def _link_values(subnet) -> dict[str, Any]:
    out: dict[str, Any] = {
        "network_address": str(subnet.network_address),
        "prefix_length": subnet.prefixlen,
    }
    if subnet.version == 4:
        out["subnet_mask"] = prefix_mask(subnet.prefixlen)
    return out


def _empty_link_block(fam: int) -> dict[str, Any]:
    return {**dict.fromkeys(LINK_FIELDS[fam]), "source_ip": None, "target_ip": None}
