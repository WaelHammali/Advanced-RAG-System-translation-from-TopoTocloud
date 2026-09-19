"""Artifact and runtime-command regressions; no Docker daemon or AWS calls."""

import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from generator_common import load_plan, runtime_spec, validate_plan

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@pytest.fixture
def plan():
    return load_plan(ROOT / "examples/generator_plan.json")


@pytest.fixture(scope="module")
def generators():
    return (
        module("terraform_generator", "Generator terraform/generator.py"),
        module("ansible_generator", "Generator ansible/generator.py"),
    )


@pytest.fixture(scope="module")
def runtime():
    return module("lab_runtime", "Generator ansible/runtime/lab.py")


@pytest.fixture(scope="module")
def configure():
    return module("node_configuration", "Generator ansible/runtime/configure.py")


def test_generators_produce_matching_projects_without_mutating_source(plan, generators, tmp_path):
    before = deepcopy(plan)
    terraform, ansible = generators
    tf, ans = tmp_path / "terraform", tmp_path / "ansible"
    terraform.generate(plan, tf)
    ansible.generate(plan, ans)
    assert plan == before
    assert json.loads((tf / "arch.json").read_text()) == before
    assert json.loads((ans / "arch.json").read_text()) == before
    assert (
        json.loads((tf / "manifest.json").read_text())["plan_sha256"]
        == json.loads((ans / "manifest.json").read_text())["plan_sha256"]
    )
    hcl = (tf / "main.tf").read_text()
    assert hcl.count('resource "aws_instance"') == 1
    assert "aws_nat_gateway" not in hcl and "aws_ec2_transit_gateway" not in hcl
    assert "arm64" in hcl and 'cpu_credits = "standard"' in hcl
    settings = json.loads((tf / "lab.auto.tfvars.json").read_text())
    assert settings["instance_type"] == "t4g.nano"
    plays = yaml.safe_load((ans / "site.yml").read_text())
    assert plays[0]["hosts"] == "lab_workers"
    assert not any("shell" in key for task in plays[0]["tasks"] for key in task)
    nodes = {n["id"]: n for n in json.loads((ans / "files/lab.json").read_text())["nodes"]}
    for nid, node in nodes.items():
        dockerfile = (ans / "files/nodes" / node["runtime_name"] / "Dockerfile").read_text()
        assert ("apt-get install" in dockerfile) == (nid == "WEB1")
    web = ans / "files/nodes" / nodes["WEB1"]["runtime_name"]
    assert "listen 10.20.20.30:80;" in (web / "nginx.conf").read_text()
    assert "--chown=www-data:www-data" in (web / "Dockerfile").read_text()
    r1 = ans / "files/nodes" / nodes["R1"]["runtime_name"]
    assert "ospf router-id 1.1.1.1" in (r1 / "frr.conf").read_text()
    assert "passive-interface lan0" in (r1 / "frr.conf").read_text()


@pytest.mark.parametrize("generator_index", [0, 1])
def test_existing_output_and_state_are_never_overwritten(
    plan, generators, tmp_path, generator_index
):
    target = tmp_path / "existing"
    target.mkdir()
    state = target / "terraform.tfstate"
    state.write_text("important state")
    with pytest.raises(ValueError, match="already exists"):
        generators[generator_index].generate(plan, target)
    assert list(target.iterdir()) == [state]
    assert state.read_text() == "important state"
    assert not list(tmp_path.glob(".generator-*"))


@pytest.mark.parametrize(
    "change",
    [
        "backend",
        "firewall",
        "tls",
        "unknown",
        "route_interface",
        "task",
        "mapping",
        "limitations",
        "webroot",
    ],
)
def test_unsupported_semantics_fail_before_publication(plan, generators, tmp_path, change):
    if change == "backend":
        plan["cloud_plan"]["backend"] = "generic"
    elif change == "firewall":
        plan["architecture"]["components"][0]["type"] = "firewall"
    elif change == "tls":
        plan["architecture"]["components"][-1]["services"][0]["protocol"] = "https"
    elif change == "unknown":
        plan["architecture"]["components"][0]["acl"] = ["deny any"]
    elif change == "route_interface":
        plan["architecture"]["components"][2]["routing"]["static_routes"] = [
            {"destination": "10.20.20.0/24", "via": "10.255.0.2"}
        ]
    elif change == "task":
        plan["ansible_plan"]["tasks"][-1]["operation"] = "ansible.builtin.shell"
    elif change == "mapping":
        plan["cloud_plan"]["component_mapping"][0]["configuration"]["worker_id"] = "other"
    elif change == "limitations":
        plan["limitations"] = ["not implemented"]
    else:
        plan["architecture"]["components"][-1]["services"][0]["document_root"] = "/etc/frr"
    for index, generator in enumerate(generators):
        output = tmp_path / str(index)
        with pytest.raises(ValueError):
            generator.generate(plan, output)
        assert not output.exists()


def test_ospf_mismatch_disabled_protocol_and_disabled_http_are_preserved(
    plan, generators, tmp_path
):
    plan["architecture"]["components"][2]["routing"]["protocols"][0]["enabled"] = False
    plan["architecture"]["components"][3]["routing"]["protocols"][0]["interfaces"][0]["area"] = (
        "0.0.0.7"
    )
    plan["architecture"]["components"][-1]["services"][0]["enabled"] = False
    generators[1].generate(plan, tmp_path / "ansible")
    spec = runtime_spec(validate_plan(plan))
    nodes = {n["id"]: n for n in spec["nodes"]}
    r1 = tmp_path / "ansible/files/nodes" / nodes["R1"]["runtime_name"]
    r2 = tmp_path / "ansible/files/nodes" / nodes["R2"]["runtime_name"]
    assert "ospfd=no" in (r1 / "daemons").read_text()
    assert "router ospf" not in (r1 / "frr.conf").read_text()
    assert "ip ospf area 0.0.0.7" in (r2 / "frr.conf").read_text()
    assert nodes["WEB1"]["services"][0]["enabled"] is False


def test_rip_is_rendered_without_ospf_or_static_fallback(plan, generators, tmp_path):
    for node in plan["architecture"]["components"]:
        if node["type"] == "router":
            node["routing"]["protocols"] = [
                {
                    "name": "rip",
                    "version": 2,
                    "enabled": True,
                    "interfaces": [
                        {"id": "wan0", "passive": False},
                        {"id": "lan0", "passive": True},
                    ],
                }
            ]
    generators[1].generate(plan, tmp_path / "ansible")
    for config in (tmp_path / "ansible/files/nodes").glob("*/frr.conf"):
        text = config.read_text()
        assert "router ospf" not in text and "ip route " not in text
        if "router rip" in text:
            assert "version 2" in text and "no passive-interface wan0" in text
            assert "no passive-interface lan0" not in text


def test_configuration_commands_do_not_repair_absent_routes_or_start_disabled_services(
    plan, configure, monkeypatch
):
    nodes = {n["id"]: n for n in runtime_spec(plan)["nodes"]}
    node = nodes["R1"]
    node["routing"]["protocols"] = []
    calls = []
    monkeypatch.setattr(configure, "run", lambda *args: calls.append(args))
    configure.configure(node)
    assert not any(c[:2] == ("ip", "route") for c in calls)
    assert not any("frrinit.sh" in c[0] for c in calls)
    calls.clear()
    nodes["WEB1"]["services"][0]["enabled"] = False
    nodes["WEB1"]["interfaces"][0]["link_enabled"] = False
    configure.configure(nodes["WEB1"])
    assert not any(c[0] == "nginx" for c in calls)
    assert ("ip", "link", "set", "eth0", "down") in calls
    assert ("ip", "link", "set", "eth0", "up") not in calls


def test_static_route_commands_keep_exact_next_hop_interface_and_metric(
    plan, configure, monkeypatch
):
    node = next(n for n in runtime_spec(plan)["nodes"] if n["id"] == "R1")
    node["routing"]["protocols"] = []
    node["routing"]["static_routes"] = [
        {"destination": "10.20.20.0/24", "via": "10.255.0.2", "interface": "wan0", "metric": 17}
    ]
    calls = []
    monkeypatch.setattr(configure, "run", lambda *args: calls.append(args))
    configure.configure(node)
    routes = [c for c in calls if c[:2] == ("ip", "route")]
    assert routes == [
        (
            "ip",
            "route",
            "add",
            "10.20.20.0/24",
            "via",
            "10.255.0.2",
            "dev",
            "wan0",
            "proto",
            "static",
            "metric",
            "17",
        )
    ]


class FakeWorker:
    def __init__(self, lab_name):
        self.lab_name = lab_name
        self.containers = {}
        self.calls = []
        self.next_pid = 1000
        self.fail_configure = False

    def command(self, *args, check=True):
        self.calls.append(args)
        out, code = "", 0
        if args[:2] == ("docker", "inspect"):
            value = self.containers.get(args[2])
            out, code = (json.dumps([value]), 0) if value else ("", 1)
        elif args[:3] == ("docker", "image", "inspect"):
            out = "[{}]"
        elif args[:2] == ("docker", "run"):
            name = args[args.index("--name") + 1]
            self.next_pid += 1
            self.containers[name] = {
                "Config": {"Labels": {"net2cloud.lab": self.lab_name}},
                "State": {"Pid": self.next_pid, "Running": True},
            }
        elif args[:3] == ("docker", "ps", "-aq"):
            out = "\n".join(
                name
                for name, c in self.containers.items()
                if c["Config"]["Labels"].get("net2cloud.lab") == self.lab_name
            )
        elif args[:3] == ("docker", "rm", "-f"):
            self.containers.pop(args[3])
        elif args[:4] == ("ip", "-j", "link", "show"):
            out = "[]"
        elif args[:2] == ("docker", "exec") and self.fail_configure:
            raise subprocess.CalledProcessError(1, args, stderr="configuration failure")
        return subprocess.CompletedProcess(args, code, stdout=out, stderr="")


def test_runtime_realizes_exact_links_and_reuses_unchanged_lab(
    plan, runtime, tmp_path, monkeypatch
):
    spec = runtime_spec(plan)
    worker = FakeWorker(spec["lab_name"])
    monkeypatch.setattr(runtime, "command", worker.command)
    state = tmp_path / "state.json"
    assert runtime.apply(tmp_path, spec, "revision", state) is True
    runs = [c for c in worker.calls if c[:2] == ("docker", "run")]
    assert len(runs) == len(spec["nodes"])
    assert all(c[c.index("--network") + 1] == "none" and "-p" not in c for c in runs)
    cables = [c for c in worker.calls if c[:3] == ("ip", "link", "add")]
    assert len(cables) == len(spec["edges"])
    assert all("veth" in c for c in cables)
    renames = [c for c in worker.calls if c[0] == "nsenter"]
    assert len(renames) == 2 * len(spec["edges"])
    calls_before = len(worker.calls)
    assert runtime.apply(tmp_path, spec, "revision", state) is False
    assert all(c[:2] == ("docker", "inspect") for c in worker.calls[calls_before:])


def test_runtime_rolls_back_owned_containers_on_failure(plan, runtime, tmp_path, monkeypatch):
    spec = runtime_spec(plan)
    worker = FakeWorker(spec["lab_name"])
    foreign = {
        "Config": {"Labels": {"net2cloud.lab": "other"}},
        "State": {"Pid": 42, "Running": True},
    }
    worker.containers["other-container"] = foreign
    worker.fail_configure = True
    monkeypatch.setattr(runtime, "command", worker.command)
    state = tmp_path / "state.json"
    with pytest.raises(subprocess.CalledProcessError):
        runtime.apply(tmp_path, spec, "revision", state)
    assert worker.containers == {"other-container": foreign}
    assert not state.exists()


def test_existing_unowned_container_is_not_replaced(plan, runtime, tmp_path, monkeypatch):
    spec = runtime_spec(plan)
    worker = FakeWorker(spec["lab_name"])
    worker.containers[spec["nodes"][0]["runtime_name"]] = {
        "Config": {"Labels": {}},
        "State": {"Pid": 42, "Running": True},
    }
    monkeypatch.setattr(runtime, "command", worker.command)
    with pytest.raises(ValueError, match="owned outside"):
        runtime.apply(tmp_path, spec, "revision", tmp_path / "state.json")
    assert not any(c[:2] in [("docker", "run"), ("docker", "rm")] for c in worker.calls)


@pytest.mark.parametrize("folder", ["Generator terraform", "Generator ansible"])
def test_generator_cli_works_outside_repo_without_live_services(tmp_path, folder):
    out = tmp_path / "output"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / folder / "generator.py"),
            "--input",
            str(ROOT / "examples/generator_plan.json"),
            "--output",
            str(out),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"generated": str(out), "deployed": False}
