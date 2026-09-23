# Architecture readiness before translation

`net2cloud/readiness.py` checks the source topology before retrieval, model creation or
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
      "path": "/devices/0/network/ip_address",
      "message": "Provide an IPv4 address string."
    }
  ]
}
```

All detected issues are returned together, with JSON Pointer paths. The calling
application can show them to the user, complete the JSON and resubmit it.

## Required information

- Nonempty `devices` and `links` lists of objects.
- Every device has a unique, nonempty `id`, a nonempty `name` and a nonempty
  `type`, such as `pc`, `router`, `server` or `switch`.
- Every device has a `network` object with `ip_address`, `prefix_length`
  (0–32), `subnet_mask` and `network_address`. For any type other than
  `switch`/`bridge`/`hub`, all four must be present (not `null`) and
  mutually consistent: `subnet_mask` must be the canonical mask for
  `prefix_length`, and `network_address` must be the canonical network base
  of `ip_address`/`prefix_length`. A `switch`/`bridge`/`hub` may leave all
  four fields `null`; an explicitly supplied address on one is still checked
  the same way.
- A `pc` may have exactly one link; any other type may have any number of links.
- Every link has a unique, nonempty `id`, and `source`/`target` naming existing
  device `id`s (not display names). A link cannot connect a device to itself.
- Every link has its own `network` object with `network_address`,
  `prefix_length` and `subnet_mask`, always required and internally
  consistent the same way as a device's.
- Every link's `network` also has `source_ip` and `target_ip`: the address
  each end uses on that link. Each is required unless that end is a
  switch/bridge/hub (then it may be `null`), must be a valid IPv4 address, and
  must lie inside the link's network. A router joining two subnets uses a
  different address on each link.
- A device's own `ip_address` must be the address it uses on at least one of
  its links (for a `pc`, its only link).
- Every device has at least one valid link to a different device. A
  self-loop does not satisfy this requirement. A typo or dangling reference
  does not make an isolated device ready.
- All values must be JSON-compatible, with finite numbers, string object keys,
  no reference cycles and at most 64 levels of nesting. JSON Pointer errors escape
  `/` and `~` in extension keys.

## Completeness is different from working connectivity

This gate is deliberately strict about the input's own consistency (an address
must match its own mask, and a link's network must match its own devices), but
it says nothing about whether devices can actually reach each other beyond one
link, or whether a plan built from this input is correct. Separate connected
groups are permitted as long as no individual device is alone; the gate does
not require all devices to reach each other. It does not check for duplicate
addresses across the whole topology (only within one connected group — see
below), route feasibility, service readiness, implementation support or cloud
limits.

One consequence of the per-link check: two devices in genuinely different
subnets, cabled directly with no router between them, are rejected. One cable
is one network, so one end's address falls outside the link's network.
Routers joining different subnets are fine: each of their links carries its
own network and per-end addresses (see
[router_chain_no_routes.json](../examples/edge_cases/router_chain_no_routes.json)).

These limits are deliberate: passing readiness means the requested identity,
addressing and link prerequisites are complete and self-consistent. It does
not mean ping will pass or every feature has an implementation.

## Issue list

`net2cloud.issues.list_issues(architecture)` returns every readiness problem as a
`(device, other, message)` tuple, for a person or an assistant to act on. `other`
is `""` when one device is concerned; it names the second device for a shared
ID or a shared IP address. Problems belonging to no device have an empty
device. Same-address clashes are reported for devices in one connected group
only and never block translation, so the list can be non-empty while the file
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

AWS is this application's only target provider; that is fixed by the planner
prompt and is not a field the input JSON carries. Unknown extension fields
otherwise remain attached to the source.
