# Application architecture

The responsibility is topology JSON → readiness/corrections → AWS lab plan JSON.
The separate NLP agent and Terraform/Ansible generators are not implemented here.
Phase 1 is independent and excluded from root application checks.

## Processing path

1. `json_io.py` rejects duplicate keys and non-finite numbers, then writes atomically.
2. `readiness.py` validates device/link identity, addressing and graph references.
   It returns errors and issue tuples, warnings and a source revision together.
3. `corrections.py` applies explicit revision-bound tuples to a copy, synchronizes
   redundant address fields and revalidates. No clarification model runs here.
4. `hosting.py` selects one bounded educational worker from a reviewed catalog.
   Unsupported roles/capacity stop before model retrieval/downloads.
5. `retriever.py` selects topology-phase KB cards with mandatory mapping/isolation
   rules, plus relevant examples. The source is never normalized or repaired.
6. `plan_contract.py` derives exact hosting, device, cable, runtime and later
   configuration-target requirements. `planner.py` supplies these and the source
   and retrieved knowledge to Groq, requesting the required AWS plan and limitations.
7. Python checks the model envelope, citations and every nested plan requirement.
   It adds mandatory limitations and attaches the authoritative source/provenance.

Public APIs are `plan_architecture`, `check_readiness`, and `apply_corrections`.
Both orchestration and direct planner calls enforce readiness. Injected retrievers
and provider clients support offline tests. The model cannot override hosting or
source topology; failures never publish a partial or silently repaired plan.

## Retrieval and cache

BM25 is available without ML dependencies. Hybrid retrieval combines BM25 and
local embeddings with reciprocal-rank fusion and cross-encoder reranking. Required
core, device-mapping, runtime-isolation and link-realization cards are pinned.
Switch/router roles add their required topology rules. Feature queries cover
shared switches, direct host links and /31-/32 addressing. `top_k` is a positive
integer target; required rules and feature coverage may exceed it.

Cards tagged `Phase: configuration` are excluded. Source `translation_mode`
extensions cannot change the fixed behavioral profile. Only `kb/` Markdown is
retrieved; `docs/` is for humans. Cache fingerprints cover document paths/content,
chunking source, record metadata and embedding model identity. Invalid caches are
rebuilt. Embedding dimensions, finite nonzero floating values and reranker outputs
are checked; pickle loading is disabled.

## Contract and execution limits

See [the enforced JSON contract](json-contract.md), [hosting policy](hosting.md),
and [clarification interface](validation.md). Stable safe runtime names derive
from source IDs, not display names; future operations must address those targets.

Groq uses GPT-OSS 120B by default, with 20B as the supported alternative. Requests
use JSON object mode, temperature zero, medium reasoning, and a 4,096-token
completion cap including reasoning. SDK retries and provider/model fallback are
disabled. Large inputs/plans may exceed free-tier request/completion limits even
inside the hosting profile's node limit; truncation fails rather than losing nodes.
No input size guarantees or live-model success claims are made by offline tests.

The plan is a versioned, structurally checked specification. An external runtime
must actually create the namespaces, bridges and veth cables; provisioning EC2
alone does not do that. Management, AMI, package access, capacity and cost remain
explicit dependencies. Later user requests configure OSPF/RIP/services without
changing the initial graph. Positive and negative packet tests are still required
to establish real network behavior and supported vendor differences.
