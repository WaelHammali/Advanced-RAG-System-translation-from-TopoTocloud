# Topology input and versioned AWS plan output

The fixed input remains `devices` and `links`. The RAG plans the initial topology;
OSPF/RIP, gateways, packages and services belong to the later external NLP and
Ansible stage. Their absence never blocks readiness. No agent or generator runs
inside this application.

## Input

| Field | Contract |
| --- | --- |
| `devices` | Nonempty list of objects with unique `id`, display `name`, `type`, and `network`. |
| `devices[].network` | `ip_address`, integer `prefix_length`, matching `subnet_mask`, canonical `network_address`. Switch/bridge/hub fields may all be null. |
| `links` | Nonempty list with unique `id`, `source` and `target` device IDs, and `network`. |
| `links[].network` | Canonical `network_address`, `prefix_length`, `subnet_mask`, and `source_ip`/`target_ip` inside that network; only L2 endpoints may omit their IP. |

A main device IP must appear on one of its links. Each PC has exactly one link;
routers/server/switches may have several. Names need not be unique: use IDs for
all references. See [validation and correction tuples](validation.md).

The schema contains no protocol configuration or named interfaces. Per-link
runtime interface IDs are assigned deterministically, without changing source
IDs. When an endpoint IP equals the device's main IP, its device prefix is used;
other addresses use the link prefix. This preserves /32 host exercises instead of
silently widening their masks. Independently configured masks on other interfaces
are outside the present input format.

Unknown extensions remain attached to the original source and receive explicit
limitations. They never select a different translation mode or configure software.

## Output contract 1.0

The model returns `cloud_plan`, nonempty retrieved `rule_ids`, and `limitations`.
The application attaches the unchanged `architecture` and `knowledge` provenance,
and mandatory warnings/dependencies that the model cannot suppress.

`cloud_plan` has the following enforced fields:

| Field | Purpose |
| --- | --- |
| `contract_version`, `provider`, `translation_mode` | `1.0`, `aws`, `behavioral_lab`. |
| `hosting` | Deterministic [educational profile](hosting.md), instance, capacity reservation, price provenance and cap. |
| `resources` | One VPC, subnet, worker security group and EC2 worker with stable IDs and consistent references. |
| `device_mapping` | Every source device's exact ID/name/type/network and its isolated namespace or bridge. |
| `networking.links` | Every source cable, exact network fields, endpoint device/runtime references and deterministic veth interface IDs. |
| `networking.isolation` | No worker forwarding, management shortcuts, automatic masquerading or proxy ARP between lab segments. |
| `configuration_targets` | Every device mapped to its worker, runtime, interface IDs and symbolic management endpoint for later configuration. |
| `initial_configuration` | Connected routes from supplied addresses, router forwarding, no host forwarding, no STP, empty added routes/gateways/protocols/services. |
| `dependencies` | Required runtime/bootstrap, image, transport, management and cost checks. |
| `verification_status` | Always `not_run`. |

[The complete example](../examples/aws_plan.json) is hand-authored from deterministic
requirements, not a live model result. Terraform generation and runtime bootstrap
must consume this version explicitly. Instantiating EC2 alone does not realize
namespaces, bridges or cables: external runtime setup is a required step before
later Ansible configuration.

The current profile has one supported realization. The model receives its exact
requirements and may assess/cite additional limitations, but cannot choose a
different graph, instance, IP, configuration target, initial route or extra AWS
resource. Python recursively checks fields, types, list coverage/order and values
against requirements independently derived from the input. Missing devices,
rewired links, changed addresses, unknown references and invented routing fail.
There is no silent repair or fallback plan on model failure.

This checks structural conformance, not live network equivalence. Linux software
runtimes do not claim exact vendor behavior. Unsupported runtime types/capacity
fail before the model. Switch cycles are preserved with a mandatory loop-control
limitation; do not deploy them assuming STP. Source warnings and uninterpreted
extensions remain visible in the output limitations.

## Deployment dependencies

Transport CIDRs, a suitable x86-64 Linux AMI and management/bootstrap access are
symbolic deployment inputs. The initial private worker has no ingress or egress
permissions. A downstream system must resolve access and package delivery without
creating a hidden path between lab nodes. It must verify AWS CIDRs, instance
availability, image/root-volume compatibility and total cost before provisioning.

Later configuration uses `device_id` and `configuration_targets`; display names
alone are ambiguous. This repository does not define an NLP operation catalog or
implement the agent, Terraform renderer or Ansible renderer.

## Failure and migration behavior

Malformed, duplicate-key, non-finite, empty, truncated, uncited or nonconforming
model output fails without replacing an existing output file. Provider failures
are not retried or replaced by another model. Input and output paths must differ.

This is a stricter output contract: previous envelope-only outputs and former
`component_mapping`/`ansible_plan`/`terraform_plan` formats are rejected. Input
migration from `components`/`edges` remains caller-owned. JSON source values are
never reconstructed from the model's answer.
