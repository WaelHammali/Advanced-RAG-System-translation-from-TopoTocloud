#!/usr/bin/env python3
"""Configure a fresh isolated container after its exact cables have been attached."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def run(*arguments: str) -> None:
    subprocess.run(list(arguments), check=True)


def configure(node: dict) -> None:
    run("ip", "link", "set", "lo", "up")
    if node["type"] == "switch":
        run(
            "ip",
            "link",
            "add",
            "br0",
            "type",
            "bridge",
            "vlan_filtering",
            "1",
            "mcast_snooping",
            "0",
            "stp_state",
            "0",
        )
        run("ip", "link", "set", "br0", "up")
    for interface in node["interfaces"]:
        name = interface["id"]
        if node["type"] == "switch":
            run("ip", "link", "set", name, "master", "br0")
            vlan = interface.get("access_vlan", 1)
            if vlan != 1:
                run("bridge", "vlan", "del", "dev", name, "vid", "1")
                run("bridge", "vlan", "add", "dev", name, "vid", str(vlan), "pvid", "untagged")
        if "ipv4" in interface:
            run("ip", "address", "add", interface["ipv4"], "dev", name)
        run(
            "ip",
            "link",
            "set",
            name,
            "up"
            if (interface.get("enabled", True) and interface.get("link_enabled", True))
            else "down",
        )
    routing = node.get("routing", {})
    gateway = routing.get("default_gateway")
    if gateway:
        run("ip", "route", "add", "default", "via", gateway["via"], "dev", gateway["interface"])
    for route in routing.get("static_routes", []):
        command = [
            "ip",
            "route",
            "add",
            route["destination"],
            "via",
            route["via"],
            "dev",
            route["interface"],
            "proto",
            "static",
        ]
        if "metric" in route:
            command += ["metric", str(route["metric"])]
        run(*command)
    if any(p.get("enabled", True) for p in routing.get("protocols", [])):
        run("/usr/lib/frr/frrinit.sh", "start")
        run("vtysh", "-c", "show version")
    for service in node.get("services", []):
        if service.get("enabled", True):
            run("nginx", "-t")
            run("nginx")


if __name__ == "__main__":
    configure(json.loads(Path("/opt/net2cloud/node.json").read_text(encoding="utf-8")))
