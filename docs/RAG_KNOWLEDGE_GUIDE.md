# Knowledge retrieval and planning

Corpus version: 2.2.0. The active pipeline is architecture JSON → deterministic
readiness check → retrieval → JSON plan. Discussion and downstream generation
are separate. See the [JSON contract](JSON_CONTRACT.md) and [readiness rules](READINESS.md).

## Knowledge authority

Only `kb/**/*.md` is indexed. The [engineering specification](NETWORK_TRANSLATION_SPEC.md)
explains the intended behavior, while [sources.json](sources.json) records primary
references. `PROJECT` identifies a project requirement, not a platform guarantee.
Examples illustrate rules and never authorize new links, routes or public access.
The caller's explicit configuration remains authoritative, including disabled
protocols and intentional failures.

Each heading starts a complete record with `Rule-ID`, `Kind`, `Mode`, `Status`,
`Keywords`, `Applies`, `Required`, `Forbidden`, `Expected`, `Verify`, `Sources`
and `Related` fields. Records must fit the real chunker's 1,800-character limit.
Every record includes its conditions and prohibited shortcuts. `Verify` describes
downstream checks; the translation model does not run probes or validation.
The application checks input readiness before retrieval begins.
`Status: target_specification` describes the engineering requirement and is not a
deployment status returned by the RAG.

## Active retrieval

`retriever.py` pins `CORE-001`, `CORE-002` and `CORE-003`. It filters other records
by the requested mode (default `behavioral_lab`) or `all`, then queries with the
complete architecture JSON. Additional queries focus on component roles, routing
settings, protocol names, service names and Ansible operations, without allowing
matching example IP addresses to dominate those feature queries. This helps keep
service requests alongside network requests.
There is no router-count boost or topology decision inside retrieval.

The lexical backend uses BM25 and needs only the Python standard library. The
hybrid backend combines BM25 and normalized sentence-transformer similarities
with reciprocal-rank fusion, then reranks candidates using a cross-encoder.
BM25 document statistics are built once and reused across the request's queries.
Long JSON queries are split into token windows. Each configuration subject also
contributes its best lexical match so a dominant topology description does not
consume all selected records. `--top-k` is the target number of relevant records;
subject coverage can exceed it. Three pinned core records are additional.

This selection is a relevance heuristic, not proof of complete knowledge coverage.
It does not automatically follow every `Related` reference. Large inputs can
produce many subject queries and reranking pairs; callers should apply their own
input/context budgets. Record token length is checked before embedding, but
cross-encoder pair truncation may still lose detail. Semantic retrieval quality
and multilingual behavior need model-based evaluation.

Document cache identity includes sorted file names/content hashes, chunk size
and retriever source. Embedding cache identity additionally includes model name,
sequence limit and selected record IDs. JSON and NumPy caches use atomic writes;
legacy pickle/FAISS caches are unused. Cache paths default to this checkout's
`index/` and can be configured through `NET2TF_INDEX_DIR`. Hosted model revisions
are not pinned by this project; deployments requiring reproducibility must pin
local model artifacts and dependency versions.

Malformed record caches and invalid cached embedding matrices are rebuilt.
Shared atomic-write helpers remove temporary files on failure and preserve an
existing destination until replacement succeeds.

## Planning boundary

`planner.py` sends the unchanged architecture and selected records in one Groq
request, with temperature zero and JSON object mode. System instructions request
cloud mapping, network intentions, Ansible operations, rule citations and
implementation limitations. They prohibit field-validation reports, dialogue,
code generation and execution. HTTP, OSPF and custom Ansible tasks are planned
together on their actual component targets.

The instructions live in `prompts/planner.txt`. Missing/empty completions,
non-completion finish reasons, ambiguous JSON and malformed output envelopes fail
explicitly; no guessed plan is substituted. `contracts.py` describes Python
interfaces only and does not introduce runtime architecture-field validation.

`app.py` attaches the original architecture and knowledge references itself.
It does not overwrite model choices with peering/TGW/device-count heuristics.
The planner checks required top-level response sections/types and rejects extra
sections such as dialogue or generated files. Beyond the deterministic readiness
gate, it does not validate full protocol configuration or nested plan semantics. The consumer checks
whether its generator can implement the requested operations and references.
The RAG cannot establish that a proposed plan will deploy or reproduce ping.

## Evaluation and maintenance

```bash
python tools/validate_knowledge_base.py
python -m pytest -q
python app.py context --input examples/architecture.json --retrieval lexical
```

The KB checker validates the actual chunker, record fields/IDs, source references,
local document links, evaluation references and manifest hashes. The automated
suite exercises input preservation, JSON boundaries, retrieval, cache refresh,
service/routing coverage and CLI behavior using offline fixtures and model stubs.
These checks do not measure a real model's answers or deploy a network.

[evaluations/rag_cases.jsonl](../evaluations/rag_cases.jsonl) retains 32 engineering
scenarios originally written as natural-language questions. They are conceptual
behavior assertions and seeds for upstream/whole-system evaluation, not valid
inputs to the active JSON API. Convert them into prepared architectures before
measuring this RAG; do not reintroduce prompt extraction to run them. Cases with
standalone components or missing interface IPs now expect a readiness rejection,
even when the older engineering scenario describes their theoretical behavior.

For real model evaluation, score requested-feature coverage, exact preservation
of IDs and parameters, rule support, absence of invented connectivity, correct
service targets and usable downstream references. Include disabled services,
missing routes, incompatible OSPF areas, arbitrary IDs and mixed service/routing
requests. Test the downstream generator and deployed network separately.

After knowledge edits, update affected documents/tests, increment the corpus
version for semantic changes, refresh `kb/manifest.json` using
`python tools/validate_knowledge_base.py --refresh-manifest`, then run checks.
The runtime notices content changes and rebuilds the applicable caches.
