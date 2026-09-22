# Application architecture

The single responsibility is translating prepared architecture JSON into an AWS
plan. The application does not implement cloud provisioning, deployment code
rendering, device configuration or network probes.

## Processing path

1. `net2cloud/json_io.py` reads strict JSON: duplicate keys and non-finite numbers
   are rejected. JSON output uses atomic replacement.
2. `readiness.py` checks device/link identities, per-device and per-link
   addressing, and graph references. Invalid input never reaches retrieval
   or Groq. See [validation](validation.md).
3. `retriever.py` reads only the rule cards and examples under `kb/`. It selects
   relevant network and AWS knowledge and attaches stable rule IDs.
4. `planner.py` sends the source architecture and selected records to Groq. The
   prompt lives in `net2cloud/prompts/planner.txt` and requests AWS JSON only.
5. `app.py` attaches the authoritative source architecture and knowledge metadata
   to the checked model response. The CLI writes only JSON.

The Python API is `from net2cloud import plan_architecture`. Both the orchestration
API and direct planner calls enforce readiness. Retrieval and the provider client
can be injected for testing; no live model is needed for the regression suite.

## Retrieval and cache

Lexical retrieval uses BM25. Hybrid retrieval combines BM25 with sentence-transformer
embeddings using reciprocal-rank fusion, then applies cross-encoder reranking.
Three core records are pinned. Other records are filtered by translation mode.
Feature queries cover device-type mapping, switch chains, hosts sharing one
switch, direct host-to-host links and /31 or /32 host prefixes, without
rewriting the source topology.

`--top-k` must be a positive integer. It is a target, not a hard budget: core rules and subject coverage may add
records. Long queries are windowed for embeddings; reranker truncation can still
lose detail. These are relevance heuristics, not proof of complete coverage.

Caches default to `.cache/net2cloud/`. Document identity includes sorted paths,
content hashes, chunk size and retriever source. Embedding identity adds model
name, token limit and record identity. Invalid caches are rebuilt. NumPy caches
disable pickle loading. Cached vectors must be finite, real floating-point values,
with nonzero rows and dimensions matching the current model's query vectors.
Invalid fresh embeddings or reranker scores fail explicitly. Model artifacts and
versions are not pinned here.

## Model boundary and limits

The configured Groq models are GPT-OSS 120B and the optional 20B alternative. The
request uses JSON object mode, temperature zero, medium reasoning and a 4,096-token
completion cap including reasoning. Reasoning text is excluded from the response.
Truncated, empty, ambiguous or malformed responses fail rather than producing a
replacement plan. SDK retries and automatic provider/model fallback are disabled.

The parser checks the top-level envelope and requires `cloud_plan.provider` to be
`aws`. Nested resource/configuration content remains planning intentions, not a
certified executable deployment schema. A model can omit or misinterpret a setting;
source preservation and rule citations alone do not prove translation fidelity.
See [the JSON contract](json-contract.md).

## Evidence

Offline tests cover readiness, JSON parsing, source preservation, the AWS output
boundary, retrieval/cache behavior, quota errors and both CLI entry points.
Model and embedding doubles test orchestration, not model quality. Conceptual
network cases are in `evaluations/rag_cases.jsonl`; they are not executable input
fixtures and have not been scored against a live provider.

Live Groq output quality, semantic retrieval, protocol convergence and packet
paths require separate evaluation. This repository neither deploys nor verifies
a working network. Keep predicted behavior and observed results distinct.
