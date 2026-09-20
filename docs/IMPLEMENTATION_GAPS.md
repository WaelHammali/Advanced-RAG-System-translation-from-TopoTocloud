# Current implementation and limits

Reviewed: 2026-09-20. The active application checks architecture JSON readiness and returns
a cloud/Ansible JSON plan for a separate generator.

| Area | Current behavior |
| --- | --- |
| Input | Consumes a JSON object directly; preserves arbitrary nested fields. |
| Readiness and discussion | Local gate checks graph prerequisites, known nested types/references and Ansible dependency cycles. Generators repeat this gate. Discussion stays in the calling application. |
| Retrieval | BM25 or hybrid embeddings/reranking, mode filtering, mandatory core rules and configuration-subject matching. |
| Caching | Refreshes on document content, file names and retriever changes; embedding identity also includes model/settings. |
| Planning | One Groq call asks for structured cloud and Ansible intentions with exact source targets. |
| Output | Parsed JSON object plus untouched source architecture and retrieved knowledge references. |
| File generation and deployment | Separate educational generators now render Terraform/Ansible; deployment is an explicit subsequent action. They are not imported by the RAG. |
| Original implementation | Preserved under `legacy/`; unused by the root API. |

The old system extracted a prompt into a restricted schema, selected peering/TGW
from router counts, reconstructed addresses and rendered infrastructure through
hardcoded templates. Its Ansible builder guessed prefixes and targeted fixed
router names. Those paths were archived; none is a fallback for the new planner.
The archive is historical source, not a supported standalone application.

The current model's output is checked for JSON-object syntax, required top-level
sections/types and unexpected sections. Nested plan schema and semantic
correctness remain external checks. Source preservation does not guarantee that the
model mapped every field correctly. A consuming generator must check required
sections, target references, supported modules, resource limits and parameter
compatibility before rendering or executing anything.

Knowledge records describe intended network fidelity. The separate
`aws_single_host_docker_v1` generators implement an initial Docker/veth/bridge/FRR
backend with the bounded subset in [the generator contract](GENERATOR_CONTRACT.md).
They have artifact and mocked-command tests, not live AWS or privileged Docker
conformance evidence. OSPF/RIP convergence, packet paths, HTTP availability and
negative connectivity still need measurements. Unsupported provider/runtime
requirements remain visible in limitations and prevent generation.
The generator rejects active Layer 2 switch/VLAN cycles because STP is not
implemented. See the [edge-case study](ARCHITECTURE_EDGE_CASES.md) for checked
boundaries and the distinction between complete JSON and working connectivity.

Offline tests cover contract behavior, lexical retrieval and cache mechanics.
Stubbed hybrid tests, where present, verify orchestration rather than real model
quality. Live Groq output quality, real embedding/reranking performance, AWS
provisioning and end-to-end network behavior require separate integration runs.
