"""Address arithmetic shared by the validator, the corrections and the auto-addressing.

Standard library ``ipaddress`` only; both families behind one small API. Nothing here reads
or writes files.
"""

from __future__ import annotations

import ipaddress
from typing import Any

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

LAYER2_TYPES = {"switch", "bridge", "hub"}
BLOCK = {4: "network", 6: "network6"}
DEVICE_FIELDS = {
    4: ("ip_address", "prefix_length", "subnet_mask", "network_address"),
    6: ("ip_address", "prefix_length", "network_address"),
}
LINK_FIELDS = {
    4: ("network_address", "prefix_length", "subnet_mask"),
    6: ("network_address", "prefix_length"),
}
MAX_PREFIX = {4: 32, 6: 128}
#: an IPv6 LAN is a /64 (SLAAC, RFC 4291); used as the suggested IPv6 segment size
IPV6_SEGMENT_PREFIX = 64


def is_layer2(device: dict[str, Any]) -> bool:
    role = device.get("type")
    return isinstance(role, str) and role.lower() in LAYER2_TYPES


def parse_ip(value: Any, family: int) -> IPAddress | None:
    """A host address of exactly ``family``; ``None`` for anything else (no zone ids)."""
    if not isinstance(value, str) or "%" in value or value != value.strip():
        return None
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return None
    return ip if ip.version == family else None


def family_of(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    try:
        return ipaddress.ip_address(value).version
    except ValueError:
        return None


def parse_prefix(value: Any, family: int) -> int | None:
    if type(value) is not int or not 0 <= value <= MAX_PREFIX[family]:
        return None
    return value


def mask_prefix(value: Any) -> int | None:
    """Prefix length of a contiguous dotted IPv4 mask, else ``None`` (255.0.255.0 is not a mask)."""
    ip = parse_ip(value, 4)
    if ip is None:
        return None
    n = int(ip)
    inverted = (~n) & 0xFFFFFFFF
    if inverted & (inverted + 1):
        return None
    return 32 - inverted.bit_length()


def prefix_mask(prefix: int) -> str:
    return str(ipaddress.IPv4Network((0, prefix)).netmask)


def network(address: IPAddress | str, prefix: int) -> IPNetwork:
    return ipaddress.ip_network(f"{address}/{prefix}", strict=False)


def usable_hosts(prefix: int, family: int) -> int:
    """Addresses a segment of this size can give to devices.

    IPv4: network and broadcast are excluded, except /31 (point-to-point, RFC 3021) and /32.
    IPv6: only the all-zero subnet-router anycast address is excluded (no broadcast), except
    /127 (point-to-point, RFC 6164) and /128.
    """
    host_bits = MAX_PREFIX[family] - prefix
    if family == 4:
        return 1 if host_bits == 0 else 2 if host_bits == 1 else 2**host_bits - 2
    return 1 if host_bits == 0 else 2 if host_bits == 1 else 2**host_bits - 1


def smallest_prefix(hosts: int, family: int) -> int | None:
    """The smallest segment (longest prefix) holding ``hosts`` devices, VLSM style.

    IPv4 follows the classic VLSM rule (never smaller than a /30, so network and broadcast
    stay reserved even on point-to-point links); IPv6 segments are always a /64.
    """
    if family == 6:
        return IPV6_SEGMENT_PREFIX
    for prefix in range(30, -1, -1):
        if usable_hosts(prefix, 4) >= max(hosts, 1):
            return prefix
    return None


def host_problem(ip: IPAddress, prefix: int | None) -> tuple[str, str, str] | None:
    """Why ``ip`` cannot be a device address: ``(code, severity, message)`` or ``None``."""
    if ip.version == 4:
        as_mask = mask_prefix(str(ip))
        if as_mask is not None and as_mask >= 8:
            return (
                "ip_looks_like_mask",
                "error",
                f"{ip} is a subnet mask (/{as_mask}), not a device address; the mask was probably read as the IP.",
            )
        if int(ip) >> 24 == 0:
            return (
                "reserved_ip",
                "error",
                f"{ip} is in 0.0.0.0/8 ('this network'), not usable by a device.",
            )
    if ip.is_unspecified:
        return ("reserved_ip", "error", f"{ip} is the unspecified address, not usable by a device.")
    if ip.is_loopback:
        return ("reserved_ip", "error", f"{ip} is a loopback address, not usable on a link.")
    if ip.is_multicast:
        return ("reserved_ip", "error", f"{ip} is a multicast address, not usable by a device.")
    if ip.version == 4 and ip.is_reserved:
        return (
            "reserved_ip",
            "error",
            f"{ip} is reserved (240.0.0.0/4 or the broadcast 255.255.255.255).",
        )
    if prefix is not None:
        net = network(ip, prefix)
        if ip.version == 4 and prefix <= 30:
            if ip == net.network_address:
                return (
                    "ip_is_network_address",
                    "error",
                    f"{ip} is the network address of {net}, not a host.",
                )
            if ip == net.broadcast_address:
                return (
                    "ip_is_broadcast_address",
                    "error",
                    f"{ip} is the broadcast address of {net}, not a host.",
                )
        if ip.version == 6 and prefix <= 126 and ip == net.network_address:
            return (
                "ip_is_network_address",
                "error",
                f"{ip} is the subnet-router anycast address of {net}, not a host.",
            )
    if ip.is_link_local:
        return (
            "link_local_ip",
            "warning",
            f"{ip} is link-local; it is only valid on its own link.",
        )
    return None
