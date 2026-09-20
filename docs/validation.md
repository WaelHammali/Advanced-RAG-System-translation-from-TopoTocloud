# Architecture readiness before translation

`net2cloud/readiness.py` checks the source architecture before retrieval, model creation or
translation. It never modifies the JSON, fills missing values or calls an LLM.
It validates known routing/service/automation field shapes as well as the graph.
See the [architecture boundary study](edge-cases.md) for the case matrix.

```bash
python app.py check --input examples/architecture.json
```

Ready input returns `{"ready": true, "status": "ready", "errors": []}`. Incomplete
input returns a report such as:

```json
{
  "ready": false,
  "status": "not_ready",
  "errors": [
    {
      "code": "missing_ip_address",
      "path": "/components/0/interfaces/0/ipv4",
      "message": "Provide an IPv4 address with its prefix, for example 10.0.0.10/24."
    }
  ]
}
```

All detected issues are returned together, with JSON Pointer paths. The calling
application can show them to the user, complete the JSON and resubmit it.

## Required information

- Nonempty `components` and `edges` lists of objects.
- Every component has a unique, nonempty `id` and a nonempty `type`. `id` is its
  canonical name/reference, such as PC1 or R1. An optional display `name` must be
  nonempty when present; the app does not invent one or rename components.
- Every component has interfaces with IDs unique within that component.
- Every non-L2 interface has an `ipv4` address and explicit prefix, such as
  `10.10.10.10/24`. This applies to router, PC and server interfaces, including
  explicitly disabled interfaces. Switch/bridge/hub ports need no IP; an optional
  supplied address is still checked for IPv4 syntax and prefix.
- Every edge has a unique ID, and each endpoint names an existing component and
  interface. One cable per interface; use switch ports for multi-device LANs.
- Every component has at least one valid edge to a different component. A
  self-loop does not satisfy this requirement. A typo or dangling edge does not
  make an isolated component ready.
- Interface/edge `enabled`, when supplied, is a Boolean.
- Optional `access_vlan` values are integers 1–4094. An omitted switch IP is valid;
  an explicitly supplied null address is not.
- Supplied routing, services and automation sections must have their documented
  object/list shapes. Known Boolean and numeric fields are checked without coercion.
- Gateway/static-route and RIP/OSPF interface references must exist on that device.
  Static destinations use canonical network prefixes (no host bits). OSPF requires
  a router ID, interface list and area on each listed interface; RIP requires a
  version and interface list. Empty interface lists represent no participation.
- Supplied service listeners require an integer port 1–65535 and a valid IPv4
  address when an address is supplied. Services require a nonempty protocol name.
- Automation tasks have unique IDs, named operations, object parameters, existing
  target IDs and acyclic dependencies on existing task IDs. Forward references
  are allowed. Connection target IDs are checked too.
- If present, `schema_version` is `"1.0"` and `translation_mode` is `behavioral_lab`
  or `cloud_native`. Known metadata fields must have the documented types.
- All values must be JSON-compatible, with finite numbers, string object keys,
  no reference cycles and at most 64 levels of nesting. JSON Pointer errors escape
  `/` and `~` in extension keys.

## Completeness is different from working connectivity

An explicit disabled cable still connects the objects structurally, so it is
retained as a failure exercise. Empty static-route lists, disabled protocols,
OSPF mismatches and absent optional gateways are not automatically repaired or
rejected by this check. Two same-LAN hosts do not need a gateway.
Disabled sections must still be well-formed. Single-device architectures are
rejected under the explicit no-isolated-components policy; two directly cabled
PCs are accepted without a router or switch.

Separate connected groups are permitted as long as no individual component is
alone. The gate does not require all components to reach each other. It does not
check address uniqueness within VLANs, route feasibility, protocol convergence,
service readiness, implementation support or cloud limits. Additional unused but
addressed interfaces are permitted by this input gate; external tools may impose
their own implementation requirements. Unknown protocol names and custom extension
fields are preserved; their specific semantics are not declared valid by this gate.
Interface address checking remains syntactic: special-address semantics and
same-segment address conflicts are not checked. Switch cycles require explicit
loop-control requirements in the plan; this translator does not implement STP.

These limits are deliberate: passing readiness means the requested identity,
addressing and link prerequisites are complete. It does not mean ping will pass
or every feature has an implementation.

## Issue list

`net2cloud.issues.list_issues(architecture)` returns every readiness problem as a
`(component, other, message)` tuple, for a person or an assistant to act on. `other`
is `""` when one component is concerned; it names the second component for a shared
name or a shared IP address. Problems belonging to no component have an empty
component. Same-address clashes are reported for enabled interfaces in one connected
group only and never block translation, so the list can be non-empty while the file
is ready. It does not change the architecture or the `check` report.

## API and CLI behavior

`net2cloud.plan_architecture()` and `net2cloud.planner.plan_with_rag()` both enforce the gate.
`ArchitectureNotReady` exposes its machine-readable `report`. The application
checks before constructing retrieval; the planner also checks direct calls before
constructing a provider client. There is no bypass flag.

`plan` and `context` exit with status 2 and write the report to stderr if input is
not ready. No new plan/context output file is published; an existing file is left
untouched. Do not consume an old plan after a failed command.

`check` writes the report to stdout (and optional `--output`), exits 0 for ready or
2 for not ready, and requires no model dependencies. Malformed JSON and unrelated
runtime errors use exit 1. Discussion and correction remain in the calling app.

## AWS-only boundary

`cloud.provider` may be omitted (AWS is the target), or explicitly set to `aws`.
Other providers are rejected before retrieval. Generator-specific `generation`
settings are rejected; they have no meaning in an AWS JSON-only translator.
The old `ansible` input section is rejected with a migration error: use the
provider-neutral `automation` section for declarative task/access requirements.
Unknown extension fields otherwise remain attached to the source.
