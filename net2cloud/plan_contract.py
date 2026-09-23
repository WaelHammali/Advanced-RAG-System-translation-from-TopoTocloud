"""Versioned topology plan and deterministic preservation checks for generators."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

from .hosting import select_hosting
from .json_io import dumps_json
from .readiness import check_readiness

BASE_LIMITATIONS = (
    "Runtime implementation and packet behavior have not been verified.",
    "Routing protocols, gateways and services require the later user configuration stage.",
    "Worker capacity is provisional; catalog prices and availability need rechecking before deployment.",
    "Management access, Linux image and package delivery must be resolved before configuration.",
)


class PlanContractError(ValueError):
    """A proposed plan violates the topology or educational hosting contract."""


def runtime_id(kind: str, source_id: str) -> str:
    """Stable safe runtime names; source labels never become shell identifiers."""
    return kind + hashlib.sha256(source_id.encode()).hexdigest()[:12]


def required_cloud_plan(architecture: dict) -> dict:
    """Explicit requirements supplied to the model and independently checked afterward."""
    hosting = select_hosting(architecture)
    worker = "lab_worker"
    mappings = []
    for device in architecture["devices"]:
        role = device["type"].lower()
        mappings.append(
            {
                "device_id": device["id"],
                "name": device["name"],
                "type": device["type"],
                "network": deepcopy(device["network"]),
                "resource_ref": worker,
                "runtime": {
                    "kind": "linux_bridge" if role in {"switch", "bridge"} else "network_namespace",
                    "id": runtime_id("n", device["id"]),
                    "filesystem_isolation": role not in {"switch", "bridge"},
                },
            }
        )
    by_id = {m["device_id"]: m for m in mappings}
    links = []
    for link in architecture["links"]:
        endpoints = {}
        for side, suffix in (("source", "a"), ("target", "b")):
            device = by_id[link[side]]
            # The device's primary prefix wins for its primary address (/32 labs
            # remain /32). Other router addresses use that link's declared prefix.
            ip = link["network"].get(side + "_ip")
            network = device["network"]
            prefix = (
                network.get("prefix_length")
                if ip is not None and ip == network.get("ip_address")
                else link["network"]["prefix_length"]
            )
            endpoints[side] = {
                "device_id": link[side],
                "runtime_ref": device["runtime"]["id"],
                "interface_id": runtime_id("v" + suffix, link["id"]),
                "ip_address": ip,
                "prefix_length": prefix if ip is not None else None,
            }
        links.append(
            {
                "link_id": link["id"],
                "implementation": "veth",
                "resource_ref": worker,
                "network": deepcopy(link["network"]),
                **endpoints,
            }
        )
    return {
        "contract_version": "1.0",
        "provider": "aws",
        "translation_mode": "behavioral_lab",
        "hosting": hosting,
        "resources": [
            {"id": "lab_vpc", "type": "aws_vpc", "cidr_ref": "deployment.transport_vpc_cidr"},
            {
                "id": "lab_subnet",
                "type": "aws_subnet",
                "vpc_ref": "lab_vpc",
                "cidr_ref": "deployment.transport_subnet_cidr",
                "public_ipv4": False,
            },
            {
                "id": "worker_security",
                "type": "aws_security_group",
                "vpc_ref": "lab_vpc",
                "ingress": [],
                "egress": [],
            },
            {
                "id": worker,
                "type": "aws_instance",
                "instance_type": hosting["instance_type"],
                "subnet_ref": "lab_subnet",
                "security_group_refs": ["worker_security"],
                "image_ref": "deployment.linux_ami_x86_64",
                "public_ipv4": False,
                "cpu_credits": hosting["cpu_credits"],
                "root_volume": hosting["root_volume"],
            },
        ],
        "device_mapping": mappings,
        "networking": {
            "links": links,
            "isolation": {
                "worker_forwards_lab_traffic": False,
                "management_enters_lab": False,
                "automatic_masquerade": False,
                "automatic_proxy_arp": False,
            },
        },
        "configuration_targets": [
            {
                "device_id": m["device_id"],
                "resource_ref": worker,
                "runtime_ref": m["runtime"]["id"],
                "management_ref": "deployment.worker_management",
                "interface_refs": [
                    end["interface_id"]
                    for link in links
                    for end in (link["source"], link["target"])
                    if end["device_id"] == m["device_id"]
                ],
            }
            for m in mappings
        ],
        "initial_configuration": {
            "static_routes": [],
            "default_gateways": [],
            "routing_protocols": [],
            "services": [],
            "connected_routes": "from_exact_endpoint_addresses",
            "router_ipv4_forwarding": True,
            "host_ipv4_forwarding": False,
            "bridge_stp": False,
            "configuration_stage": "deferred_to_external_agent",
        },
        "dependencies": [
            "Resolve transport CIDRs, an eligible Linux AMI and worker management access.",
            "Implement isolated node runtimes and exact veth links before applying later configuration.",
            "Validate sizing, storage and total deployment cost before provisioning.",
        ],
        "verification_status": "not_run",
    }


def required_limitations(architecture: dict) -> list[str]:
    limitations = list(BASE_LIMITATIONS)
    limitations.extend(w["message"] for w in check_readiness(architecture)["warnings"])
    # A cycle consisting only of switches/bridges has no declared loop-control
    # settings in this topology-only input. Keep the exact links and flag it.
    bridges = {
        d["id"] for d in architecture["devices"] if d["type"].lower() in {"switch", "bridge"}
    }
    parent = {d: d for d in bridges}

    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for link in architecture["links"]:
        a, b = link["source"], link["target"]
        if a in bridges and b in bridges:
            a, b = find(a), find(b)
            if a == b:
                limitations.append(
                    "Switch cycle has no configured loop control; safe forwarding is not established."
                )
                break
            parent[a] = b
    scopes = [("", architecture, {"devices", "links"})]
    for group, keys in (
        ("devices", {"id", "name", "type", "network"}),
        ("links", {"id", "source", "target", "network"}),
    ):
        for index, item in enumerate(architecture[group]):
            scopes.append((f"/{group}/{index}", item, keys))
            fields = {"network_address", "prefix_length", "subnet_mask"}
            fields |= {"ip_address"} if group == "devices" else {"source_ip", "target_ip"}
            scopes.append((f"/{group}/{index}/network", item["network"], fields))
    for path, item, known in scopes:
        for field in sorted(item.keys() - known):
            escaped = field.replace("~", "~0").replace("/", "~1")
            limitations.append(
                f"Uninterpreted source extension {path}/{escaped}; retained in architecture, not implemented."
            )
    return limitations


def validate_cloud_plan(plan: Any, architecture: dict, *, expected: dict | None = None) -> None:
    """Reject omissions, additions, type changes and altered source/runtime mappings.

    The current profile has exactly one supported realization. It intentionally
    does not accept loosely equivalent graphs or arbitrary deployment settings.
    """
    expected = required_cloud_plan(architecture) if expected is None else expected

    def compare(actual, required, path):
        if type(actual) is not type(required):
            raise PlanContractError(f"Invalid plan type at {path}.")
        if isinstance(required, dict):
            if actual.keys() != required.keys():
                raise PlanContractError(f"Missing or unexpected plan fields at {path}.")
            for key in required:
                compare(actual[key], required[key], path + "/" + key)
        elif isinstance(required, list):
            if len(actual) != len(required):
                raise PlanContractError(f"Missing or extra plan entries at {path}.")
            for index, (value, wanted) in enumerate(zip(actual, required)):
                compare(value, wanted, f"{path}/{index}")
        elif actual != required:
            raise PlanContractError(f"Plan changes a required value at {path}.")

    compare(plan, expected, "/cloud_plan")
    # Explicit uniqueness guards cover the extremely unlikely hash-name collision.
    runtime_ids = [m["runtime"]["id"] for m in plan["device_mapping"]]
    interfaces = [
        link[side]["interface_id"]
        for link in plan["networking"]["links"]
        for side in ("source", "target")
    ]
    if len(set(runtime_ids)) != len(runtime_ids) or len(set(interfaces)) != len(interfaces):
        raise PlanContractError("Runtime identifiers collide; cannot publish an ambiguous plan.")
    dumps_json(plan)  # also rejects non-finite numbers at direct Python boundaries
