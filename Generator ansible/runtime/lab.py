#!/usr/bin/env python3
"""Manage only this educational lab's labelled containers and explicit veth links.

Runs on the worker through Ansible/systemd, never during artifact generation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

LABEL = "net2cloud.lab"


def command(*arguments: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(list(arguments), check=check, text=True, capture_output=True)


def fingerprint(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            digest.update(str(path.relative_to(directory)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def image_name(node: dict, revision: str) -> str:
    return f"net2cloud-{node['runtime_name']}:{revision[:16]}"


def build(directory: Path, spec: dict, revision: str) -> bool:
    changed = False
    base = command("docker", "image", "inspect", "net2cloud-base:debian12", check=False)
    base_revision = hashlib.sha256((directory / "base/Dockerfile").read_bytes()).hexdigest()
    labels = {} if base.returncode else (json.loads(base.stdout)[0]["Config"].get("Labels") or {})
    if not base.returncode and labels.get("net2cloud.managed") != "true":
        raise ValueError("The base image tag belongs to an unmanaged image")
    if base.returncode or labels.get("net2cloud.base_revision") != base_revision:
        command(
            "docker",
            "build",
            "--label",
            "net2cloud.managed=true",
            "--label",
            f"net2cloud.base_revision={base_revision}",
            "-t",
            "net2cloud-base:debian12",
            str(directory / "base"),
        )
        changed = True
    for node in spec["nodes"]:
        name = image_name(node, revision)
        if command("docker", "image", "inspect", name, check=False).returncode:
            command(
                "docker",
                "build",
                "--label",
                f"{LABEL}={spec['lab_name']}",
                "-t",
                name,
                str(directory / "nodes" / node["runtime_name"]),
            )
            changed = True
    return changed


def inspect(name: str) -> dict | None:
    result = command("docker", "inspect", name, check=False)
    if result.returncode:
        return None
    return json.loads(result.stdout)[0]


def destroy(spec: dict, state_file: Path) -> None:
    # A label filter owns deletions; never operate on arbitrary containers.
    result = command("docker", "ps", "-aq", "--filter", f"label={LABEL}={spec['lab_name']}")
    for container in result.stdout.split():
        command("docker", "rm", "-f", container)
    links = json.loads(command("ip", "-j", "link", "show").stdout)
    for link in links:
        if link.get("ifalias") == f"net2cloud:{spec['lab_name']}":
            command("ip", "link", "delete", link["ifname"], check=False)
    state_file.unlink(missing_ok=True)


def apply(directory: Path, spec: dict, revision: str, state_file: Path) -> bool:
    names = [node["runtime_name"] for node in spec["nodes"]]
    present = {name: inspect(name) for name in names}
    # Never replace an unrelated resource that happens to share a generated name.
    for name, container in present.items():
        if container and (container["Config"].get("Labels") or {}).get(LABEL) != spec["lab_name"]:
            raise ValueError(f"Container name already owned outside this lab: {name}")
    try:
        previous = json.loads(state_file.read_text())
    except (OSError, ValueError):
        previous = {}
    pids = {
        name: value["State"]["Pid"]
        for name, value in present.items()
        if value and value["State"]["Running"]
    }
    if (
        previous.get("revision") == revision
        and previous.get("pids") == pids
        and len(pids) == len(names)
    ):
        return False
    for node in spec["nodes"]:
        if command(
            "docker", "image", "inspect", image_name(node, revision), check=False
        ).returncode:
            raise ValueError("Build all lab images before applying the topology")
    destroy(spec, state_file)
    pids = {}
    try:
        for node in spec["nodes"]:
            name = node["runtime_name"]
            command(
                "docker",
                "run",
                "-d",
                "--init",
                "--name",
                name,
                "--hostname",
                name,
                "--network",
                "none",
                "--cap-add",
                "NET_ADMIN",
                "--cap-add",
                "NET_RAW",
                "--cap-add",
                "SYS_ADMIN",
                "--sysctl",
                "net.ipv4.conf.all.rp_filter=0",
                "--sysctl",
                "net.ipv4.conf.default.rp_filter=0",
                "--sysctl",
                "net.ipv6.conf.all.disable_ipv6=1",
                "--sysctl",
                "net.ipv6.conf.default.disable_ipv6=1",
                "--sysctl",
                "net.ipv4.ip_forward="
                + ("1" if node.get("routing", {}).get("ipv4_forwarding", False) else "0"),
                "--label",
                f"{LABEL}={spec['lab_name']}",
                "--label",
                f"net2cloud.revision={revision}",
                image_name(node, revision),
            )
            pids[name] = inspect(name)["State"]["Pid"]
        nodes = {node["id"]: node for node in spec["nodes"]}
        for edge in spec["edges"]:
            short = hashlib.sha256((spec["lab_name"] + edge["id"]).encode()).hexdigest()[:10]
            left, right = "v" + short + "a", "v" + short + "b"
            command("ip", "link", "add", left, "type", "veth", "peer", "name", right)
            for temporary, end in [(left, edge["source"]), (right, edge["target"])]:
                command("ip", "link", "set", temporary, "alias", f"net2cloud:{spec['lab_name']}")
                pid = str(pids[nodes[end["component"]]["runtime_name"]])
                command("ip", "link", "set", temporary, "netns", pid)
                command(
                    "nsenter",
                    "-t",
                    pid,
                    "-n",
                    "--",
                    "ip",
                    "link",
                    "set",
                    temporary,
                    "name",
                    end["interface"],
                )
        # Configure while all peers exist; no generated default Docker networking.
        for node in spec["nodes"]:
            command(
                "docker", "exec", node["runtime_name"], "python3", "/opt/net2cloud/configure.py"
            )
        # Edge state is independent of endpoint administrative state.
        for edge in spec["edges"]:
            if not edge.get("enabled", True):
                for end in [edge["source"], edge["target"]]:
                    command(
                        "docker",
                        "exec",
                        nodes[end["component"]]["runtime_name"],
                        "ip",
                        "link",
                        "set",
                        end["interface"],
                        "down",
                    )
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps({"revision": revision, "pids": pids}) + "\n")
    except Exception:
        destroy(spec, state_file)
        raise
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["build", "apply", "destroy"])
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    directory = args.directory.resolve()
    try:
        spec = json.loads((directory / "lab.json").read_text())
        revision = fingerprint(directory)
        state = Path("/var/lib/net2cloud") / spec["lab_name"] / "state.json"
        if args.action == "build":
            changed = build(directory, spec, revision)
        elif args.action == "destroy":
            destroy(spec, state)
            changed = True
        else:
            changed = apply(directory, spec, revision, state)
        print(json.dumps({"changed": changed}))
        return 0
    except Exception as error:
        detail = error.stderr if isinstance(error, subprocess.CalledProcessError) else str(error)
        print(json.dumps({"error": detail}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
