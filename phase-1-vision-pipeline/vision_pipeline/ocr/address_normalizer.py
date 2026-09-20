"""IPv4 address normalisation and host-suffix arithmetic.

Everything is exact integer arithmetic. Nothing is ever assumed: a value is either read from
the text, derived deterministically from values that were read, or ``None``.

Normalised shape (all four fields nullable)::

    ip_address, prefix_length, subnet_mask, network_address
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_OCTET = r"(?:0|[1-9]\d{0,2})"  # no leading zeros: "01" is ambiguous (octal?) -> rejected
_IPV4_RE = re.compile(rf"^({_OCTET})\.({_OCTET})\.({_OCTET})\.({_OCTET})$")
_CIDR_RE = re.compile(rf"^({_OCTET})\.({_OCTET})\.({_OCTET})\.({_OCTET})/(\d{{1,2}})$")
_SUFFIX_RE = re.compile(r"^\.(0|[1-9]\d{0,2})$")


# ------------------------------------------------------------------------ integer helpers


def ip_to_int(ip: str) -> int | None:
    """Dotted quad -> int, or ``None`` if it is not a strictly valid IPv4 address."""
    m = _IPV4_RE.match(ip)
    if not m:
        return None
    octets = [int(g) for g in m.groups()]
    if any(o > 255 for o in octets):
        return None
    return (octets[0] << 24) | (octets[1] << 16) | (octets[2] << 8) | octets[3]


def int_to_ip(value: int) -> str:
    return ".".join(str((value >> s) & 0xFF) for s in (24, 16, 8, 0))


def is_valid_ipv4(text: str) -> bool:
    return ip_to_int(text) is not None


def mask_to_prefix(mask: str) -> int | None:
    """Prefix length of a *contiguous* dotted mask, else ``None``.

    255.255.255.0 -> 24; 255.255.0.255 -> None (not contiguous); 192.168.1.1 -> None.
    ``0.0.0.0`` (/0) is rejected: it carries no usable subnet information.
    """
    m = ip_to_int(mask)
    if m is None or m == 0:
        return None
    inverted = ~m & 0xFFFFFFFF
    if inverted & (inverted + 1):  # inverted must be 2^k - 1 for a contiguous mask
        return None
    return 32 - inverted.bit_length()


def prefix_to_mask(prefix: int) -> str | None:
    if not isinstance(prefix, int) or isinstance(prefix, bool) or not 0 <= prefix <= 32:
        return None
    return int_to_ip((0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF) if prefix else "0.0.0.0"


def network_of(ip: str, prefix: int) -> str | None:
    value = ip_to_int(ip)
    mask = prefix_to_mask(prefix)
    if value is None or mask is None:
        return None
    return int_to_ip(value & ip_to_int(mask))  # type: ignore[operator]


def broadcast_of(network: str, prefix: int) -> str | None:
    value, mask = ip_to_int(network), prefix_to_mask(prefix)
    if value is None or mask is None:
        return None
    return int_to_ip(value | (~ip_to_int(mask) & 0xFFFFFFFF))  # type: ignore[operator]


# -------------------------------------------------------------------------- normalisation


@dataclass
class NormalizedAddress:
    ip_address: str | None = None
    prefix_length: int | None = None
    subnet_mask: str | None = None
    network_address: str | None = None
    #: how each non-null field was obtained: "ocr" (read as written) or "derived_from_<x>"
    field_origin: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ip_address": self.ip_address,
            "prefix_length": self.prefix_length,
            "subnet_mask": self.subnet_mask,
            "network_address": self.network_address,
        }

    @property
    def is_network_form(self) -> bool:
        """True when the value is a network (host bits all zero, prefix <= 30), not a host."""
        return (
            self.ip_address is not None
            and self.prefix_length is not None
            and self.prefix_length <= 30
            and self.ip_address == self.network_address
        )


def normalize_cidr(text: str) -> NormalizedAddress | None:
    """Case A: ``192.168.1.1/24``. ``None`` if ``text`` is not a valid CIDR address."""
    m = _CIDR_RE.match(text)
    if not m:
        return None
    ip = ".".join(m.groups()[:4])
    prefix = int(m.group(5))
    if ip_to_int(ip) is None or not 0 <= prefix <= 32:
        return None
    return NormalizedAddress(
        ip_address=ip,
        prefix_length=prefix,
        subnet_mask=prefix_to_mask(prefix),
        network_address=network_of(ip, prefix),
        field_origin={
            "ip_address": "ocr",
            "prefix_length": "ocr",
            "subnet_mask": "derived_from_prefix_length",
            "network_address": "derived_from_ip_and_prefix_length",
        },
    )


def normalize_ip_and_mask(ip: str, mask: str) -> NormalizedAddress | None:
    """Case B: ``192.168.1.1`` + ``255.255.255.0``."""
    prefix = mask_to_prefix(mask)
    if ip_to_int(ip) is None or prefix is None:
        return None
    return NormalizedAddress(
        ip_address=ip,
        prefix_length=prefix,
        subnet_mask=mask,
        network_address=network_of(ip, prefix),
        field_origin={
            "ip_address": "ocr",
            "subnet_mask": "ocr",
            "prefix_length": "derived_from_subnet_mask",
            "network_address": "derived_from_ip_and_prefix_length",
        },
    )


def normalize_ip_only(ip: str) -> NormalizedAddress | None:
    """Case C: only the address. Prefix, mask and network stay ``None``."""
    if ip_to_int(ip) is None:
        return None
    return NormalizedAddress(ip_address=ip, field_origin={"ip_address": "ocr"})


def normalize_mask_only(mask: str) -> NormalizedAddress | None:
    """Case D: only a mask. Keep mask + prefix; ip and network stay ``None``."""
    prefix = mask_to_prefix(mask)
    if prefix is None:
        return None
    return NormalizedAddress(
        subnet_mask=mask,
        prefix_length=prefix,
        field_origin={"subnet_mask": "ocr", "prefix_length": "derived_from_subnet_mask"},
    )


def parse_host_suffix(text: str) -> int | None:
    """``".10"`` -> 10. ``None`` unless it is a dot followed by an integer 0..255."""
    m = _SUFFIX_RE.match(text)
    if not m:
        return None
    value = int(m.group(1))
    return value if value <= 255 else None


# -------------------------------------------------------------------- host-suffix resolver


@dataclass
class HostResolution:
    address: NormalizedAddress | None
    #: machine-readable reason, always set (``"resolved"`` on success)
    reason: str


def resolve_host_suffix(
    network_address: str,
    prefix_length: int,
    suffix: str,
    *,
    min_prefix: int = 24,
    max_prefix: int = 31,
) -> HostResolution:
    """Turn ``network=192.168.1.0/24`` + ``suffix=".2"`` into ``192.168.1.2/24``.

    The suffix is interpreted ONLY as the final octet, and ONLY when the prefix is within
    ``[min_prefix, max_prefix]`` (so the final octet is the only octet that can differ
    between hosts). For shorter prefixes ("10.10.0.0/16" + ".20") there is no convention
    that says which octet ".20" is, so nothing is resolved.

    The candidate is built with integer arithmetic and then verified: it must lie inside the
    network and, for prefixes <= /30, must not be the network or broadcast address.
    """
    value = parse_host_suffix(suffix)
    if value is None:
        return HostResolution(None, "invalid_host_suffix")
    net_int = ip_to_int(network_address)
    if net_int is None or not isinstance(prefix_length, int) or not 0 <= prefix_length <= 32:
        return HostResolution(None, "invalid_network")
    if not min_prefix <= prefix_length <= max_prefix:
        return HostResolution(None, "prefix_outside_final_octet_range")
    if network_of(network_address, prefix_length) != network_address:
        return HostResolution(None, "network_address_has_host_bits")
    candidate = (net_int & 0xFFFFFF00) | value
    candidate_ip = int_to_ip(candidate)
    if network_of(candidate_ip, prefix_length) != network_address:
        return HostResolution(None, "suffix_outside_network")
    if prefix_length <= 30 and candidate_ip in (
        network_address,
        broadcast_of(network_address, prefix_length),
    ):
        return HostResolution(None, "suffix_is_network_or_broadcast_address")
    return HostResolution(
        NormalizedAddress(
            ip_address=candidate_ip,
            prefix_length=prefix_length,
            subnet_mask=prefix_to_mask(prefix_length),
            network_address=network_address,
            field_origin={
                "ip_address": "derived_from_host_suffix_and_link_network",
                "prefix_length": "derived_from_link_network",
                "subnet_mask": "derived_from_link_network",
                "network_address": "derived_from_link_network",
            },
        ),
        "resolved",
    )
