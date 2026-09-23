"""topology.simple.json: the minimal form handed to the RAG (a pure projection of topology.json)."""

import json

import helpers as h
import pytest
from test_addressing_patterns import _test_d_inputs
from vision_pipeline.topology.topology_builder import (
    TopologyBuilder,
    TopologyValidationError,
    validate_simple,
)

NULL4 = {"ip_address": None, "prefix_length": None, "subnet_mask": None, "network_address": None}
NULL_LINK = {
    "network_address": None,
    "prefix_length": None,
    "subnet_mask": None,
    "source_ip": None,
    "target_ip": None,
}


def simple_of(topo, aliases=None):
    return TopologyBuilder(aliases).build_simple(topo)


def test_matches_the_requested_form_exactly():
    _, topo = h.run(*_test_d_inputs())
    assert simple_of(topo) == {
        "devices": [
            {
                "id": "device_1",
                "type": "router",
                "name": "R1",
                "network": {
                    "ip_address": "192.168.1.1",
                    "prefix_length": 24,
                    "subnet_mask": "255.255.255.0",
                    "network_address": "192.168.1.0",
                },
            },
            {
                "id": "device_2",
                "type": "pc",
                "name": "PC1",
                "network": {
                    "ip_address": "192.168.1.2",
                    "prefix_length": 24,
                    "subnet_mask": "255.255.255.0",
                    "network_address": "192.168.1.0",
                },
            },
        ],
        "links": [
            {
                "id": "link_1",
                "source": "device_1",
                "target": "device_2",
                "network": {
                    "network_address": "192.168.1.0",
                    "prefix_length": 24,
                    "subnet_mask": "255.255.255.0",
                    "source_ip": "192.168.1.1",
                    "target_ip": "192.168.1.2",
                },
            }
        ],
    }


def test_no_extra_keys_anywhere():
    _, topo = h.run(*_test_d_inputs())
    s = simple_of(topo)
    assert set(s) == {"devices", "links"}
    assert all(
        set(d) == {"id", "type", "name", "network"} and set(d["network"]) == set(NULL4)
        for d in s["devices"]
    )
    assert all(set(lk) == {"id", "source", "target", "network"} for lk in s["links"])
    assert (
        "host_suffix" not in json.dumps(s)
        and "confidence" not in json.dumps(s)
        and "unresolved" not in s
    )


def test_missing_values_stay_null_and_nothing_is_added():
    _, topo = h.run(
        *_test_d_inputs(with_label=False)
    )  # suffixes but no network -> nothing resolvable
    s = simple_of(topo)
    assert all(d["network"] == NULL4 for d in s["devices"])
    assert s["links"][0]["network"] == NULL_LINK


def test_half_link_keeps_null_target():
    _, topo = h.run(
        h.yolo([("router", (100, 150, 180, 230)), ("pc", (500, 150, 580, 230))]),
        h.ocr([]),
        h.opencv([h.link([(180.0, 190.0), (400.0, 190.0)])]),
    )
    (lk,) = simple_of(topo)["links"]
    assert (lk["source"], lk["target"]) == ("device_1", None)


def _router_joining_two_subnets():
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
        (".10", (132, 165, 150, 180)),
        (".20", (580, 165, 598, 180)),
    ]
    _, topo = h.run(h.yolo(devs), h.ocr(texts), h.opencv(links))
    return topo


def test_router_joining_two_subnets_carries_its_address_on_each_link():
    # the RAG contract: a router joining two subnets uses a different address on each link, and
    # its own ip_address is the one it uses on (its first) link
    topo = _router_joining_two_subnets()
    assert len(h.device(topo, "device_001")["addresses"]) == 2  # rich file keeps both
    s = simple_of(topo)
    router = next(d for d in s["devices"] if d["type"] == "router")
    l1, l2 = s["links"]
    assert (
        l1["network"]["network_address"] == "192.168.1.0"
        and l2["network"]["network_address"] == "192.168.2.0"
    )
    ip_on = {
        lk["network"]["network_address"]: lk["network"]["source_ip"]
        if lk["source"] == router["id"]
        else lk["network"]["target_ip"]
        for lk in (l1, l2)
    }
    assert ip_on == {"192.168.1.0": "192.168.1.1", "192.168.2.0": "192.168.2.1"}
    assert router["network"]["ip_address"] == ip_on[l1["network"]["network_address"]]
    pcs = {d["network"]["ip_address"] for d in s["devices"] if d["type"] == "pc"}
    assert pcs == {"192.168.1.10", "192.168.2.20"}


def test_unlabelled_cable_takes_the_network_both_ends_agree_on():
    devs = [("router", (100, 100, 180, 180)), ("pc", (500, 100, 580, 180))]
    texts = [("192.168.5.1/24", (95, 186, 185, 202)), ("192.168.5.9/24", (495, 186, 585, 202))]
    _, topo = h.run(
        h.yolo(devs), h.ocr(texts), h.opencv([h.link([(180.0, 140.0), (500.0, 140.0)])])
    )
    (lk,) = simple_of(topo)["links"]
    assert lk["network"] == {
        "network_address": "192.168.5.0",
        "prefix_length": 24,
        "subnet_mask": "255.255.255.0",
        "source_ip": "192.168.5.1",
        "target_ip": "192.168.5.9",
    }


def test_unlabelled_cable_whose_ends_disagree_stays_null():
    devs = [("router", (100, 100, 180, 180)), ("pc", (500, 100, 580, 180))]
    texts = [("192.168.5.1/24", (95, 186, 185, 202)), ("10.0.0.9/24", (495, 186, 585, 202))]
    _, topo = h.run(
        h.yolo(devs), h.ocr(texts), h.opencv([h.link([(180.0, 140.0), (500.0, 140.0)])])
    )
    (lk,) = simple_of(topo)["links"]
    assert lk["network"]["network_address"] is None  # never picks one of them
    assert (lk["network"]["source_ip"], lk["network"]["target_ip"]) == ("192.168.5.1", "10.0.0.9")


def test_an_address_without_a_prefix_never_invents_a_link_network():
    devs = [("router", (100, 100, 180, 180)), ("pc", (500, 100, 580, 180))]
    texts = [("192.168.5.1", (95, 186, 185, 202))]
    _, topo = h.run(
        h.yolo(devs), h.ocr(texts), h.opencv([h.link([(180.0, 140.0), (500.0, 140.0)])])
    )
    (lk,) = simple_of(topo)["links"]
    assert lk["network"]["network_address"] is None and lk["network"]["source_ip"] == "192.168.5.1"


def test_type_alias_applies_to_the_minimal_form_only():
    _, topo = h.run(h.yolo([("desktop", (100, 100, 180, 180))]), h.ocr([]), h.opencv())
    assert topo["devices"][0]["type"] == "desktop"
    assert simple_of(topo, {"desktop": "pc"})["devices"][0]["type"] == "pc"
    assert simple_of(topo)["devices"][0]["type"] == "desktop"


def test_default_settings_map_desktop_to_pc():
    from vision_pipeline.config.settings import Settings

    assert Settings().device_type_aliases == {"desktop": "pc"}


def test_ids_are_consistent_between_devices_and_links():
    _, topo = h.run(*_test_d_inputs())
    s = simple_of(topo)
    ids = {d["id"] for d in s["devices"]}
    assert all(
        lk["source"] in ids and (lk["target"] is None or lk["target"] in ids) for lk in s["links"]
    )


def test_validation_rejects_bad_minimal_documents():
    good = {
        "devices": [{"id": "device_1", "type": "pc", "name": None, "network": dict(NULL4)}],
        "links": [],
    }
    validate_simple(good)
    for bad in (
        {**good, "extra": 1},
        {"devices": [{**good["devices"][0], "confidence": 0.5}], "links": []},
        {
            "devices": [
                {
                    **good["devices"][0],
                    "network": {**NULL4, "subnet_mask": "255.255.0.0", "prefix_length": 24},
                }
            ],
            "links": [],
        },
        {
            "devices": good["devices"],
            "links": [
                {"id": "link_1", "source": "device_9", "target": None, "network": dict(NULL_LINK)}
            ],
        },
        {
            "devices": good["devices"],
            "links": [
                {
                    "id": "link_1",
                    "source": "device_1",
                    "target": None,
                    "network": {**NULL_LINK, "target_ip": "10.0.0.1"},
                }
            ],
        },
        {
            "devices": good["devices"],
            "links": [
                {
                    "id": "link_1",
                    "source": "device_1",
                    "target": None,
                    "network": {**NULL_LINK, "source_ip": "10.0.0.300"},
                }
            ],
        },
    ):
        with pytest.raises(TopologyValidationError):
            validate_simple(bad)
