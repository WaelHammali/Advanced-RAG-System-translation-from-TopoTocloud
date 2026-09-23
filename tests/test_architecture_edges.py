"""Boundary matrix: completeness, graph/address errors, and input preservation."""

import json
import math
from copy import deepcopy
from pathlib import Path

import pytest

from net2cloud.readiness import check_readiness

ROOT = Path(__file__).resolve().parents[1]


def example(name):
    return json.loads((ROOT / "examples/edge_cases" / (name + ".json")).read_text())


@pytest.mark.parametrize(
    "case,ready",
    [
        ("single_pc", False),
        ("two_pcs_direct", True),
        # A link has one network; PC2's address on it lies outside that network.
        ("two_pcs_different_subnets", False),
        ("two_pcs_31", True),
        ("two_pcs_32", True),
        ("separate_pairs", True),
        ("switch_loop", True),
        # PC1-R1-R2-PC2 with no routes: routers use a different address per link.
        ("router_chain_no_routes", True),
    ],
)
def test_topology_matrix(case, ready):
    architecture = example(case)
    before = deepcopy(architecture)
    assert check_readiness(architecture)["ready"] is ready
    assert architecture == before


@pytest.mark.parametrize("value", [float("inf"), math.nan, {1: "bad key"}, {"set"}, b"bytes"])
def test_python_only_values_in_extensions_are_rejected(value):
    architecture = example("two_pcs_direct")
    architecture["a/b~c"] = value
    report = check_readiness(architecture)
    assert not report["ready"]
    assert report["errors"][0]["path"] == "/a~1b~0c"


def test_cyclic_python_object_returns_an_error_and_shared_objects_are_allowed():
    architecture = example("two_pcs_direct")
    architecture["cycle"] = architecture
    assert check_readiness(architecture)["errors"][0]["code"] == "json_nesting_limit"
    del architecture["cycle"]
    shared = {"data": [1, False, None]}
    architecture.update(left=shared, right=shared)
    assert check_readiness(architecture)["ready"]


def test_explicit_null_ip_on_a_pc_is_not_equivalent_to_omission():
    architecture = example("two_pcs_direct")
    architecture["devices"][0]["network"]["ip_address"] = None
    assert "missing_ip_address" in {e["code"] for e in check_readiness(architecture)["errors"]}


def test_field_type_mutations_never_crash_the_readiness_api():
    baseline = json.loads((ROOT / "examples/architecture.json").read_text())
    paths = []

    def walk(value, path):
        if path:
            paths.append(path)
        children = (
            value.items()
            if isinstance(value, dict)
            else enumerate(value)
            if isinstance(value, list)
            else []
        )
        for key, child in children:
            walk(child, [*path, key])

    walk(baseline, [])
    for path in paths:
        for value in (None, True, 0, 1.5, "", [], {}, [{}], {"x": []}):
            architecture = deepcopy(baseline)
            target = architecture
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            report = check_readiness(architecture)
            assert type(report["ready"]) is bool, (path, value)
            assert report["ready"] == (report["errors"] == [])
            json.dumps(report, allow_nan=False)


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("empty", "missing_devices"),
        ("duplicate_node", "duplicate_device_id"),
        ("duplicate_link", "duplicate_link_id"),
        ("self_link", "self_link"),
        ("unknown_node", "unknown_device"),
        ("numeric_ip", "invalid_ip_address"),
        ("ipv6", "invalid_ip_address"),
        ("missing_prefix", "missing_prefix_length"),
        ("prefix_33", "invalid_prefix_length"),
        ("null_links", "missing_links"),
    ],
)
def test_graph_and_address_boundary_errors(mutation, code):
    architecture = example("two_pcs_direct")
    node = architecture["devices"][0]
    link = architecture["links"][0]
    if mutation == "empty":
        architecture["devices"] = []
    elif mutation == "duplicate_node":
        architecture["devices"][1]["id"] = architecture["devices"][0]["id"]
    elif mutation == "duplicate_link":
        architecture["links"].append(deepcopy(link))
        architecture["links"][1]["id"] = link["id"]
    elif mutation == "self_link":
        link["target"] = link["source"]
    elif mutation == "unknown_node":
        link["target"] = "ghost"
    elif mutation == "null_links":
        architecture["links"] = None
    elif mutation == "missing_prefix":
        node["network"]["prefix_length"] = None
    elif mutation == "prefix_33":
        node["network"]["prefix_length"] = 33
    else:
        node["network"]["ip_address"] = {"numeric_ip": 123, "ipv6": "2001:db8::1"}[mutation]
    assert code in {e["code"] for e in check_readiness(architecture)["errors"]}


def test_nesting_limit_is_reported_for_json_compatible_input():
    architecture = example("two_pcs_direct")
    child = architecture
    for _ in range(66):
        child["extension"] = {}
        child = child["extension"]
    assert check_readiness(architecture)["errors"][0]["code"] == "json_nesting_limit"
