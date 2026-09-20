# Architecture boundary study and JSON validation

Reviewed: 2026-09-20. Scope: the current IPv4 architecture contract and educational
AWS JSON planning boundary. This is a bounded engineering matrix, not a proof
for every possible architecture, operating system, protocol or vendor feature.

## Three different decisions

1. **Ready JSON:** names, addressing, links, known configuration shapes and
   references are complete. A deterministic check runs before retrieval or Groq.
2. **Implementation feasibility:** the plan describes required capabilities and limitations.
   No deployment backend is implemented in this repository.
3. **Network behavior:** packet delivery depends on the actual configuration and
   runtime. A ready, supported lab can intentionally fail to ping. The application
   does not currently compute or measure reachability.

A single PC is a legitimate standalone computing architecture. It is **not accepted
by this project's current network-lab policy**, because the requested policy says
no component may be alone. There is no hidden singleton exception. Supporting
standalone hosts later should be an explicit contract/profile decision, with no
invented cable or router. An attached PC may have a display name, but its unique
`id` is the required canonical name; a separate `name` field is optional.

## Topology matrix

The expected behavior below assumes ordinary IPv4 stacks, functioning interfaces,
no unmentioned filtering, and no unmentioned alternate paths. It is an engineering
prediction, not a result from live ping tests.

| Architecture / condition | Readiness | Behavior or implementation decision |
| --- | --- | --- |
| Empty object, no devices | Reject | Missing components and links. |
| One PC, server, router or switch, no links | Reject | Isolated component, even with a valid IP. |
| Two PCs without a cable | Reject | Both isolated. |
| PC connected to itself | Reject | Self-links do not satisfy the no-isolation policy. |
| Two PCs connected directly, distinct addresses in the same /24 | Accept | Local communication needs no router, gateway, RIP or OSPF. |
| Direct PCs in different /24 networks, no routes | Accept | Preserve the failure; a physical cable alone supplies no remote route. |
| Direct PCs on the two addresses of a /31 | Accept | Valid point-to-point addressing on supporting stacks. |
| Direct PCs with different /32 addresses, no peer routes | Accept | A host address alone does not establish the peer's on-link route. |
| PC and router only | Accept | Direct peer reachability can work; this says nothing about other destinations. |
| PC and switch only | Accept | Complete two-node topology; an unaddressed switch is not a remote IP endpoint. |
| Same switch, same VLAN and compatible subnet | Accept | The hosts can communicate locally without routing. |
| Same switch, different VLANs, no routing | Accept | Preserve VLAN isolation. |
| Same switch and VLAN, different subnets, no routes | Accept | Do not invent gateways to make ping work. |
| Multiple switches in an acyclic path | Accept | Preserve every switch and cable; one subnet per switch is not required. |
| Active switch cycle / redundant same-VLAN links | Accept | Plan must describe loop-control requirements or limitations; no runtime is built here. |
| Switch cycle broken by a disabled port/cable | Accept | Disabled state is preserved; it can interrupt the active cycle. |
| Switch cycle interrupted by access-VLAN separation | Accept | Reason about L2 domains per switch VLAN, not just device counts. |
| Two separate connected groups | Accept | Each group stays isolated; the graph need not be globally connected. |
| Separate groups reusing the same addresses | Accept | No blanket global IP-uniqueness rule; isolated address spaces may overlap. |
| One extra isolated node beside a valid network | Reject | The valid part does not excuse the isolated node. |
| Duplicate node, interface-within-node, or link IDs | Reject | References are ambiguous. |
| One port used by two cables | Reject | Add a switch or another port; do not silently create a shared LAN. |
| Two nodes with parallel cables on distinct ports | Accept | Not a duplicate cable; loop-control requirements must be described separately. |
| Disabled cable or interface | Accept | Structural attachment remains present; operational reachability may fail. |
| Additional unused but addressed interface | Accept | Retain the unused port; a future runtime must represent its disconnected state. |
| IPv6-only or DHCP-only host without explicit IPv4 | Reject | Outside the current explicit-IPv4 readiness contract. |
| Trunks, firewalls, vendor OS, or unknown protocol | Shape-dependent | Preserve unknown settings; implementation support is not implied. |
| Large topology | Shape-dependent | No fixed device-count claim; free API token limits and worker capacity can still prevent use. |

Host local/remote delivery follows [RFC 1122](https://www.rfc-editor.org/rfc/rfc1122).
The /31 exception is specified by [RFC 3021](https://www.rfc-editor.org/rfc/rfc3021).
Switch VLAN and STP behavior is described in the
[Linux bridge documentation](https://docs.kernel.org/networking/bridge.html).
Cloud management connectivity must not supply a hidden path between lab devices.

## Routing, services and automation matrix

| Configuration | Validation decision |
| --- | --- |
| Missing `routing`, or empty routes/protocol lists | Accept. Absence is meaningful; no routes are inserted. |
| `routing: null`, routes as an object, protocols as a string | Reject the malformed shape. |
| Default gateway with missing/invalid `via` or unknown interface | Reject. Omit the whole gateway if no gateway is intended. |
| Validly written gateway outside the connected subnet | Accept as input; installation may fail. No gateway feasibility solver exists. |
| Static destination `10.9.0.0/24`, `0.0.0.0/0`, or a /32 | Accept the canonical network; require `via`, `interface`, or both. |
| Static destination `10.9.0.1/24` | Reject host bits in a network field; do not normalize silently. |
| Interface-only static route | Accept; retain the explicit on-link route without inventing a gateway. |
| Static route with nonexistent interface, negative/Boolean metric | Reject. |
| Forward route with no return route | Accept; a reply may fail. No return route is invented. |
| Forwarding false on an intermediate router | Accept and preserve it. |
| OSPF with missing router ID, interface list, or per-interface area | Reject incomplete known protocol fields. An explicit empty interface list is allowed. |
| RIP without version, or with a malformed interface entry | Reject. Readiness permits version 1 or 2; runtime support must be stated in the plan. |
| OSPF area/network-type mismatch, passive transit interface, duplicate router IDs | Accept syntactically complete input; adjacency may fail. |
| Unknown named routing protocol | Preserve its configuration; do not pretend its protocol-specific schema was validated. |
| Missing services, or empty service list | Accept; do not create an HTTP server. |
| Service missing protocol or using string `enabled` | Reject. |
| Supplied listener with port 0, 65536, Boolean, or nonnumeric port | Reject; TCP/UDP service ports here are integers 1–65535. |
| Listener `0.0.0.0` | Accept as an IPv4 bind address. |
| Valid listener IP not configured locally | Ready; service startup can fail. No binding feasibility check exists. |
| Unknown custom automation operation with valid fields | Ready; unsupported operations must be reported as limitations. |
| Unknown/duplicate automation targets, duplicate task IDs | Reject. |
| Unknown dependency, self-dependency, or task dependency cycle | Reject before translation. |
| Task references a later task, without a cycle | Ready; preserve dependencies for external execution tooling. |
| Disabled service/protocol with malformed supplied fields | Reject malformed fields; disabling does not excuse incomplete JSON. |

OSPF requirements depend on the configuration and implementation; see
[FRR OSPF documentation](https://docs.frrouting.org/en/latest/ospfd.html).
The local checker validates shape and references, not convergence. It also does
not resolve duplicate IPs within VLANs, network/broadcast/loopback/multicast host
address semantics, ARP behavior, MTU, ACLs, NAT, policy routing, ECMP, redistribution,
route-installation errors or service binding conflicts. Those need a separate
semantic diagnostic layer and runtime tests; they must not silently modify input.

## JSON boundary

- A JSON object is required. Parsing rejects duplicate keys, NaN, Infinity and
  floating-point overflow. Direct Python callers also get structured errors for
  non-JSON values, non-string object keys and cyclic objects.
- Nesting is limited to 64 levels in readiness. Reports use escaped JSON Pointer
  paths. There is no architecture file-size or API-token-fit guarantee.
- `schema_version`, when supplied, must be the string `1.0`. Omission retains the
  current default contract. `translation_mode` accepts `behavioral_lab` or
  `cloud_native`; cloud-native planning is not implemented by these implementations.
- Known objects/lists have their types checked; present Boolean fields must be
  actual Booleans. Integers do not accept Python/JSON Booleans as numbers.
- Non-L2 interfaces need explicit IPv4 prefixes, including disabled interfaces.
  L2 ports may omit `ipv4`; an explicitly supplied null or malformed address fails.
  Optional access VLANs are integers 1–4094.
- Unknown extension fields remain unchanged if they contain valid JSON. Passing
  readiness does not claim those fields have a recognized schema or implementation.
- All detected readiness errors are collected in the existing `errors` envelope.
  Invalid JSON values stop deeper validation. No RAG request is sent on failure.
- Output is checked for the AWS provider and the required JSON envelope. No deployment
  project or executable artifact is published.

## Reproducible examples and evidence

Seven minimal fixtures are in [examples/edge_cases](../examples/edge_cases).
Run the local checks without model credentials:

```bash
python app.py check --input examples/edge_cases/single_pc.json
# exit 2: isolated component / missing links
python app.py check --input examples/edge_cases/two_pcs_direct.json
# exit 0: complete; this command does not send a ping
python -m pytest -q tests/test_architecture_edges.py
```

The tests preserve original input through stubbed AWS-plan calls, check graph
errors, malformed nested configuration, cyclic tasks, deep/non-JSON input and a
1,200-task dependency chain. Systematic field-type mutations exercise checker
robustness. Retrieval tests cover direct hosts, /31 and /32, and switch-loop
knowledge after renaming components. These are offline tests, not packet probes.

No live Groq request, Docker network, AWS deployment, ping, protocol convergence or
HTTP probe is performed by this application. Real-network equivalence requires
external positive/negative probes and recorded routes, neighbors and packet paths.
A ready input is not a proven working or production-ready network.
