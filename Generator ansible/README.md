# Ansible generator

A deterministic Python generator for the same `aws_single_host_docker_v1` plan as
the Terraform generator. It builds a standalone Ansible project containing a
playbook, per-device Docker build contexts, FRR/nginx configuration, a labelled
runtime manager and a systemd unit for reboot persistence.

```bash
python -m pip install -r 'Generator ansible/requirements.txt'
python 'Generator ansible/generator.py' --input examples/generator_plan.json --output generated/ansible
```

Generation never connects to a worker, runs Docker, or calls an LLM. Unsupported
operations fail before an output directory is published. Existing output projects
are not overwritten. See [the contract](../docs/GENERATOR_CONTRACT.md) and
[generated-project instructions](PROJECT_README.md).

Supported: explicit IPv4 cables, access-VLAN switches, host gateways, static
routes, FRR OSPFv2/RIPv2, nginx HTTP and explicit Debian package-install tasks.
Routing and services share the source device's isolated network stack. No source
container receives Docker's default bridge, a management NIC or a published port.
Package installation happens while building images, before the lab is isolated.

Trunks, IPv6, ACL/firewall devices, TLS, redistribution, arbitrary Ansible modules,
vendor OS images and multiple workers need explicit extensions. The generator
rejects these requests rather than approximating their behavior.
