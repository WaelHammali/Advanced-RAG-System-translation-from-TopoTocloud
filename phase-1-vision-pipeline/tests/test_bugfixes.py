"""Regression tests for reported bugs, added one at a time as each is fixed.

1. A directly-read address was hidden from `network` (and therefore from topology.simple.json)
   whenever a stray, unresolved host suffix also happened to be near the same device.
"""

from __future__ import annotations

import helpers as h
from helpers import device

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
