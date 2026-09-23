# Readiness and clarification

The input remains `devices` and `links`. Missing OSPF, RIP, gateways, services or
packages is **not** an error: the external NLP/configuration stage handles those
later. This application neither starts that agent nor executes configuration.

`check_readiness(architecture)` returns:

- `ready`, `status`: whether topology prerequisites pass.
- `revision`: SHA-256 of the canonical source JSON, or null for non-JSON input.
- `errors`: blocking findings with `code`, JSON Pointer `path`, and `message`.
- `issues`: matching `(entity_id, path, message)` tuples for clarification.
- `warnings`, `warning_issues`: advisory findings, explicitly separate from blockers.

Tuples become three-element arrays in JSON. IDs identify devices or links, never
display names; the path disambiguates duplicate or missing IDs. A finding outside
an existing entity uses an empty ID. `list_issues()` returns blocking tuples only.

```bash
python -m net2cloud check --input examples/architecture.json
```

## Blocking checks

Every device needs a unique ID, name, type and network object. Non-L2 devices need
IPv4, prefix (integer 0–32), matching subnet mask and canonical network address.
Switch/bridge/hub network fields may all be null. Every link needs a unique ID,
existing source and target IDs, a consistent network and each non-L2 endpoint's IP
inside that network. A device's main IP must occur on one of its links.

Every device must have a valid link to another device. A PC has exactly one link.
Separate connected groups are permitted. Duplicate IDs, self-links, unknown
endpoints, malformed objects, non-finite numbers, non-string JSON keys, cycles and
nesting above 64 levels are rejected. Parsing also rejects duplicate JSON keys.

These are the current input policies, not a claim that every real network fits
this format. For example, directly cabled hosts outside the declared link subnet
are rejected. Passing these checks does not prove reachability.

Same-IP endpoint conflicts on one L2 segment are **warnings**, allowing deliberate
negative labs. Switches/bridges/hubs join those segments; routers do not. These
warnings appear in the same report and must remain visible to callers. The gate
does not certify route convergence, protocol support, cloud capacity or ping.

## Applying explicit corrections

The external agent can return `(entity_id, path, replacement_value)` tuples. It
must supply the revision from the report it used. `apply_corrections()` operates
on a copy and returns `{architecture, validation}`. A stale revision, mismatched
ID/path, overlapping paths or an unsupported edit rejects the whole batch.

```python
from net2cloud import apply_corrections, check_readiness

report = check_readiness(source)
result = apply_corrections(
    source,
    [("device_1", "/devices/0/network/ip_address", "192.168.1.10")],
    expected_revision=report["revision"],
)
# Resubmit result["architecture"] only when result["validation"]["ready"] is true.
```

Corrections can replace device/link identity fields, network objects/fields, or
whole `/devices` and `/links` lists (empty entity ID). They cannot introduce
routing or execute arbitrary operations. Whole-list replacements are treated as
explicit graph replacements and fully revalidated without inferred rewiring.

Single-field corrections recompute redundant subnet mask/network base fields.
An explicitly supplied conflicting field is retained and reported. Main-IP edits
update matching link endpoint copies; a missing main IP on a single-linked device
can fill its endpoint copy. An endpoint-IP edit updates a matching main IP. A
unique device-ID rename updates existing link references. No peer IP, route, cable
or gateway is invented; ambiguous missing router addresses require explicit edits.

```bash
python -m net2cloud correct --input architecture.json \
  --corrections corrections.json --revision REVISION_FROM_CHECK \
  --output corrected.json
```

The output is an envelope containing corrected `architecture` and `validation`,
not a plan input by itself. `check`/`correct` exit 0 when ready or 2 when blocked.
`plan`/`context` fail before retrieval on incomplete input, writing the same report
to stderr and exiting 2. Runtime errors exit 1. Atomic writes preserve existing
files on failed commands; do not consume an old plan after a failure.
