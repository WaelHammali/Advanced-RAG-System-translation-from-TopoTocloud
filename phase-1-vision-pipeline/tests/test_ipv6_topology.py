"""IPv6 carried through fusion into topology.json and topology.simple.json.

IPv6 lives in separate ``network6`` blocks; an IPv4-only diagram must not change at all.
"""

import json
from pathlib import Path

import pytest
from helpers import device, link, ocr, opencv, run, yolo
from vision_pipeline.topology.topology_builder import (
    TopologyBuilder,
    TopologyValidationError,
    validate_simple,
    validate_topology,
)

SCHEMAS = Path(__file__).resolve().parents[1] / "vision_pipeline" / "schemas" / "json"
DEVICES = [("router", (100, 150, 180, 230)), ("pc", (600, 150, 680, 230))]
NAMES = [("R1", (125, 240, 150, 256)), ("PC1", (620, 240, 655, 256))]
CABLE = [link([(180, 190), (600, 190)])]


def dual_stack():
    return run(
        yolo(DEVICES),
        ocr(
            [
                ("192.168.1.0/24", (330, 168, 450, 184)),
                ("2001:db8:1::/64", (330, 196, 460, 212)),
                (".1", (186, 168, 200, 184)),
                ("::1", (186, 196, 206, 212)),
                (".2", (580, 168, 594, 184)),
                ("::2", (574, 196, 594, 212)),
                *NAMES,
            ]
        ),
        opencv(CABLE),
    )


def test_dual_stack_cable_resolves_both_families_side_by_side():
    _, topo = dual_stack()
    lk = topo["links"][0]
    assert lk["network"] == {
        "network_address": "192.168.1.0",
        "prefix_length": 24,
        "subnet_mask": "255.255.255.0",
    }
    assert lk["network6"] == {"network_address": "2001:db8:1::", "prefix_length": 64}
    r1, pc = device(topo, "device_001"), device(topo, "device_002")
    assert (
        r1["network"]["ip_address"] == "192.168.1.1"
        and r1["network6"]["ip_address"] == "2001:db8:1::1"
    )
    assert (
        pc["network"]["ip_address"] == "192.168.1.2"
        and pc["network6"]["ip_address"] == "2001:db8:1::2"
    )
    assert topo["unresolved"] == []


def test_dual_stack_simple_form_carries_a_network6_extension():
    _, topo = dual_stack()
    simple = TopologyBuilder().build_simple(topo)
    lk = simple["links"][0]
    assert (
        lk["network"]["source_ip"] == "192.168.1.1" and lk["network"]["target_ip"] == "192.168.1.2"
    )
    assert lk["network6"] == {
        "network_address": "2001:db8:1::",
        "prefix_length": 64,
        "source_ip": "2001:db8:1::1",
        "target_ip": "2001:db8:1::2",
    }
    assert simple["devices"][0]["network6"] == {
        "ip_address": "2001:db8:1::1",
        "prefix_length": 64,
        "network_address": "2001:db8:1::",
    }


def test_dual_stack_outputs_match_the_json_schemas():
    jsonschema = pytest.importorskip("jsonschema")
    _, topo = dual_stack()
    jsonschema.validate(
        json.loads(json.dumps(topo)), json.loads((SCHEMAS / "topology.schema.json").read_text())
    )
    jsonschema.validate(
        TopologyBuilder().build_simple(topo),
        json.loads((SCHEMAS / "topology_simple.schema.json").read_text()),
    )


def test_ipv6_suffix_never_resolves_against_an_ipv4_label():
    _, topo = run(
        yolo(DEVICES),
        ocr([("192.168.1.0/24", (330, 168, 450, 184)), ("::1", (186, 196, 206, 212)), *NAMES]),
        opencv(CABLE),
    )
    r1 = device(topo, "device_001")
    assert r1["network6"]["ip_address"] is None and r1["network6"]["host_suffix"] == "::1"
    assert r1["addresses"][0]["unresolved_reason"] == "link_has_no_network_label"
    assert r1["network"]["ip_address"] is None


def test_device_label_with_ipv4_and_ipv6_lines_gives_both_addresses():
    _, topo = run(
        yolo(DEVICES),
        ocr(
            [
                ("R1", (110, 240, 135, 256)),
                ("10.0.0.1/24", (110, 258, 200, 274)),
                ("2001:db8::1/64", (110, 276, 225, 292)),
                ("PC1", (620, 240, 655, 256)),
            ]
        ),
        opencv(CABLE),
    )
    r1 = device(topo, "device_001")
    assert r1["name"] == "R1"
    assert r1["network"]["ip_address"] == "10.0.0.1" and r1["network"]["prefix_length"] == 24
    assert r1["network6"] == {
        "ip_address": "2001:db8::1",
        "prefix_length": 64,
        "network_address": "2001:db8::",
        "host_suffix": None,
    }


def test_ipv4_only_diagram_has_no_network6_anywhere():
    _, topo = run(
        yolo(DEVICES),
        ocr(
            [
                ("192.168.1.0/24", (330, 168, 450, 184)),
                (".1", (186, 168, 200, 184)),
                (".2", (580, 168, 594, 184)),
                *NAMES,
            ]
        ),
        opencv(CABLE),
    )
    simple = TopologyBuilder().build_simple(topo)
    for doc in (topo, simple):
        assert all("network6" not in x for x in doc["devices"] + doc["links"])


def test_two_ipv6_labels_on_one_cable_conflict_but_an_ipv4_one_does_not():
    _, topo = run(
        yolo(DEVICES),
        ocr(
            [
                ("192.168.1.0/24", (330, 168, 450, 184)),
                ("2001:db8:1::/64", (330, 196, 460, 212)),
                ("2001:db8:2::/64", (250, 196, 320, 212)),
                *NAMES,
            ]
        ),
        opencv(CABLE),
    )
    lk = topo["links"][0]
    assert lk["network"]["network_address"] == "192.168.1.0"
    assert "network6" not in lk
    refused = [u["raw_text"] for u in topo["unresolved"] if u["kind"] == "network_label"]
    assert sorted(refused) == ["2001:db8:1::/64", "2001:db8:2::/64"]


@pytest.mark.parametrize(
    "block,bad,msg",
    [
        ("network6", {"subnet_mask": "255.255.255.0"}, "no subnet_mask"),
        ("network6", {"ip_address": "10.0.0.1"}, "is not IPv6"),
        ("network6", {"ip_address": "2001:DB8::1"}, "invalid ip_address"),
        ("network6", {"prefix_length": 129}, "invalid prefix_length"),
        ("network6", {"network_address": "2001:db8:2::"}, "does not match"),
        ("network", {"ip_address": "2001:db8:1::1"}, "is not IPv4"),
        ("network", {"prefix_length": 33}, "invalid prefix_length"),
    ],
)
def test_validation_rejects_family_mistakes(block, bad, msg):
    _, topo = dual_stack()
    topo["devices"][0][block].update(bad)
    with pytest.raises(TopologyValidationError, match=msg):
        validate_topology(topo)


def test_simple_validation_rejects_an_ipv4_end_address_in_network6():
    _, topo = dual_stack()
    simple = TopologyBuilder().build_simple(topo)
    simple["links"][0]["network6"]["source_ip"] = "192.168.1.1"
    with pytest.raises(TopologyValidationError, match="network6.source_ip"):
        validate_simple(simple)
