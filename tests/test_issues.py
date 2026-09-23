"""Clarification findings identify exact fields and separate warnings from blockers."""

import json
from copy import deepcopy
from pathlib import Path

from net2cloud.issues import list_issues
from net2cloud.readiness import check_readiness

ROOT = Path(__file__).resolve().parents[1]


def architecture():
    return json.loads((ROOT / "examples/architecture.json").read_text())


def test_stable_ids_and_paths_disambiguate_equal_display_names():
    source = architecture()
    source["devices"][0]["name"] = source["devices"][4]["name"] = "PC"
    for index in (0, 4):
        source["devices"][index]["network"]["ip_address"] = None
    before = deepcopy(source)
    report = check_readiness(source)
    assert not report["ready"]
    assert list_issues(source) == report["issues"]
    assert {(i[0], i[1]) for i in report["issues"]} == {
        ("device_1", "/devices/0/network/ip_address"),
        ("device_5", "/devices/4/network/ip_address"),
    }
    assert source == before


def test_duplicate_ip_is_an_explicit_advisory_not_an_invisible_blocker():
    source = architecture()
    source["devices"][4]["network"]["ip_address"] = "192.168.1.10"
    source["links"][3]["network"]["source_ip"] = "192.168.1.10"
    report = check_readiness(source)
    assert report["ready"] and report["issues"] == []
    assert report["warnings"][0]["code"] == "duplicate_lan_ip"
    assert report["warning_issues"][0][:2] == ("link_4", "/links/3/network/source_ip")
    assert "device_1" in report["warning_issues"][0][2]


def test_address_reuse_across_router_boundaries_is_not_a_same_lan_conflict():
    source = json.loads((ROOT / "examples/edge_cases/router_chain_no_routes.json").read_text())
    # Reuse the left LAN's addressing on the right LAN, separated by routers.
    left = source["links"][0]["network"]
    right = source["links"][2]["network"]
    right.update(
        network_address=left["network_address"],
        prefix_length=left["prefix_length"],
        subnet_mask=left["subnet_mask"],
        source_ip=left["target_ip"],
        target_ip=left["source_ip"],
    )
    source["devices"][3]["network"] = deepcopy(source["devices"][0]["network"])
    router = source["devices"][2]
    if router["network"]["ip_address"].startswith("10.0.2."):
        router["network"] = {**source["devices"][0]["network"], "ip_address": left["target_ip"]}
    report = check_readiness(source)
    assert report["ready"], report
    assert report["warnings"] == []


def test_duplicate_id_is_located_without_claiming_two_identical_display_names():
    source = architecture()
    source["devices"][1]["id"] = "device_1"
    issue = next(i for i in list_issues(source) if i[1] == "/devices/1/id")
    assert issue[:2] == ("device_1", "/devices/1/id")


def test_invalid_input_and_cycles_are_reported_without_recursing():
    assert list_issues(None)[0][:2] == ("", "")
    source = architecture()
    source["cycle"] = source
    report = check_readiness(source)
    assert report["revision"] is None and not report["ready"]
    assert report["issues"][0][1] == "/cycle"
