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
    assert check_readiness(architecture) == {"ready": True, "status": "ready", "errors": []}
    assert architecture == original


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        "input",
        1,
        {},
        {"components": None, "edges": None},
        {"components": [None], "edges": [None]},
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
        "prefix",
        "bad_ip",
        "unknown_endpoint",
        "unknown_interface",
        "missing_edge_id",
        "reused_port",
        "isolated",
    ],
)
def test_required_fields_and_connectivity_block_translation(architecture, issue):
    if issue == "missing_id":
        del architecture["components"][0]["id"]
        code = "missing_component_id"
    elif issue == "empty_name":
        architecture["components"][0]["name"] = " "
        code = "missing_component_name"
    elif issue == "missing_type":
        del architecture["components"][0]["type"]
        code = "missing_component_type"
    elif issue == "duplicate_id":
        architecture["components"][1]["id"] = "PC1"
        code = "duplicate_component_id"
    elif issue == "missing_ip":
        del architecture["components"][2]["interfaces"][0]["ipv4"]
        code = "missing_ip_address"
    elif issue == "prefix":
        architecture["components"][0]["interfaces"][0]["ipv4"] = "10.10.10.10"
        code = "missing_ip_prefix"
    elif issue == "bad_ip":
        architecture["components"][0]["interfaces"][0]["ipv4"] = "999.10.10.10/24"
        code = "invalid_ip_address"
    elif issue == "unknown_endpoint":
        architecture["edges"][0]["source"]["component"] = "ghost"
        code = "unknown_component"
    elif issue == "unknown_interface":
        architecture["edges"][0]["source"]["interface"] = "ghost"
        code = "unknown_interface"
    elif issue == "missing_edge_id":
        del architecture["edges"][0]["id"]
        code = "missing_edge_id"
    elif issue == "reused_port":
        extra = deepcopy(architecture["edges"][0])
        extra["id"] = "extra-cable"
        architecture["edges"].append(extra)
        code = "interface_reused"
    else:
        architecture["components"].append(
            {"id": "Alone", "type": "pc", "interfaces": [{"id": "eth0", "ipv4": "10.9.0.2/24"}]}
        )
        code = "isolated_component"
    before = deepcopy(architecture)
    report = check_readiness(architecture)
    assert not report["ready"]
    assert code in {e["code"] for e in report["errors"]}
    assert all("path" in e and e["message"] for e in report["errors"])
    assert architecture == before


def test_all_issues_are_reported_together(architecture):
    del architecture["components"][0]["interfaces"][0]["ipv4"]
    architecture["components"][2]["name"] = ""
    architecture["components"].append(
        {"id": "Alone", "type": "router", "interfaces": [{"id": "eth0"}]}
    )
    report = check_readiness(architecture)
    codes = {e["code"] for e in report["errors"]}
    assert {"missing_ip_address", "missing_component_name", "isolated_component"} <= codes


def test_switches_need_no_ip_and_intentional_routing_failures_remain_allowed(architecture):
    for component in architecture["components"]:
        if component["type"] == "router":
            component["routing"]["protocols"] = []
            component["routing"]["static_routes"] = []
    architecture["edges"][2]["enabled"] = False
    assert check_readiness(architecture)["ready"]


def test_same_lan_hosts_need_no_gateway():
    architecture = {
        "components": [
            {"id": "PC1", "type": "pc", "interfaces": [{"id": "eth0", "ipv4": "10.0.0.1/24"}]},
            {"id": "PC2", "type": "pc", "interfaces": [{"id": "eth0", "ipv4": "10.0.0.2/24"}]},
            {"id": "SW", "type": "switch", "interfaces": [{"id": "p1"}, {"id": "p2"}]},
        ],
        "edges": [
            {
                "id": "e1",
                "source": {"component": "PC1", "interface": "eth0"},
                "target": {"component": "SW", "interface": "p1"},
            },
            {
                "id": "e2",
                "source": {"component": "PC2", "interface": "eth0"},
                "target": {"component": "SW", "interface": "p2"},
            },
        ],
    }
    assert check_readiness(architecture)["ready"]


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
    architecture["components"][0]["interfaces"][0].pop("ipv4")
    path.write_text(json.dumps(architecture))
    assert app.main(["check", "--input", str(path)]) == 2
    assert json.loads(capsys.readouterr().out)["ready"] is False


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("cloud", {"provider": "azure"}, "unsupported_cloud_provider"),
        ("cloud", {"provider": "gcp"}, "unsupported_cloud_provider"),
        ("generation", {"profile": "aws_single_host_docker_v1"}, "unsupported_generation_settings"),
        ("ansible", {"tasks": []}, "legacy_automation_field"),
    ],
)
def test_out_of_scope_inputs_are_rejected_before_retrieval(
    field, value, code, architecture, monkeypatch
):
    architecture[field] = value
    monkeypatch.setattr(app, "KnowledgeRetriever", lambda: pytest.fail("Unexpected retrieval"))
    with pytest.raises(ArchitectureNotReady) as error:
        app.plan_architecture(architecture)
    assert code in {item["code"] for item in error.value.report["errors"]}
