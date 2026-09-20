"""The issue list is (component, other component or "", message) and changes nothing."""

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
    del architecture["components"][0]["interfaces"][0]["ipv4"]
    architecture["components"].append({"id": "Alone", "type": "pc", "interfaces": [{"id": "e"}]})
    issues = list_issues(architecture)
    assert issues and all(len(i) == 3 and all(isinstance(x, str) for x in i) for i in issues)


def test_missing_address_mask_and_invalid_address(architecture):
    ports = {c["id"]: c["interfaces"] for c in architecture["components"]}
    del ports["PC1"][0]["ipv4"]
    ports["R1"][0]["ipv4"] = "10.10.10.1"
    ports["R2"][0]["ipv4"] = "999.1.1.1/24"
    assert list_issues(architecture) == [
        ("PC1", "", "no IP address"),
        ("R1", "", "IP address has no mask"),
        ("R2", "", "invalid IP address"),
    ]


def test_a_component_with_no_link_is_reported_alone(architecture):
    architecture["components"].append(
        {"id": "Alone", "type": "pc", "interfaces": [{"id": "eth0", "ipv4": "10.9.0.2/24"}]}
    )
    assert list_issues(architecture) == [("Alone", "", "not linked to any other component")]


def test_a_shared_name_names_both_sides(architecture):
    architecture["components"][1]["id"] = "PC1"
    assert ("PC1", "PC1", "same name as another component") in list_issues(architecture)


def test_the_same_address_in_one_group_names_both_components(architecture):
    architecture["components"][0]["interfaces"][0]["ipv4"] = "10.20.20.30/24"  # WEB1's address
    assert list_issues(architecture) == [("WEB1", "PC1", "same IP address as PC1")]
    assert check_readiness(architecture)["ready"]  # reported, but never blocks translation


def test_the_same_address_on_two_interfaces_of_one_component(architecture):
    router = architecture["components"][2]
    router["interfaces"][1]["ipv4"] = router["interfaces"][0]["ipv4"]
    assert list_issues(architecture) == [("R1", "R1", "same IP address as R1")]


def test_separate_groups_and_disabled_interfaces_may_reuse_addresses():
    def pair(a, b, address):
        cable = {
            "id": f"{a}-{b}",
            "source": {"component": a, "interface": "eth0"},
            "target": {"component": b, "interface": "eth0"},
        }
        hosts = [
            {"id": n, "type": "pc", "interfaces": [{"id": "eth0", "ipv4": f"{address}{i}/24"}]}
            for i, n in enumerate((a, b), 1)
        ]
        return hosts, cable

    (a, b), first = pair("A", "B", "10.0.0.")
    (c, d), second = pair("C", "D", "10.0.0.")
    separate = {"components": [a, b, c, d], "edges": [first, second]}
    assert list_issues(separate) == []
    joined = deepcopy(separate)
    joined["edges"].append(
        {
            "id": "bridge",
            "source": {"component": "B", "interface": "eth1"},
            "target": {"component": "C", "interface": "eth1"},
        }
    )
    joined["components"][1]["interfaces"].append({"id": "eth1", "ipv4": "10.1.0.1/24"})
    joined["components"][2]["interfaces"].append({"id": "eth1", "ipv4": "10.1.0.2/24"})
    assert ("C", "A", "same IP address as A") in list_issues(joined)
    joined["components"][2]["interfaces"][0]["enabled"] = False
    assert ("C", "A", "same IP address as A") not in list_issues(joined)


def test_nameless_components_are_named_by_position_and_links_by_id(architecture):
    del architecture["components"][0]["id"]
    architecture["edges"][2]["source"]["component"] = "ghost"
    issues = list_issues(architecture)
    assert ("components[0]", "", "has no name") in issues
    assert ("link-3", "", "link source points to unknown component 'ghost'") in issues


def test_problems_that_belong_to_no_component_have_an_empty_name():
    assert list_issues({"components": [], "edges": []})[0] == (
        "",
        "",
        "Provide a nonempty list of components.",
    )
    assert list_issues(None) == [("", "", "The architecture must be a JSON object.")]


def test_the_architecture_is_never_changed(architecture):
    del architecture["components"][0]["interfaces"][0]["ipv4"]
    before = deepcopy(architecture)
    list_issues(architecture)
    assert architecture == before


def test_problems_outside_components_keep_their_location(architecture):
    architecture["automation"] = {
        "tasks": [{"id": "t1", "targets": ["ghost"], "operation": "package.install"}]
    }
    located = [i for i in list_issues(architecture) if i[0] == "" and "/automation" in i[2]]
    assert located and all(i[1] == "" for i in located)


@pytest.mark.parametrize("mask", ["-1", "-24", "33", "64", "abc", "", "24.5"])
def test_a_negative_too_large_or_non_numeric_mask_is_an_invalid_mask(architecture, mask):
    architecture["components"][0]["interfaces"][0]["ipv4"] = f"10.10.10.10/{mask}"
    assert ("PC1", "", "invalid mask") in list_issues(architecture)


@pytest.mark.parametrize("mask", ["0", "8", "24", "30", "31", "32"])
def test_masks_from_zero_to_thirty_two_are_accepted(architecture, mask):
    architecture["components"][0]["interfaces"][0]["ipv4"] = f"10.10.10.10/{mask}"
    assert not [i for i in list_issues(architecture) if i[0] == "PC1"]


def test_a_bad_address_is_reported_as_the_address_not_the_mask(architecture):
    architecture["components"][0]["interfaces"][0]["ipv4"] = "10.10.10.999/33"
    assert ("PC1", "", "invalid IP address") in list_issues(architecture)
