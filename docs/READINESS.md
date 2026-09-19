# Architecture readiness before translation

`readiness.py` checks the source architecture before retrieval, model creation or
translation. It never modifies the JSON, fills missing values or calls an LLM.

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

## Completeness is different from working connectivity

An explicit disabled cable still connects the objects structurally, so it is
retained as a failure exercise. Empty static-route lists, disabled protocols,
OSPF mismatches and absent optional gateways are not automatically repaired or
rejected by this check. Two same-LAN hosts do not need a gateway.

Separate connected groups are permitted as long as no individual component is
alone. The gate does not require all components to reach each other. It does not
check address uniqueness within VLANs, route feasibility, protocol convergence,
service readiness, generator support or cloud limits. Additional unused but
addressed interfaces are permitted by this input gate; a generator may impose
stricter interface/link requirements.

These limits are deliberate: passing readiness means the requested identity,
addressing and link prerequisites are complete. It does not mean ping will pass
or a generator can deploy every feature.

## API and CLI behavior

`app.plan_architecture()` and `planner.plan_with_rag()` both enforce the gate.
`ArchitectureNotReady` exposes its machine-readable `report`. The application
checks before constructing retrieval; the planner also checks direct calls before
constructing a provider client. There is no bypass flag.

`plan` and `context` exit with status 2 and write the report to stderr if input is
not ready. No new plan/context output file is published; an existing file is left
untouched. Do not consume an old plan after a failed command.

`check` writes the report to stdout (and optional `--output`), exits 0 for ready or
2 for not ready, and requires no model dependencies. Malformed JSON and unrelated
runtime errors use exit 1. Discussion and correction remain in the calling app.
