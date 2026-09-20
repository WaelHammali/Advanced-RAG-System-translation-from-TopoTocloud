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
    assert s["links"][0]["network"] == {
        "network_address": None,
        "prefix_length": None,
        "subnet_mask": None,
    }


def test_half_link_keeps_null_target():
    _, topo = h.run(
        h.yolo([("router", (100, 150, 180, 230)), ("pc", (500, 150, 580, 230))]),
        h.ocr([]),
        h.opencv([h.link([(180.0, 190.0), (400.0, 190.0)])]),
    )
    (lk,) = simple_of(topo)["links"]
    assert (lk["source"], lk["target"]) == ("device_1", None)


def test_multi_homed_device_is_all_null_and_full_detail_stays_in_topology_json():
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
    assert len(h.device(topo, "device_001")["addresses"]) == 2  # rich file keeps both
    assert simple_of(topo)["devices"][0]["network"] == NULL4  # minimal form never picks one


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
                {
                    "id": "link_1",
                    "source": "device_9",
                    "target": None,
                    "network": {
                        "network_address": None,
                        "prefix_length": None,
                        "subnet_mask": None,
                    },
                }
            ],
        },
    ):
        with pytest.raises(TopologyValidationError):
            validate_simple(bad)
