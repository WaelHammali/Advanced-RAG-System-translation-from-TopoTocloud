"""Regression tests for four reported bugs, plus the device-name-uniqueness feature.

1. A directly-read address was hidden from `network` (and therefore from topology.simple.json)
   whenever a stray, unresolved host suffix also happened to be near the same device.
2. A pipeline run that failed partway left the *previous* run's output files in place, looking
   like a valid, current result.
3. An unmasked or very busy image could make collinear segment merging exhaust memory (covered
   in test_opencv_detector.py, since it needs the real OpenCV stage).
4. Two overlapping YOLO detections of one physical device (e.g. once as "router", once as
   "switch") left every nearby text association "ambiguous", so the device ended up with no
   name and no address at all.
5. (feature) two different devices that end up with the same name are disambiguated instead of
   being left indistinguishable in the output.
"""

from __future__ import annotations

import json

import helpers as h
import pytest
from helpers import device
from vision_pipeline.config.thresholds import Thresholds
from vision_pipeline.fusion.coordinate_normalizer import normalize_coordinates
from vision_pipeline.geometry import Rect
from vision_pipeline.schemas.raw import YoloDetection
from vision_pipeline.topology.topology_builder import (
    TopologyBuilder,
    TopologyValidationError,
    validate_topology,
)

NULL_NET = {
    "ip_address": None,
    "prefix_length": None,
    "subnet_mask": None,
    "network_address": None,
    "host_suffix": None,
}


# ============================================================== bug 1: address hidden by a
# ============================================================== stray unresolved suffix


def test_direct_address_is_not_hidden_by_a_nearby_unresolvable_suffix():
    # R1 has a real, directly-read CIDR address, AND an unrelated bare suffix sits close enough
    # to also associate with R1 - but with no link at all, it can never resolve to anything.
    dev = [("router", (100, 100, 180, 180))]
    texts = [
        ("R1", (128, 186, 152, 202)),
        ("192.168.1.1/24", (95, 206, 185, 222)),
        (".9", (160, 96, 174, 111)),
    ]
    _, topo = h.run(h.yolo(dev), h.ocr(texts), h.opencv())
    d = device(topo, "device_001")
    assert d["name"] == "R1"
    assert d["network"] == {
        "ip_address": "192.168.1.1",
        "prefix_length": 24,
        "subnet_mask": "255.255.255.0",
        "network_address": "192.168.1.0",
        "host_suffix": None,
    }
    # the stray suffix is not lost either - it is simply not allowed to blank out the real address
    assert len(d["addresses"]) == 2
    sources = {a["source"] for a in d["addresses"]}
    assert sources == {"ocr_direct", "host_suffix_only"}
    stray = next(a for a in d["addresses"] if a["source"] == "host_suffix_only")
    assert stray["host_suffix"] == ".9" and stray["ip_address"] is None


def test_a_bare_suffix_alone_still_appears_in_the_mirror():
    # unchanged behaviour (Test E from the spec): with NO other address information at all, the
    # device's only fact (an unresolved suffix) must still surface in the scalar `network` block.
    dev = [("pc", (100, 100, 180, 180))]
    _, topo = h.run(h.yolo(dev), h.ocr([(".2", (105, 186, 175, 200))]), h.opencv())
    assert device(topo, "device_001")["network"] == {**NULL_NET, "host_suffix": ".2"}


def test_two_substantive_addresses_still_null_the_mirror():
    # unchanged behaviour: a genuinely multi-homed device (two real addresses) must not have one
    # arbitrarily picked for the scalar block.
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
    d = device(topo, "device_001")
    assert len(d["addresses"]) == 2
    assert d["network"] == NULL_NET


# ================================================================== bug 4: duplicate YOLO
# ================================================================== detections of one device


def test_coordinate_normalizer_drops_the_lower_confidence_duplicate():
    y = h.yolo([("router", (100, 100, 180, 180))], conf=0.97)
    # a near-duplicate box for the SAME icon, misclassified and lower confidence
    y.detections.append(YoloDetection("device_002", "switch", 0.55, Rect(103, 103, 183, 183)))
    inp = normalize_coordinates(y, h.ocr([]), h.opencv(), Thresholds())
    assert [d.id for d in inp.devices] == ["device_001"]
    w = next(w for w in inp.warnings if w["code"] == "duplicate_device_detection_dropped")
    assert w["id"] == "device_002" and w["kept_id"] == "device_001"
    assert w["iou"] >= Thresholds().duplicate_detection_iou


def test_coordinate_normalizer_keeps_two_genuinely_separate_devices():
    y = h.yolo([("router", (100, 100, 180, 180)), ("pc", (500, 100, 580, 180))])
    inp = normalize_coordinates(y, h.ocr([]), h.opencv(), Thresholds())
    assert [d.id for d in inp.devices] == ["device_001", "device_002"]
    assert not any(w["code"] == "duplicate_device_detection_dropped" for w in inp.warnings)


def test_duplicate_detection_end_to_end_device_keeps_its_name_and_address():
    y = h.yolo([("router", (100, 100, 180, 180))], conf=0.97)
    y.detections.append(YoloDetection("device_002", "switch", 0.5, Rect(101, 101, 181, 181)))
    texts = [("R1", (128, 186, 152, 202)), ("192.168.1.1/24", (100, 206, 180, 222))]
    _, topo = h.run(y, h.ocr(texts), h.opencv())
    assert len(topo["devices"]) == 1  # the duplicate never reaches the topology
    d = topo["devices"][0]
    assert d["type"] == "router"  # the higher-confidence detection wins
    assert d["name"] == "R1"
    assert d["network"]["ip_address"] == "192.168.1.1"


def test_duplicate_detection_also_fixes_the_originally_reported_symptom():
    # the exact scenario found during review: two overlapping boxes of DIFFERENT classes left
    # BOTH devices completely blank ("ambiguous") before the fix.
    y = h.yolo([("router", (100, 150, 180, 230))], conf=0.95)
    y.detections.append(YoloDetection("device_002", "switch", 0.94, Rect(102, 152, 182, 232)))
    y.detections.append(YoloDetection("device_003", "pc", 0.95, Rect(500, 150, 580, 230)))
    texts = [("R1", (110, 236, 134, 252)), ("192.168.1.1/24", (95, 256, 185, 272))]
    _, topo = h.run(y, h.ocr(texts), h.opencv())
    assert len(topo["devices"]) == 2
    named = [d for d in topo["devices"] if d["name"] is not None]
    assert len(named) == 1
    assert named[0]["name"] == "R1" and named[0]["network"]["ip_address"] == "192.168.1.1"


# =========================================================== feature: unique device names


def test_two_different_devices_named_the_same_are_disambiguated():
    devs = [("router", (100, 100, 180, 180)), ("router", (500, 100, 580, 180))]
    texts = [("R1", (128, 186, 152, 202)), ("R1", (528, 186, 552, 202))]
    _, topo = h.run(h.yolo(devs), h.ocr(texts), h.opencv())
    names = sorted(d["name"] for d in topo["devices"])
    assert names == ["R1", "R1 (2)"]

    winner = next(d for d in topo["devices"] if d["name"] == "R1")
    loser = next(d for d in topo["devices"] if d["name"] == "R1 (2)")
    assert "name_deduplicated" not in winner["flags"]
    assert "name_deduplicated" in loser["flags"]
    assert loser["provenance"]["name"]["deduplicated_from"] == "R1"
    assert loser["provenance"]["name"]["collided_with_device_id"] == winner["id"]

    # the RAG-facing minimal file inherits the same, already-unique names
    simple = TopologyBuilder().build_simple(topo)
    assert sorted(d["name"] for d in simple["devices"]) == ["R1", "R1 (2)"]


def test_three_way_name_collision_gets_numbered_suffixes():
    devs = [
        ("router", (100, 100, 180, 180)),
        ("router", (400, 100, 480, 180)),
        ("router", (700, 100, 780, 180)),
    ]
    texts = [
        ("R1", (128, 186, 152, 202)),
        ("R1", (428, 186, 452, 202)),
        ("R1", (728, 186, 752, 202)),
    ]
    _, topo = h.run(h.yolo(devs), h.ocr(texts), h.opencv())
    assert sorted(d["name"] for d in topo["devices"]) == ["R1", "R1 (2)", "R1 (3)"]


def test_devices_with_different_names_are_never_touched():
    devs = [("router", (100, 100, 180, 180)), ("router", (500, 100, 580, 180))]
    texts = [("R1", (128, 186, 152, 202)), ("R2", (528, 186, 552, 202))]
    _, topo = h.run(h.yolo(devs), h.ocr(texts), h.opencv())
    assert sorted(d["name"] for d in topo["devices"]) == ["R1", "R2"]
    assert all("name_deduplicated" not in d["flags"] for d in topo["devices"])


def test_validate_topology_rejects_a_duplicate_name():
    _, topo = h.run(
        h.yolo([("router", (100, 100, 180, 180))]),
        h.ocr([("R1", (128, 186, 152, 202))]),
        h.opencv(),
    )
    bad = json.loads(json.dumps(topo))
    bad["devices"].append({**bad["devices"][0], "id": "device_999"})  # same name, different id
    with pytest.raises(TopologyValidationError, match="duplicate device name"):
        validate_topology(bad)
