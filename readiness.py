"""Deterministic architecture completeness checks before retrieval or translation.

Readiness is about named, connected and addressed input. It does not predict
reachability, repair configuration or decide which generator supports a feature.
"""

from __future__ import annotations

import ipaddress
from typing import Any

from contracts import JSONObject


class ArchitectureNotReady(ValueError):
    """Translation is blocked; report contains all detected input issues."""

    def __init__(self, report: JSONObject) -> None:
        self.report = report
        super().__init__(f"Architecture is not ready: {len(report['errors'])} issue(s).")


def check_readiness(architecture: Any) -> JSONObject:
    """Return a machine-readable report without changing the supplied JSON."""
    errors: list[dict[str, str]] = []

    def error(code: str, path: str, message: str) -> None:
        errors.append({"code": code, "path": path, "message": message})

    def result() -> JSONObject:
        return {"ready": not errors, "status": "not_ready" if errors else "ready", "errors": errors}

    def named(value: Any) -> bool:
        return isinstance(value, str) and bool(value.strip())

    if not isinstance(architecture, dict):
        error("invalid_architecture", "", "The architecture must be a JSON object.")
        return result()
    components = architecture.get("components")
    if not isinstance(components, list) or not components:
        error("missing_components", "/components", "Provide a nonempty list of components.")
        components = []
    component_paths: dict[str, str] = {}
    interfaces: dict[str, set[str]] = {}
    for index, component in enumerate(components):
        path = f"/components/{index}"
        if not isinstance(component, dict):
            error("invalid_component", path, "Each component must be an object.")
            continue
        identifier = component.get("id")
        valid_id = named(identifier)
        if not valid_id:
            error(
                "missing_component_id",
                path + "/id",
                "Give this component a nonempty unique ID/name, such as PC1 or R1.",
            )
        elif identifier in component_paths:
            error(
                "duplicate_component_id",
                path + "/id",
                f"Component ID {identifier!r} is already used.",
            )
            valid_id = False
        else:
            component_paths[identifier] = path
        if "name" in component and not named(component["name"]):
            error(
                "missing_component_name",
                path + "/name",
                "An explicitly supplied display name must not be empty.",
            )
        role = component.get("type")
        if not named(role):
            error(
                "missing_component_type",
                path + "/type",
                "Specify the component type, such as pc, router, server or switch.",
            )
        layer2 = isinstance(role, str) and role.lower() in {"switch", "bridge", "hub"}
        ports = component.get("interfaces")
        if not isinstance(ports, list) or not ports:
            error(
                "missing_interfaces",
                path + "/interfaces",
                "Provide the component's interfaces and their IDs.",
            )
            ports = []
        port_ids: set[str] = set()
        for port_index, port in enumerate(ports):
            port_path = f"{path}/interfaces/{port_index}"
            if not isinstance(port, dict):
                error("invalid_interface", port_path, "Each interface must be an object.")
                continue
            port_id = port.get("id")
            if not named(port_id):
                error(
                    "missing_interface_id", port_path + "/id", "Give this interface a nonempty ID."
                )
            elif port_id in port_ids:
                error(
                    "duplicate_interface_id",
                    port_path + "/id",
                    f"Interface {port_id!r} is repeated on this component.",
                )
            else:
                port_ids.add(port_id)
            if "enabled" in port and type(port["enabled"]) is not bool:
                error(
                    "invalid_enabled_state",
                    port_path + "/enabled",
                    "enabled must be true or false.",
                )
            address = port.get("ipv4")
            if address is None and layer2:
                continue
            if not named(address):
                error(
                    "missing_ip_address",
                    port_path + "/ipv4",
                    "Provide an IPv4 address with its prefix, for example 10.0.0.10/24.",
                )
            elif "/" not in address:
                error(
                    "missing_ip_prefix",
                    port_path + "/ipv4",
                    "Include the subnet prefix with the IPv4 address, for example /24.",
                )
            else:
                try:
                    ipaddress.IPv4Interface(address)
                except ValueError:
                    error(
                        "invalid_ip_address",
                        port_path + "/ipv4",
                        "The IPv4 address or subnet prefix is invalid.",
                    )
        if valid_id:
            interfaces[identifier] = port_ids

    edges = architecture.get("edges")
    if not isinstance(edges, list) or not edges:
        error("missing_edges", "/edges", "Provide links connecting the components.")
        edges = []
    connected: set[str] = set()
    edge_ids: set[str] = set()
    used_ports: set[tuple[str, str]] = set()
    for index, edge in enumerate(edges):
        path = f"/edges/{index}"
        if not isinstance(edge, dict):
            error("invalid_edge", path, "Each link must be an object.")
            continue
        before = len(errors)
        identifier = edge.get("id")
        if not named(identifier):
            error("missing_edge_id", path + "/id", "Give this link a nonempty ID.")
        elif identifier in edge_ids:
            error("duplicate_edge_id", path + "/id", f"Link ID {identifier!r} is already used.")
        else:
            edge_ids.add(identifier)
        if "enabled" in edge and type(edge["enabled"]) is not bool:
            error("invalid_enabled_state", path + "/enabled", "enabled must be true or false.")
        ends: list[tuple[str, str]] = []
        for side in ("source", "target"):
            endpoint = edge.get(side)
            endpoint_path = path + "/" + side
            if not isinstance(endpoint, dict):
                error(
                    "missing_link_endpoint",
                    endpoint_path,
                    "Specify the endpoint component and interface IDs.",
                )
                continue
            node_id = endpoint.get("component")
            port_id = endpoint.get("interface")
            if not named(node_id) or node_id not in interfaces:
                error(
                    "unknown_component",
                    endpoint_path + "/component",
                    "This link must reference an existing component ID.",
                )
                continue
            if not named(port_id) or port_id not in interfaces[node_id]:
                error(
                    "unknown_interface",
                    endpoint_path + "/interface",
                    f"Reference an existing interface on {node_id!r}.",
                )
                continue
            key = (node_id, port_id)
            if key in used_ports or key in ends:
                error(
                    "interface_reused",
                    endpoint_path,
                    "An interface can have only one cable; add a switch or another interface.",
                )
            ends.append(key)
        if len(ends) == 2 and ends[0][0] == ends[1][0]:
            error("self_link", path, "Connect this component to another component, not itself.")
        if len(errors) == before:
            used_ports.update(ends)
            connected.update(node_id for node_id, _ in ends)
    for identifier, path in component_paths.items():
        if identifier not in connected:
            error(
                "isolated_component",
                path,
                f"Component {identifier!r} has no valid link to another component.",
            )
    return result()


def require_ready(architecture: Any) -> None:
    report = check_readiness(architecture)
    if not report["ready"]:
        raise ArchitectureNotReady(report)
