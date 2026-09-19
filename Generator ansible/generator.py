"""Render an Ansible project for the explicit single-worker educational profile."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from configuration import BASE_DOCKERFILE, node_files  # noqa: E402

from generator_common import (  # noqa: E402
    load_plan,
    manifest,
    runtime_spec,
    validate_plan,
    write_bundle,
)
from json_io import dumps_json  # noqa: E402


def generate(plan: dict, output: Path) -> None:
    import yaml

    plan = validate_plan(plan)
    spec = runtime_spec(plan)
    name = spec["lab_name"]
    destination = f"/opt/net2cloud/{name}"
    runtime = f"{destination}/lab.py"
    service = f"net2cloud-{name}"
    restart = "Restart educational lab"
    play = [
        {
            "name": "Build the educational network on its management worker",
            "hosts": "lab_workers",
            "become": True,
            "gather_facts": False,
            "tasks": [
                {
                    "name": "Wait for worker SSH",
                    "ansible.builtin.wait_for_connection": {"timeout": 900},
                },
                {
                    "name": "Wait for cloud-init and swap setup",
                    "ansible.builtin.command": {"argv": ["cloud-init", "status", "--wait"]},
                    "changed_when": False,
                },
                {
                    "name": "Install worker tools",
                    "ansible.builtin.apt": {
                        "name": ["docker.io", "iproute2", "util-linux", "python3"],
                        "state": "present",
                        "update_cache": True,
                        "cache_valid_time": 3600,
                    },
                },
                {
                    "name": "Start Docker",
                    "ansible.builtin.systemd_service": {
                        "name": "docker",
                        "enabled": True,
                        "state": "started",
                    },
                },
                {
                    "name": "Create private lab project directory",
                    "ansible.builtin.file": {
                        "path": destination,
                        "state": "directory",
                        "mode": "0700",
                    },
                },
                {
                    "name": "Copy generated lab assets",
                    "ansible.builtin.copy": {
                        "src": "files/",
                        "dest": destination + "/",
                        "mode": "0600",
                        "directory_mode": "0700",
                    },
                    "notify": restart,
                },
                {
                    "name": "Build node images before isolating their networks",
                    "ansible.builtin.command": {
                        "argv": ["python3", runtime, "build", "--directory", destination]
                    },
                    "register": "lab_build",
                    "changed_when": "(lab_build.stdout | from_json).changed",
                    "notify": restart,
                },
                {
                    "name": "Install reboot persistence",
                    "ansible.builtin.copy": {
                        "src": f"{service}.service",
                        "dest": f"/etc/systemd/system/{service}.service",
                        "mode": "0644",
                    },
                    "notify": restart,
                },
                {"name": "Apply updated lab files", "ansible.builtin.meta": "flush_handlers"},
                {
                    "name": "Enable and start the lab",
                    "ansible.builtin.systemd_service": {
                        "name": service,
                        "enabled": True,
                        "daemon_reload": True,
                        "state": "started",
                    },
                },
            ],
            "handlers": [
                {
                    "name": restart,
                    "ansible.builtin.systemd_service": {
                        "name": service,
                        "daemon_reload": True,
                        "state": "restarted",
                    },
                }
            ],
        }
    ]
    files = {
        "site.yml": yaml.safe_dump(play, sort_keys=False, allow_unicode=True),
        "inventory.example.yml": yaml.safe_dump(
            {
                "all": {
                    "children": {
                        "lab_workers": {
                            "hosts": {
                                "lab_worker": {
                                    "ansible_host": "REPLACE_WITH_WORKER_IP",
                                    "ansible_user": "ubuntu",
                                }
                            }
                        }
                    }
                }
            },
            sort_keys=False,
        ),
        "files/lab.json": dumps_json(spec, indent=2) + "\n",
        "files/lab.py": (Path(__file__).parent / "runtime/lab.py").read_text(encoding="utf-8"),
        "files/base/Dockerfile": BASE_DOCKERFILE,
        f"{service}.service": f"""[Unit]
Description=Educational network {name}
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/python3 {runtime} apply --directory {destination}
ExecStop=/usr/bin/python3 {runtime} destroy --directory {destination}
TimeoutStartSec=900
TimeoutStopSec=120

[Install]
WantedBy=multi-user.target
""",
        "arch.json": dumps_json(plan, indent=2) + "\n",
        "manifest.json": manifest(plan, "ansible"),
        "README.md": (Path(__file__).parent / "PROJECT_README.md").read_text(encoding="utf-8"),
        "requirements.txt": "ansible-core>=2.17,<2.20\n",
    }
    for node in spec["nodes"]:
        for filename, content in node_files(node).items():
            files[f"files/nodes/{node['runtime_name']}/{filename}"] = content
    write_bundle(output, files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Concrete RAG arch.json plan")
    parser.add_argument("--output", type=Path, required=True, help="New output directory")
    args = parser.parse_args(argv)
    try:
        generate(load_plan(args.input), args.output)
        print(dumps_json({"generated": str(args.output), "deployed": False}))
        return 0
    except (ValueError, OSError, KeyError, TypeError, ImportError) as error:
        print(dumps_json({"error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
