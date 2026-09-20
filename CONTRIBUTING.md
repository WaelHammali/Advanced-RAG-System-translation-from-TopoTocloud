# Working on the RAG

The public entry points are `app.plan_architecture()` and `python app.py`.
Keep the existing boundary: prepared architecture JSON in, cloud/Ansible plan JSON
out. A deterministic readiness gate blocks incomplete identities, addressing and
links before retrieval/model calls. Discussion belongs to the caller. Artifact
generation, execution and network conformance checks belong to the consumer.

## Development setup

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m ruff format --check .
python tools/validate_knowledge_base.py
python -m pytest -q
```

Development checks use fake model clients and local knowledge. They need no API
key, Groq package or embedding-model download. NumPy is included to exercise the
hybrid retrieval/cache orchestration with deterministic model doubles.
`requirements.txt` installs runtime dependencies separately.

Run `python -m ruff check --fix .` and `python -m ruff format .` when editing.
The configuration in `pyproject.toml` excludes the historical `legacy/` archive.
The GitHub Actions workflow runs these offline checks on pushes and pull requests;
it does not deploy or make paid model calls.

## Code boundaries

| File | Responsibility |
| --- | --- |
| `app.py` | API orchestration, source preservation and CLI handling. |
| `readiness.py` | Input completeness checks and structured readiness errors. |
| `configuration_validation.py` | Known routing/service/Ansible field shapes, references and task dependency graphs. |
| `planner.py` | Model request and response-envelope parsing. |
| `prompts/planner.txt` | Planning instructions and expected JSON shape. |
| `retriever.py` | Knowledge loading, caching, feature queries and ranking. |
| `contracts.py` | Static knowledge types and an injectable retriever interface. |
| `json_io.py` | Strict JSON syntax/encoding and atomic file replacement. |
| `config.py` | Paths, model identifiers and retrieval defaults. |
| `generator_common.py` | Downstream capability checks and shared artifact contract; never imported by the RAG. |
| `Generator terraform/` | Deterministic educational Terraform rendering. |
| `Generator ansible/` | Deterministic Ansible/configuration rendering and worker runtime assets. |

Keep architecture values as data. Do not add topology-count decisions, automatic
route repairs or prompt extraction. JSON syntax and model-response envelope checks
are distinct from checking whether an IP, route or protocol configuration is valid.
Static Python types are not runtime schemas. `readiness.py` checks the documented
input prerequisites; it must not repair intentional routing failures or infer IPs.
Preserve caller-defined fields.

`PlanResponseError` signals an unusable model response. Provider exceptions remain
visible to Python callers; the CLI converts runtime exceptions into a JSON error
on stderr and exits with status 1. `ArchitectureNotReady` carries a structured
report; the CLI exits 2 and writes no plan. The offline `check` command reports on
stdout. CLI usage/help follows argparse conventions.
Plan truncation also raises an error. Do not replace failures with guessed plans.

## Knowledge changes

Follow [the RAG guide](docs/RAG_KNOWLEDGE_GUIDE.md). After reviewing record changes,
refresh the manifest and run the structural checker:

```bash
python tools/validate_knowledge_base.py --refresh-manifest
python tools/validate_knowledge_base.py
```

Add meaningful regression cases for changed behavior. A passing offline suite
does not establish live-model quality, support for all network examples, or
readiness for company production use. Assess those separately with held-out
architectures, the actual generator and deployed network measurements.

The artifact CI job initializes the generated Terraform provider for schema
validation and runs Ansible syntax checks. It does not run Terraform plan/apply,
contact AWS APIs, create Docker containers or execute a playbook on a worker.
