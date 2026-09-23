"""Educational worker selection is explicit, bounded and independent of an LLM."""

import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest

from net2cloud.hosting import UnsupportedTopology, select_hosting

ROOT = Path(__file__).resolve().parents[1]


def example(path):
    return json.loads((ROOT / "examples" / path).read_text())


def test_small_direct_lab_uses_one_micro_with_bounded_cost():
    source = example("edge_cases/two_pcs_direct.json")
    before = deepcopy(source)
    plan = select_hosting(source)
    assert plan["instance_count"] == 1 and plan["instance_type"] == "t3a.micro"
    assert plan["reserved_memory_mib"] <= plan["memory_mib"]
    assert Decimal(plan["cost"]["hourly_compute_estimate"]) <= Decimal(
        plan["cost"]["hourly_compute_cap"]
    )
    assert plan["cost"]["recheck_before_deployment"]
    assert plan["cpu_credits"] == "standard" and not plan["public_ipv4"]
    assert source == before


def test_mixed_lab_gets_larger_worker_without_one_instance_per_device():
    plan = select_hosting(example("architecture.json"))
    assert plan["instance_type"] == "t3a.small" and plan["instance_count"] == 1


@pytest.mark.parametrize("role", ["hub", "firewall", "vendor-special"])
def test_unknown_or_inexact_runtime_is_rejected_instead_of_replaced(role):
    source = example("architecture.json")
    source["devices"][1]["type"] = role
    if role != "hub":
        source["devices"][1]["network"] = deepcopy(source["devices"][0]["network"])
        for link in source["links"]:
            link["network"]["target_ip"] = "192.168.1.10"
    with pytest.raises(UnsupportedTopology, match="Unsupported runtime"):
        select_hosting(source)
