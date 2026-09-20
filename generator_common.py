"""Shared contract for the opt-in educational artifact generators.

This is downstream capability validation. It is never imported by the RAG.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from json_io import dumps_json, loads_json
from readiness import check_readiness

PROFILE = "aws_single_host_docker_v1"
INSTANCE_TYPES = {
    f"t4g.{size}" for size in ("nano", "micro", "small", "medium", "large", "xlarge", "2xlarge")
}
INTERFACE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,14}\Z")
PACKAGE = re.compile(r"[a-z0-9][a-z0-9+.-]*\Z")


class UnsupportedPlan(ValueError):
    """The artifact backend cannot implement this plan without changing it."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise UnsupportedPlan(message)


def fields(value: dict, allowed: set[str], context: str) -> None:
    require(isinstance(value, dict), f"{context} must be an object")
    unknown = set(value) - allowed
    require(not unknown, f"Unsupported {context} fields: {sorted(unknown)}")


def token(value: str) -> str:
    """Opaque source IDs never become shell commands or filesystem paths."""
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def load_plan(path: Path) -> dict[str, Any]:
    return validate_plan(loads_json(path.read_text(encoding="utf-8")))


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Reject malformed plans with one public exception type before writing files."""
    try:
        return _validate_plan(plan)
    except UnsupportedPlan:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise UnsupportedPlan(f"Malformed generator plan: {error}") from error


def _validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Accept the documented concrete backend contract; never infer a translation."""
    require(isinstance(plan, dict), "Input must be a RAG plan object, not raw architecture")
    architecture = plan.get("architecture")
    cloud = plan.get("cloud_plan")
    ansible = plan.get("ansible_plan")
    require(
        all(isinstance(x, dict) for x in (architecture, cloud, ansible)),
        "Require architecture, cloud_plan and ansible_plan objects",
    )
    report = check_readiness(architecture)
    require(report["ready"], "Source architecture is not ready: " + dumps_json(report["errors"]))
    require(
        plan.get("limitations") == [],
        "Resolve plan limitations before generating executable artifacts",
    )
    require(cloud.get("backend") == PROFILE, f"cloud_plan.backend must be {PROFILE}")
    require(cloud.get("translation_mode") == "behavioral_lab", "Only behavioral_lab is implemented")
    fields(
        cloud,
        {
            "backend",
            "translation_mode",
            "settings",
            "component_mapping",
            "networking",
            "dependencies",
        },
        "cloud_plan",
    )
    require(cloud.get("dependencies") == [], "Unresolved cloud dependencies")
    fields(
        architecture,
        {
            "schema_version",
            "translation_mode",
            "generation",
            "cloud",
            "components",
            "edges",
            "ansible",
        },
        "architecture",
    )
    require(
        architecture.get("translation_mode", "behavioral_lab") == "behavioral_lab",
        "Conflicting source mode",
    )
    if "generation" in architecture:
        require(
            architecture["generation"] == {"profile": PROFILE},
            "Unsupported source generation settings",
        )
    fields(architecture.get("cloud", {}), {"provider", "region"}, "source cloud")
    require(architecture.get("cloud", {}).get("provider", "aws") == "aws", "Only AWS is supported")
    settings = cloud.get("settings", {})
    fields(settings, {"lab_name", "region", "instance_type", "root_volume_gib"}, "cloud settings")
    name = settings.get("lab_name", "learnlab")
    require(
        isinstance(name, str) and re.fullmatch(r"[a-z][a-z0-9-]{0,23}", name) is not None,
        "lab_name: 1-24 lowercase letters/digits/hyphens",
    )
    require(
        settings.get("instance_type", "t4g.nano") in INSTANCE_TYPES,
        "Use a supported ARM t4g instance size",
    )
    region = settings.get("region", architecture.get("cloud", {}).get("region", "us-east-1"))
    require(
        isinstance(region, str) and re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d", region) is not None,
        "Invalid AWS region",
    )
    require(
        region == architecture.get("cloud", {}).get("region", region),
        "Plan/source region disagreement",
    )
    disk = settings.get("root_volume_gib", 8)
    require(type(disk) is int and 8 <= disk <= 100, "root_volume_gib must be 8-100")
    nodes = architecture.get("components", [])
    require(isinstance(nodes, list) and bool(nodes), "At least one component is required")
    by_id = {}
    ports = set()
    for node in nodes:
        fields(node, {"id", "name", "type", "interfaces", "routing", "services", "os"}, "component")
        nid = node.get("id")
        require(
            isinstance(nid, str) and bool(nid) and nid not in by_id,
            "Component IDs must be nonempty and unique",
        )
        require(
            node.get("type") in {"pc", "server", "router", "switch"}, f"Unsupported role on {nid}"
        )
        if "os" in node:
            require(
                node["os"] == {"distribution": "debian", "version": "12"},
                "This backend implements Debian 12 container userspace only",
            )
        interfaces = node.get("interfaces", [])
        require(
            isinstance(interfaces, list) and bool(interfaces), f"{nid} needs explicit interfaces"
        )
        for port in interfaces:
            fields(port, {"id", "ipv4", "enabled", "access_vlan"}, f"{nid} interface")
            pid = port.get("id", "")
            require(
                isinstance(pid, str)
                and INTERFACE.fullmatch(pid) is not None
                and pid not in {"lo", "br0"},
                "Invalid/reserved interface name",
            )
            require((nid, pid) not in ports, f"Duplicate interface {nid}/{pid}")
            require(type(port.get("enabled", True)) is bool, "Interface enabled must be boolean")
            if "ipv4" in port:
                require(node["type"] != "switch", "L3 switch addresses are not implemented")
                require(
                    isinstance(ipaddress.ip_interface(port["ipv4"]), ipaddress.IPv4Interface),
                    "Only IPv4 is implemented",
                )
            if "access_vlan" in port:
                require(
                    node["type"] == "switch"
                    and type(port["access_vlan"]) is int
                    and 1 <= port["access_vlan"] <= 4094,
                    "Only switch access VLANs 1-4094 are implemented",
                )
            ports.add((nid, pid))
        _routing(node)
        _services(node)
        by_id[nid] = node
    edges = architecture.get("edges", [])
    require(isinstance(edges, list), "edges must be a list")
    used, edge_ids = set(), set()
    for edge in edges:
        fields(edge, {"id", "source", "target", "enabled"}, "edge")
        require(
            isinstance(edge.get("id"), str) and edge["id"] and edge["id"] not in edge_ids,
            "Unique edge IDs required",
        )
        edge_ids.add(edge["id"])
        require(type(edge.get("enabled", True)) is bool, "Edge enabled must be boolean")
        for end in ("source", "target"):
            fields(edge[end], {"component", "interface"}, "edge endpoint")
            key = (edge[end].get("component"), edge[end].get("interface"))
            require(
                key in ports and key not in used, f"Missing or multiply connected interface {key}"
            )
            used.add(key)
    require(
        used == ports,
        "This profile requires every interface to have an explicit cable; use a disabled edge for a down cable",
    )
    _reject_switch_loops(by_id, edges)
    mappings = cloud.get("component_mapping", [])
    require(
        isinstance(mappings, list) and len(mappings) == len(nodes),
        "Map each source component exactly once",
    )
    mapped = set()
    for mapping in mappings:
        fields(
            mapping,
            {"component_id", "role", "cloud_representation", "configuration", "rule_ids"},
            "component mapping",
        )
        nid = mapping.get("component_id")
        require(nid in by_id and nid not in mapped, "Invalid/duplicate mapped component")
        require(mapping.get("role") == by_id[nid]["type"], "Mapping role differs from source")
        require(
            mapping.get("cloud_representation") == "docker_container"
            and mapping.get("configuration") == {"worker_id": "lab_worker"},
            "All nodes must explicitly map to containers on lab_worker",
        )
        mapped.add(nid)
    require(
        cloud.get("networking")
        == {"source": "architecture", "realization": "veth_and_linux_bridge"},
        "Use the explicit source-topology realization contract",
    )
    _ansible(ansible, architecture, by_id)
    result = deepcopy(plan)
    result["cloud_plan"]["settings"] = {
        "lab_name": name,
        "region": region,
        "instance_type": settings.get("instance_type", "t4g.nano"),
        "root_volume_gib": disk,
    }
    return result


def _reject_switch_loops(by_id: dict, edges: list) -> None:
    """The v1 switch has no STP; an active L2 cycle cannot be deployed safely."""
    parents = {}

    def root(key):
        parents.setdefault(key, key)
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    ports = {(nid, port["id"]): port for nid, node in by_id.items() for port in node["interfaces"]}
    for edge in edges:
        if not edge.get("enabled", True):
            continue
        ends = [edge["source"], edge["target"]]
        if any(by_id[end["component"]]["type"] != "switch" for end in ends):
            continue
        if any(
            not ports[(end["component"], end["interface"])].get("enabled", True) for end in ends
        ):
            continue
        left, right = [
            root(
                (
                    end["component"],
                    ports[(end["component"], end["interface"])].get("access_vlan", 1),
                )
            )
            for end in ends
        ]
        require(
            left != right,
            "Active Layer 2 loop: this profile does not implement STP or link aggregation",
        )
        parents[left] = right


def _routing(node: dict) -> None:
    routing = node.get("routing", {})
    fields(routing, {"ipv4_forwarding", "default_gateway", "static_routes", "protocols"}, "routing")
    require(node["type"] != "switch" or not routing, "Switch routing is not implemented")
    require(type(routing.get("ipv4_forwarding", False)) is bool, "ipv4_forwarding must be boolean")
    names = {p["id"] for p in node["interfaces"]}
    gateway = routing.get("default_gateway")
    if gateway is not None:
        fields(gateway, {"interface", "via"}, "gateway")
        require(gateway.get("interface") in names, "Gateway interface not found")
        ipaddress.IPv4Address(gateway["via"])
    for route in routing.get("static_routes", []):
        fields(route, {"destination", "via", "interface", "metric"}, "static route")
        ipaddress.IPv4Network(route["destination"], strict=False)
        ipaddress.IPv4Address(route["via"])
        require(route.get("interface") in names, "Static routes require an explicit interface")
        require(
            type(route.get("metric", 0)) is int and 0 <= route.get("metric", 0) <= 4294967295,
            "Invalid static metric",
        )
    seen = set()
    for protocol in routing.get("protocols", []):
        fields(
            protocol, {"name", "enabled", "router_id", "version", "interfaces"}, "routing protocol"
        )
        name = protocol.get("name")
        require(
            name in {"ospf", "rip"} and name not in seen,
            "Support one OSPFv2 and one RIPv2 process per router",
        )
        require(node["type"] == "router", "Dynamic routing requires router role")
        seen.add(name)
        require(type(protocol.get("enabled", True)) is bool, "Protocol enabled must be boolean")
        if name == "ospf":
            ipaddress.IPv4Address(protocol["router_id"])
            require("version" not in protocol, "OSPF version is implicit v2")
        else:
            require(
                protocol.get("version") == 2 and "router_id" not in protocol,
                "Only RIPv2 is implemented",
            )
        participating = set()
        for interface in protocol.get("interfaces", []):
            fields(
                interface,
                {"id", "passive", "area", "network_type", "cost"}
                if name == "ospf"
                else {"id", "passive"},
                "protocol interface",
            )
            require(
                interface.get("id") in names and interface["id"] not in participating,
                "Invalid/duplicate protocol interface",
            )
            participating.add(interface["id"])
            require(type(interface.get("passive", False)) is bool, "Passive must be boolean")
            if name == "ospf":
                ipaddress.IPv4Address(interface["area"])
                require(
                    interface.get("network_type", "broadcast") in {"broadcast", "point-to-point"},
                    "Unsupported OSPF network type",
                )
                require(
                    type(interface.get("cost", 1)) is int
                    and 1 <= interface.get("cost", 1) <= 65535,
                    "Invalid OSPF cost",
                )


def _services(node: dict) -> None:
    services = node.get("services", [])
    require(
        isinstance(services, list) and len(services) <= 1,
        "At most one HTTP service per component in v1",
    )
    for service in services:
        fields(
            service,
            {"protocol", "implementation", "enabled", "listen", "document_root", "content"},
            "service",
        )
        require(
            service.get("protocol") == "http" and service.get("implementation") == "nginx",
            "Only nginx HTTP is implemented; TLS and other servers need a backend extension",
        )
        require(type(service.get("enabled", True)) is bool, "Service enabled must be boolean")
        listener = service.get("listen", {})
        fields(listener, {"address", "port"}, "HTTP listener")
        ipaddress.IPv4Address(listener["address"])
        require(
            type(listener.get("port")) is int and 1 <= listener["port"] <= 65535,
            "Invalid HTTP port",
        )
        root = service.get("document_root")
        require(
            isinstance(root, str)
            and re.fullmatch(r"/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+", root) is not None,
            "Use a simple absolute HTTP document_root",
        )
        require(
            root.startswith(("/var/www/", "/srv/www/")),
            "HTTP roots must be below /var/www or /srv/www",
        )
        content = service.get("content", {})
        require(isinstance(content, dict), "HTTP content must map filenames to text")
        for filename, text in content.items():
            require(
                re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9]+", filename) is not None
                and isinstance(text, str),
                "Only simple HTTP content filenames/text are supported",
            )


def _ansible(ansible: dict, architecture: dict, by_id: dict) -> None:
    fields(ansible, {"targets", "tasks", "dependencies"}, "ansible_plan")
    require(ansible.get("dependencies") == [], "Unresolved Ansible dependencies")
    targets = ansible.get("targets", [])
    require(len(targets) == len(by_id), "Target every source component exactly once")
    seen = set()
    for target in targets:
        fields(target, {"component_id", "connection", "variables"}, "Ansible target")
        nid = target.get("component_id")
        require(nid in by_id and nid not in seen, "Invalid/duplicate target")
        require(
            target.get("connection") == {"type": "docker_exec", "worker_id": "lab_worker"}
            and target.get("variables") == {},
            "Only explicit docker_exec management with empty target variables is implemented",
        )
        seen.add(nid)
    source_ansible = architecture.get("ansible", {})
    fields(source_ansible, {"tasks"}, "source ansible")
    source_tasks = source_ansible.get("tasks", [])
    configured, task_ids, package_tasks = set(), set(), []
    for task in ansible.get("tasks", []):
        fields(
            task, {"id", "target_ids", "operation", "parameters", "depends_on", "rule_ids"}, "task"
        )
        require(
            isinstance(task.get("id"), str) and task["id"] and task["id"] not in task_ids,
            "Unique nonempty task IDs required",
        )
        require(
            set(task.get("depends_on", [])) <= task_ids,
            "Tasks must be ordered after their dependencies",
        )
        task_ids.add(task["id"])
        targets = task.get("target_ids", [])
        require(
            isinstance(targets, list)
            and bool(targets)
            and len(set(targets)) == len(targets)
            and set(targets) <= set(by_id),
            "Invalid task targets",
        )
        if task.get("operation") == "lab.configure_component":
            require(
                len(targets) == 1 and targets[0] not in configured,
                "Configure each component exactly once",
            )
            require(
                task.get("parameters") == {"source_component_id": targets[0]},
                "Configuration must reference its exact source component",
            )
            configured.add(targets[0])
        elif task.get("operation") == "ansible.builtin.package":
            parameters = task.get("parameters", {})
            fields(parameters, {"name", "state"}, "package task")
            names = parameters.get("name")
            require(
                parameters.get("state") == "present" and isinstance(names, list) and bool(names),
                "Only explicit package lists with state=present are supported",
            )
            require(
                all(isinstance(n, str) and PACKAGE.fullmatch(n) is not None for n in names),
                "Invalid Debian package name",
            )
            require(
                not task.get("depends_on"),
                "Package installation is an image-build operation; runtime dependencies are unsupported",
            )
            package_tasks.append({k: v for k, v in task.items() if k != "rule_ids"})
        else:
            raise UnsupportedPlan(f"Unsupported Ansible operation: {task.get('operation')}")
    require(configured == set(by_id), "Missing component configuration tasks")
    require(
        package_tasks == source_tasks,
        "Plan package tasks must exactly match source tasks; no invented or dropped operations",
    )


def runtime_spec(plan: dict) -> dict:
    architecture = plan["architecture"]
    name = plan["cloud_plan"]["settings"]["lab_name"]
    packages = {n["id"]: [] for n in architecture["components"]}
    for task in architecture.get("ansible", {}).get("tasks", []):
        for nid in task["target_ids"]:
            packages[nid].extend(task["parameters"]["name"])
    nodes = []
    by_id = {node["id"]: node for node in architecture["components"]}
    order = [
        task["target_ids"][0]
        for task in plan["ansible_plan"]["tasks"]
        if task["operation"] == "lab.configure_component"
    ]
    for nid in order:
        source = by_id[nid]
        node = deepcopy(source)
        node["runtime_name"] = f"{name}-{token(source['id'])}"
        node["packages"] = sorted(set(packages[source["id"]]))
        for interface in node["interfaces"]:
            interface["link_enabled"] = next(
                edge.get("enabled", True)
                for edge in architecture["edges"]
                if {"component": source["id"], "interface": interface["id"]}
                in (edge["source"], edge["target"])
            )
        nodes.append(node)
    return {
        "profile": PROFILE,
        "lab_name": name,
        "nodes": nodes,
        "edges": deepcopy(architecture["edges"]),
    }


def write_bundle(output: Path, files: dict[str, str]) -> None:
    """Stage the whole project, never overwrite an existing project or state."""
    import shutil
    import tempfile

    require(not output.exists(), f"Output already exists: {output}. Choose a new directory.")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".generator-", dir=output.parent))
    try:
        for name, content in files.items():
            path = staging / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        staging.rename(output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def manifest(plan: dict, generator: str) -> str:
    return (
        dumps_json(
            {
                "generator": generator,
                "profile": PROFILE,
                "plan_sha256": hashlib.sha256(
                    dumps_json(plan, sort_keys=True).encode()
                ).hexdigest(),
                "deployed": False,
            },
            indent=2,
        )
        + "\n"
    )
