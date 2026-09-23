"""Pre-RAG validator: readiness rules + addressing checks, IPv4 and IPv6."""

import copy
import ipaddress
import json

import pytest
from vision_pipeline.validation import validate
from vision_pipeline.validation.addressing import (
    host_problem,
    mask_prefix,
    smallest_prefix,
    usable_hosts,
)
from vision_pipeline.validation.segments import find_segments


def dev(i, t, name, ip=None, p=None, ip6=None, p6=64):
    net = {
        "ip_address": ip,
        "prefix_length": p,
        "subnet_mask": None if p is None else str(ipaddress.ip_network(f"0.0.0.0/{p}").netmask),
        "network_address": None
        if ip is None
        else str(ipaddress.ip_network(f"{ip}/{p}", strict=False).network_address),
    }
    d = {"id": i, "type": t, "name": name, "network": net}
    if ip6:
        d["network6"] = {
            "ip_address": ip6,
            "prefix_length": p6,
            "network_address": str(
                ipaddress.ip_network(f"{ip6}/{p6}", strict=False).network_address
            ),
        }
    return d


def lk(i, s, t, net, p, sip, tip, net6=None, s6=None, t6=None):
    out = {
        "id": i,
        "source": s,
        "target": t,
        "network": {
            "network_address": net,
            "prefix_length": p,
            "subnet_mask": str(ipaddress.ip_network(f"0.0.0.0/{p}").netmask),
            "source_ip": sip,
            "target_ip": tip,
        },
    }
    if net6:
        out["network6"] = {
            "network_address": net6,
            "prefix_length": 64,
            "source_ip": s6,
            "target_ip": t6,
        }
    return out


def lan():
    """R1 -- SW1 -- {PC1, PC2} on 192.168.1.0/24 and 2001:db8:1::/64; R1 -- R2 on 10.0.0.0/30."""
    return {
        "devices": [
            dev("d1", "router", "R1", "192.168.1.1", 24, "2001:db8:1::1"),
            dev("d2", "switch", "SW1"),
            dev("d3", "pc", "PC1", "192.168.1.10", 24, "2001:db8:1::10"),
            dev("d4", "pc", "PC2", "192.168.1.11", 24, "2001:db8:1::11"),
            dev("d5", "router", "R2", "10.0.0.2", 30, "2001:db8:2::2"),
        ],
        "links": [
            lk(
                "l1",
                "d1",
                "d2",
                "192.168.1.0",
                24,
                "192.168.1.1",
                None,
                "2001:db8:1::",
                "2001:db8:1::1",
            ),
            lk(
                "l2",
                "d2",
                "d3",
                "192.168.1.0",
                24,
                None,
                "192.168.1.10",
                "2001:db8:1::",
                None,
                "2001:db8:1::10",
            ),
            lk(
                "l3",
                "d2",
                "d4",
                "192.168.1.0",
                24,
                None,
                "192.168.1.11",
                "2001:db8:1::",
                None,
                "2001:db8:1::11",
            ),
            lk(
                "l4",
                "d1",
                "d5",
                "10.0.0.0",
                30,
                "10.0.0.1",
                "10.0.0.2",
                "2001:db8:2::",
                "2001:db8:2::1",
                "2001:db8:2::2",
            ),
        ],
    }


def errors(doc, **kw):
    return {(e["code"], e["path"]) for e in validate(doc, **kw)["errors"]}


def codes(doc, **kw):
    return {e["code"] for e in validate(doc, **kw)["errors"]}


def changed(fn):
    doc = copy.deepcopy(lan())
    fn(doc)
    return doc


# --------------------------------------------------------------------------- good input
def test_a_correct_dual_stack_network_is_valid():
    r = validate(lan())
    assert r["valid"] and r["status"] == "valid" and r["errors"] == [] and r["warnings"] == []
    seg = r["segments"][0]
    assert seg["links"] == ["l1", "l2", "l3"] and seg["layer2_devices"] == ["d2"]
    assert seg["hosts"] == ["d1", "d3", "d4"]
    assert seg["network"] == "192.168.1.0/24" and seg["network6"] == "2001:db8:1::/64"
    assert seg["suggested_prefix"] == {"ipv4": 29, "ipv6": 64}


def test_the_report_is_json_and_does_not_change_its_input():
    doc = lan()
    before = copy.deepcopy(doc)
    json.dumps(validate(doc))
    assert doc == before


# ------------------------------------------------------------------------ duplicates
def test_duplicate_ipv4_is_reported_everywhere_it_is_used():
    doc = changed(
        lambda d: (
            d["devices"][3]["network"].update(ip_address="192.168.1.10"),
            d["links"][2]["network"].update(target_ip="192.168.1.10"),
        )
    )
    dup = [e for e in validate(doc)["errors"] if e["code"] == "duplicate_ip"]
    assert {e["path"] for e in dup} == {
        "/devices/2/network/ip_address",
        "/devices/3/network/ip_address",
        "/links/1/network/target_ip",
        "/links/2/network/target_ip",
    }
    assert {e["subject"]: e["related"] for e in dup if e["path"].startswith("/devices")} == {
        "d3": ["d4"],
        "d4": ["d3"],
    }


def test_duplicate_ipv6_is_reported():
    doc = changed(
        lambda d: (
            d["devices"][3]["network6"].update(ip_address="2001:db8:1::10"),
            d["links"][2]["network6"].update(target_ip="2001:db8:1::10"),
        )
    )
    assert ("duplicate_ip", "/links/2/network6/target_ip") in errors(doc)


def test_duplicate_device_names_are_reported():
    doc = changed(lambda d: d["devices"][4].update(name="pc1"))
    assert {p for c, p in errors(doc) if c == "duplicate_device_name"} == {
        "/devices/2/name",
        "/devices/4/name",
    }


# ------------------------------------------------------------------- mask / format
def test_a_mask_read_as_an_ip_is_named_as_such():
    doc = changed(lambda d: d["links"][1]["network"].update(target_ip="255.255.0.0"))
    assert ("ip_looks_like_mask", "/links/1/network/target_ip") in errors(doc)


@pytest.mark.parametrize(
    "mask,expected",
    [
        ("255.0.255.0", {"invalid_subnet_mask", "subnet_mask_mismatch"}),
        ("255.255.0.0", {"subnet_mask_mismatch"}),
        ("255.255.255.256", {"invalid_subnet_mask"}),
    ],
)
def test_bad_masks(mask, expected):
    doc = changed(lambda d: d["links"][3]["network"].update(subnet_mask=mask))
    assert {c for c, p in errors(doc) if p == "/links/3/network/subnet_mask"} == expected


@pytest.mark.parametrize("ip", ["10.0.0.256", "10.0.0", "10.0.0.02", "abc", " 10.0.0.2", 10])
def test_malformed_ipv4_is_rejected(ip):
    doc = changed(lambda d: d["links"][3]["network"].update(target_ip=ip))
    assert ("invalid_link_ip", "/links/3/network/target_ip") in errors(doc)


@pytest.mark.parametrize(
    "ip", ["2001:db8:2:::2", "2001:db8:2::g", "fe80::1%eth0", "2001:db8:2::2/64"]
)
def test_malformed_ipv6_is_rejected(ip):
    doc = changed(lambda d: d["links"][3]["network6"].update(target_ip=ip))
    assert ("invalid_link_ip", "/links/3/network6/target_ip") in errors(doc)


def test_an_address_in_the_wrong_family_block_is_rejected_with_a_clear_message():
    doc = changed(
        lambda d: (
            d["links"][3]["network"].update(target_ip="2001:db8:2::2"),
            d["links"][3]["network6"].update(source_ip="10.0.0.1"),
        )
    )
    r = validate(doc)
    msgs = {e["path"]: e["message"] for e in r["errors"] if e["code"] == "invalid_link_ip"}
    assert "is an IPv6 address" in msgs["/links/3/network/target_ip"]
    assert "is an IPv4 address" in msgs["/links/3/network6/source_ip"]


def test_ipv6_block_rules():
    doc = changed(
        lambda d: d["links"][3]["network6"].update(prefix_length=129, subnet_mask="255.255.255.0")
    )
    assert {c for c, _ in errors(doc)} >= {"invalid_prefix_length", "unexpected_subnet_mask"}
    doc = changed(lambda d: d["links"][3]["network6"].update(network_address="2001:db8:2::5"))
    assert ("invalid_network_address", "/links/3/network6/network_address") in errors(doc)


def test_non_canonical_ipv6_is_only_a_warning():
    r = validate(changed(lambda d: d["links"][3]["network6"].update(target_ip="2001:DB8:2::2")))
    assert r["valid"] and [w["code"] for w in r["warnings"]] == ["non_canonical_ip"]
    assert r["warnings"][0]["hint"] == {"expected": "2001:db8:2::2"}


# --------------------------------------------------------------- host addresses
@pytest.mark.parametrize(
    "ip,code",
    [
        ("10.0.0.3", "ip_is_broadcast_address"),
        ("10.0.0.0", "ip_is_network_address"),
        ("127.0.0.1", "reserved_ip"),
        ("224.0.0.5", "reserved_ip"),
        ("0.0.0.1", "reserved_ip"),
        ("255.255.255.255", "ip_looks_like_mask"),
    ],
)
def test_ipv4_addresses_a_device_cannot_use(ip, code):
    doc = changed(lambda d: d["links"][3]["network"].update(target_ip=ip))
    assert (code, "/links/3/network/target_ip") in errors(doc)


@pytest.mark.parametrize(
    "ip,code",
    [("2001:db8:2::", "ip_is_network_address"), ("ff02::1", "reserved_ip"), ("::1", "reserved_ip")],
)
def test_ipv6_addresses_a_device_cannot_use(ip, code):
    doc = changed(lambda d: d["links"][3]["network6"].update(target_ip=ip))
    assert (code, "/links/3/network6/target_ip") in errors(doc)


def test_point_to_point_31_has_no_network_or_broadcast():
    assert host_problem(ipaddress.ip_address("10.0.0.0"), 31) is None
    assert host_problem(ipaddress.ip_address("169.254.1.1"), 16)[0] == "link_local_ip"


# ----------------------------------------------------------------- segments / VLSM
def test_links_behind_one_switch_must_share_one_network():
    doc = changed(lambda d: d["links"][2]["network"].update(network_address="192.168.2.0"))
    assert {p for c, p in errors(doc) if c == "segment_network_mismatch"} == {
        f"/links/{i}/network/network_address" for i in range(3)
    }


def test_overlapping_and_reused_networks():
    doc = changed(
        lambda d: d["links"][3]["network"].update(
            network_address="192.168.1.0",
            prefix_length=30,
            source_ip="192.168.1.1",
            target_ip="192.168.1.2",
        )
    )
    assert {"overlapping_networks", "ip_reused_on_several_links"} <= codes(doc)
    doc = changed(
        lambda d: d["links"][3]["network6"].update(network_address="2001:db8::", prefix_length=32)
    )
    assert "overlapping_networks" in codes(doc)


def test_a_segment_too_small_for_its_devices_suggests_the_vlsm_prefix():
    def shrink(d):
        for x in d["links"][:3]:
            x["network"].update(prefix_length=30, subnet_mask="255.255.255.252")

    r = validate(changed(shrink))
    small = [e for e in r["errors"] if e["code"] == "network_too_small"]
    assert len(small) == 1 and small[0]["hint"] == {"hosts": 3, "suggested_prefix": 29}


def test_a_switch_with_a_management_ip_is_a_host_of_its_segment():
    doc = lan()
    doc["links"][0]["network"]["target_ip"] = "192.168.1.2"
    segs = find_segments(doc["devices"], doc["links"])
    assert segs[0].hosts == ["d1", "d2", "d3", "d4"] and segs[0].layer2_ids == ["d2"]
    assert validate(doc)["valid"]


def test_a_switch_with_addresses_in_two_networks_routes_between_them():
    doc = lan()
    doc["links"][0]["network"]["target_ip"] = "192.168.1.2"
    doc["links"][1]["network"].update(
        network_address="192.168.2.0", source_ip="192.168.2.1", target_ip="192.168.2.10"
    )
    doc["devices"][2]["network"].update(ip_address="192.168.2.10", network_address="192.168.2.0")
    doc["links"][1]["network6"].update(
        network_address="2001:db8:3::", source_ip="2001:db8:3::1", target_ip="2001:db8:3::10"
    )
    doc["devices"][2]["network6"].update(
        ip_address="2001:db8:3::10", network_address="2001:db8:3::"
    )
    r = validate(doc)
    assert r["valid"], r["errors"]
    assert [w["code"] for w in r["warnings"]] == ["layer2_device_routes"]
    assert [s["links"] for s in r["segments"]] == [["l1", "l3"], ["l2"], ["l4"]]


def test_vlsm_arithmetic():
    assert [usable_hosts(p, 4) for p in (24, 30, 31, 32)] == [254, 2, 2, 1]
    assert [usable_hosts(p, 6) for p in (64, 126, 127, 128)] == [2**64 - 1, 3, 2, 1]
    assert [smallest_prefix(n, 4) for n in (1, 2, 3, 6, 7, 50, 254, 255)] == [
        30,
        30,
        29,
        29,
        28,
        26,
        24,
        23,
    ]
    assert smallest_prefix(1000, 6) == 64
    assert mask_prefix("255.255.255.0") == 24 and mask_prefix("255.0.255.0") is None


# ------------------------------------------------------------ readiness rules
def test_readiness_rules_are_mirrored_with_the_same_codes_and_paths():
    doc = changed(
        lambda d: (
            d["devices"][0].update(name=" "),
            d["devices"].append(dev("d6", "pc", "PC3")),
            d["links"].append(
                lk("l5", "d3", "d1", "192.168.1.0", 24, "192.168.1.10", "192.168.1.1")
            ),
            d["links"][1]["network"].update(target_ip=None),
            d["devices"][4]["network"].update(ip_address="10.0.0.1"),
        )
    )
    got = errors(doc)
    assert {
        ("missing_device_name", "/devices/0/name"),
        ("missing_ip_address", "/devices/5/network/ip_address"),
        ("isolated_device", "/devices/5"),
        ("too_many_links", "/devices/2"),
        ("missing_link_ip", "/links/1/network/target_ip"),
        ("device_ip_not_on_link", "/devices/4/network/ip_address"),
    } <= got


def test_ipv6_only_network_needs_the_opt_in():
    doc = lan()
    for x in doc["devices"] + doc["links"]:
        x["network"] = dict.fromkeys(x["network"])
    assert not validate(doc)["valid"]
    assert validate(doc, require_ipv4=False)["valid"]
    doc["devices"][2].pop("network6")
    assert "missing_device_address" in codes(doc, require_ipv4=False)


def test_parity_with_the_rag_readiness_check():
    readiness = pytest.importorskip("net2cloud.readiness")
    cases = [
        lan(),
        changed(lambda d: d["links"][3]["network"].update(subnet_mask="255.0.255.0")),
        changed(lambda d: d["links"][1]["network"].update(target_ip="10.9.9.9")),
        changed(lambda d: d["devices"][0].update(name="")),
    ]
    for doc in cases:
        theirs = {(e["code"], e["path"]) for e in readiness.check_readiness(doc)["errors"]}
        assert theirs <= errors(doc)


# ------------------------------------------------------------------------ CLI / pipeline
def test_cli_validate_exit_code_and_report(tmp_path, capsys):
    from vision_pipeline.cli import main

    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text(json.dumps(lan()))
    bad.write_text(
        json.dumps(changed(lambda d: d["links"][3]["network"].update(target_ip="10.0.0.3")))
    )
    assert main(["validate", "--input", str(good), "--output-dir", str(tmp_path)]) == 0
    assert json.loads((tmp_path / "validation.json").read_text())["valid"]
    assert main(["validate", "--input", str(bad), "--report", str(tmp_path / "r.json")]) == 1
    assert "ip_is_broadcast_address" in capsys.readouterr().out
    assert not json.loads((tmp_path / "r.json").read_text())["valid"]


# ------------------------------------------------------------------------ corrections
from vision_pipeline.validation.corrections import (  # noqa: E402
    CorrectionError,
    apply_corrections,
    parse_address,
)


def dup_lan():
    return changed(
        lambda d: (
            d["devices"][3]["network"].update(ip_address="192.168.1.10"),
            d["links"][2]["network"].update(target_ip="192.168.1.10"),
        )
    )


def test_correcting_a_duplicate_ip_makes_the_topology_valid_and_leaves_the_input_alone():
    doc = dup_lan()
    before = copy.deepcopy(doc)
    r = apply_corrections(doc, [{"device": "PC2", "ip": "192.168.1.11"}])
    assert doc == before and r["rejected"] == [] and r["report"]["valid"]
    t = r["topology"]
    assert t["devices"][3]["network"] == {
        "ip_address": "192.168.1.11",
        "prefix_length": 24,
        "subnet_mask": "255.255.255.0",
        "network_address": "192.168.1.0",
    }
    assert t["links"][2]["network"]["target_ip"] == "192.168.1.11"


@pytest.mark.parametrize(
    "corr,code",
    [
        ({"device": "PC2", "ip": "192.168.1.10"}, "duplicate_ip"),
        ({"device": "PC2", "ip": "255.255.0.0"}, "ip_looks_like_mask"),
        ({"device": "PC2", "ip": "192.168.1.255"}, "ip_is_broadcast_address"),
        ({"device": "PC2", "ip": "192.168.1.0"}, "ip_is_network_address"),
        ({"device": "PC2", "ip": "127.0.0.1/8"}, "reserved_ip"),
        ({"device": "PC2", "ip": "192.168.1.300"}, "invalid_ip"),
        ({"device": "PC2", "ip": "192.168.1.12/33"}, "invalid_prefix_length"),
        ({"device": "PC2", "ip": "192.168.1.12/024"}, "invalid_prefix_length"),
        ({"device": "PC2", "ip": "10.0.0.5/24"}, "ip_outside_link_network"),
        ({"device": "PC2", "ip": "192.168.1.12", "mask": "255.0.255.0"}, "invalid_subnet_mask"),
        ({"device": "PC2", "ip": "192.168.1.12/24", "mask": "255.255.255.252"}, "prefix_mismatch"),
        (
            {"device": "PC2", "ip": "2001:db8:1::12", "mask": "255.255.255.0"},
            "unexpected_subnet_mask",
        ),
        ({"device": "PC2", "ip": "2001:db8:1::10"}, "duplicate_ip"),
        ({"device": "PC2", "ip": "fe80::1%eth0"}, "invalid_ip"),
        ({"device": "R1", "link": "l3", "ip": "10.0.0.1"}, "link_not_on_device"),
        ({"link": "l4", "network": "10.0.0.1/30"}, "invalid_network_address"),
        ({"link": "l4", "network": "10.0.0.0"}, "prefix_required"),
        ({"device": "PC2", "name": "pc1"}, "duplicate_device_name"),
        ({"device": "PC2", "name": "  "}, "invalid_name"),
        ({"device": "nope", "ip": "1.2.3.4"}, "unknown_device"),
        ({"link": "l9", "network": "10.0.0.0/30"}, "unknown_link"),
        ({"device": "PC2", "ip": "192.168.1.12", "colour": "red"}, "invalid_correction"),
        ("PC2 192.168.1.12", "invalid_correction"),
    ],
)
def test_bad_corrections_are_rejected_and_change_nothing(corr, code):
    doc = dup_lan()
    r = apply_corrections(doc, [corr])
    assert [x["code"] for x in r["rejected"]] == [code] and r["applied"] == []
    assert r["topology"] == doc


def test_ipv6_correction_uses_the_link_prefix_and_goes_to_network6():
    r = apply_corrections(lan(), [{"device": "PC2", "ip": "2001:DB8:1::12"}])
    t = r["topology"]
    assert t["devices"][3]["network6"] == {
        "ip_address": "2001:db8:1::12",
        "prefix_length": 64,
        "network_address": "2001:db8:1::",
    }
    assert t["links"][2]["network6"]["target_ip"] == "2001:db8:1::12" and r["report"]["valid"]


def test_router_on_two_links_needs_the_link_only_when_unclear():
    r = apply_corrections(
        lan(), [{"device": "R1", "ip": "192.168.1.5"}]
    )  # its main address is on l1
    t = r["topology"]
    assert (
        t["links"][0]["network"]["source_ip"] == "192.168.1.5"
        and t["links"][3]["network"]["source_ip"] == "10.0.0.1"
    )
    doc = lan()
    doc["devices"][0]["network"] = dict.fromkeys(doc["devices"][0]["network"])
    r = apply_corrections(doc, [{"device": "R1", "ip": "192.168.1.5"}])
    assert r["rejected"][0]["code"] == "link_required" and r["rejected"][0]["hint"] == {
        "links": ["l1", "l4"]
    }
    r = apply_corrections(lan(), [{"device": "R1", "link": "l4", "ip": "10.0.0.2/30"}])
    assert r["rejected"][0]["code"] == "duplicate_ip"


def test_other_link_address_does_not_move_the_main_address():
    r = apply_corrections(
        lan(),
        [
            {"link": "l4", "network": "10.0.0.4/30"},
            {"device": "R1", "link": "l4", "ip": "10.0.0.5"},
            {"device": "R2", "ip": "10.0.0.6"},
        ],
    )
    assert r["rejected"] == [] and r["report"]["valid"], r["report"]["errors"]
    assert r["topology"]["devices"][0]["network"]["ip_address"] == "192.168.1.1"


def test_a_missing_address_is_filled_and_the_link_network_is_derived():
    doc = lan()
    doc["links"][3]["network"] = {
        "network_address": None,
        "prefix_length": None,
        "subnet_mask": None,
        "source_ip": None,
        "target_ip": None,
    }
    doc["devices"][4]["network"] = dict.fromkeys(doc["devices"][4]["network"])
    r = apply_corrections(
        doc,
        [{"device": "R1", "link": "l4", "ip": "10.0.0.1/30"}, {"device": "R2", "ip": "10.0.0.2"}],
    )
    assert r["rejected"] == [] and r["report"]["valid"], r["report"]["errors"]
    assert r["topology"]["links"][3]["network"]["network_address"] == "10.0.0.0"


def test_parse_address_forms():
    assert parse_address("10.0.0.1/24")[1] == 24
    assert parse_address("10.0.0.1", prefix="24")[1] == 24
    assert parse_address("10.0.0.1", mask="255.255.255.0")[1] == 24
    assert parse_address("2001:db8::1/64") == (ipaddress.ip_address("2001:db8::1"), 64)
    with pytest.raises(CorrectionError):
        parse_address("10.0.0.1", prefix=True)


def test_cli_correct_loop(tmp_path):
    from vision_pipeline.cli import main

    simple = tmp_path / "topology.simple.json"
    simple.write_text(json.dumps(dup_lan()))
    assert main(["validate", "--output-dir", str(tmp_path)]) == 1
    fixes = '[{"device": "PC2", "ip": "192.168.1.11"}]'
    assert main(["correct", "--corrections", fixes, "--output-dir", str(tmp_path)]) == 0
    assert json.loads((tmp_path / "validation.json").read_text())["valid"]
    assert json.loads((tmp_path / "topology.simple.detected.json").read_text()) == dup_lan()
    assert (
        main(
            [
                "correct",
                "--corrections",
                '[{"device": "PC2", "ip": "1.2.3"}]',
                "--output-dir",
                str(tmp_path),
            ]
        )
        == 1
    )
    assert json.loads(simple.read_text())["devices"][3]["network"]["ip_address"] == "192.168.1.11"


# ---------------------------------------------------------------------- auto-addressing
from vision_pipeline.validation.autoaddress import AutoAddressError, autoaddress  # noqa: E402


def vlsm_exercise():
    """R1-R2-R3 in a chain, each router with one LAN behind a switch: 50, 20 and 5 PCs."""
    devs = [dev("r1", "router", "R1"), dev("r2", "router", "R2"), dev("r3", "router", "R3")]
    links = [
        lk("p1", "r1", "r2", "0.0.0.0", 30, None, None),
        lk("p2", "r2", "r3", "0.0.0.0", 30, None, None),
    ]
    for name, router, n in (("A", "r1", 50), ("B", "r2", 20), ("C", "r3", 5)):
        devs.append(dev(f"sw{name}", "switch", f"SW{name}"))
        links.append(lk(f"u{name}", router, f"sw{name}", "0.0.0.0", 30, None, None))
        for i in range(n):
            devs.append(dev(f"pc{name}{i}", "pc", f"PC{name}{i}"))
            links.append(lk(f"l{name}{i}", f"sw{name}", f"pc{name}{i}", "0.0.0.0", 30, None, None))
    return {"devices": devs, "links": links}


def test_autoaddress_solves_the_classic_vlsm_exercise():
    r = autoaddress(vlsm_exercise(), ipv4_base="172.16.0.0/24")
    assert r["report"]["valid"], r["report"]["errors"]
    got = {s["hosts"]: (s["ipv4"]["network"], s["ipv4"]["mask"]) for s in r["plan"]["segments"]}
    assert got == {
        51: ("172.16.0.0/26", "255.255.255.192"),
        21: ("172.16.0.64/27", "255.255.255.224"),
        6: ("172.16.0.96/29", "255.255.255.248"),
        2: ("172.16.0.108/30", "255.255.255.252"),
    }
    p2p = [s["ipv4"]["network"] for s in r["plan"]["segments"] if s["hosts"] == 2]
    assert p2p == ["172.16.0.104/30", "172.16.0.108/30"]
    lan_a = next(s for s in r["plan"]["segments"] if s["hosts"] == 51)
    assert lan_a["ipv4"]["addresses"]["r1"] == "172.16.0.1"  # the gateway gets the first address
    assert "network6" not in json.dumps(r["topology"])


def test_autoaddress_blocks_never_overlap_and_fit_their_hosts():
    r = autoaddress(vlsm_exercise(), ipv4_base="10.0.0.0/8", ipv6_base="2001:db8:acad::/48")
    nets = [
        ipaddress.ip_network(s[k]["network"])
        for s in r["plan"]["segments"]
        for k in ("ipv4", "ipv6")
    ]
    assert not any(a.overlaps(b) for i, a in enumerate(nets) for b in nets[i + 1 :])
    assert all(s["ipv6"]["network"].endswith("/64") for s in r["plan"]["segments"])
    assert r["report"]["valid"] and all(
        s["ipv4"]["usable"] >= s["hosts"] for s in r["plan"]["segments"]
    )


def test_autoaddress_ipv6_can_be_sized_like_ipv4():
    doc = vlsm_exercise()
    for x in doc["links"]:
        x["network"] = dict.fromkeys(x["network"])  # an IPv6-only diagram
    r = autoaddress(
        doc, ipv4_base=None, ipv6_base="2001:db8:acad::/64", ipv6_prefix=None, require_ipv4=False
    )
    got = sorted((s["hosts"], s["ipv6"]["network"]) for s in r["plan"]["segments"])
    assert got == [
        (2, "2001:db8:acad::68/126"),
        (2, "2001:db8:acad::6c/126"),
        (6, "2001:db8:acad::60/125"),
        (21, "2001:db8:acad::40/123"),
        (51, "2001:db8:acad::/122"),
    ]
    assert r["report"]["valid"], r["report"]["errors"]


def test_autoaddress_repairs_a_broken_detection_and_keeps_names():
    doc = changed(
        lambda d: (
            d["links"][2]["network"].update(target_ip="255.255.0.0"),
            d["devices"][3]["network"].update(ip_address="192.168.1.10"),
            d["links"][3]["network"].update(subnet_mask="255.0.255.0"),
        )
    )
    assert not validate(doc)["valid"]
    r = autoaddress(doc)
    assert r["report"]["valid"], r["report"]["errors"]
    assert [d["name"] for d in r["topology"]["devices"]] == [d["name"] for d in doc["devices"]]
    assert r["topology"]["devices"][1]["network"] == dict.fromkeys(
        ("ip_address", "prefix_length", "subnet_mask", "network_address")
    )  # the switch
    assert (
        "network6" in r["topology"]["links"][0]
    )  # the input had IPv6, so IPv6 is re-addressed too


def test_autoaddress_refuses_a_base_that_is_too_small():
    with pytest.raises(AutoAddressError, match="needs 112"):
        autoaddress(vlsm_exercise(), ipv4_base="172.16.0.0/26")
    with pytest.raises(AutoAddressError):
        autoaddress(lan(), ipv4_base="10.0.0.1/8")
    with pytest.raises(AutoAddressError):
        autoaddress(lan(), ipv4_base="2001:db8::/48")


def test_cli_autoaddress(tmp_path, capsys):
    from vision_pipeline.cli import main

    simple = tmp_path / "topology.simple.json"
    simple.write_text(json.dumps(vlsm_exercise()))
    assert main(["autoaddress", "--output-dir", str(tmp_path), "--ipv4-base", "172.16.0.0/24"]) == 0
    assert "172.16.0.0/26" in capsys.readouterr().out
    assert (
        json.loads((tmp_path / "addressing_plan.json").read_text())["ipv4_base"] == "172.16.0.0/24"
    )
    assert json.loads((tmp_path / "validation.json").read_text())["valid"]
    assert main(["autoaddress", "--output-dir", str(tmp_path), "--ipv4-base", "172.16.0.0/26"]) == 2
