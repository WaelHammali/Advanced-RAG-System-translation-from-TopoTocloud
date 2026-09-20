# Network architecture JSON → AWS plan JSON

This application validates a network architecture, retrieves networking knowledge,
and uses Groq to translate it into a structured AWS architecture plan. It preserves
source devices, links, addresses, routing, services and configuration requirements.
It returns JSON only and does not provision infrastructure or execute configuration.

```text
architecture.json → readiness checks → knowledge retrieval → Groq → aws_plan.json
```

## Run

Python 3.10+ is required. Offline readiness checks need no third-party dependencies:

```bash
python -m net2cloud check --input examples/architecture.json
python -m net2cloud context --input examples/architecture.json --retrieval lexical
```

To translate:

```bash
python -m pip install -r requirements.txt
export GROQ_API_KEY='your-key'
export NET2TF_PLAN_MODEL='openai/gpt-oss-120b'
python -m net2cloud plan --input examples/architecture.json --output generated/aws_plan.json
```

Use a **Groq Free-plan account** to avoid API charges. The app cannot inspect your
billing tier. GPT-OSS 120B is the default; GPT-OSS 20B is the supported alternative.
There are no automatic model fallbacks or SDK retries. Quota failures stop the
request. Free-tier availability and limits can change; see
[Groq limits](https://console.groq.com/docs/rate-limits) and
[billing](https://console.groq.com/docs/billing-faqs).
No paid API calls or AWS deployments are needed to run the tests.

`--retrieval lexical` avoids embedding-model downloads. Default hybrid retrieval
uses local embeddings and reranking. Configuration lives in
[net2cloud/config.py](net2cloud/config.py); [.env.example](.env.example) lists
settings. The existing `NET2TF_*` environment names are retained for compatibility.
The app does not automatically load `.env`. `python app.py ...` remains a small
compatibility launcher; application logic lives in the package.

## Output and validation

The output has `cloud_plan` (with `provider: "aws"`), `rule_ids`, `limitations`,
the unchanged input `architecture`, and retrieved `knowledge` metadata. Service
and automation requirements belong inside `cloud_plan.configuration`.
See the [JSON contract](docs/json-contract.md) and the
[hand-authored output example](examples/aws_plan.json).

Incomplete input is rejected before retrieval or model calls. Single isolated
components remain blocked under the project's policy; directly connected PCs are
valid. Complete configurations that deliberately fail to ping remain unchanged.
Readiness does not prove that a model's plan is correct or deployable.

`check` returns a readiness report, with exit 0 for ready or 2 for incomplete.
`plan` and `context` return readiness errors on stderr with exit 2; other runtime
errors use exit 1. Failures do not replace an existing output file.

## Repository layout

```text
net2cloud/           Python application and planner prompt
kb/
  rules/             Atomic networking/AWS rules read by the RAG
  examples/          Small behavioral examples read by the RAG
  sources.json       Primary-reference register
  manifest.json      Generated inventory and content hashes
docs/               Human guides: architecture, contract, validation, edge cases
examples/            Runnable source JSON and illustrative AWS plan JSON
evaluations/        Conceptual network-behavior scenarios
tests/              Offline regression tests
tools/              Knowledge-base integrity checker
```

`kb` and `docs` serve different readers. **Only `kb` is retrieved by the RAG.**
Networking rules have one canonical home in the KB; docs explain how the application
uses them. Start with the [architecture guide](docs/architecture.md),
[knowledge-base guide](docs/knowledge-base.md), [validation](docs/validation.md),
and [edge-case study](docs/edge-cases.md).

## Development

```bash
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m ruff format --check .
python tools/validate_knowledge_base.py
python -m pytest -q
```

See [CONTRIBUTING.md](CONTRIBUTING.md). Deployment generators and archived legacy
code have been removed; their previous versions remain available in Git history.
