import pytest
from vision_pipeline.geometry import Rect
from vision_pipeline.ocr.semantic_parser import SemanticParser
from vision_pipeline.schemas.raw import OcrText

P = SemanticParser()


def parse(text, box=(0, 0, 200, 20), polygon=None):
    return P.parse(OcrText("text_001", text, 0.9, Rect.from_list(box), polygon))


@pytest.mark.parametrize(
    "text,kind",
    [
        ("R1", "device_name"),
        ("R2", "device_name"),
        ("PC1", "device_name"),
        ("SW1", "device_name"),
        ("Router1", "device_name"),
        ("SW-2", "device_name"),
        ("192.168.1.1", "ipv4"),
        ("10.0.0.1", "ipv4"),
        ("192.168.1.1/24", "ipv4_cidr"),
        ("10.0.0.1/30", "ipv4_cidr"),
        ("192.168.1.0/24", "ipv4_cidr"),
        ("255.255.255.0", "subnet_mask"),
        ("255.255.0.0", "subnet_mask"),
        ("255.255.255.252", "subnet_mask"),
        (".1", "host_suffix"),
        (".2", "host_suffix"),
        (".10", "host_suffix"),
        (".254", "host_suffix"),
    ],
)
def test_classification(text, kind):
    (p,) = parse(text)
    assert p.semantic_type == kind
    assert p.raw_text == text


@pytest.mark.parametrize(
    "text",
    [
        "Hello",
        "Figure 1",
        "24",
        "/24",
        "192.168.1",
        "256.1.1.1",
        "01.2.3.4",
        "192.168.1.1/33",
        ".256",
        "1.2.3.4.5",
        "0.0.0.0",
        "",
        "R",
        "12345",
    ],
)
def test_unknown_is_never_forced(text):
    (p,) = parse(text)
    assert p.semantic_type == "unknown"
    assert p.semantic_confidence is None
    assert p.address is None and p.host_suffix is None


def test_ipv4_vs_mask_is_mathematical():
    assert parse("255.255.255.0")[0].semantic_type == "subnet_mask"
    assert parse("255.255.255.0")[0].address.prefix_length == 24
    assert parse("192.168.1.1")[0].semantic_type == "ipv4"
    assert parse("255.0.255.0")[0].semantic_type == "ipv4"  # not contiguous -> plain address
    assert parse("255.255.255.252")[0].address.prefix_length == 30


def test_original_string_kept_after_normalisation():
    (p,) = parse("  192.168. 1.1 ")
    assert p.raw_text == "  192.168. 1.1 "
    assert p.normalized_text == "192.168.1.1" and p.semantic_type == "ipv4"
    assert "whitespace_removed_around_dot_or_slash" in p.notes
    assert p.semantic_confidence < 1.0  # a repair lowers the classification confidence


def test_fullwidth_digits_are_normalised():
    (p,) = parse("１９２．１６８．１．１")
    assert p.semantic_type == "ipv4" and p.normalized_text == "192.168.1.1"


def test_multi_token_region_is_split_only_if_every_token_classifies():
    parts = parse("R1 192.168.1.1", box=(0, 0, 140, 20))
    assert [(p.id, p.semantic_type) for p in parts] == [
        ("text_001.1", "device_name"),
        ("text_001.2", "ipv4"),
    ]
    assert parts[0].bbox.x2 <= parts[1].bbox.x1 + 1e-6
    assert all(p.source_id == "text_001" for p in parts)
    (whole,) = parse("R1 hello")
    assert whole.semantic_type == "unknown"


def test_newline_separated_region_splits_vertically():
    a, b = parse("R1\n192.168.1.1/24", box=(0, 0, 100, 40))
    assert (a.semantic_type, b.semantic_type) == ("device_name", "ipv4_cidr")
    assert a.bbox.y2 <= b.bbox.y1 + 1e-6


def test_network_label_candidate_flag():
    assert parse("192.168.1.0/24")[0].is_network_form
    assert not parse("192.168.1.1/24")[0].is_network_form
    assert not parse("192.168.1.1")[0].is_network_form


def test_custom_name_pattern():
    p = SemanticParser(device_name_pattern=r"^(R|SW|PC)\d+$")
    assert p.parse(OcrText("t", "Router1", 0.9, Rect(0, 0, 9, 9)))[0].semantic_type == "unknown"
    assert p.parse(OcrText("t", "R1", 0.9, Rect(0, 0, 9, 9)))[0].semantic_type == "device_name"


@pytest.mark.parametrize(
    "text",
    [
        "Ethernet",
        "ethernet",
        "Gigabit",
        "GigabitEthernet0/1",
        "GigabitEthernet0/0/1",
        "FastEthernet0/1",
        "TenGigabitEthernet1/1",
        "Gi0/1",
        "gi0/1",
        "Fa0/0",
        "Fa0/0/1",
        "Se0/0/0",
        "Lo0",
        "Tu5",
        "Vlan10",
        "Vl10",
        "Po1",
        "Port-channel1",
        "PortChannel2",
        "Management0/0/0",
        "Mgmt0",
        "Eth0",
        "Eth1/1",
        "Trunk",
        "Uplink",
        "Downlink",
        "Fiber",
        "Copper",
        "Optical",
        "Fe0/1",
        "Te0/1",
        "Hu0/1",
        "Ge0/1",
        "Duplex",
    ],
)
def test_link_type_and_interface_terms_are_always_ignored(text):
    """These would otherwise match DEFAULT_DEVICE_NAME_PATTERN (or, unnumbered, would just be
    unmatched); either way they must never become a device_name or anything else - interface
    names are explicitly out of scope for this phase."""
    (p,) = parse(text)
    assert p.semantic_type == "unknown"
    assert p.semantic_confidence is None
    assert "ignored_link_type_or_interface_term" in p.notes
    assert p.raw_text == text  # still preserved verbatim for traceability in fusion.json


def test_link_type_ignore_does_not_shadow_real_device_names():
    for text in ("R1", "R2", "PC1", "SW1", "SW-2", "Server10", "FW1", "Router5", "AP3"):
        (p,) = parse(text)
        assert p.semantic_type == "device_name", text


def test_link_type_ignore_does_not_shadow_addresses():
    for text, kind in (
        ("192.168.1.1", "ipv4"),
        ("192.168.1.1/24", "ipv4_cidr"),
        ("255.255.255.0", "subnet_mask"),
        (".1", "host_suffix"),
    ):
        (p,) = parse(text)
        assert p.semantic_type == kind


def test_link_type_pattern_is_configurable():
    p = SemanticParser(link_type_pattern=r"^only-this-term$")
    assert (
        p.parse(OcrText("t", "only-this-term", 0.9, Rect(0, 0, 9, 9)))[0].semantic_type == "unknown"
    )
    # with a narrower override, "Gi0/1" is no longer in the ignore list...
    assert (
        p.parse(OcrText("t", "Gi0/1", 0.9, Rect(0, 0, 9, 9)))[0].semantic_type == "unknown"
    )  # no slash match anyway
    # ...but a bare abbreviation that used to be ignored now falls through to device_name
    assert p.parse(OcrText("t", "Se0", 0.9, Rect(0, 0, 9, 9)))[0].semantic_type == "device_name"


def test_axis_angle_from_polygon():
    (p,) = parse(
        "192.168.1.0/24", box=(0, 0, 20, 100), polygon=[(0, 0), (0, 100), (20, 100), (20, 0)]
    )
    assert abs(p.axis_angle - 1.5707963) < 1e-3
    assert p.text_height == 20
