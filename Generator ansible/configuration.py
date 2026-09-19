"""Compile source configuration into files; no network decisions or model calls."""

from __future__ import annotations

import json
from pathlib import Path

BASE_DOCKERFILE = """FROM debian:12-slim
ENV DEBIAN_FRONTEND=noninteractive
RUN printf '#!/bin/sh\\nexit 101\\n' > /usr/sbin/policy-rc.d \\
 && chmod +x /usr/sbin/policy-rc.d \\
 && apt-get update \\
 && apt-get install -y --no-install-recommends iproute2 iputils-ping procps python3 frr nginx ca-certificates \\
 && rm -rf /var/lib/apt/lists/*
CMD ["sleep", "infinity"]
"""


def frr_configuration(node: dict) -> tuple[str, str]:
    routing = node.get("routing", {})
    protocols = [p for p in routing.get("protocols", []) if p.get("enabled", True)]
    active = {p["name"] for p in protocols}
    lines = [
        f"hostname {node['runtime_name']}",
        "log stdout",
        "ip forwarding" if routing.get("ipv4_forwarding", False) else "no ip forwarding",
        "!",
    ]
    for protocol in protocols:
        if protocol["name"] == "ospf":
            for interface in protocol.get("interfaces", []):
                lines.extend([f"interface {interface['id']}", f" ip ospf area {interface['area']}"])
                if "network_type" in interface:
                    lines.append(f" ip ospf network {interface['network_type']}")
                if "cost" in interface:
                    lines.append(f" ip ospf cost {interface['cost']}")
                lines.extend(["exit", "!"])
            lines.extend(["router ospf", f" ospf router-id {protocol['router_id']}"])
            for interface in protocol.get("interfaces", []):
                if interface.get("passive", False):
                    lines.append(f" passive-interface {interface['id']}")
        else:
            lines.extend(["router rip", " version 2", " passive-interface default"])
            for interface in protocol.get("interfaces", []):
                lines.append(f" network {interface['id']}")
                if not interface.get("passive", False):
                    lines.append(f" no passive-interface {interface['id']}")
        lines.extend(["exit", "!"])
    daemon_names = [
        "zebra",
        "bgpd",
        "ospfd",
        "ospf6d",
        "ripd",
        "ripngd",
        "isisd",
        "pimd",
        "ldpd",
        "nhrpd",
        "eigrpd",
        "babeld",
        "sharpd",
        "pbrd",
        "bfdd",
        "fabricd",
        "vrrpd",
        "staticd",
    ]
    enabled = {"zebra"} if active else set()
    enabled |= {"ospfd"} if "ospf" in active else set()
    enabled |= {"ripd"} if "rip" in active else set()
    daemons = [f"{name}={'yes' if name in enabled else 'no'}" for name in daemon_names]
    daemons += [
        "vtysh_enable=yes",
        'zebra_options=" -s 90000000 --daemon -A 127.0.0.1"',
        'ospfd_options=" --daemon -A 127.0.0.1"',
        'ripd_options=" --daemon -A 127.0.0.1"',
    ]
    return "\n".join(lines) + "\n", "\n".join(daemons) + "\n"


def node_files(node: dict) -> dict[str, str]:
    dockerfile = ["FROM net2cloud-base:debian12"]
    if node["packages"]:
        dockerfile += [
            "RUN apt-get update && apt-get install -y --no-install-recommends "
            + " ".join(node["packages"])
            + " && rm -rf /var/lib/apt/lists/*"
        ]
    dockerfile += [
        'COPY ["node.json", "/opt/net2cloud/node.json"]',
        'COPY ["configure.py", "/opt/net2cloud/configure.py"]',
        'COPY ["frr.conf", "/etc/frr/frr.conf"]',
        'COPY ["daemons", "/etc/frr/daemons"]',
        "RUN chown frr:frr /etc/frr/frr.conf /etc/frr/daemons && chmod 640 /etc/frr/frr.conf /etc/frr/daemons",
    ]
    frr, daemons = frr_configuration(node)
    files = {
        "node.json": json.dumps(node, indent=2) + "\n",
        "frr.conf": frr,
        "daemons": daemons,
        "configure.py": (Path(__file__).parent / "runtime/configure.py").read_text(
            encoding="utf-8"
        ),
    }
    for service in node.get("services", []):
        listen = service["listen"]
        files["nginx.conf"] = f"""user www-data;
worker_processes 1;
pid /run/nginx.pid;
events {{ worker_connections 128; }}
http {{
  include /etc/nginx/mime.types;
  access_log /var/log/nginx/access.log;
  server {{
    listen {listen["address"]}:{listen["port"]};
    root {service["document_root"]};
    index index.html;
  }}
}}
"""
        dockerfile += [
            'COPY ["nginx.conf", "/etc/nginx/nginx.conf"]',
            "RUN mkdir -p " + service["document_root"],
        ]
        if service.get("content"):
            dockerfile.append(
                "COPY --chown=www-data:www-data "
                + json.dumps(["site/", service["document_root"] + "/"])
            )
            for filename, content in service["content"].items():
                files[f"site/{filename}"] = content
    files["Dockerfile"] = "\n".join(dockerfile) + "\n"
    return files
