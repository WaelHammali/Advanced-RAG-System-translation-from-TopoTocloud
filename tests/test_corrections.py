"""Corrections are explicit, transactional and bound to one topology revision."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from net2cloud.corrections import CorrectionError, apply_corrections
from net2cloud.readiness import check_readiness


@pytest.fixture
def source():
    return json.loads(
        (Path(__file__).resolve().parents[1] / "examples/architecture.json").read_text()
    )


def correct(source, changes):
    return apply_corrections(source, changes, expected_revision=check_readiness(source)["revision"])


def test_missing_ip_is_repaired_and_mirrored_without_changing_input(source):
    source["devices"][0]["network"]["ip_address"] = None
    source["links"][0]["network"]["source_ip"] = None
    before = deepcopy(source)
    result = correct(source, [("device_1", "/devices/0/network/ip_address", "192.168.1.50")])
    assert result["validation"]["ready"]
    assert result["architecture"]["links"][0]["network"]["source_ip"] == "192.168.1.50"
    assert source == before


def test_prefix_updates_derived_mask_and_network_without_changing_peer(source):
    result = correct(source, [("device_1", "/devices/0/network/prefix_length", 25)])
    network = result["architecture"]["devices"][0]["network"]
    assert network["subnet_mask"] == "255.255.255.128"
    assert network["network_address"] == "192.168.1.0"
    assert result["architecture"]["links"] == source["links"]


def test_endpoint_correction_updates_matching_main_address(source):
    result = correct(source, [("link_1", "/links/0/network/source_ip", "192.168.1.99")])
    assert result["architecture"]["devices"][0]["network"]["ip_address"] == "192.168.1.99"
    assert result["validation"]["ready"]


def test_id_rename_updates_existing_link_references(source):
    result = correct(source, [("device_1", "/devices/0/id", "west")])
    assert result["architecture"]["links"][0]["source"] == "west"
    assert result["validation"]["ready"]


def test_partial_or_invalid_correction_stays_blocked(source):
    result = correct(source, [("device_1", "/devices/0/network/ip_address", "invalid")])
    assert not result["validation"]["ready"]
    assert result["validation"]["issues"]


def test_explicit_inconsistent_mask_is_not_silently_overwritten(source):
    result = correct(
        source,
        [
            ("device_1", "/devices/0/network/prefix_length", 25),
            ("device_1", "/devices/0/network/subnet_mask", "255.255.255.0"),
        ],
    )
    assert not result["validation"]["ready"]


@pytest.mark.parametrize(
    "changes",
    [
        [("wrong", "/devices/0/name", "new")],
        [("device_1", "/devices/0/name", "one"), ("device_1", "/devices/0/name", "two")],
        [("", "/devices", []), ("device_1", "/devices/0/name", "new")],
        [("device_1", "/devices/0/routing", {})],
        [("device_1", "/devices/-1/name", "new")],
        [("device_1", "/devices/0/name", float("nan"))],
    ],
)
def test_ambiguous_or_unsupported_batch_is_rejected_atomically(source, changes):
    before = deepcopy(source)
    with pytest.raises(CorrectionError):
        correct(source, changes)
    assert source == before


def test_stale_revision_is_rejected(source):
    revision = check_readiness(source)["revision"]
    source["devices"][0]["name"] = "newer"
    with pytest.raises(CorrectionError, match="Stale"):
        apply_corrections(
            source, [("device_1", "/devices/0/name", "old")], expected_revision=revision
        )


def test_graph_replacement_requires_full_revalidation(source):
    result = correct(source, [("", "/links", [])])
    assert not result["validation"]["ready"]
    assert any(e["code"] == "isolated_device" for e in result["validation"]["errors"])


def test_simultaneous_id_swap_preserves_original_cable_ownership(source):
    result = correct(
        source,
        [("device_1", "/devices/0/id", "device_5"), ("device_5", "/devices/4/id", "device_1")],
    )
    assert result["validation"]["ready"]
    links = result["architecture"]["links"]
    assert links[0]["source"] == "device_5"
    assert links[3]["source"] == "device_1"


def test_endpoint_edit_does_not_overwrite_an_explicit_bad_mask(source):
    result = correct(
        source,
        [
            ("link_1", "/links/0/network/source_ip", "192.168.1.99"),
            ("device_1", "/devices/0/network/subnet_mask", "invalid"),
        ],
    )
    assert result["architecture"]["devices"][0]["network"]["subnet_mask"] == "invalid"
    assert not result["validation"]["ready"]
