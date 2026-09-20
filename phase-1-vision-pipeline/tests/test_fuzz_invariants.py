"""Seeded random inputs: the pipeline must never crash and never invent information."""

import random
import re

import helpers as h
import pytest
from vision_pipeline.ocr.address_normalizer import ip_to_int, network_of

NAMES = ["R1", "R2", "SW1", "PC1", "PC2", "FW1"]
POOL = NAMES + [
    "192.168.1.1",
    "192.168.1.1/24",
    "10.0.0.1/30",
    "255.255.255.0",
    "192.168.1.0/24",
    "10.0.0.0/30",
    "172.16.0.0/16",
    ".1",
    ".2",
    ".10",
    ".254",
    "Lab 3",
    "Figure",
    "192.168.1",
    "300.1.1.1",
    "R",
]


def scenario(seed: int):
    rnd = random.Random(seed)
    devs = []
    for _ in range(rnd.randint(0, 5)):
        x, y = rnd.randint(20, 650), rnd.randint(20, 300)
        devs.append(
            (
                rnd.choice(["router", "switch", "pc", "server"]),
                (x, y, x + rnd.randint(40, 90), y + rnd.randint(40, 90)),
            )
        )
    texts = []
    for _ in range(rnd.randint(0, 14)):
        x, y = rnd.randint(0, 700), rnd.randint(0, 370)
        texts.append((rnd.choice(POOL), (x, y, x + rnd.randint(10, 110), y + rnd.randint(10, 20))))
    links = []
    for i in range(rnd.randint(0, 4)):
        pts = [
            (float(rnd.randint(0, 780)), float(rnd.randint(0, 380)))
            for _ in range(rnd.randint(2, 3))
        ]
        c = h.link(
            pts,
            conf=rnd.random(),
            cid=f"link_candidate_{i + 1:03d}",
            path_type=rnd.choice(["chain", "chain", "single", "branched"]),
        )
        if rnd.random() < 0.2:
            c.end = None
        if c.path_type == "branched":
            c.start = c.end = None
        links.append(c)
    return devs, texts, links


@pytest.mark.parametrize("seed", range(300))
def test_never_crashes_and_never_invents(seed):
    devs, texts, links = scenario(seed)
    ocr_texts = h.ocr(texts)
    _, topo = h.run(h.yolo(devs), ocr_texts, h.opencv(links))  # also runs validate_topology
    read = {t.text.strip() for t in ocr_texts.texts}
    read_blob = " ".join(t.text for t in ocr_texts.texts)
    link_nets = {
        (lk["network"]["network_address"], lk["network"]["prefix_length"]) for lk in topo["links"]
    }
    link_nets.discard((None, None))
    label_nets = {
        (m.group(1), int(m.group(2))) for m in re.finditer(r"(\d+\.\d+\.\d+\.\d+)/(\d+)", read_blob)
    }

    for d in topo["devices"]:
        assert d["name"] is None or d["name"] in read  # names are only ever read
        for a in [d["network"], *d["addresses"]]:
            if a["ip_address"] is not None:
                direct = a["ip_address"] in read_blob
                derived = (
                    a["host_suffix"] is not None
                    and a["prefix_length"] is not None
                    and (network_of(a["ip_address"], a["prefix_length"]), a["prefix_length"])
                    in label_nets
                )
                assert direct or derived, (seed, a)
            if a["prefix_length"] is not None:
                assert a["subnet_mask"] is not None or a["ip_address"] is None
            if a["ip_address"] is None:
                assert a["network_address"] is None  # no network without an address
        for a in d["addresses"]:
            if a["source"] == "host_suffix_resolution":  # needs suffix + link network
                assert (
                    a["host_suffix"] is not None
                    and a["link_id"] is not None
                    and a["prefix_length"] is not None
                )
            if a["source"] == "host_suffix_only":  # a bare suffix carries nothing else
                assert (
                    a["ip_address"]
                    is a["prefix_length"]
                    is a["subnet_mask"]
                    is a["network_address"]
                    is None
                )
            if a["source"] == "ocr_direct":
                assert a["host_suffix"] is None and a["link_id"] is None
    for lk in topo["links"]:
        n = lk["network"]
        assert (n["network_address"], n["prefix_length"]) == (None, None) or (
            n["network_address"],
            n["prefix_length"],
        ) in label_nets
        assert lk["source"] is not None and lk["source"] != lk["target"]
    for d in topo["devices"]:
        for a in d["addresses"]:
            if a["ip_address"] is not None:
                assert ip_to_int(a["ip_address"]) is not None


# ---------------------------------------------------------------- structured "correct or null"


def jitter_d(seed: int, amount: int):
    """Test-D diagram with every position jittered and random distractor texts added."""
    rnd = random.Random(seed)
    j = lambda v: v + rnd.uniform(-amount, amount)  # noqa: E731

    def box(x1, y1, x2, y2):
        return (j(x1), j(y1), j(x2), j(y2))

    devs = [("router", box(100, 150, 180, 230)), ("pc", box(500, 150, 580, 230))]
    texts = [
        ("R1", box(110, 236, 134, 252)),
        ("PC1", box(525, 236, 555, 252)),
        (".1", box(185, 165, 199, 180)),
        (".2", box(481, 165, 495, 180)),
        ("192.168.1.0/24", box(280, 200, 400, 216)),
    ]
    for _ in range(rnd.randint(0, 5)):  # distractors anywhere
        x, y = rnd.randint(0, 700), rnd.randint(0, 370)
        texts.append((rnd.choice(POOL), (x, y, x + rnd.randint(10, 100), y + rnd.randint(10, 20))))
    cable = h.link([(j(180.0), j(190.0)), (j(500.0), j(190.0))], conf=rnd.uniform(0.6, 1.0))
    return devs, texts, [cable]


def test_jittered_diagram_is_correct_or_null_never_wrong():
    resolved = 0
    for seed in range(200):
        devs, texts, links = jitter_d(seed, amount=6)
        _, topo = h.run(h.yolo(devs), h.ocr(texts), h.opencv(links))
        r1, pc1 = topo["devices"]
        n1, n2 = r1["network"], pc1["network"]
        for n, ip in ((n1, "192.168.1.1"), (n2, "192.168.1.2")):
            if (
                n["host_suffix"] in (".1", ".2")
                and n["ip_address"] is not None
                and n["prefix_length"] == 24
            ):
                assert (
                    n["ip_address"].startswith("192.168.1.")
                    and n["network_address"] == "192.168.1.0"
                )
                assert n["subnet_mask"] == "255.255.255.0"
        if n1["ip_address"] == "192.168.1.1" and n2["ip_address"] == "192.168.1.2":
            resolved += 1
        for lk in topo["links"]:
            assert lk["network"]["network_address"] in (
                None,
                "192.168.1.0",
                "10.0.0.0",
                "172.16.0.0",
            )
            if lk["network"]["network_address"] == "192.168.1.0":
                assert (
                    lk["network"]["prefix_length"] == 24
                    and lk["network"]["subnet_mask"] == "255.255.255.0"
                )
    assert resolved >= 100, (
        f"only {resolved}/200 jittered diagrams resolved: the fuzz is not exercising resolution"
    )


def test_larger_jitter_degrades_to_null_not_to_wrong_values():
    wrong = 0
    for seed in range(200):
        devs, texts, links = jitter_d(seed, amount=30)
        texts = [
            t for t in texts if t[0] in ("R1", "PC1", ".1", ".2", "192.168.1.0/24")
        ]  # no distractors
        _, topo = h.run(h.yolo(devs), h.ocr(texts), h.opencv(links))
        r1, pc1 = topo["devices"]
        for dev, expect in ((r1, "192.168.1.1"), (pc1, "192.168.1.2")):
            ip = dev["network"]["ip_address"]
            if ip is not None and ip != expect:
                wrong += 1
        # suffixes must never be attached to the wrong device
        for dev, suffix in ((r1, ".1"), (pc1, ".2")):
            assert dev["network"]["host_suffix"] in (None, suffix)
    assert wrong == 0
