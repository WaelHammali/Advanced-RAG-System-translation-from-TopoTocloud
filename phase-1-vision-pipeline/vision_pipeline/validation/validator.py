"""Pre-RAG validator: is ``topology.simple.json`` a correct network before the RAG sees it?

It applies the RAG's own readiness rules (same codes, same JSON-pointer paths, so one UI can
show both) and adds the addressing checks a human would make:

* format       - every address, prefix and mask is valid for its family (IPv4 in
                 ``network``, IPv6 in ``network6``); 255.0.255.0 is not a mask
* host address - no mask read as an IP (``255.255.0.0``), no reserved / loopback /
                 multicast address, no network or broadcast address given to a device
* duplicates   - one address used by two devices, or by one device on two segments
* segments     - the links joined by switches/hubs form one broadcast segment, which must
                 be ONE network; two segments must never overlap
* VLSM         - a segment's network must be big enough for the devices on it; the
                 report says the smallest prefix that fits

Nothing is changed: the report says what is wrong and where, so the user (or an agent) can
fix it with :mod:`.corrections` or regenerate it with :mod:`.autoaddress`.

``require_ipv4=True`` (default) mirrors the RAG exactly: every non-L2 device needs IPv4.
With ``False`` an IPv6-only device or link is accepted.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .addressing import (
    BLOCK,
    DEVICE_FIELDS,
    LINK_FIELDS,
    MAX_PREFIX,
    family_of,
    host_problem,
    is_layer2,
    mask_prefix,
    network,
    parse_ip,
    parse_prefix,
    prefix_mask,
    smallest_prefix,
    usable_hosts,
)
from .segments import Segment, find_segments, routing_layer2

VALIDATION_SCHEMA_VERSION = "1.0"
FAMILY_NAME = {4: "IPv4", 6: "IPv6"}


@dataclass
class Issue:
    code: str
    severity: str  # "error" blocks the RAG, "warning" does not
    path: str
    message: str
    subject: str | None = None  # device or link id
    value: Any = None
    related: list[str] = field(default_factory=list)
    hint: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out = {
            "code": self.code,
            "severity": self.severity,
            "path": self.path,
            "message": self.message,
            "subject": self.subject,
            "value": self.value,
            "related": self.related,
        }
        if self.hint:
            out["hint"] = self.hint
        return out


def validate(doc: Any, *, require_ipv4: bool = True) -> dict[str, Any]:
    """Validate a minimal topology; returns a JSON-ready report (``report["valid"]``)."""
    return _Validator(doc, require_ipv4).run()


class _Validator:
    def __init__(self, doc: Any, require_ipv4: bool) -> None:
        self.doc, self.require_ipv4 = doc, require_ipv4
        self.issues: list[Issue] = []
        self.devices: dict[str, tuple[int, dict[str, Any]]] = {}  # id -> (index, device)
        #: family -> device id -> (ip, prefix) of its own network block
        self.own: dict[int, dict[str, tuple[Any, int | None]]] = {4: {}, 6: {}}
        #: family -> ip -> [(device id, path)] for every place the address is used
        self.uses: dict[int, dict[Any, list[tuple[str, str]]]] = {
            4: defaultdict(list),
            6: defaultdict(list),
        }
        #: family -> link id -> parsed network
        self.link_nets: dict[int, dict[str, Any]] = {4: {}, 6: {}}
        #: family -> (link id, device id) -> ip
        self.end_ips: dict[int, dict[tuple[str, str], Any]] = {4: {}, 6: {}}
        self.valid_links: list[tuple[int, dict[str, Any]]] = []

    def add(self, code: str, path: str, message: str, severity: str = "error", **kw: Any) -> None:
        self.issues.append(Issue(code, severity, path, message, **kw))

    # ------------------------------------------------------------------------ run
    def run(self) -> dict[str, Any]:
        doc = self.doc
        if not isinstance(doc, dict):
            self.add("invalid_architecture", "", "The topology must be a JSON object.")
            return self.report([])
        devices, links = doc.get("devices"), doc.get("links")
        if not isinstance(devices, list) or not devices:
            self.add("missing_devices", "/devices", "Provide a nonempty list of devices.")
            devices = []
        if not isinstance(links, list) or not links:
            self.add("missing_links", "/links", "Provide links connecting the devices.")
            links = []
        for i, d in enumerate(devices):
            self.device(i, d)
        self.duplicate_names()
        link_ids: set[str] = set()
        for i, lk in enumerate(links):
            self.link(i, lk, link_ids)
        self.connectivity()
        self.duplicates()
        devs, links_ok = [d for _, d in self.devices.values()], [lk for _, lk in self.valid_links]
        for dev in sorted(routing_layer2(devs, links_ok)):
            self.add(
                "layer2_device_routes",
                f"/devices/{self.devices[dev][0]}",
                f"{dev} is a {self.devices[dev][1]['type']} but holds addresses in several networks, so it is "
                "treated as a layer-3 switch that routes between them.",
                "warning",
                subject=dev,
            )
        segs = find_segments(devs, links_ok)
        self.segment_checks(segs)
        return self.report(segs)

    # -------------------------------------------------------------------- devices
    def device(self, i: int, d: Any) -> None:
        path = f"/devices/{i}"
        if not isinstance(d, dict):
            self.add("invalid_device", path, "Each device must be an object.")
            return
        ident = d.get("id")
        if not _named(ident):
            self.add(
                "missing_device_id",
                path + "/id",
                "Give this device a nonempty unique ID, such as device_1.",
            )
        elif ident in self.devices:
            self.add(
                "duplicate_device_id",
                path + "/id",
                f"Device ID {ident!r} is already used.",
                subject=ident,
            )
        else:
            self.devices[ident] = (i, d)
        subject = ident if _named(ident) else None
        if not _named(d.get("name")):
            self.add(
                "missing_device_name",
                path + "/name",
                "Give this device a nonempty display name, such as R1.",
                subject=subject,
            )
        if not _named(d.get("type")):
            self.add(
                "missing_device_type",
                path + "/type",
                "Specify the device type, such as pc, router, server or switch.",
                subject=subject,
            )
        if not isinstance(d.get("network"), dict):
            self.add(
                "missing_device_network",
                path + "/network",
                "Provide a network object; use null values for fields that do not apply.",
                subject=subject,
            )
        for fam in (4, 6):
            block = d.get(BLOCK[fam])
            if not isinstance(block, dict):
                continue
            optional = is_layer2(d) or (fam == 4 and not self.require_ipv4)
            got = self.address_block(
                block, f"{path}/{BLOCK[fam]}", fam, DEVICE_FIELDS[fam], optional, subject
            )
            if got is not None and subject in self.devices and self.devices[subject][1] is d:
                ip, prefix = got
                self.own[fam][subject] = (ip, prefix)
                self.uses[fam][ip].append((subject, f"{path}/{BLOCK[fam]}/ip_address"))
        if (
            not self.require_ipv4
            and not is_layer2(d)
            and not _complete(d, 4)
            and not _complete(d, 6)
        ):
            self.add(
                "missing_device_address",
                path,
                "Give this device an IPv4 or an IPv6 address.",
                subject=subject,
            )

    def duplicate_names(self) -> None:
        by_name: dict[str, list[str]] = defaultdict(list)
        for ident, (_, d) in self.devices.items():
            if _named(d.get("name")):
                by_name[d["name"].strip().lower()].append(ident)
        for ids in by_name.values():
            if len(ids) > 1:
                for ident in ids:
                    i, d = self.devices[ident]
                    self.add(
                        "duplicate_device_name",
                        f"/devices/{i}/name",
                        f"The name {d['name']!r} is used by {len(ids)} devices; each device needs its own name.",
                        subject=ident,
                        value=d["name"],
                        related=[x for x in ids if x != ident],
                    )

    def address_block(
        self,
        block: dict[str, Any],
        path: str,
        fam: int,
        fields: tuple[str, ...],
        optional: bool,
        subject: str | None,
    ) -> tuple[Any, int | None] | None:
        """Checks one device ``network`` / ``network6`` block. Returns (ip, prefix) when usable."""
        values = {f: block.get(f) for f in fields}
        if optional and all(v is None for v in values.values()):
            return None
        missing = [f for f in fields if values[f] is None]
        for f in missing:
            self.add(
                "missing_" + f, f"{path}/{f}", f"Provide {f} ({FAMILY_NAME[fam]}).", subject=subject
            )
        prefix = self.prefix(values["prefix_length"], f"{path}/prefix_length", fam, subject)
        if fam == 4:
            self.mask(values["subnet_mask"], prefix, f"{path}/subnet_mask", subject)
        elif block.get("subnet_mask") is not None:
            self.add(
                "unexpected_subnet_mask",
                f"{path}/subnet_mask",
                "IPv6 has no subnet mask; use prefix_length.",
                subject=subject,
                value=block["subnet_mask"],
            )
        ip = self.ip(values["ip_address"], f"{path}/ip_address", fam, "invalid_ip_address", subject)
        net_addr = self.ip(
            values["network_address"],
            f"{path}/network_address",
            fam,
            "invalid_network_address",
            subject,
        )
        if ip is not None and prefix is not None:
            expected = network(ip, prefix).network_address
            if net_addr is not None and net_addr != expected:
                self.add(
                    "network_address_mismatch",
                    f"{path}/network_address",
                    f"network_address should be {expected} for {ip}/{prefix}.",
                    subject=subject,
                    value=values["network_address"],
                    hint={"expected": str(expected)},
                )
        if ip is not None:
            self.host(ip, prefix, f"{path}/ip_address", subject)
        return None if ip is None or missing else (ip, prefix)

    # ---------------------------------------------------------------------- links
    def link(self, i: int, lk: Any, link_ids: set[str]) -> None:
        path = f"/links/{i}"
        if not isinstance(lk, dict):
            self.add("invalid_link", path, "Each link must be an object.")
            return
        ident = lk.get("id")
        ok = _named(ident)
        if not ok:
            self.add("missing_link_id", path + "/id", "Give this link a nonempty ID.")
        elif ident in link_ids:
            self.add(
                "duplicate_link_id",
                path + "/id",
                f"Link ID {ident!r} is already used.",
                subject=ident,
            )
            ok = False
        else:
            link_ids.add(ident)
        subject = ident if ok else None
        ends = []
        for side in ("source", "target"):
            node = lk.get(side)
            if not _named(node) or node not in self.devices:
                self.add(
                    "unknown_device",
                    f"{path}/{side}",
                    f"This link's {side} must reference an existing device ID.",
                    subject=subject,
                    value=node,
                )
                ok = False
            else:
                ends.append((side, node))
        if len(ends) == 2 and ends[0][1] == ends[1][1]:
            self.add(
                "self_link",
                path,
                "Connect this link to another device, not itself.",
                subject=subject,
            )
            ok = False
        if not isinstance(lk.get("network"), dict):
            self.add(
                "missing_link_network",
                path + "/network",
                "Provide this link's network object.",
                subject=subject,
            )
        for fam in (4, 6):
            block = lk.get(BLOCK[fam])
            if not isinstance(block, dict):
                continue
            if (
                fam == 4
                and not self.require_ipv4
                and all(v is None for v in block.values())
                and isinstance(lk.get("network6"), dict)
            ):
                continue
            self.link_block(block, f"{path}/{BLOCK[fam]}", fam, ends, subject)
        if ok:
            self.valid_links.append((i, lk))

    def link_block(
        self,
        block: dict[str, Any],
        path: str,
        fam: int,
        ends: list[tuple[str, str]],
        subject: str | None,
    ) -> None:
        fields = LINK_FIELDS[fam]
        values = {f: block.get(f) for f in fields}
        for f in fields:
            if values[f] is None:
                self.add(
                    "missing_" + f,
                    f"{path}/{f}",
                    f"Provide {f} ({FAMILY_NAME[fam]}).",
                    subject=subject,
                )
        prefix = self.prefix(values["prefix_length"], f"{path}/prefix_length", fam, subject)
        if fam == 4:
            self.mask(values["subnet_mask"], prefix, f"{path}/subnet_mask", subject)
        elif block.get("subnet_mask") is not None:
            self.add(
                "unexpected_subnet_mask",
                f"{path}/subnet_mask",
                "IPv6 has no subnet mask; use prefix_length.",
                subject=subject,
                value=block["subnet_mask"],
            )
        net_ip = self.ip(
            values["network_address"],
            f"{path}/network_address",
            fam,
            "invalid_network_address",
            subject,
        )
        net = None
        if net_ip is not None and prefix is not None:
            net = network(net_ip, prefix)
            if net.network_address != net_ip:
                self.add(
                    "invalid_network_address",
                    f"{path}/network_address",
                    f"{net_ip} has host bits set for /{prefix}; the network is {net.network_address}.",
                    subject=subject,
                    value=values["network_address"],
                    hint={"expected": str(net.network_address)},
                )
                net = None
        if net is not None and subject is not None:
            self.link_nets[fam][subject] = net
        for side, node in ends:
            ip_path = f"{path}/{side}_ip"
            value = block.get(f"{side}_ip")
            if value is None:
                if not is_layer2(self.devices[node][1]):
                    self.add(
                        "missing_link_ip",
                        ip_path,
                        f"Provide the {FAMILY_NAME[fam]} address {node!r} uses on this link.",
                        subject=subject,
                        related=[node],
                    )
                continue
            ip = self.ip(value, ip_path, fam, "invalid_link_ip", subject)
            if ip is None:
                continue
            self.uses[fam][ip].append((node, ip_path))
            if subject is not None:
                self.end_ips[fam][(subject, node)] = ip
            if net is not None and ip not in net:
                self.add(
                    "link_ip_outside_network",
                    ip_path,
                    f"{node}'s address {ip} on this link is not inside the link's network {net}.",
                    subject=subject,
                    value=value,
                    related=[node],
                )
            self.host(ip, prefix, ip_path, subject)

    # ------------------------------------------------------------------ primitives
    def ip(self, value: Any, path: str, fam: int, code: str, subject: str | None):
        if value is None:
            return None
        ip = parse_ip(value, fam)
        if ip is None:
            other = family_of(value)
            if other is not None and other != fam:
                msg = f"{value!r} is an {FAMILY_NAME[other]} address; this field is {FAMILY_NAME[fam]} ({BLOCK[other]} holds {FAMILY_NAME[other]})."
            else:
                msg = f"{value!r} is not a valid {FAMILY_NAME[fam]} address."
            self.add(code, path, msg, subject=subject, value=value)
            return None
        if str(ip) != value:
            self.add(
                "non_canonical_ip",
                path,
                f"Write {value!r} as {ip}.",
                "warning",
                subject=subject,
                value=value,
                hint={"expected": str(ip)},
            )
        return ip

    def prefix(self, value: Any, path: str, fam: int, subject: str | None) -> int | None:
        if value is None:
            return None
        prefix = parse_prefix(value, fam)
        if prefix is None:
            self.add(
                "invalid_prefix_length",
                path,
                f"Provide an integer prefix length from 0 to {MAX_PREFIX[fam]} ({FAMILY_NAME[fam]}).",
                subject=subject,
                value=value,
            )
        return prefix

    def mask(self, value: Any, prefix: int | None, path: str, subject: str | None) -> None:
        if value is None:
            return
        if parse_ip(value, 4) is None:
            self.add(
                "invalid_subnet_mask",
                path,
                f"{value!r} is not a dotted IPv4 subnet mask.",
                subject=subject,
                value=value,
            )
            return
        as_prefix = mask_prefix(value)
        if as_prefix is None:
            self.add(
                "invalid_subnet_mask",
                path,
                f"{value} is not a subnet mask: its 1-bits must be contiguous (like 255.255.255.0).",
                subject=subject,
                value=value,
            )
        if prefix is not None and as_prefix != prefix:
            said = "" if as_prefix is None else f" is /{as_prefix} but prefix_length"
            self.add(
                "subnet_mask_mismatch",
                path,
                f"subnet_mask {value}{said} does not match prefix_length /{prefix} (/{prefix} is {prefix_mask(prefix)}).",
                subject=subject,
                value=value,
                hint={"expected": prefix_mask(prefix)},
            )

    def host(self, ip, prefix: int | None, path: str, subject: str | None) -> None:
        problem = host_problem(ip, prefix)
        if problem is not None:
            code, severity, message = problem
            self.add(code, path, message, severity, subject=subject, value=str(ip))

    # --------------------------------------------------------------- whole graph
    def connectivity(self) -> None:
        count: dict[str, int] = defaultdict(int)
        for _, lk in self.valid_links:
            for side in ("source", "target"):
                count[lk[side]] += 1
        for ident, (i, d) in self.devices.items():
            path = f"/devices/{i}"
            if count[ident] == 0:
                self.add(
                    "isolated_device",
                    path,
                    f"Device {ident!r} has no valid link to another device.",
                    subject=ident,
                )
            elif isinstance(d.get("type"), str) and d["type"].lower() == "pc" and count[ident] > 1:
                self.add(
                    "too_many_links",
                    path,
                    f"Device {ident!r} is a pc; a pc may have only one link.",
                    subject=ident,
                )
            for fam in (4, 6):
                own = self.own[fam].get(ident)
                used = {ip for (lid, dev), ip in self.end_ips[fam].items() if dev == ident}
                if own is not None and used and own[0] not in used:
                    self.add(
                        "device_ip_not_on_link",
                        f"{path}/{BLOCK[fam]}/ip_address",
                        f"Device {ident}'s {FAMILY_NAME[fam]} address {own[0]} is not the address it uses on any link.",
                        subject=ident,
                        value=str(own[0]),
                        hint={"link_addresses": sorted(map(str, used))},
                    )

    def duplicates(self) -> None:
        for fam in (4, 6):
            for ip, uses in self.uses[fam].items():
                owners = sorted({dev for dev, _ in uses})
                if len(owners) < 2:
                    continue
                for dev, path in uses:
                    self.add(
                        "duplicate_ip",
                        path,
                        f"{ip} is used by {len(owners)} devices ({', '.join(owners)}); each device needs its own address.",
                        subject=dev,
                        value=str(ip),
                        related=[o for o in owners if o != dev],
                    )

    def segment_checks(self, segs: list[Segment]) -> None:
        link_index = {lk["id"]: i for i, lk in self.valid_links}
        for fam in (4, 6):
            seg_net: dict[str, Any] = {}
            for s in segs:
                nets = {
                    self.link_nets[fam][lid] for lid in s.link_ids if lid in self.link_nets[fam]
                }
                if len(nets) > 1:
                    listed = ", ".join(sorted(map(str, nets)))
                    for lid in s.link_ids:
                        if lid in self.link_nets[fam]:
                            self.add(
                                "segment_network_mismatch",
                                f"/links/{link_index[lid]}/{BLOCK[fam]}/network_address",
                                f"Links {', '.join(s.link_ids)} are one broadcast segment (joined by "
                                f"{', '.join(s.layer2_ids)}) but carry different {FAMILY_NAME[fam]} networks: {listed}.",
                                subject=lid,
                                value=str(self.link_nets[fam][lid]),
                                related=[x for x in s.link_ids if x != lid],
                            )
                    continue
                if not nets:
                    continue
                net = nets.pop()
                seg_net[s.id] = net
                # one device, one address per segment; one address per device across segments
                if usable_hosts(net.prefixlen, fam) < len(s.hosts):
                    need = smallest_prefix(len(s.hosts), fam)
                    lid = s.link_ids[0]
                    self.add(
                        "network_too_small",
                        f"/links/{link_index[lid]}/{BLOCK[fam]}/prefix_length",
                        f"{net} gives {usable_hosts(net.prefixlen, fam)} usable address(es) but segment "
                        f"{s.id} has {len(s.hosts)} devices; use /{need} or shorter.",
                        subject=lid,
                        value=net.prefixlen,
                        related=list(s.link_ids),
                        hint={"hosts": len(s.hosts), "suggested_prefix": need},
                    )
            self.reused_across_segments(fam, segs)
            items = sorted(seg_net.items(), key=lambda kv: kv[0])
            for a in range(len(items)):
                for b in range(a + 1, len(items)):
                    (sa, na), (sb, nb) = items[a], items[b]
                    if not na.overlaps(nb):
                        continue
                    same = na == nb
                    for sid, net, other_sid, other in ((sa, na, sb, nb), (sb, nb, sa, na)):
                        lid = next(x for x in _seg(segs, sid).link_ids if x in self.link_nets[fam])
                        msg = (
                            f"{net} is used by two separate segments ({sid} and {other_sid}); "
                            "devices on different segments need different networks."
                            if same
                            else f"{net} ({sid}) overlaps {other} ({other_sid}); VLSM blocks must not overlap."
                        )
                        self.add(
                            "overlapping_networks",
                            f"/links/{link_index[lid]}/{BLOCK[fam]}/network_address",
                            msg,
                            subject=lid,
                            value=str(net),
                            related=list(_seg(segs, other_sid).link_ids),
                        )

    def reused_across_segments(self, fam: int, segs: list[Segment]) -> None:
        seg_of = {lid: s.id for s in segs for lid in s.link_ids}
        by_dev_ip: dict[tuple[str, Any], set[str]] = defaultdict(set)
        for (lid, dev), ip in self.end_ips[fam].items():
            if lid in seg_of:
                by_dev_ip[(dev, ip)].add(seg_of[lid])
        for (dev, ip), sids in by_dev_ip.items():
            if len(sids) > 1:
                i, _ = self.devices[dev]
                self.add(
                    "ip_reused_on_several_links",
                    f"/devices/{i}",
                    f"Device {dev!r} uses {ip} on {len(sids)} different segments ({', '.join(sorted(sids))}); "
                    "each interface needs an address of its own segment.",
                    subject=dev,
                    value=str(ip),
                )

    # --------------------------------------------------------------------- report
    def report(self, segs: list[Segment]) -> dict[str, Any]:
        errors = [x.to_dict() for x in self.issues if x.severity == "error"]
        warnings = [x.to_dict() for x in self.issues if x.severity == "warning"]
        return {
            "schema_version": VALIDATION_SCHEMA_VERSION,
            "valid": not errors,
            "status": "valid" if not errors else "invalid",
            "require_ipv4": self.require_ipv4,
            "summary": {
                "errors": len(errors),
                "warnings": len(warnings),
                "codes": dict(sorted(_count(errors + warnings).items())),
            },
            "errors": errors,
            "warnings": warnings,
            "segments": [self.segment_view(s) for s in segs],
        }

    def segment_view(self, s: Segment) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": s.id,
            "links": s.link_ids,
            "layer2_devices": s.layer2_ids,
            "hosts": s.hosts,
        }
        for fam in (4, 6):
            nets = sorted(
                {str(self.link_nets[fam][lid]) for lid in s.link_ids if lid in self.link_nets[fam]}
            )
            out[BLOCK[fam]] = nets[0] if len(nets) == 1 else None if not nets else nets
        out["suggested_prefix"] = {
            "ipv4": smallest_prefix(len(s.hosts), 4),
            "ipv6": smallest_prefix(len(s.hosts), 6),
        }
        return out


def _seg(segs: list[Segment], sid: str) -> Segment:
    return next(s for s in segs if s.id == sid)


def _named(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _complete(d: dict[str, Any], fam: int) -> bool:
    block = d.get(BLOCK[fam])
    return isinstance(block, dict) and all(block.get(f) is not None for f in DEVICE_FIELDS[fam])


def _count(issues: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for x in issues:
        out[x["code"]] += 1
    return out
