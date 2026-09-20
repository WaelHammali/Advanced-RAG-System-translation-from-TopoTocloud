import pytest
from vision_pipeline.ocr.address_normalizer import (
    broadcast_of,
    mask_to_prefix,
    network_of,
    normalize_cidr,
    normalize_ip_and_mask,
    normalize_ip_only,
    normalize_mask_only,
    parse_host_suffix,
    prefix_to_mask,
    resolve_host_suffix,
)


@pytest.mark.parametrize(
    "mask,prefix",
    [
        ("255.255.255.0", 24),
        ("255.255.0.0", 16),
        ("255.255.255.252", 30),
        ("255.0.0.0", 8),
        ("255.255.255.255", 32),
        ("128.0.0.0", 1),
        ("255.255.254.0", 23),
    ],
)
def test_valid_masks(mask, prefix):
    assert mask_to_prefix(mask) == prefix
    assert prefix_to_mask(prefix) == mask


@pytest.mark.parametrize(
    "text",
    ["192.168.1.1", "255.0.255.0", "255.255.255.1", "0.0.0.0", "255.255.255", "256.0.0.0", "abc"],
)
def test_non_masks(text):
    assert mask_to_prefix(text) is None


def test_case_a_cidr():
    a = normalize_cidr("192.168.1.1/24")
    assert a.to_dict() == {
        "ip_address": "192.168.1.1",
        "prefix_length": 24,
        "subnet_mask": "255.255.255.0",
        "network_address": "192.168.1.0",
    }
    assert a.field_origin["subnet_mask"] == "derived_from_prefix_length"


def test_case_b_ip_plus_mask():
    a = normalize_ip_and_mask("192.168.1.1", "255.255.255.0")
    assert a.to_dict() == normalize_cidr("192.168.1.1/24").to_dict()
    assert a.field_origin["prefix_length"] == "derived_from_subnet_mask"
    assert normalize_ip_and_mask("192.168.1.1", "255.0.255.0") is None


def test_case_c_ip_only():
    assert normalize_ip_only("192.168.1.1").to_dict() == {
        "ip_address": "192.168.1.1",
        "prefix_length": None,
        "subnet_mask": None,
        "network_address": None,
    }


def test_case_d_mask_only():
    assert normalize_mask_only("255.255.255.0").to_dict() == {
        "ip_address": None,
        "prefix_length": 24,
        "subnet_mask": "255.255.255.0",
        "network_address": None,
    }


@pytest.mark.parametrize(
    "bad",
    [
        "192.168.1.1/33",
        "192.168.1.1/",
        "192.168.1/24",
        "300.1.1.1/24",
        "192.168.01.1/24",
        "192.168.1.1/-1",
    ],
)
def test_invalid_cidr(bad):
    assert normalize_cidr(bad) is None


def test_network_arithmetic_uses_bits_not_strings():
    assert network_of("10.10.10.77", 26) == "10.10.10.64"
    assert broadcast_of("10.10.10.64", 26) == "10.10.10.127"
    assert network_of("172.16.5.9", 12) == "172.16.0.0"


def test_network_form_flag():
    assert normalize_cidr("192.168.1.0/24").is_network_form
    assert not normalize_cidr("192.168.1.1/24").is_network_form
    assert not normalize_cidr("10.0.0.1/32").is_network_form  # host route
    assert not normalize_cidr("10.0.0.0/31").is_network_form  # point-to-point pair


@pytest.mark.parametrize("text,value", [(".1", 1), (".254", 254), (".0", 0), (".255", 255)])
def test_suffix_parse(text, value):
    assert parse_host_suffix(text) == value


@pytest.mark.parametrize("text", [".256", "1", "..1", ".01", ".1.2", ". 1", ""])
def test_suffix_parse_rejects(text):
    assert parse_host_suffix(text) is None


def test_resolve_suffix_slash24():
    r = resolve_host_suffix("192.168.1.0", 24, ".2")
    assert r.reason == "resolved"
    assert r.address.to_dict() == {
        "ip_address": "192.168.1.2",
        "prefix_length": 24,
        "subnet_mask": "255.255.255.0",
        "network_address": "192.168.1.0",
    }


def test_resolve_suffix_uses_arithmetic_in_small_subnet():
    assert resolve_host_suffix("10.0.0.4", 30, ".5").address.ip_address == "10.0.0.5"
    assert resolve_host_suffix("10.0.0.4", 30, ".6").address.ip_address == "10.0.0.6"
    assert resolve_host_suffix("10.0.0.0", 31, ".1").address.ip_address == "10.0.0.1"


@pytest.mark.parametrize(
    "net,prefix,suffix,reason",
    [
        ("10.10.0.0", 16, ".20", "prefix_outside_final_octet_range"),
        ("10.0.0.0", 8, ".1", "prefix_outside_final_octet_range"),
        ("10.0.0.4", 30, ".1", "suffix_outside_network"),  # 10.0.0.1 is not in 10.0.0.4/30
        ("10.0.0.4", 30, ".4", "suffix_is_network_or_broadcast_address"),
        ("10.0.0.4", 30, ".7", "suffix_is_network_or_broadcast_address"),
        ("192.168.1.0", 24, ".0", "suffix_is_network_or_broadcast_address"),
        ("192.168.1.0", 24, ".255", "suffix_is_network_or_broadcast_address"),
        ("192.168.1.0", 24, ".300", "invalid_host_suffix"),
        ("192.168.1.5", 24, ".2", "network_address_has_host_bits"),
        ("192.168.1.0", 32, ".2", "prefix_outside_final_octet_range"),
    ],
)
def test_resolve_suffix_refuses(net, prefix, suffix, reason):
    r = resolve_host_suffix(net, prefix, suffix)
    assert r.address is None and r.reason == reason
