"""Reject altered topology, bad references and configuration added before user input."""

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from net2cloud.app import plan_architecture
from net2cloud.plan_contract import PlanContractError, required_cloud_plan, validate_cloud_plan
from net2cloud.retriever import KnowledgeRetriever

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def architecture():
    return json.loads((ROOT / "examples/edge_cases/router_chain_no_routes.json").read_text())


@pytest.mark.parametrize(
    "mutation",
    [
        "empty",
        "missing_device",
        "extra_device",
        "changed_ip",
        "missing_link",
        "rewired_link",
        "unknown_resource",
        "wrong_target",
        "static_route",
        "ospf",
        "gateway",
        "public_ip",
        "expensive_instance",
        "shared_runtime",
        "bridge_stp",
        "wrong_type",
        "extra_field",
    ],
)
def test_model_cannot_change_required_network_or_cost_policy(architecture, mutation):
    plan = required_cloud_plan(architecture)
    if mutation == "empty":
        plan = {"provider": "aws"}
    elif mutation == "missing_device":
        plan["device_mapping"].pop()
    elif mutation == "extra_device":
        plan["device_mapping"].append(deepcopy(plan["device_mapping"][0]))
    elif mutation == "changed_ip":
        plan["device_mapping"][0]["network"]["ip_address"] = "10.100.0.99"
    elif mutation == "missing_link":
        plan["networking"]["links"].pop()
    elif mutation == "rewired_link":
        plan["networking"]["links"][0]["target"]["device_id"] = architecture["devices"][-1]["id"]
    elif mutation == "unknown_resource":
        plan["device_mapping"][0]["resource_ref"] = "missing"
    elif mutation == "wrong_target":
        plan["configuration_targets"][0]["runtime_ref"] = plan["configuration_targets"][1][
            "runtime_ref"
        ]
    elif mutation in {"static_route", "ospf", "gateway"}:
        key = {
            "static_route": "static_routes",
            "ospf": "routing_protocols",
            "gateway": "default_gateways",
        }[mutation]
        plan["initial_configuration"][key].append({"invented": True})
    elif mutation == "public_ip":
        plan["resources"][-1]["public_ipv4"] = True
    elif mutation == "expensive_instance":
        plan["resources"][-1]["instance_type"] = "m7i.8xlarge"
    elif mutation == "shared_runtime":
        plan["device_mapping"][0]["runtime"] = plan["device_mapping"][1]["runtime"]
    elif mutation == "bridge_stp":
        plan["initial_configuration"]["bridge_stp"] = True
    elif mutation == "wrong_type":
        plan["hosting"]["instance_count"] = True
    elif mutation == "extra_field":
        plan["networking"]["aws_bypass"] = True
    with pytest.raises(PlanContractError):
        validate_cloud_plan(plan, architecture)


def test_runtime_identifiers_survive_source_order_and_display_name_changes(architecture):
    first = required_cloud_plan(architecture)
    architecture["devices"].reverse()
    for device in architecture["devices"]:
        device["name"] = "same label"
    second = required_cloud_plan(architecture)
    assert {m["device_id"]: m["runtime"]["id"] for m in first["device_mapping"]} == {
        m["device_id"]: m["runtime"]["id"] for m in second["device_mapping"]
    }


def test_per_link_router_addresses_and_host_32_prefixes_are_preserved(architecture):
    plan = required_cloud_plan(architecture)
    for source, link in zip(architecture["links"], plan["networking"]["links"]):
        assert source["network"] == link["network"]
        for side in ("source", "target"):
            assert source["network"][side + "_ip"] == link[side]["ip_address"]
    source = json.loads((ROOT / "examples/edge_cases/two_pcs_32.json").read_text())
    link = required_cloud_plan(source)["networking"]["links"][0]
    assert link["source"]["prefix_length"] == link["target"]["prefix_length"] == 32


def test_invalid_output_never_replaces_previous_file(tmp_path, monkeypatch, capsys):
    from net2cloud import app

    class Client:
        chat = None

        def __init__(self):
            self.chat = SimpleNamespace(completions=self)

        def create(self, **kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(
                            content=json.dumps(
                                {
                                    "cloud_plan": {"provider": "aws"},
                                    "rule_ids": ["CORE-001"],
                                    "limitations": [],
                                }
                            )
                        ),
                    )
                ]
            )

    monkeypatch.setattr(
        app,
        "plan_with_rag",
        lambda a, k, **kw: __import__(
            "net2cloud.planner", fromlist=["plan_with_rag"]
        ).plan_with_rag(a, k, client=Client()),
    )
    monkeypatch.setattr(
        app,
        "KnowledgeRetriever",
        lambda **kw: KnowledgeRetriever(index_dir=tmp_path / "cache", **kw),
    )
    output = tmp_path / "result.json"
    output.write_text("previous")
    assert (
        app.main(
            [
                "plan",
                "--input",
                str(ROOT / "examples/architecture.json"),
                "--retrieval",
                "lexical",
                "--output",
                str(output),
            ]
        )
        == 1
    )
    assert output.read_text() == "previous"
    assert "Missing or unexpected" in capsys.readouterr().err


def test_switch_cycle_and_extensions_cannot_be_silently_declared_ready(tmp_path):
    source = json.loads((ROOT / "examples/edge_cases/switch_loop.json").read_text())
    source["custom"] = {"unrecognized": True}

    class Client:
        def __init__(self):
            self.chat = SimpleNamespace(completions=self)

        def create(self, **request):
            supplied = json.loads(request["messages"][1]["content"])
            response = {
                "cloud_plan": supplied["required_cloud_plan"],
                "rule_ids": ["CORE-001"],
                "limitations": [],
            }
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="stop", message=SimpleNamespace(content=json.dumps(response))
                    )
                ]
            )

    output = plan_architecture(
        source, client=Client(), retriever=KnowledgeRetriever(backend="lexical", index_dir=tmp_path)
    )
    assert any("loop control" in item for item in output["limitations"])
    assert any("/custom" in item for item in output["limitations"])
    assert output["cloud_plan"]["verification_status"] == "not_run"
