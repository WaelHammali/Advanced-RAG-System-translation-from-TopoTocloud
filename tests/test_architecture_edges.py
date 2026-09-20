"""Boundary matrix: completeness, intentional failures, and input preservation."""

import json
import math
from copy import deepcopy
from pathlib import Path

import pytest

from net2cloud import app
from net2cloud.readiness import check_readiness

ROOT = Path(__file__).resolve().parents[1]


def example(name):
    return json.loads((ROOT / "examples/edge_cases" / (name + ".json")).read_text())


@pytest.mark.parametrize(
    "case,ready",
    [
        ("single_pc", False),
        ("two_pcs_direct", True),
        ("two_pcs_different_subnets", True),
        ("two_pcs_31", True),
        ("two_pcs_32", True),
        ("separate_pairs", True),
        ("switch_loop", True),
    ],
)
def test_topology_matrix(case, ready):
    architecture = example(case)
    before = deepcopy(architecture)
    assert check_readiness(architecture)["ready"] is ready
    assert architecture == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("/routing", None),
        ("/routing", []),
        ("/routing/ipv4_forwarding", "true"),
        ("/routing/default_gateway", None),
        ("/routing/default_gateway/via", 123),
        ("/routing/default_gateway/interface", "ghost"),
        ("/routing/static_routes", {}),
        ("/routing/static_routes", [None]),
        ("/routing/protocols", "ospf"),
        ("/routing/protocols", [True]),
        ("/routing/protocols/0/name", []),
        ("/routing/protocols/0/enabled", 1),
        ("/routing/protocols/0/router_id", "invalid"),
        ("/routing/protocols/0/interfaces", None),
        ("/routing/protocols/0/interfaces/0/id", "ghost"),
        ("/routing/protocols/0/interfaces/0/area", None),
        ("/routing/protocols/0/interfaces/0/cost", True),
        ("/routing/protocols/0/interfaces/0/passive", "false"),
        ("/services", {}),
        ("/services", [None]),
        ("/services/0/protocol", ""),
        ("/services/0/enabled", "false"),
        ("/services/0/listen", None),
        ("/services/0/listen/port", True),
        ("/services/0/listen/port", 65536),
        ("/services/0/listen/address", "bad"),
        ("/interfaces/0/access_vlan", 4095),
        ("/interfaces/0/access_vlan", True),
        ("/os", []),
    ],
)
def test_nested_configuration_errors_block_model_before_retrieval(field, value, monkeypatch):
    architecture = example("two_pcs_direct")
    node = architecture["components"][0]
    node["routing"] = {
        "default_gateway": {"interface": "eth0", "via": "10.0.0.254"},
        "protocols": [
            {
                "name": "ospf",
                "router_id": "1.1.1.1",
                "interfaces": [{"id": "eth0", "area": "0.0.0.0"}],
            }
        ],
    }
    node["services"] = [{"protocol": "http", "listen": {"address": "0.0.0.0", "port": 80}}]
    parts = field.strip("/").split("/")
    target = node
    for part in parts[:-1]:
        target = target[int(part)] if isinstance(target, list) else target[part]
    target[parts[-1]] = value
    before = deepcopy(architecture)
    report = check_readiness(architecture)
    assert not report["ready"]
    assert any(e["path"].startswith("/components/0" + field) for e in report["errors"])
    assert architecture == before
    monkeypatch.setattr(app, "KnowledgeRetriever", lambda: pytest.fail("Unexpected retrieval"))
    with pytest.raises(ValueError):
        app.plan_architecture(architecture)


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        "tasks",
        {"tasks": [None]},
        {"connections": [{"target_ids": ["ghost"]}]},
        {"tasks": [{"id": "a", "target_ids": [[], "PC1"]}]},
    ],
)
def test_malformed_automation_produces_structured_errors(value):
    architecture = example("two_pcs_direct")
    architecture["automation"] = value
    assert not check_readiness(architecture)["ready"]


def test_automation_dependencies_allow_forward_references_but_reject_cycles():
    architecture = example("two_pcs_direct")
    architecture["automation"] = {
        "tasks": [
            {"id": "a", "target_ids": ["PC1"], "operation": "custom.module", "depends_on": ["b"]},
            {"id": "b", "target_ids": ["PC2"], "operation": "custom.module", "depends_on": []},
        ]
    }
    assert check_readiness(architecture)["ready"]
    architecture["automation"]["tasks"][1]["depends_on"] = ["a"]
    assert "cyclic_task_dependencies" in {
        e["code"] for e in check_readiness(architecture)["errors"]
    }
    architecture["automation"]["tasks"][1]["depends_on"] = ["missing"]
    assert "unknown_reference" in {e["code"] for e in check_readiness(architecture)["errors"]}


@pytest.mark.parametrize(
    "destination,ready",
    [
        ("0.0.0.0/0", True),
        ("10.9.0.0/24", True),
        ("10.9.0.1/32", True),
        ("10.9.0.1/24", False),
        ("10.9.0.0", False),
        (None, False),
    ],
)
def test_static_destinations_are_explicit_and_not_silently_normalized(destination, ready):
    architecture = example("two_pcs_direct")
    architecture["components"][0]["routing"] = {
        "static_routes": [{"destination": destination, "interface": "eth0"}]
    }
    assert check_readiness(architecture)["ready"] is ready


def test_disabled_settings_and_known_failure_exercises_are_preserved():
    architecture = example("two_pcs_direct")
    architecture["components"][1]["interfaces"][0]["ipv4"] = "10.0.0.1/24"  # duplicate-IP lab
    architecture["edges"][0]["enabled"] = False
    architecture["components"][0]["routing"] = {
        "ipv4_forwarding": False,
        "static_routes": [],
        "default_gateway": {"via": "192.0.2.1", "interface": "eth0"},
    }  # unreachable gateway
    assert check_readiness(architecture)["ready"]


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


def test_explicit_null_switch_address_is_not_equivalent_to_omission():
    architecture = example("switch_loop")
    architecture["components"][0]["interfaces"][0]["ipv4"] = None
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
        ("empty", "missing_components"),
        ("duplicate_node", "duplicate_component_id"),
        ("duplicate_port", "duplicate_interface_id"),
        ("duplicate_edge", "duplicate_edge_id"),
        ("self_link", "self_link"),
        ("reused_port", "interface_reused"),
        ("unknown_node", "unknown_component"),
        ("unknown_port", "unknown_interface"),
        ("numeric_ip", "missing_ip_address"),
        ("ipv6", "invalid_ip_address"),
        ("no_prefix", "missing_ip_prefix"),
        ("mask_33", "invalid_ip_address"),
        ("null_edges", "missing_edges"),
        ("string_enabled", "invalid_enabled_state"),
    ],
)
def test_graph_and_address_boundary_errors(mutation, code):
    architecture = example("two_pcs_direct")
    node = architecture["components"][0]
    edge = architecture["edges"][0]
    if mutation == "empty":
        architecture["components"] = []
    elif mutation == "duplicate_node":
        architecture["components"][1]["id"] = "PC1"
    elif mutation == "duplicate_port":
        node["interfaces"].append(deepcopy(node["interfaces"][0]))
    elif mutation in ("duplicate_edge", "reused_port"):
        architecture["edges"].append(deepcopy(edge))
        if mutation == "reused_port":
            architecture["edges"][1]["id"] = "another"
    elif mutation == "self_link":
        edge["target"] = deepcopy(edge["source"])
    elif mutation == "unknown_node":
        edge["target"]["component"] = "ghost"
    elif mutation == "unknown_port":
        edge["target"]["interface"] = "ghost"
    elif mutation == "null_edges":
        architecture["edges"] = None
    elif mutation == "string_enabled":
        edge["enabled"] = "false"
    else:
        node["interfaces"][0]["ipv4"] = {
            "numeric_ip": 123,
            "ipv6": "2001:db8::1/64",
            "no_prefix": "10.0.0.1",
            "mask_33": "10.0.0.1/33",
        }[mutation]
    assert code in {e["code"] for e in check_readiness(architecture)["errors"]}


def test_large_task_chain_and_topology_do_not_require_recursive_graph_walks():
    architecture = example("two_pcs_direct")
    architecture["automation"] = {
        "tasks": [
            {
                "id": f"t{i}",
                "target_ids": ["PC1"],
                "operation": "custom.task",
                "depends_on": [f"t{i + 1}"] if i < 1199 else [],
            }
            for i in range(1200)
        ]
    }
    assert check_readiness(architecture)["ready"]
    architecture["automation"]["tasks"][-1]["depends_on"] = ["t0"]
    assert "cyclic_task_dependencies" in {
        e["code"] for e in check_readiness(architecture)["errors"]
    }


def test_ip_only_validity_does_not_imply_network_reachability():
    architecture = example("two_pcs_direct")
    architecture["components"][0]["interfaces"][0]["ipv4"] = "10.0.0.0/24"
    assert check_readiness(architecture)["ready"]  # semantic diagnostics remain separate


def test_nesting_limit_is_reported_for_json_compatible_input():
    architecture = example("two_pcs_direct")
    child = architecture
    for _ in range(66):
        child["extension"] = {}
        child = child["extension"]
    assert check_readiness(architecture)["errors"][0]["code"] == "json_nesting_limit"
