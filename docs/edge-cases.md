# Topology boundary study and JSON validation

Reviewed: 2026-09-22. Scope: the current devices/links topology contract and
educational AWS JSON planning boundary. This is a bounded engineering matrix,
not a proof for every possible topology, operating system or vendor feature.

## Three different decisions

1. **Ready JSON:** device/link identities, addressing and references are
   complete and self-consistent. A deterministic check runs before retrieval or Groq.
2. **Implementation feasibility:** the plan describes required capabilities and limitations.
   No deployment backend is implemented in this repository.
3. **Network behavior:** packet delivery depends on the actual configuration and
   runtime. The application does not currently compute or measure reachability.

A single PC is a legitimate standalone computing architecture. It is **not accepted
by this project's current network-lab policy**, because the requested policy says
no device may be alone. There is no hidden singleton exception. Supporting
standalone hosts later should be an explicit contract/profile decision, with no
invented cable or router. A device's unique `id` is the required canonical
reference for links; `name` is its required nonempty display label.

## Topology matrix

The expected behavior below assumes ordinary IPv4 stacks and no unmentioned
filtering or alternate paths. It is an engineering prediction, not a result
from live ping tests.

| Architecture / condition | Readiness | Behavior or implementation decision |
| --- | --- | --- |
| Empty object, no devices | Reject | Missing devices and links. |
| One device, no links | Reject | Isolated device, even with a valid address. |
| Two devices without a link | Reject | Both isolated. |
| Device connected to itself | Reject | Self-links do not satisfy the no-isolation policy. |
| Two PCs connected directly, distinct addresses in the same subnet | Accept | Local communication needs no router. |
| Direct PCs in genuinely different subnets, no intermediate router | Reject | One cable is one network; one end's link address falls outside it. |
| PC1–R1–R2–PC2, each link its own subnet, no routes | Accept | Routers use a different address per link. Preserve the missing routes: PC1 must not reach PC2. |
| Direct PCs on the two addresses of a /31 | Accept | Valid point-to-point addressing; the link's network is the /31 itself. |
| Direct PCs with distinct /32 addresses, link network a covering /30 | Accept | Each host keeps its own maximally specific mask; the link's broader network contains both. |
| PC and router only | Accept | Direct peer reachability can work; this says nothing about other destinations. |
| PC and switch only | Accept | Complete two-device topology; an unaddressed switch is not a remote IP endpoint. |
| Multiple switches in an acyclic or cyclic path | Accept | Preserve every switch and cable; loop-control requirements are a plan-time limitation, not a readiness rejection. |
| Two separate connected groups | Accept | Each group stays isolated; the graph need not be globally connected. |
| Separate groups reusing the same addresses | Accept | No blanket global IP-uniqueness rule; isolated address spaces may overlap. |
| One extra isolated device beside a valid network | Reject | The valid part does not excuse the isolated device. |
| Duplicate device ID or link ID | Reject | References are ambiguous. |
| A pc with two or more links | Reject | Only a pc is capped at one link; router/server/switch may have any number. |
| A link's source_ip/target_ip outside that link's network, or missing at a non-switch end | Reject | The link's own data is inconsistent or incomplete. |
| A device's ip_address not used on any of its links | Reject | The device and its links disagree about its address. |
| subnet_mask not matching prefix_length, or network_address not matching ip_address/prefix_length | Reject | Internally inconsistent addressing. |
| IPv6-only or DHCP-only host without explicit IPv4 | Reject | Outside the current explicit-IPv4 readiness contract. |
| Large topology | Shape-dependent | No fixed device-count claim; free API token limits and worker capacity can still prevent use. |

Host local/remote delivery follows [RFC 1122](https://www.rfc-editor.org/rfc/rfc1122).
The /31 exception is specified by [RFC 3021](https://www.rfc-editor.org/rfc/rfc3021).
Switch behavior is described in the
[Linux bridge documentation](https://docs.kernel.org/networking/bridge.html).
Cloud management connectivity must not supply a hidden path between lab devices.

This contract has no routing, service or automation configuration to validate:
the upstream vision pipeline that produces this JSON cannot detect any of that
from a topology diagram, so there is nothing here to preserve or reject beyond
device/link identity and addressing.

## JSON boundary

- A JSON object is required. Parsing rejects duplicate keys, NaN, Infinity and
  floating-point overflow. Direct Python callers also get structured errors for
  non-JSON values, non-string object keys and cyclic objects.
- Nesting is limited to 64 levels in readiness. Reports use escaped JSON Pointer
  paths. There is no architecture file-size or API-token-fit guarantee.
- Every device's `network` object needs all four fields non-null (except
  `switch`/`bridge`/`hub`, which may leave all four null); every link's
  `network` object always needs its three network fields non-null, plus
  `source_ip`/`target_ip` (null only at a switch/bridge/hub end).
- Unknown extension fields remain unchanged if they contain valid JSON. Passing
  readiness does not claim those fields have a recognized schema or implementation.
- All detected readiness errors are collected in the existing `errors` envelope.
  Invalid JSON values stop deeper validation. No RAG request is sent on failure.
- Output is checked for the AWS provider and the required JSON envelope. No deployment
  project or executable artifact is published.

## Reproducible examples and evidence

Fixtures are in [examples/edge_cases](../examples/edge_cases). Run the local
checks without model credentials:

```bash
python app.py check --input examples/edge_cases/single_pc.json
# exit 2: isolated device / missing links
python app.py check --input examples/edge_cases/two_pcs_direct.json
# exit 0: complete; this command does not send a ping
python -m pytest -q tests/test_architecture_edges.py
```

The tests preserve original input through stubbed AWS-plan calls, check graph
errors, deep/non-JSON input, and address/mask consistency. Systematic
field-type mutations exercise checker robustness. Retrieval tests cover direct
hosts, /31 and /32, and switch-loop knowledge after renaming devices. These are
offline tests, not packet probes.

No live Groq request, Docker network, AWS deployment, ping or HTTP probe is
performed by this application. Real-network equivalence requires external
positive/negative probes and recorded routes, neighbors and packet paths. A
ready input is not a proven working or production-ready network.
