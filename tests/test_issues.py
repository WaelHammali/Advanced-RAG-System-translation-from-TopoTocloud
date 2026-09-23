"""The issue list is (device, other device or "", message) and changes nothing."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from net2cloud.issues import list_issues
from net2cloud.readiness import check_readiness

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def architecture():
    return json.loads((ROOT / "examples/architecture.json").read_text())


def test_a_complete_architecture_has_no_issues(architecture):
    assert list_issues(architecture) == []


def test_every_issue_is_a_triple_of_strings(architecture):
    architecture["devices"][0]["network"]["ip_address"] = None
    architecture["devices"].append({"id": "Alone", "type": "pc", "name": "Alone"})
    issues = list_issues(architecture)
    assert issues and all(len(i) == 3 and all(isinstance(x, str) for x in i) for i in issues)


def test_missing_address_and_invalid_address(architecture):
    architecture["devices"][0]["network"]["ip_address"] = None
    architecture["devices"][2]["network"]["ip_address"] = "999.1.1.1"
    issues = list_issues(architecture)
    assert ("PC1", "", "no IP address") in issues
    assert ("R1", "", "invalid IP address") in issues


def test_a_device_with_no_link_is_reported_alone():
    architecture = {
        "devices": [
            {
                "id": "d1",
                "type": "pc",
                "name": "Alone",
                "network": {
                    "ip_address": "10.9.0.2",
                    "prefix_length": 24,
                    "subnet_mask": "255.255.255.0",
                    "network_address": "10.9.0.0",
                },
            }
        ],
        "links": [],
    }
    assert list_issues(architecture) == [
        ("", "", "Provide links connecting the devices."),
        ("Alone", "", "not linked to any other device"),
    ]


def test_a_shared_id_names_both_sides(architecture):
    architecture["devices"][1]["id"] = architecture["devices"][0]["id"]
    issues = list_issues(architecture)
    assert ("SW1", "SW1", "same ID as another device") in issues


def test_the_same_address_in_one_group_names_both_devices(architecture):
    # PC1 (device_1, listed first) takes SRV1's (device_4, listed later) address;
    # the later device in list order is the one named as having the clash.
    architecture["devices"][0]["network"]["ip_address"] = "192.168.1.20"
    architecture["links"][0]["network"]["source_ip"] = "192.168.1.20"
    issues = list_issues(architecture)
    assert ("SRV1", "PC1", "same IP address as PC1") in issues
    assert check_readiness(architecture)["ready"]  # reported, but never blocks translation


def test_separate_groups_may_reuse_addresses():
    def pair(a, b, prefix):
        devices = [
            {
                "id": n,
                "type": "pc",
                "name": n,
                "network": {
                    "ip_address": f"{prefix}{i}",
                    "prefix_length": 24,
                    "subnet_mask": "255.255.255.0",
                    "network_address": f"{prefix}0",
                },
            }
            for i, n in enumerate((a, b), 1)
        ]
        link = {
            "id": f"{a}-{b}",
            "source": a,
            "target": b,
            "network": {
                "network_address": f"{prefix}0",
                "prefix_length": 24,
                "subnet_mask": "255.255.255.0",
                "source_ip": f"{prefix}1",
                "target_ip": f"{prefix}2",
            },
        }
        return devices, link

    (a, b), first = pair("A", "B", "10.0.0.")
    (c, d), second = pair("C", "D", "10.0.0.")
    separate = {"devices": [a, b, c, d], "links": [first, second]}
    assert list_issues(separate) == []


def test_nameless_device_falls_back_to_id_and_unknown_link_names_the_link(architecture):
    del architecture["devices"][0]["name"]
    architecture["devices"][0]["network"]["ip_address"] = None
    architecture["links"][1]["source"] = "ghost"
    issues = list_issues(architecture)
    assert ("device_1", "", "no IP address") in issues  # name absent, falls back to id
    assert ("link_2", "", "link source points to unknown device 'ghost'") in issues


def test_problems_that_belong_to_no_device_have_an_empty_name():
    assert list_issues({"devices": [], "links": []})[0] == (
        "",
        "",
        "Provide a nonempty list of devices.",
    )
    assert list_issues(None) == [("", "", "The architecture must be a JSON object.")]


def test_the_architecture_is_never_changed(architecture):
    architecture["devices"][0]["network"]["ip_address"] = None
    before = deepcopy(architecture)
    list_issues(architecture)
    assert architecture == before


def test_a_link_ip_outside_the_network_names_the_device_and_link(architecture):
    architecture["links"][1]["network"].update(
        network_address="172.16.0.0", prefix_length=30, subnet_mask="255.255.255.252"
    )
    issues = list_issues(architecture)
    assert ("R1", "", "IP address on link link_2 is outside the link's network") in issues


def test_a_missing_link_ip_names_the_device_and_link(architecture):
    architecture["links"][1]["network"]["source_ip"] = None
    assert ("R1", "", "no IP address on link link_2") in list_issues(architecture)


def test_a_link_ip_reused_by_another_device_in_the_group_is_reported():
    architecture = json.loads(
        (ROOT / "examples/edge_cases/router_chain_no_routes.json").read_text()
    )
    # PC2 claims R2's LAN-side address on link_3.
    architecture["devices"][3]["network"]["ip_address"] = "10.0.2.1"
    architecture["links"][2]["network"]["target_ip"] = "10.0.2.1"
    assert ("PC2", "R2", "same IP address as R2") in list_issues(architecture)


@pytest.mark.parametrize(
    "prefix,message",
    [(-1, "invalid mask"), (33, "invalid mask"), ("abc", "invalid mask"), (None, "IP address has no mask")],
)
def test_an_invalid_prefix_length_is_reported(architecture, prefix, message):
    architecture["devices"][0]["network"]["prefix_length"] = prefix
    assert ("PC1", "", message) in list_issues(architecture)


@pytest.mark.parametrize("prefix", [0, 8, 24, 30, 31, 32])
def test_prefixes_from_zero_to_thirty_two_are_accepted(architecture, prefix):
    import ipaddress

    network = ipaddress.IPv4Network(f"192.168.1.10/{prefix}", strict=False)
    architecture["devices"][0]["network"] = {
        "ip_address": "192.168.1.10",
        "prefix_length": prefix,
        "subnet_mask": str(network.netmask),
        "network_address": str(network.network_address),
    }
    # This device's only link (link_1) must still agree with the new network.
    architecture["links"][0]["network"] = {
        "network_address": str(network.network_address),
        "prefix_length": prefix,
        "subnet_mask": str(network.netmask),
        "source_ip": "192.168.1.10",
        "target_ip": None,  # SW1's end
    }
    assert not [i for i in list_issues(architecture) if i[0] == "PC1"]
