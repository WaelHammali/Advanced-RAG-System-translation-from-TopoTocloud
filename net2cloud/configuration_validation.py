"""Validate known configuration shapes and references without predicting connectivity."""

from __future__ import annotations

import ipaddress
from collections import deque
from collections.abc import Callable
from typing import Any

Error = Callable[[str, str, str], None]


class ConfigurationValidator:
    def __init__(self, interfaces: dict[str, set[str]], error: Error):
        self.interfaces = interfaces
        self.error = error

    def object(self, value: Any, path: str) -> dict:
        if not isinstance(value, dict):
            self.error(
                "invalid_object",
                path,
                "Expected a JSON object; omit optional settings instead of null.",
            )
            return {}
        return value

    def objects(self, value: Any, path: str):
        if not isinstance(value, list):
            self.error("invalid_list", path, "Expected a list of objects.")
            return
        for index, item in enumerate(value):
            item_path = f"{path}/{index}"
            if not isinstance(item, dict):
                self.error("invalid_object", item_path, "Expected a JSON object.")
            else:
                yield item, item_path

    def text(self, value: Any, path: str) -> bool:
        valid = isinstance(value, str) and bool(value.strip())
        if not valid:
            self.error("missing_configuration_value", path, "Provide a nonempty string.")
        return valid

    def boolean(self, obj: dict, key: str, path: str) -> None:
        if key in obj and type(obj[key]) is not bool:
            self.error(
                "invalid_boolean",
                path + "/" + key,
                "Expected true or false, not a string or number.",
            )

    def integer(self, value: Any, path: str, low: int, high: int) -> None:
        if type(value) is not int or not low <= value <= high:
            self.error("invalid_integer", path, f"Expected an integer from {low} to {high}.")

    def address(self, value: Any, path: str, *, network: bool = False) -> None:
        try:
            if not isinstance(value, str) or (network and "/" not in value):
                raise ValueError
            if network:
                ipaddress.IPv4Network(value, strict=True)
            else:
                ipaddress.IPv4Address(value)
        except ValueError:
            self.error(
                "invalid_network" if network else "invalid_ipv4",
                path,
                "Provide a canonical IPv4 network/prefix."
                if network
                else "Provide an IPv4 address string.",
            )

    def reference(self, value: Any, allowed: set[str], path: str, code: str) -> None:
        if not isinstance(value, str) or value not in allowed:
            self.error(code, path, "Reference an existing identifier in this scope.")

    def references(
        self, value: Any, allowed: set[str], path: str, *, nonempty: bool = False
    ) -> list[str]:
        if not isinstance(value, list) or (nonempty and not value):
            self.error(
                "invalid_references",
                path,
                "Provide a list of unique existing IDs"
                + (" with at least one entry." if nonempty else "."),
            )
            return []
        seen = set()
        for index, item in enumerate(value):
            item_path = f"{path}/{index}"
            if not isinstance(item, str) or item not in allowed:
                self.error("unknown_reference", item_path, "Reference an existing identifier.")
            elif item in seen:
                self.error("duplicate_reference", item_path, "An identifier may appear only once.")
            else:
                seen.add(item)
        return list(seen)

    def routing(self, node: dict, ports: set[str], path: str) -> None:
        routing = self.object(node.get("routing", {}), path)
        self.boolean(routing, "ipv4_forwarding", path)
        if "default_gateway" in routing:
            gateway_path = path + "/default_gateway"
            gateway = self.object(routing["default_gateway"], gateway_path)
            self.address(gateway.get("via"), gateway_path + "/via")
            self.reference(
                gateway.get("interface"), ports, gateway_path + "/interface", "unknown_interface"
            )
        for route, route_path in self.objects(
            routing.get("static_routes", []), path + "/static_routes"
        ):
            self.address(route.get("destination"), route_path + "/destination", network=True)
            if "via" in route:
                self.address(route["via"], route_path + "/via")
            if "interface" in route:
                self.reference(
                    route["interface"], ports, route_path + "/interface", "unknown_interface"
                )
            if "via" not in route and "interface" not in route:
                self.error(
                    "missing_route_target",
                    route_path,
                    "Supply a next hop (via), an interface, or both.",
                )
            if "metric" in route:
                self.integer(route["metric"], route_path + "/metric", 0, 4294967295)
        for protocol, protocol_path in self.objects(
            routing.get("protocols", []), path + "/protocols"
        ):
            name = protocol.get("name")
            self.text(name, protocol_path + "/name")
            self.boolean(protocol, "enabled", protocol_path)
            # Unknown protocols retain their own configuration contract.
            if name not in ("ospf", "rip"):
                continue
            if name == "ospf":
                self.address(protocol.get("router_id"), protocol_path + "/router_id")
            else:
                self.integer(protocol.get("version"), protocol_path + "/version", 1, 2)
            seen = set()
            for interface, interface_path in self.objects(
                protocol.get("interfaces"), protocol_path + "/interfaces"
            ):
                pid = interface.get("id")
                self.reference(pid, ports, interface_path + "/id", "unknown_interface")
                if isinstance(pid, str):
                    if pid in seen:
                        self.error(
                            "duplicate_protocol_interface",
                            interface_path + "/id",
                            "Configure this protocol interface only once.",
                        )
                    seen.add(pid)
                self.boolean(interface, "passive", interface_path)
                if name == "ospf":
                    self.address(interface.get("area"), interface_path + "/area")
                    if "cost" in interface:
                        self.integer(interface["cost"], interface_path + "/cost", 1, 65535)
                    if "network_type" in interface:
                        self.text(interface["network_type"], interface_path + "/network_type")

    def services(self, node: dict, path: str) -> None:
        for service, service_path in self.objects(node.get("services", []), path):
            self.text(service.get("protocol"), service_path + "/protocol")
            self.boolean(service, "enabled", service_path)
            if "implementation" in service:
                self.text(service["implementation"], service_path + "/implementation")
            if "listen" in service:
                listen_path = service_path + "/listen"
                listener = self.object(service["listen"], listen_path)
                self.integer(listener.get("port"), listen_path + "/port", 1, 65535)
                if "address" in listener:
                    self.address(listener["address"], listen_path + "/address")

    def automation(self, value: Any, path: str) -> None:
        automation = self.object(value, path)
        for connection, connection_path in self.objects(
            automation.get("connections", []), path + "/connections"
        ):
            self.references(
                connection.get("target_ids"),
                set(self.interfaces),
                connection_path + "/target_ids",
                nonempty=True,
            )
        tasks = list(self.objects(automation.get("tasks", []), path + "/tasks"))
        task_paths = {}
        for task, task_path in tasks:
            identifier = task.get("id")
            if self.text(identifier, task_path + "/id"):
                if identifier in task_paths:
                    self.error("duplicate_task_id", task_path + "/id", "Task IDs must be unique.")
                task_paths[identifier] = task_path
            self.references(
                task.get("target_ids"),
                set(self.interfaces),
                task_path + "/target_ids",
                nonempty=True,
            )
            self.text(task.get("operation"), task_path + "/operation")
            self.object(task.get("parameters", {}), task_path + "/parameters")
        graph = {}
        for task, task_path in tasks:
            dependencies = self.references(
                task.get("depends_on", []), set(task_paths), task_path + "/depends_on"
            )
            if isinstance(task.get("id"), str) and task["id"] in task_paths:
                graph[task["id"]] = dependencies
        # Kahn's algorithm permits forward references and avoids recursion on large DAGs.
        degree = {identifier: len(deps) for identifier, deps in graph.items()}
        dependents = {identifier: [] for identifier in graph}
        for identifier, deps in graph.items():
            for dependency in deps:
                dependents[dependency].append(identifier)
        queue = deque(identifier for identifier, count in degree.items() if count == 0)
        visited = 0
        while queue:
            identifier = queue.popleft()
            visited += 1
            for dependent in dependents[identifier]:
                degree[dependent] -= 1
                if degree[dependent] == 0:
                    queue.append(dependent)
        if visited != len(graph):
            self.error(
                "cyclic_task_dependencies",
                path + "/tasks",
                "Task dependencies must not contain a cycle or self-reference.",
            )


def validate_configuration(
    architecture: dict, interfaces: dict[str, set[str]], error: Error
) -> None:
    validator = ConfigurationValidator(interfaces, error)
    cloud = validator.object(architecture.get("cloud", {}), "/cloud")
    for name in ("provider", "region"):
        if name in cloud:
            validator.text(cloud[name], "/cloud/" + name)
    if cloud.get("provider", "aws") != "aws":
        error("unsupported_cloud_provider", "/cloud/provider", "This translator targets AWS only.")
    if "generation" in architecture:
        error(
            "unsupported_generation_settings",
            "/generation",
            "Remove generator profile settings; this application returns an AWS JSON plan only.",
        )
    if "ansible" in architecture:
        error(
            "legacy_automation_field",
            "/ansible",
            "Use automation for declarative tasks; tool-specific generation is outside this application.",
        )
    if "schema_version" in architecture and architecture["schema_version"] != "1.0":
        error(
            "unsupported_schema_version",
            "/schema_version",
            "This contract supports schema_version '1.0'.",
        )
    if "translation_mode" in architecture and architecture["translation_mode"] not in (
        "behavioral_lab",
        "cloud_native",
    ):
        error(
            "invalid_translation_mode", "/translation_mode", "Use behavioral_lab or cloud_native."
        )
    components = architecture.get("components", [])
    if isinstance(components, list):
        for index, node in enumerate(components):
            if not isinstance(node, dict):
                continue
            path = f"/components/{index}"
            nid = node.get("id")
            ports = interfaces.get(nid, set()) if isinstance(nid, str) else set()
            validator.routing(node, ports, path + "/routing")
            validator.services(node, path + "/services")
            if "os" in node:
                settings = validator.object(node["os"], path + "/os")
                for key in ("distribution", "version"):
                    if key in settings:
                        validator.text(settings[key], path + "/os/" + key)
    validator.automation(architecture.get("automation", {}), "/automation")
