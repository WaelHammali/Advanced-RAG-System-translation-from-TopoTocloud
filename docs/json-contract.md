# Architecture input and AWS JSON output

The caller owns discussion and supplies a prepared JSON object. This application
checks readiness, retrieves knowledge and returns a proposed AWS architecture.
[examples/architecture.json](../examples/architecture.json) shows a mixed network
with PCs, switches, two OSPF routers, an HTTP server and a declarative package task.

## Input

| Field | Meaning |
| --- | --- |
| `schema_version` | Optional string `1.0`; other versions are rejected. |
| `translation_mode` | `behavioral_lab` (default) or `cloud_native`; both target AWS. |
| `cloud` | Optional object; supplied `provider` must be `aws`; `region` is optional. |
| `components` | Nonempty device list with unique canonical `id`, type and interfaces. |
| `components[].name` | Optional nonempty display name; IDs remain authoritative. |
| `components[].interfaces` | Interface ID, IPv4/prefix, enabled state and optional VLAN settings. |
| `components[].routing` | Forwarding, default gateway, static routes, routing protocols. |
| `components[].services` | Protocol, implementation, enabled state, listener and service settings. |
| `edges` | Named cables with exact source and target component/interface references. |
| `automation.connections` | Optional declarative target access settings and symbolic secret references. |
| `automation.tasks` | ID, target IDs, operation, object parameters and dependency IDs. |

See [validation](validation.md) for required types, references and rejection rules.
Empty lists, disabled settings and omitted configuration are distinct. Do not
substitute a routing protocol when the source contains no remote routes. Unknown
extension values remain attached to the source and must be described as unresolved
if their implementation is not understood.

Automation operations are declarative names, such as `package.install`; the RAG
neither resolves modules nor executes them. HTTP remains a service on its source
server; OSPF and RIP remain routing configuration on their source devices.

## Output

The model returns these three top-level sections:

```json
{
  "cloud_plan": {
    "provider": "aws",
    "translation_mode": "behavioral_lab",
    "resources": [],
    "component_mapping": [],
    "networking": {"links": [], "addressing": [], "routing": [], "security": []},
    "configuration": {"targets": [], "tasks": [], "services": []},
    "dependencies": []
  },
  "rule_ids": [],
  "limitations": []
}
```

The empty arrays show shape, not a complete plan. The application then attaches:

- `architecture`: a deep copy of the original input, never reconstructed by the model.
- `knowledge`: selected rule IDs, source paths and headings for provenance.

AWS resources use stable symbolic IDs and types. Component mappings refer to exact
source IDs and proposed resource IDs. The original network graph and AWS hosting
relationships are distinct: hosting two devices together does not connect their
lab interfaces. Configuration requirements stay under `cloud_plan.configuration`.
Unresolved capacities, mappings, runtime capabilities or source semantics belong
in `limitations` and dependencies. No deployment status or observed ping is implied.

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

## Migration from the former combined project

There is no `ansible_plan`, `terraform_plan` or generated-files section. Move source
`ansible` settings to the declarative `automation` section and remove `generation`
profiles. These old input fields are rejected with explicit migration errors.
External tools may consume the AWS JSON later; no generator contract is maintained
inside this translation repository. Historical code remains in Git history.
