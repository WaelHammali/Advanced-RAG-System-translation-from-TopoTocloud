# Architecture input and plan output

The caller supplies a JSON object and owns the conversation. The application now
enforces [readiness prerequisites](READINESS.md) before translation: component
identities, interfaces, usable link references and provided IPv4 addresses/prefixes.
Known routing/service/Ansible shapes, scalar types and references are also checked.
Protocol convergence, packet reachability and generator capability checks remain separate.
See the complete [example](../examples/architecture.json).

JSON parsing rejects duplicate object keys, NaN/Infinity and numbers exceeding
the supported finite floating-point range. These are data-format checks, not
checks of addresses, routes or other architecture fields. File output is atomic;
the CLI does not allow the input architecture path as its output path.

## Architecture input

| Field | Meaning |
| --- | --- |
| `schema_version` | Caller contract version; the example uses `1.0`. |
| `translation_mode` | `behavioral_lab` preserves network forwarding behavior; `cloud_native` requests cloud equivalents. Planning defaults to `behavioral_lab`. |
| `cloud` | Provider, region and any requested placement settings. Current knowledge focuses on AWS. |
| `generation` | Optional opt-in artifact profile; use `{"profile":"aws_single_host_docker_v1"}` for the educational generators. |
| `components` | Devices identified by required unique `id`, such as `PC1`, `EdgeWest` or `WEB1`; optional display `name` must be nonempty if supplied. |
| `components[].type` | Source role, such as `pc`, `switch`, `router`, `firewall` or `server`. |
| `components[].interfaces` | Interface `id`, IPv4 CIDR in `ipv4`, `enabled`, VLAN membership and other interface settings. |
| `components[].routing` | Forwarding state, `default_gateway`, `static_routes`, and `protocols` with their interface-specific configuration. |
| `components[].services` | Application protocol, implementation, enabled state, listener and service-specific settings. |
| `edges` | Exact links with `source` and `target`, each naming `component` and `interface`; includes link `id` and enabled state. |
| `ansible.connections` | Target IDs, connection settings and symbolic management/credential references. |
| `ansible.tasks` | Unique task ID, existing `target_ids`, named `operation`, object `parameters`, and acyclic `depends_on`. |

For static routing, an entry can specify `destination`, `via`, `interface` and
`metric`. For RIP, a protocol entry can specify `name: "rip"`, `enabled`,
`version: 2`, and participating interfaces with their passive settings. The
example shows explicit OSPF areas, router IDs and point-to-point/passive interfaces.
The deterministic gate checks these known fields before the model call; see
[readiness](READINESS.md). Syntactically complete settings that cause connectivity
failure, such as mismatched OSPF areas or absent return routes, remain unchanged.
Static destinations require canonical network prefixes, while interface addresses
carry the host address and prefix. The checker never silently normalizes either.

HTTP/HTTPS belong under the server's services; OSPF/RIP belong under routing.
The planner covers both in the same response. Explicit custom Ansible operations
remain bound to their supplied targets and parameters.

An empty list, `enabled: false`, an omitted setting and a populated configuration
carry different meanings. The RAG must not silently add routes, activate disabled
services or create public access. Unknown/custom fields remain in the attached
architecture, even if the model cannot map them; required unsupported operations
should be described in `limitations`.

A reference such as `deployment.management.WEB1` is a symbolic name for the
separate generator to resolve. It is not an interpolated value or a deployed IP.
Keep secrets as references. Connection to a worker and execution inside a source
component's isolated runtime must be distinguished in the plan.

## Plan output

```json
{
  "cloud_plan": {
    "translation_mode": "behavioral_lab",
    "component_mapping": [],
    "networking": {"links": [], "addressing": [], "routing": [], "security": []},
    "dependencies": []
  },
  "ansible_plan": {"targets": [], "tasks": [], "dependencies": []},
  "rule_ids": [],
  "limitations": [],
  "architecture": {},
  "knowledge": []
}
```

The empty containers above describe shape, not a completed example plan.
`cloud_plan.component_mapping` entries have `component_id`, `role`,
`cloud_representation`, `configuration` and `rule_ids`. Networking entries carry
source IDs, actual interface configuration and proposed runtime/transport mapping.
`ansible_plan.targets` entries have `component_id`, `connection` and `variables`.
Tasks have `id`, `target_ids`, `operation`, `parameters`, `depends_on` and `rule_ids`.
Dependencies state external resources or runtime capabilities required by the
separate generator. Tasks describe intentions; they contain no executable YAML.

The model produces `cloud_plan`, `ansible_plan`, `rule_ids` and `limitations`.
The application attaches `architecture` and `knowledge` deterministically,
overriding any model attempt to change those two fields. Knowledge entries contain
`rule_id`, `source` and `heading`; full retrieved text is available with `context`.

Local parsing requires a JSON object with `cloud_plan` and `ansible_plan` objects
and `rule_ids` and `limitations` lists. Unexpected top-level sections, such as
`questions` or `files`, are rejected. Model-supplied `architecture` and `knowledge`
are discarded in favor of the application's authoritative values. This is a
model-response envelope check, not validation of input fields or nested plan
semantics. Model omissions within sections, incorrect task parameters or
unsupported operations are still possible. The consuming generator owns acceptance checks; this
translation model does not return a validation report or silently replace failed output with a
hardcoded topology plan. Transport/API failures, invalid JSON and truncation
raise an error through the API and produce a nonzero CLI exit.

Before that model call, an incomplete architecture raises `ArchitectureNotReady`
with a structured report. The CLI returns exit 2 and no plan. This application
readiness response is separate from the successful plan envelope above.

## Executable educational profile

The generic nested shapes above are planning intentions. The new Python generators
require the more precise [generator contract](GENERATOR_CONTRACT.md), selected by
`generation.profile` in the source architecture. In that profile, `cloud_plan`
adds `backend` and `settings`, networking explicitly references the source graph,
and component configuration tasks reference exact source component IDs. Unsupported
features stay in the source and produce limitations; they must not be discarded to
make generation pass. See the [reviewed example](../examples/generator_plan.json).
