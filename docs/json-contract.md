# Topology input and AWS JSON output

The caller owns discussion and supplies a prepared JSON object. This application
checks readiness, retrieves knowledge and returns a proposed AWS architecture.
[examples/architecture.json](../examples/architecture.json) shows a small LAN
with PCs, a switch, a router and a server.

## Input

The input has exactly two top-level lists: `devices` and `links`. There is no
routing, service or automation configuration, no VLANs and no NAT/DHCP — the
upstream vision pipeline that produces this JSON cannot detect any of that from
a topology diagram, so the contract does not carry it.

| Field | Meaning |
| --- | --- |
| `devices` | Nonempty list; each device has a unique `id`, a nonempty `name`, a nonempty `type` (such as `pc`, `router`, `server` or `switch`) and a `network` object. |
| `devices[].network` | `ip_address`, `prefix_length` (0–32), `subnet_mask` and `network_address`. All four must be present and mutually consistent for every device except `switch`/`bridge`/`hub`, which may leave all four `null`. |
| `links` | Nonempty list; each link has a unique `id`, a `source` and `target` (existing device `id`s, not names) and its own `network` object. |
| `links[].network` | `network_address`, `prefix_length`, `subnet_mask`, plus `source_ip` and `target_ip`: the address each end uses on this link. The three network fields are always required and internally consistent; each endpoint IP is required (except at a switch/bridge/hub end, which may be `null`) and must lie inside the link's network. |

A device has no named ports or interfaces. Its own `network` object holds its
main address; the address it uses on each link is that link's `source_ip` or
`target_ip`. A router joining two subnets therefore has a different address on
each link, and its own `ip_address` must be one of them. A `pc` may have
exactly one link; every other type may have any number.

```json
{"id": "link_2", "source": "device_2", "target": "device_3",
 "network": {"network_address": "10.0.12.0", "prefix_length": 30,
             "subnet_mask": "255.255.255.252",
             "source_ip": "10.0.12.1", "target_ip": "10.0.12.2"}}
```

See [validation](validation.md) for the exact required fields and rejection rules.
Unknown extension fields are preserved unchanged; passing readiness does not
imply their schema is recognized or implemented.

## Output

The model returns these three top-level sections:

```json
{
  "cloud_plan": {
    "provider": "aws",
    "resources": [],
    "device_mapping": [],
    "networking": {"links": [], "addressing": [], "security": []},
    "dependencies": []
  },
  "rule_ids": [],
  "limitations": []
}
```

The empty arrays show shape, not a complete plan. The application then attaches:

- `architecture`: a deep copy of the original input, never reconstructed by the model.
- `knowledge`: selected rule IDs, source paths and headings for provenance.

AWS resources use stable symbolic IDs and types. Device mappings refer to exact
source device IDs and proposed resource IDs. The original network graph and AWS
hosting relationships are distinct: hosting two devices together does not
connect their lab links. Unresolved capacities, mappings, runtime capabilities
or source semantics belong in `limitations` and dependencies. No deployment
status or observed ping is implied.

[examples/aws_plan.json](../examples/aws_plan.json) is a hand-authored illustration
for the directly connected PC input, not live Groq output or a deployable template.

## Enforced response boundary

The parser requires a `cloud_plan` object whose provider is `aws`, and `rule_ids`
and `limitations` lists containing only nonempty strings. Rule IDs must be unique
and belong to the retrieved context supplied to the model. Unexpected top-level
fields are rejected. Model-authored
source architecture and knowledge are discarded in favor of the authoritative
application values. Nested plan contents remain model-produced intentions; strict
JSON Schema enforcement and full semantic output validation are not implemented.

Malformed, duplicate-key, non-finite, empty or truncated JSON fails. On failure no
new plan is published and an existing output file remains unchanged. Input and
output paths cannot be the same. See the CLI exit statuses in the root README.

## Migration from the former combined-configuration contract

There is no `components`/`edges`/`interfaces` layout, and no `routing`, `services`,
`automation`, `os`, `cloud` or `schema_version` sections. A device's main address lives
on its `network` object, per-link addresses live on each link's `source_ip`/`target_ip`,
and per-link identity comes from the link's own `id`, not from a named interface. These old input fields have no equivalent in
this contract; a caller migrating from the former layout must convert to
`devices`/`links` before calling this application. Historical code remains in
Git history.
