"""IPv4 and IPv6 address normalisation and host-suffix arithmetic.

Everything is exact arithmetic (integers for IPv4, the standard ``ipaddress`` module for
IPv6). Nothing is ever assumed: a value is either read from the text, derived
deterministically from values that were read, or ``None``.

Normalised shape (all four fields nullable)::

    ip_address, prefix_length, subnet_mask, network_address

IPv6 has no dotted mask: ``subnet_mask`` is always ``None`` for an IPv6 address (not
applicable, not missing). IPv6 addresses are stored in their canonical compressed,
lowercase form (``2001:DB8:0:0::1`` -> ``2001:db8::1``).
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from typing import Any

_OCTET = r"(?:0|[1-9]\d{0,2})"  # no leading zeros: "01" is ambiguous (octal?) -> rejected
_IPV4_RE = re.compile(rf"^({_OCTET})\.({_OCTET})\.({_OCTET})\.({_OCTET})$")
_CIDR_RE = re.compile(rf"^({_OCTET})\.({_OCTET})\.({_OCTET})\.({_OCTET})/(\d{{1,2}})$")
_SUFFIX_RE = re.compile(r"^\.(0|[1-9]\d{0,2})$")
#: characters an IPv6 address may contain (hex groups, colons, an embedded dotted IPv4 tail)
_IPV6_CHARS_RE = re.compile(r"^[0-9A-Fa-f:.]+$")
_IPV6_CIDR_RE = re.compile(r"^([0-9A-Fa-f:.]+)/(0|[1-9]\d{0,2})$")
#: IPv6 host suffix: "::2", "::1f" - the host part written alone next to a device
_SUFFIX6_RE = re.compile(r"^::([0-9A-Fa-f]{1,4})$")


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
    def version(self) -> int | None:
        return ip_version(self.ip_address or self.network_address or "")

    @property
    def is_network_form(self) -> bool:
        """True when the value is a network (host bits all zero), not a host.

        IPv4 up to /30 and IPv6 up to /126: in smaller blocks (/31, /32, /127, /128) the
        all-zero address is itself a usable host, so it is not read as a network label.
        """
        if self.ip_address is None or self.prefix_length is None:
            return False
        limit = 126 if self.version == 6 else 30
        return self.prefix_length <= limit and self.ip_address == self.network_address


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


def parse_host_suffix6(text: str) -> int | None:
    """``"::2"`` -> 2, ``"::1f"`` -> 31. ``None`` unless it is ``::`` + 1-4 hex digits, non-zero.

    Written alone next to a device, ``::2`` is the host part of the prefix on its link - the
    IPv6 form of the ``.2`` convention - not the full address ``::2``.
    """
    m = _SUFFIX6_RE.match(text)
    if not m:
        return None
    value = int(m.group(1), 16)
    return value or None


def host_suffix_version(text: str | None) -> int | None:
    """4 for ``.N``, 6 for ``::N``, ``None`` if ``text`` is not a host suffix."""
    if text is None:
        return None
    if parse_host_suffix(text) is not None:
        return 4
    if parse_host_suffix6(text) is not None:
        return 6
    return None


# --------------------------------------------------------------------------------- IPv6


def ipv6_canonical(text: str) -> str | None:
    """Strictly parse an IPv6 address; canonical compressed lowercase form, else ``None``.

    Rejected: zone ids (``fe80::1%eth0`` - interface names are out of scope), anything but
    hex digits / colons / an embedded dotted IPv4 tail, and the unspecified address ``::``.
    """
    if ":" not in text or not _IPV6_CHARS_RE.match(text):
        return None
    try:
        addr = ipaddress.IPv6Address(text)
    except ValueError:
        return None
    if addr.is_unspecified:
        return None
    return str(addr)


def normalize_ipv6_only(text: str) -> NormalizedAddress | None:
    ip = ipv6_canonical(text)
    if ip is None:
        return None
    return NormalizedAddress(ip_address=ip, field_origin={"ip_address": "ocr"})


def normalize_ipv6_cidr(text: str) -> NormalizedAddress | None:
    """``2001:db8:1::5/64`` -> ip, prefix, network. ``subnet_mask`` is not used by IPv6."""
    m = _IPV6_CIDR_RE.match(text)
    if not m:
        return None
    prefix = int(m.group(2))
    if prefix > 128:
        return None
    try:
        addr = ipaddress.IPv6Address(m.group(1)) if ":" in m.group(1) else None
    except ValueError:
        return None
    if addr is None:
        return None
    net = ipaddress.IPv6Network((addr, prefix), strict=False)
    return NormalizedAddress(
        ip_address=str(addr),
        prefix_length=prefix,
        network_address=str(net.network_address),
        field_origin={
            "ip_address": "ocr",
            "prefix_length": "ocr",
            "network_address": "derived_from_ip_and_prefix_length",
        },
    )


# ------------------------------------------------------------ family-agnostic helpers


def ip_version(text: str | None) -> int | None:
    """4 or 6 for a valid address (strict IPv4, see :func:`ip_to_int`), else ``None``."""
    if not isinstance(text, str):
        return None
    if ip_to_int(text) is not None:
        return 4
    if ":" in text and _IPV6_CHARS_RE.match(text):
        try:
            ipaddress.IPv6Address(text)
            return 6
        except ValueError:
            return None
    return None


def canonical_ip(text: str | None) -> str | None:
    """The address as it must be stored: strict IPv4 unchanged, IPv6 compressed lowercase."""
    version = ip_version(text)
    if version == 4:
        return text
    if version == 6:
        return str(ipaddress.IPv6Address(text))
    return None


def max_prefix(version: int) -> int:
    return 128 if version == 6 else 32


def mask_for(prefix: int | None, version: int) -> str | None:
    """Dotted mask for IPv4; ``None`` for IPv6, which does not use masks."""
    if version == 6 or prefix is None:
        return None
    return prefix_to_mask(prefix)


def network_of_any(ip: str, prefix: int) -> str | None:
    version = ip_version(ip)
    if (
        version is None
        or not isinstance(prefix, int)
        or isinstance(prefix, bool)
        or not 0 <= prefix <= max_prefix(version)
    ):
        return None
    if version == 4:
        return network_of(ip, prefix)
    return str(
        ipaddress.IPv6Network((ipaddress.IPv6Address(ip), prefix), strict=False).network_address
    )


def ip_in_network(ip: str, network_address: str, prefix: int) -> bool:
    version = ip_version(ip)
    return (
        version is not None
        and version == ip_version(network_address)
        and network_of_any(ip, prefix) == canonical_ip(network_address)
    )


def parse_cidr_any(text: str) -> tuple[str, int | None, int] | None:
    """``"ip"`` or ``"ip/prefix"`` (either family) -> (canonical ip, prefix or None, version)."""
    if not isinstance(text, str):
        return None
    text = text.strip()
    addr, _, prefix_text = text.partition("/")
    version = ip_version(addr)
    if version is None:
        return None
    prefix = None
    if prefix_text:
        if not re.fullmatch(r"0|[1-9]\d{0,2}", prefix_text) or int(prefix_text) > max_prefix(
            version
        ):
            return None
        prefix = int(prefix_text)
    return canonical_ip(addr), prefix, version  # type: ignore[return-value]


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

    IPv6 (``2001:db8:1::/64`` + ``::2`` -> ``2001:db8:1::2/64``): the suffix is the host part
    itself, so any prefix up to /127 works as long as the value fits in the host bits. A
    suffix of one family never resolves against a network of the other.
    """
    suffix_version, net_version = host_suffix_version(suffix), ip_version(network_address)
    if suffix_version is None:
        return HostResolution(None, "invalid_host_suffix")
    if net_version is None:
        return HostResolution(None, "invalid_network")
    if suffix_version != net_version:
        return HostResolution(None, "suffix_family_mismatch")
    if suffix_version == 6:
        return _resolve_host_suffix6(network_address, prefix_length, suffix)
    value = parse_host_suffix(suffix)
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


def _resolve_host_suffix6(network_address: str, prefix_length: int, suffix: str) -> HostResolution:
    if (
        not isinstance(prefix_length, int)
        or isinstance(prefix_length, bool)
        or not 0 <= prefix_length <= 128
    ):
        return HostResolution(None, "invalid_network")
    if prefix_length >= 128:
        return HostResolution(None, "prefix_has_no_host_bits")
    net = ipaddress.IPv6Address(network_address)
    network = ipaddress.IPv6Network((net, prefix_length), strict=False)
    if network.network_address != net:
        return HostResolution(None, "network_address_has_host_bits")
    value = parse_host_suffix6(suffix)
    if value is None or value >= 2 ** (128 - prefix_length):
        return HostResolution(None, "suffix_outside_network")
    candidate = str(ipaddress.IPv6Address(int(net) | value))
    return HostResolution(
        NormalizedAddress(
            ip_address=candidate,
            prefix_length=prefix_length,
            network_address=str(net),
            field_origin={
                "ip_address": "derived_from_host_suffix_and_link_network",
                "prefix_length": "derived_from_link_network",
                "network_address": "derived_from_link_network",
            },
        ),
        "resolved",
    )
