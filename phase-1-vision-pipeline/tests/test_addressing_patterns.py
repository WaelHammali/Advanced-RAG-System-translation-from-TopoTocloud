"""The eight addressing patterns from the phase-1 specification (tests A-H), run through the
whole fusion + topology path with hand-made raw detector output."""

from __future__ import annotations

import json

import helpers as h
from helpers import device
from vision_pipeline.geometry import Rect
from vision_pipeline.schemas.raw import OcrText

ROUTER = ("router", (100, 100, 180, 180))
NULL_NET = {
    "ip_address": None,
    "prefix_length": None,
    "subnet_mask": None,
    "network_address": None,
    "host_suffix": None,
}


def _single_router(texts):
    return h.run(h.yolo([ROUTER]), h.ocr(texts), h.opencv())


def test_A_cidr_address():
    _, topo = _single_router(
        [("R1", (128, 186, 152, 202)), ("192.168.1.1/24", (100, 206, 180, 222))]
    )
    d = device(topo, "device_001")
    assert d["name"] == "R1"
    assert d["network"] == {
        "ip_address": "192.168.1.1",
        "prefix_length": 24,
        "subnet_mask": "255.255.255.0",
        "network_address": "192.168.1.0",
        "host_suffix": None,
    }
    assert d["provenance"]["name"]["sources"] == ["ocr", "fusion"]
    assert d["addresses"][0]["provenance"]["subnet_mask"]["method"] == "derived_from_prefix_length"
    assert d["addresses"][0]["provenance"]["ip_address"]["method"] == "ocr_direct"


def test_B_ip_plus_dotted_mask_gives_same_result_as_cidr():
    _, topo = _single_router(
        [
            ("R1", (128, 186, 152, 202)),
            ("192.168.1.1", (110, 206, 170, 220)),
            ("255.255.255.0", (105, 224, 175, 238)),
        ]
    )
    d = device(topo, "device_001")
    assert d["name"] == "R1"
    assert d["network"] == {
        "ip_address": "192.168.1.1",
        "prefix_length": 24,
        "subnet_mask": "255.255.255.0",
        "network_address": "192.168.1.0",
        "host_suffix": None,
    }
    assert d["addresses"][0]["provenance"]["prefix_length"]["method"] == "derived_from_subnet_mask"


def test_C_ip_only_never_assumes_a_prefix():
    _, topo = _single_router([("R1", (128, 186, 152, 202)), ("192.168.1.1", (110, 206, 170, 220))])
    d = device(topo, "device_001")
    assert d["network"] == {**NULL_NET, "ip_address": "192.168.1.1"}
    assert d["network"]["prefix_length"] is None and d["network"]["subnet_mask"] is None
    assert d["network"]["network_address"] is None


# ------------------------------------------------------------------------------ test D

DEVICES = [("router", (100, 150, 180, 230)), ("pc", (500, 150, 580, 230))]
CABLE = [(180.0, 190.0), (500.0, 190.0)]


def _test_d_inputs(with_label=True, suffixes=(".1", ".2")):
    texts = [("R1", (110, 236, 134, 252)), ("PC1", (525, 236, 555, 252))]
    if suffixes:
        texts += [(suffixes[0], (185, 165, 199, 180)), (suffixes[1], (481, 165, 495, 180))]
    if with_label:
        texts.append(("192.168.1.0/24", (280, 200, 400, 216)))
    return h.yolo(DEVICES), h.ocr(texts), h.opencv([h.link(CABLE)])


def test_D_abbreviated_suffixes_resolved_through_link_network():
    result, topo = h.run(*_test_d_inputs())
    r1, pc1 = device(topo, "device_001"), device(topo, "device_002")
    assert (r1["name"], pc1["name"]) == ("R1", "PC1")
    assert r1["network"] == {
        "ip_address": "192.168.1.1",
        "prefix_length": 24,
        "subnet_mask": "255.255.255.0",
        "network_address": "192.168.1.0",
        "host_suffix": ".1",
    }
    assert pc1["network"] == {
        "ip_address": "192.168.1.2",
        "prefix_length": 24,
        "subnet_mask": "255.255.255.0",
        "network_address": "192.168.1.0",
        "host_suffix": ".2",
    }
    (link,) = topo["links"]
    assert (link["source"], link["target"]) == ("device_001", "device_002")
    assert link["network"] == {
        "network_address": "192.168.1.0",
        "prefix_length": 24,
        "subnet_mask": "255.255.255.0",
    }
    # provenance of a resolved address names every contributor
    prov = r1["addresses"][0]["provenance"]["ip_address"]
    assert prov["method"] == "derived_from_host_suffix_and_link_network"
    assert set(prov["sources"]) == {"ocr", "opencv", "fusion", "address_resolver"}
    assert prov["evidence"]["link_id"] == link["id"]
    assert topo["unresolved"] == []


def test_E_suffix_without_reliable_prefix_is_not_guessed():
    # no network label at all
    _, topo = h.run(*_test_d_inputs(with_label=False))
    for dev_id, suffix in (("device_001", ".1"), ("device_002", ".2")):
        assert device(topo, dev_id)["network"] == {**NULL_NET, "host_suffix": suffix}
    assert topo["links"][0]["network"] == {
        "network_address": None,
        "prefix_length": None,
        "subnet_mask": None,
    }
    assert (
        device(topo, "device_001")["addresses"][0]["unresolved_reason"]
        == "link_has_no_network_label"
    )


def test_E_suffix_with_no_link_at_all():
    _, topo = h.run(
        h.yolo(DEVICES),
        h.ocr([("PC1", (525, 236, 555, 252)), (".2", (481, 165, 495, 180))]),
        h.opencv(),
    )
    assert device(topo, "device_002")["network"] == {**NULL_NET, "host_suffix": ".2"}
    assert topo["links"] == []


def test_E_shorter_prefix_suffix_is_ambiguous_and_not_guessed():
    # 10.10.0.0/16 + ".20": no convention says which octet ".20" is
    y, o, c = _test_d_inputs(with_label=False, suffixes=(".20", ".21"))
    o.texts.append(OcrText("text_099", "10.10.0.0/16", 0.95, Rect(280, 200, 400, 216)))
    _, topo = h.run(y, o, c)
    assert topo["links"][0]["network"]["network_address"] == "10.10.0.0"
    for dev_id, suffix in (("device_001", ".20"), ("device_002", ".21")):
        d = device(topo, dev_id)
        assert d["network"] == {**NULL_NET, "host_suffix": suffix}
        assert d["addresses"][0]["unresolved_reason"] == "prefix_outside_final_octet_range"


def test_F_network_label_near_cable_belongs_to_link_not_router():
    _, topo = h.run(*_test_d_inputs(suffixes=()))
    (link,) = topo["links"]
    assert link["network"]["network_address"] == "192.168.1.0"
    assert link["network"]["prefix_length"] == 24
    for d in topo["devices"]:
        assert d["network"]["ip_address"] is None
        assert d["addresses"] == []
    assert topo["unresolved"] == []


def test_F_unattached_network_label_is_preserved_as_unresolved():
    # label nowhere near a cable or a device
    y = h.yolo(DEVICES)
    o = h.ocr([("192.168.1.0/24", (300, 340, 420, 356))])
    _, topo = h.run(y, o, h.opencv([h.link(CABLE)]))
    assert topo["links"][0]["network"]["network_address"] is None
    (u,) = topo["unresolved"]
    assert u["kind"] == "network_label" and u["raw_text"] == "192.168.1.0/24"


def test_G_router_without_ocr_name_has_null_name():
    _, topo = h.run(h.yolo([ROUTER]), h.ocr([]), h.opencv())
    d = device(topo, "device_001")
    assert d["type"] == "router"
    assert d["name"] is None
    assert d["network"] == NULL_NET
    assert "name" not in d["provenance"]


def test_H_cable_with_one_reliable_endpoint():
    # the far end stops in empty space, 100 px from PC1
    _, topo = h.run(
        h.yolo(DEVICES), h.ocr([]), h.opencv([h.link([(180.0, 190.0), (400.0, 190.0)])])
    )
    (link,) = topo["links"]
    assert link["source"] == "device_001"
    assert link["target"] is None
    assert link["confidence"]["target_endpoint"] is None
    assert "unresolved_endpoint" in link["flags"]
    assert link["confidence"]["overall"] < link["confidence"]["cable_detection"]


def test_topology_json_is_serialisable_and_deterministic():
    a = h.run(*_test_d_inputs())[1]
    b = h.run(*_test_d_inputs())[1]
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
