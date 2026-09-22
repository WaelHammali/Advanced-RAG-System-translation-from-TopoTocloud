"""Grouping, spatial matching and the refuse-to-guess behaviour of the fusion passes."""

from __future__ import annotations

import json

import helpers as h
from helpers import device
from vision_pipeline.config.thresholds import GroupingThresholds
from vision_pipeline.fusion.ocr_grouper import group_texts
from vision_pipeline.geometry import Rect
from vision_pipeline.ocr.semantic_parser import SemanticParser
from vision_pipeline.schemas.raw import OcrText

NULL_NET = {
    "ip_address": None,
    "prefix_length": None,
    "subnet_mask": None,
    "network_address": None,
    "host_suffix": None,
}


def parsed(*items):
    p = SemanticParser()
    out = []
    for i, (text, box) in enumerate(items, start=1):
        out += p.parse(OcrText(f"text_{i:03d}", text, 0.95, Rect.from_list(box)))
    return out


# ------------------------------------------------------------------------------ grouping


def test_name_ip_mask_stack_becomes_one_group():
    texts = parsed(
        ("R1", (128, 186, 152, 202)),
        ("192.168.1.1", (110, 204, 170, 218)),
        ("255.255.255.0", (105, 220, 175, 234)),
    )
    (g,) = group_texts(texts, GroupingThresholds())
    assert [m.semantic_type for m in g.members] == ["device_name", "ipv4", "subnet_mask"]
    assert 0.6 < g.confidence <= 1.0


def test_far_apart_texts_stay_independent():
    texts = parsed(("R1", (100, 100, 124, 116)), ("192.168.1.1/24", (100, 300, 180, 316)))
    assert group_texts(texts, GroupingThresholds()) == []


def test_two_labels_side_by_side_do_not_cross_group():
    texts = parsed(
        ("R1", (100, 100, 124, 116)),
        ("10.0.0.1/24", (90, 118, 150, 132)),
        ("R2", (400, 100, 424, 116)),
        ("10.0.1.1/24", (390, 118, 450, 132)),
    )
    groups = group_texts(texts, GroupingThresholds())
    assert sorted(sorted(m.normalized_text for m in g.members) for g in groups) == [
        ["10.0.0.1/24", "R1"],
        ["10.0.1.1/24", "R2"],
    ]


def test_equidistant_competing_partners_are_not_grouped():
    # one name with two equally good IPs: refuse to pick
    texts = parsed(
        ("R1", (140, 100, 164, 116)),
        ("10.0.0.1/24", (100, 120, 170, 134)),
        ("10.0.1.1/24", (135, 120, 205, 134)),
    )
    groups = group_texts(texts, GroupingThresholds())
    assert all(len(g.members) < 3 for g in groups)
    assert not any(
        {"10.0.0.1/24", "10.0.1.1/24"} <= {m.normalized_text for m in g.members} for g in groups
    )


def test_network_label_and_suffix_are_never_grouped():
    texts = parsed(
        ("R1", (128, 186, 152, 202)),
        ("192.168.1.0/24", (100, 204, 180, 218)),
        (".1", (155, 186, 169, 202)),
    )
    assert group_texts(texts, GroupingThresholds()) == []


def test_cidr_and_separate_mask_do_not_merge():
    texts = parsed(
        ("192.168.1.1/24", (100, 100, 180, 114)), ("255.255.255.0", (100, 116, 180, 130))
    )
    assert group_texts(texts, GroupingThresholds()) == []


# ------------------------------------------------------------------- two-device diagrams


def test_two_routers_each_get_their_own_name_and_address():
    devices = [("router", (100, 100, 180, 180)), ("router", (500, 100, 580, 180))]
    texts = [
        ("R1", (128, 186, 152, 202)),
        ("10.0.0.1/24", (105, 204, 175, 218)),
        ("R2", (528, 186, 552, 202)),
        ("10.0.1.1/24", (505, 204, 575, 218)),
    ]
    _, topo = h.run(h.yolo(devices), h.ocr(texts), h.opencv())
    a, b = device(topo, "device_001"), device(topo, "device_002")
    assert (a["name"], a["network"]["ip_address"], a["network"]["prefix_length"]) == (
        "R1",
        "10.0.0.1",
        24,
    )
    assert (b["name"], b["network"]["ip_address"], b["network"]["prefix_length"]) == (
        "R2",
        "10.0.1.1",
        24,
    )
    assert topo["unresolved"] == []


def test_text_between_two_devices_is_ambiguous_and_stays_null():
    devices = [("router", (100, 100, 180, 180)), ("router", (200, 100, 280, 180))]
    _, topo = h.run(h.yolo(devices), h.ocr([("R1", (183, 130, 197, 146))]), h.opencv())
    assert all(d["name"] is None for d in topo["devices"])
    (u,) = topo["unresolved"]
    assert u["kind"] == "device_name" and u["raw_text"] == "R1"
    assert u["reason"] == "ambiguous_device_association"


def test_text_too_far_from_every_device_is_unresolved_not_attached():
    _, topo = h.run(
        h.yolo([("router", (100, 100, 180, 180))]),
        h.ocr([("R1", (600, 300, 624, 316))]),
        h.opencv(),
    )
    assert topo["devices"][0]["name"] is None
    assert topo["unresolved"][0]["reason"] == "no_device_nearby"


def test_two_names_claiming_one_device_are_both_refused_when_scores_tie():
    dev = [("router", (100, 100, 180, 180))]
    texts = [
        ("R1", (100, 186, 124, 202)),
        ("R2", (156, 186, 180, 202)),
    ]  # symmetric around the icon
    _, topo = h.run(h.yolo(dev), h.ocr(texts), h.opencv())
    assert topo["devices"][0]["name"] is None
    assert {u["raw_text"] for u in topo["unresolved"]} == {"R1", "R2"}


def test_ip_with_no_name_is_still_attached_to_its_device():
    _, topo = h.run(
        h.yolo([("pc", (100, 100, 180, 180))]),
        h.ocr([("192.168.1.9", (105, 186, 175, 200))]),
        h.opencv(),
    )
    d = topo["devices"][0]
    assert d["name"] is None
    assert d["network"] == {**NULL_NET, "ip_address": "192.168.1.9"}


def test_mask_only_near_device_keeps_mask_and_prefix_but_no_ip():
    _, topo = h.run(
        h.yolo([("pc", (100, 100, 180, 180))]),
        h.ocr([("255.255.255.0", (105, 186, 175, 200))]),
        h.opencv(),
    )
    assert topo["devices"][0]["network"] == {
        **NULL_NET,
        "subnet_mask": "255.255.255.0",
        "prefix_length": 24,
    }


def test_stray_ip_and_mask_on_same_device_are_paired():
    # far enough apart that they are not grouped, close enough that both belong to the device
    dev = [("pc", (100, 100, 180, 180))]
    texts = [("192.168.1.9", (105, 186, 175, 200)), ("255.255.255.0", (185, 120, 260, 134))]
    _, topo = h.run(h.yolo(dev), h.ocr(texts), h.opencv())
    n = topo["devices"][0]["network"]
    assert (n["ip_address"], n["prefix_length"], n["network_address"]) == (
        "192.168.1.9",
        24,
        "192.168.1.0",
    )


# ------------------------------------------------------------------- links and labels

DEV2 = [("router", (100, 150, 180, 230)), ("pc", (500, 150, 580, 230))]


def test_two_conflicting_labels_on_one_link_are_both_refused():
    texts = [("192.168.1.0/24", (250, 200, 370, 216)), ("192.168.2.0/24", (330, 165, 450, 181))]
    _, topo = h.run(
        h.yolo(DEV2), h.ocr(texts), h.opencv([h.link([(180.0, 190.0), (500.0, 190.0)])])
    )
    assert topo["links"][0]["network"]["network_address"] is None
    assert {u["raw_text"] for u in topo["unresolved"]} == {"192.168.1.0/24", "192.168.2.0/24"}


def test_link_between_three_devices_in_a_row_keeps_distinct_endpoints():
    devs = [
        ("router", (100, 150, 180, 230)),
        ("switch", (350, 150, 430, 230)),
        ("pc", (600, 150, 680, 230)),
    ]
    links = [h.link([(180.0, 190.0), (350.0, 190.0)]), h.link([(430.0, 190.0), (600.0, 190.0)])]
    _, topo = h.run(h.yolo(devs), h.ocr([]), h.opencv(links))
    assert [(lk["source"], lk["target"]) for lk in topo["links"]] == [
        ("device_001", "device_002"),
        ("device_002", "device_003"),
    ]


def test_router_with_two_subnets_keeps_both_addresses():
    devs = [
        ("router", (300, 150, 380, 230)),
        ("pc", (50, 150, 130, 230)),
        ("pc", (600, 150, 680, 230)),
    ]
    links = [h.link([(130.0, 190.0), (300.0, 190.0)]), h.link([(380.0, 190.0), (600.0, 190.0)])]
    texts = [
        ("192.168.1.0/24", (160, 200, 270, 216)),
        ("192.168.2.0/24", (420, 200, 540, 216)),
        (".1", (283, 165, 297, 180)),
        (".1", (383, 165, 397, 180)),
    ]
    _, topo = h.run(h.yolo(devs), h.ocr(texts), h.opencv(links))
    r = device(topo, "device_001")  # the router (first in the list)
    ips = sorted((a["ip_address"], a["network_address"]) for a in r["addresses"])
    assert ips == [("192.168.1.1", "192.168.1.0"), ("192.168.2.1", "192.168.2.0")]
    # a scalar block cannot represent two addresses without guessing which is primary
    assert r["network"] == NULL_NET


def test_duplicate_address_on_one_link_is_refused():
    texts = [
        (".1", (185, 165, 199, 180)),
        (".1", (481, 165, 495, 180)),
        ("192.168.1.0/24", (280, 200, 400, 216)),
    ]
    _, topo = h.run(
        h.yolo(DEV2), h.ocr(texts), h.opencv([h.link([(180.0, 190.0), (500.0, 190.0)])])
    )
    for d in topo["devices"]:
        assert d["network"]["ip_address"] is None and d["network"]["host_suffix"] == ".1"
        assert d["addresses"][0]["source"] == "host_suffix_only"


def test_noise_line_touching_no_device_is_not_a_link_but_is_preserved():
    _, topo = h.run(h.yolo(DEV2), h.ocr([]), h.opencv([h.link([(250.0, 350.0), (450.0, 350.0)])]))
    assert topo["links"] == []
    assert topo["unresolved"][0]["kind"] == "link_candidate"
    assert topo["unresolved"][0]["reason"] == "no_device_at_either_endpoint"


def test_branched_candidate_is_not_turned_into_a_link():
    c = h.link([(180.0, 190.0), (500.0, 190.0)], path_type="branched")
    c.start = c.end = None
    _, topo = h.run(h.yolo(DEV2), h.ocr([]), h.opencv([c]))
    assert topo["links"] == []
    assert topo["unresolved"][0]["reason"] == "path_endpoints_undetermined"


def test_link_looping_back_to_same_device_is_rejected():
    dev = [("router", (100, 100, 300, 300))]
    _, topo = h.run(h.yolo(dev), h.ocr([]), h.opencv([h.link([(150.0, 100.0), (250.0, 100.0)])]))
    assert topo["links"] == []
    assert topo["unresolved"][0]["reason"] == "both_endpoints_on_same_device"


def test_low_confidence_cable_is_rejected_by_threshold():
    _, topo = h.run(
        h.yolo(DEV2), h.ocr([]), h.opencv([h.link([(180.0, 190.0), (500.0, 190.0)], conf=0.1)])
    )
    assert topo["links"] == []
    assert topo["unresolved"][0]["reason"] == "low_geometric_confidence"


def test_endpoint_in_the_gap_between_two_devices_is_ambiguous_not_guessed():
    # two PCs stacked with a 20 px gap; the cable stops in that gap, pointing at neither
    devs = [
        ("pc", (100, 100, 180, 180)),
        ("pc", (100, 200, 180, 280)),
        ("router", (500, 150, 580, 230)),
    ]
    _, topo = h.run(h.yolo(devs), h.ocr([]), h.opencv([h.link([(140.0, 190.0), (500.0, 190.0)])]))
    (lk,) = topo["links"]
    assert lk["source"] == "device_003" and lk["target"] is None


def test_thresholds_are_configurable_not_hardcoded():
    from vision_pipeline.config.thresholds import Thresholds

    strict = Thresholds()
    strict.name_to_device.tier.medium = 0.99
    strict.name_to_device.tier.high = 0.999
    texts = [("R1", (128, 186, 152, 202))]
    _, topo = h.run(h.yolo([("router", (100, 100, 180, 180))]), h.ocr(texts), h.opencv())
    assert topo["devices"][0]["name"] == "R1"
    from vision_pipeline.fusion.fusion_engine import FusionEngine
    from vision_pipeline.topology import TopologyBuilder, build_graph

    res = FusionEngine(strict, graph_builder=build_graph).run(
        h.yolo([("router", (100, 100, 180, 180))]), h.ocr(texts), h.opencv()
    )
    assert TopologyBuilder().build(res.to_document())["devices"][0]["name"] is None


def test_link_type_labels_near_a_device_are_ignored_end_to_end():
    # "GigabitEthernet0/1" sits where an address would normally be grouped from, "Fa0/0" and
    # "Ethernet" sit near the two devices; none of it may become a name, an address, or leak
    # into topology.json - only the real name and IP may survive.
    dev = [("router", (100, 150, 180, 230)), ("pc", (500, 150, 580, 230))]
    cable = [(180.0, 190.0), (500.0, 190.0)]
    texts = [
        ("R1", (110, 236, 134, 252)),
        ("192.168.1.1/24", (95, 256, 185, 272)),
        ("GigabitEthernet0/1", (90, 274, 230, 290)),
        ("PC1", (525, 236, 555, 252)),
        ("Fa0/0", (505, 164, 545, 180)),
        ("Ethernet", (300, 120, 360, 136)),
    ]
    res, topo = h.run(h.yolo(dev), h.ocr(texts), h.opencv([h.link(cable)]))

    r1, pc1 = device(topo, "device_001"), device(topo, "device_002")
    assert r1["name"] == "R1" and r1["network"]["ip_address"] == "192.168.1.1"
    assert pc1["name"] == "PC1"
    assert topo["unresolved"] == []
    dump = json.dumps(topo)
    assert "GigabitEthernet" not in dump and "Fa0/0" not in dump and "Ethernet" not in dump

    ignored = [
        c
        for c in res.to_document()["ocr_classifications"]
        if "ignored_link_type_or_interface_term" in c["notes"]
    ]
    assert {c["raw_text"] for c in ignored} == {"GigabitEthernet0/1", "Fa0/0", "Ethernet"}
    assert all(c["semantic_type"] == "unknown" for c in ignored)
