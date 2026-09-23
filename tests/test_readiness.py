"""Readiness must stop incomplete input before either retrieval or translation."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from net2cloud import app
from net2cloud.planner import plan_with_rag
from net2cloud.readiness import ArchitectureNotReady, check_readiness

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def architecture():
    return json.loads((ROOT / "examples/architecture.json").read_text())


@pytest.mark.parametrize("filename", ["architecture.json", "edge_cases/two_pcs_direct.json"])
def test_complete_examples_are_ready_and_unchanged(filename):
    architecture = json.loads((ROOT / "examples" / filename).read_text())
    original = deepcopy(architecture)
    report = check_readiness(architecture)
    assert report["ready"] and report["errors"] == report["issues"] == []
    assert architecture == original


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        "input",
        1,
        {},
        {"devices": None, "links": None},
        {"devices": [None], "links": [None]},
    ],
)
def test_malformed_shapes_return_issues_instead_of_crashing(value):
    report = check_readiness(value)
    assert not report["ready"] and report["errors"]


@pytest.mark.parametrize(
    "issue",
    [
        "missing_id",
        "empty_name",
        "missing_type",
        "duplicate_id",
        "missing_ip",
        "invalid_prefix",
        "bad_ip",
        "unknown_endpoint",
        "missing_link_id",
        "isolated",
    ],
)
def test_required_fields_and_connectivity_block_translation(architecture, issue):
    if issue == "missing_id":
        del architecture["devices"][0]["id"]
        code = "missing_device_id"
    elif issue == "empty_name":
        architecture["devices"][0]["name"] = " "
        code = "missing_device_name"
    elif issue == "missing_type":
        del architecture["devices"][0]["type"]
        code = "missing_device_type"
    elif issue == "duplicate_id":
        architecture["devices"][1]["id"] = architecture["devices"][0]["id"]
        code = "duplicate_device_id"
    elif issue == "missing_ip":
        architecture["devices"][2]["network"]["ip_address"] = None
        code = "missing_ip_address"
    elif issue == "invalid_prefix":
        architecture["devices"][0]["network"]["prefix_length"] = 40
        code = "invalid_prefix_length"
    elif issue == "bad_ip":
        architecture["devices"][0]["network"]["ip_address"] = "999.10.10.10"
        code = "invalid_ip_address"
    elif issue == "unknown_endpoint":
        architecture["links"][0]["source"] = "ghost"
        code = "unknown_device"
    elif issue == "missing_link_id":
        del architecture["links"][0]["id"]
        code = "missing_link_id"
    else:
        architecture["devices"].append(
            {
                "id": "Alone",
                "type": "pc",
                "name": "Alone",
                "network": {
                    "ip_address": "10.9.0.2",
                    "prefix_length": 24,
                    "subnet_mask": "255.255.255.0",
                    "network_address": "10.9.0.0",
                },
            }
        )
        code = "isolated_device"
    before = deepcopy(architecture)
    report = check_readiness(architecture)
    assert not report["ready"]
    assert code in {e["code"] for e in report["errors"]}
    assert all("path" in e and e["message"] for e in report["errors"])
    assert architecture == before


def test_all_issues_are_reported_together(architecture):
    architecture["devices"][0]["network"]["ip_address"] = None
    architecture["devices"][2]["name"] = ""
    architecture["devices"].append(
        {
            "id": "Alone",
            "type": "router",
            "name": "Alone",
            "network": {
                "ip_address": "10.9.0.2",
                "prefix_length": 24,
                "subnet_mask": "255.255.255.0",
                "network_address": "10.9.0.0",
            },
        }
    )
    report = check_readiness(architecture)
    codes = {e["code"] for e in report["errors"]}
    assert {"missing_ip_address", "missing_device_name", "isolated_device"} <= codes


def test_switch_needs_no_address():
    architecture = {
        "devices": [
            {
                "id": "d1",
                "type": "pc",
                "name": "PC1",
                "network": {
                    "ip_address": "10.0.0.1",
                    "prefix_length": 24,
                    "subnet_mask": "255.255.255.0",
                    "network_address": "10.0.0.0",
                },
            },
            {
                "id": "d2",
                "type": "switch",
                "name": "SW1",
                "network": {
                    "ip_address": None,
                    "prefix_length": None,
                    "subnet_mask": None,
                    "network_address": None,
                },
            },
        ],
        "links": [
            {
                "id": "l1",
                "source": "d1",
                "target": "d2",
                "network": {
                    "network_address": "10.0.0.0",
                    "prefix_length": 24,
                    "subnet_mask": "255.255.255.0",
                    "source_ip": "10.0.0.1",
                    "target_ip": None,
                },
            }
        ],
    }
    assert check_readiness(architecture)["ready"]


def test_pc_may_have_only_one_link(architecture):
    # PC1 (device_1) already has one link; give it a second.
    architecture["links"].append(
        {
            "id": "extra",
            "source": "device_1",
            "target": "device_4",
            "network": {
                "network_address": "192.168.1.0",
                "prefix_length": 24,
                "subnet_mask": "255.255.255.0",
                "source_ip": "192.168.1.10",
                "target_ip": "192.168.1.20",
            },
        }
    )
    report = check_readiness(architecture)
    assert not report["ready"]
    assert "too_many_links" in {e["code"] for e in report["errors"]}


def test_router_or_server_may_join_a_second_subnet(architecture):
    # R1 (device_3) is on 192.168.1.0/24 via link_2; a second link to the server
    # on a different subnet uses a different per-link address on each end.
    architecture["links"].append(
        {
            "id": "extra",
            "source": "device_3",
            "target": "device_4",
            "network": {
                "network_address": "10.9.9.0",
                "prefix_length": 30,
                "subnet_mask": "255.255.255.252",
                "source_ip": "10.9.9.1",
                "target_ip": "10.9.9.2",
            },
        }
    )
    assert check_readiness(architecture)["ready"]


def test_router_chain_joining_three_subnets_is_ready():
    architecture = json.loads(
        (ROOT / "examples/edge_cases/router_chain_no_routes.json").read_text()
    )
    assert check_readiness(architecture)["ready"]


def test_a_link_ip_must_be_inside_the_links_network(architecture):
    architecture["links"][1]["network"].update(
        network_address="172.16.0.0", prefix_length=30, subnet_mask="255.255.255.252"
    )
    report = check_readiness(architecture)
    assert not report["ready"]
    assert "link_ip_outside_network" in {e["code"] for e in report["errors"]}


def test_a_non_switch_end_needs_its_link_ip(architecture):
    architecture["links"][1]["network"]["source_ip"] = None  # R1's end
    report = check_readiness(architecture)
    assert not report["ready"]
    assert "missing_link_ip" in {e["code"] for e in report["errors"]}


def test_a_devices_own_ip_must_be_used_on_one_of_its_links(architecture):
    architecture["devices"][0]["network"]["ip_address"] = "192.168.1.99"
    report = check_readiness(architecture)
    assert not report["ready"]
    assert "device_ip_not_on_link" in {e["code"] for e in report["errors"]}


def test_subnet_mask_must_match_prefix_length(architecture):
    architecture["devices"][0]["network"]["subnet_mask"] = "255.255.255.128"
    report = check_readiness(architecture)
    assert not report["ready"]
    assert "subnet_mask_mismatch" in {e["code"] for e in report["errors"]}


def test_network_address_must_match_ip_and_prefix(architecture):
    architecture["devices"][0]["network"]["network_address"] = "192.168.9.0"
    report = check_readiness(architecture)
    assert not report["ready"]
    assert "network_address_mismatch" in {e["code"] for e in report["errors"]}


def test_gate_runs_before_retriever_construction_and_model_client(monkeypatch):
    monkeypatch.setattr(
        app, "KnowledgeRetriever", lambda: pytest.fail("retrieval must not be initialized")
    )
    monkeypatch.setattr(
        app, "plan_with_rag", lambda *a, **kw: pytest.fail("model must not be called")
    )
    with pytest.raises(ArchitectureNotReady) as error:
        app.plan_architecture({})
    assert error.value.report["status"] == "not_ready"
    # Direct planner calls must not bypass the gate either.
    with pytest.raises(ArchitectureNotReady):
        plan_with_rag({}, [])


def test_cli_blocked_plan_never_writes_output(tmp_path, monkeypatch, capsys):
    path, output = tmp_path / "input.json", tmp_path / "arch.json"
    path.write_text("{}")
    monkeypatch.setattr(app, "KnowledgeRetriever", lambda **kw: pytest.fail("unexpected retrieval"))
    assert app.main(["plan", "--input", str(path), "--output", str(output)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["status"] == "not_ready"
    assert not output.exists()


def test_check_command_runs_offline_and_reports_readiness(
    architecture, tmp_path, monkeypatch, capsys
):
    path, report = tmp_path / "input.json", tmp_path / "report.json"
    path.write_text(json.dumps(architecture))
    monkeypatch.setattr(app, "KnowledgeRetriever", lambda **kw: pytest.fail("unexpected retrieval"))
    assert app.main(["check", "--input", str(path), "--output", str(report)]) == 0
    captured = capsys.readouterr()
    assert not captured.err
    assert json.loads(captured.out)["ready"] is True
    architecture["devices"][0]["network"]["ip_address"] = None
    path.write_text(json.dumps(architecture))
    assert app.main(["check", "--input", str(path)]) == 2
    assert json.loads(capsys.readouterr().out)["ready"] is False
