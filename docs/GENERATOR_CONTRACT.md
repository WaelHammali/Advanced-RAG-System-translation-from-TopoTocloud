# Concrete educational generator contract

Profile: `aws_single_host_docker_v1`. Both generators consume the same **RAG plan**,
not raw topology JSON. The Python generator validates its supported contract and
never uses an LLM. This downstream capability check is separate from the RAG's
new input-readiness gate; a ready topology is not necessarily supported here.

The reviewed [example plan](../examples/generator_plan.json) is a hand-authored
fixture, not a live model result. Its [input architecture](../examples/generator_architecture.json)
opts in through `generation.profile`. The original generic RAG contract remains
available; a generic free-form plan is deliberately rejected by these generators.

## Required plan sections

- `architecture`: complete components, interface-level edges, configuration and
  optional `ansible.tasks`, in the supported subset below.
- `cloud_plan.backend`: `aws_single_host_docker_v1`.
- `cloud_plan.translation_mode`: `behavioral_lab`.
- `cloud_plan.settings`: `lab_name`, `region`, `instance_type`, `root_volume_gib`.
  Educational defaults are `learnlab`, source region (otherwise `us-east-1`),
  `t4g.nano`, and `8` GiB. Only the ARM T4g family is accepted in this backend.
- `cloud_plan.component_mapping`: exactly one entry per source component, with
  matching `component_id`/`role`, `cloud_representation: "docker_container"`,
  `configuration: {"worker_id": "lab_worker"}`, and optional rule citations.
- `cloud_plan.networking`: exactly
  `{"source": "architecture", "realization": "veth_and_linux_bridge"}`.
  This explicit reference is the decision to realize the original graph, addresses
  and routing directly. No loosely described alternative networking is ignored.
- `ansible_plan.targets`: exactly one per component with its `component_id`,
  `connection: {"type": "docker_exec", "worker_id": "lab_worker"}` and `variables: {}`.
- `ansible_plan.tasks`: one `lab.configure_component` task per component, with a
  unique ID, singleton `target_ids`, and
  `parameters: {"source_component_id": "EXACT_ID"}`. This requests that component's
  interfaces, switching, routing and services from the source object. Add source
  package tasks unchanged; rule citations may be attached.
- Both `dependencies` lists and `limitations` must be empty before generation.
  Dependencies between supported component tasks may reference earlier task IDs;
  the task order is checked. Package installation occurs before runtime creation
  and therefore accepts no runtime task dependencies.

The source architecture and typed references are authoritative. The RAG must not
remove unsupported source features to obtain acceptance; it should retain them and
report limitations, after which the generators refuse to publish artifacts.

## Supported source subset

| Feature | Implemented subset |
| --- | --- |
| Components | `pc`, `server`, `router`, `switch`; Debian 12 userspace |
| Interfaces | Explicit Linux-safe names, optional IPv4 CIDR, enabled state |
| Edges | Named point-to-point cables; each interface appears exactly once; disabled cables retained |
| Switching | Access VLANs 1-4094; one isolated Linux bridge per switch; STP disabled |
| Hosts | Explicit interface/default gateway |
| Static routes | Destination, next hop, explicit interface, optional kernel metric |
| OSPF | v2; router ID, per-interface area, broadcast/point-to-point, cost, passive state |
| RIP | v2; per-interface participation and passive state |
| Services | At most one nginx HTTP service per node; listener, port, document root, text content, enabled state |
| Custom Ansible | `ansible.builtin.package`, package-name list, `state: present`, explicit targets |

An explicitly incompatible OSPF area, disabled protocol, or absent return route is
preserved; it is not repaired. An OS-rejected address/route can fail runtime setup,
which is distinct from a successfully configured lab with an expected ping failure.
Bridge loops are not protected by STP in this backend; use loop-free switching labs.
There is no implicit DHCP, NAT, redistribution, IPv6, public HTTP or cross-worker
transport. Source management connection definitions are unsupported: this profile
explicitly chooses worker SSH plus container execution, as described in the plan.
Unknown behavior-bearing fields and unsupported operations are rejected.

## Generate and deploy in separate steps

```bash
python app.py plan --input examples/generator_architecture.json --output generated/arch.json
python 'Generator terraform/generator.py' --input generated/arch.json --output generated/terraform
python 'Generator ansible/generator.py' --input generated/arch.json --output generated/ansible
```

For an offline example, replace `generated/arch.json` with
`examples/generator_plan.json`. Generation writes files only. Each output directory
must be new, preventing accidental overwriting of Terraform state or edited files.
Generated projects include their input plan and a hash for matching the two outputs.
Follow their READMEs to initialize, inspect and explicitly apply Terraform, export
`ansible_inventory`, and run Ansible with your private SSH key.

## Cost assumptions and references

One shared worker avoids one EC2 instance/public IPv4 per source node. The default
T4g nano is a small educational starting point, not a universal cheapest-price or
capacity guarantee. Small memory and Standard credits constrain installation and
lab size; change `instance_type` without changing the topology. Public IPv4,
storage and transfer have additional charges. Trial eligibility is not assumed;
Spot pricing and availability vary and interruption is possible.

- [AWS T4g specifications](https://aws.amazon.com/ec2/instance-types/t4/)
- [AWS Standard CPU credit behavior](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-performance-instances-standard-mode-concepts.html)
- [AWS public IPv4 pricing](https://aws.amazon.com/vpc/pricing/)
- [Canonical Ubuntu AMI lookup](https://documentation.ubuntu.com/aws/aws-how-to/instances/build-cloudformation-templates/)
- [FRR daemon setup](https://docs.frrouting.org/en/latest/setup.html)

Artifact tests establish generation behavior, not successful AWS deployment or
network equivalence for every topology. This backend needs real worker integration
and positive/negative routing tests before stronger operational claims.
