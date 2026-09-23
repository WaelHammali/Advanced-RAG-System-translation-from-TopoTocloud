"""IPv6 recognition: the same strict, never-guess rules as IPv4, one family further."""

import pytest
from vision_pipeline.geometry import Rect
from vision_pipeline.ocr.address_normalizer import (
    canonical_ip,
    ip_in_network,
    ip_version,
    mask_for,
    max_prefix,
    network_of_any,
    normalize_ipv6_cidr,
    normalize_ipv6_only,
    parse_cidr_any,
    parse_host_suffix6,
    resolve_host_suffix,
)
from vision_pipeline.ocr.semantic_parser import SemanticParser
from vision_pipeline.schemas.raw import OcrText

P = SemanticParser()


def parse(text):
    return P.parse(OcrText("text_001", text, 0.9, Rect.from_list([0, 0, 300, 20])))


# ------------------------------------------------------------------ normalizer
@pytest.mark.parametrize(
    "text,canon",
    [
        ("2001:db8::1", "2001:db8::1"),
        ("2001:DB8:0:0:0:0:0:1", "2001:db8::1"),
        ("fe80::1", "fe80::1"),
        ("2001:0db8:0001::0005", "2001:db8:1::5"),
    ],
)
def test_ipv6_is_stored_in_canonical_form(text, canon):
    a = normalize_ipv6_only(text)
    assert a.ip_address == canon and a.version == 6 and a.subnet_mask is None


def test_ipv6_cidr_derives_the_network_and_has_no_mask():
    a = normalize_ipv6_cidr("2001:db8:1::5/64")
    assert (a.ip_address, a.prefix_length, a.network_address, a.subnet_mask) == (
        "2001:db8:1::5",
        64,
        "2001:db8:1::",
        None,
    )
    assert not a.is_network_form
    assert normalize_ipv6_cidr("2001:DB8:1::/64").is_network_form


@pytest.mark.parametrize(
    "bad",
    [
        "2001:db8:::1",
        "12345::1",
        "fe80::1%eth0",
        "gggg::1",
        "::",
        "2001:db8::/129",
        "2001:db8::1/064",
        "1:2:3:4:5:6:7:8:9",
        "192.168.1.1",
    ],
)
def test_invalid_ipv6_is_rejected(bad):
    assert normalize_ipv6_only(bad) is None and normalize_ipv6_cidr(bad) is None


@pytest.mark.parametrize("text,value", [("::1", 1), ("::2", 2), ("::a", 10), ("::FFFF", 0xFFFF)])
def test_ipv6_suffix_parse(text, value):
    assert parse_host_suffix6(text) == value


@pytest.mark.parametrize("text", ["::0", "::", "::12345", "::g", ".2", "2"])
def test_ipv6_suffix_parse_rejects(text):
    assert parse_host_suffix6(text) is None


def test_ipv6_suffix_resolves_against_the_link_network():
    r = resolve_host_suffix("2001:db8:1::", 64, "::2")
    assert r.reason == "resolved"
    a = r.address
    assert a.ip_address == "2001:db8:1::2" and a.prefix_length == 64 and a.subnet_mask is None


@pytest.mark.parametrize(
    "net,prefix,suffix,reason",
    [
        ("2001:db8:1::", 64, ".2", "suffix_family_mismatch"),
        ("192.168.1.0", 24, "::2", "suffix_family_mismatch"),
        ("2001:db8::", 127, "::2", "suffix_outside_network"),
        ("2001:db8::1", 64, "::2", "network_address_has_host_bits"),
        ("2001:db8::1", 128, "::1", "prefix_has_no_host_bits"),
    ],
)
def test_ipv6_suffix_refuses(net, prefix, suffix, reason):
    r = resolve_host_suffix(net, prefix, suffix)
    assert r.address is None and r.reason == reason


def test_family_helpers():
    assert (
        ip_version("10.0.0.1") == 4 and ip_version("2001:db8::1") == 6 and ip_version("x") is None
    )
    assert canonical_ip("2001:DB8::0001") == "2001:db8::1"
    assert max_prefix(4) == 32 and max_prefix(6) == 128
    assert mask_for(24, 4) == "255.255.255.0" and mask_for(64, 6) is None
    assert network_of_any("2001:db8:1::5", 64) == "2001:db8:1::"
    assert ip_in_network("2001:db8:1::5", "2001:db8:1::", 64)
    assert not ip_in_network("2001:db8:2::5", "2001:db8:1::", 64)
    assert not ip_in_network("10.0.0.1", "2001:db8:1::", 64)
    assert parse_cidr_any("2001:DB8::1/64") == ("2001:db8::1", 64, 6)
    assert parse_cidr_any("10.0.0.1") == ("10.0.0.1", None, 4)
    assert parse_cidr_any("10.0.0.1/33") is None


# ------------------------------------------------------------------ parser
@pytest.mark.parametrize(
    "text,kind,value",
    [
        ("2001:db8::1", "ipv6", "2001:db8::1"),
        ("2001:db8:1::/64", "ipv6_cidr", "2001:db8:1::"),
        ("::2", "host_suffix", None),
        ("::A", "host_suffix", None),
        ("IPv6: 2001:db8::1/64", "ipv6_cidr", "2001:db8::1"),
        ("IPv6:d6ee:363a:5c51:0129::1", "ipv6", "d6ee:363a:5c51:129::1"),
        ("2001:db8::1 /64", "ipv6_cidr", "2001:db8::1"),
    ],
)
def test_parser_classifies_ipv6(text, kind, value):
    (p,) = parse(text)
    assert p.semantic_type == kind and p.raw_text == text
    if value is not None:
        assert p.address.ip_address == value
    assert p.slot == ("ip6" if kind.startswith("ipv6") else None)


def test_parser_lowercases_ipv6_suffix_and_flags_network_form():
    assert parse("::A")[0].host_suffix == "::a"
    assert parse("2001:db8:1::/64")[0].is_network_form


@pytest.mark.parametrize("text", ["::0", "::", "2001:db8:::1", "fe80::1%eth0", "10:30", "gggg::1"])
def test_parser_never_forces_bad_ipv6(text):
    assert [p.semantic_type for p in parse(text)] == ["unknown"]


def test_device_name_label_is_still_not_stripped():
    assert parse("R1: 2001:db8::1")[0].semantic_type == "unknown"
