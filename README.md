# Architecture JSON → cloud and Ansible JSON plan

This RAG checks a network architecture JSON for readiness, retrieves relevant
networking and automation knowledge, and asks a model for a JSON plan that a
separate generator can consume. It covers components, interface-level edges, IP
addresses, routing protocols, application services and Ansible task intentions.

```text
Your application                This RAG                  Separate generator
input + discussion  →  JSON → readiness → retrieval → plan  →  Terraform / Ansible
```

The application blocks translation until components have unique IDs, types and
interfaces, all components have valid links to other components, and non-L2
interfaces have valid IPv4 addresses with prefixes. Switch ports do not need IPs.
The check runs before retrieval or model calls and returns all detected issues
with JSON paths. It does not add addresses, names or links to repair the input.

The translation model asks no clarification questions and generates no files.
Discussion stays in your calling application; deployment and connectivity tests
belong to the separate generators/runtime. Original input fields are attached
unchanged to a successful plan. Response sections/types and truncation are also
checked; readiness does not prove network reachability or generator compatibility.

JSON parsing rejects duplicate keys and non-finite numbers rather than silently
discarding configuration. Output files are replaced atomically, and the CLI rejects
using the input architecture as the output path.

## Run

Check readiness locally without installing model dependencies or using an API key:

```bash
python app.py check --input examples/architecture.json
```

`check` returns `ready`, `status`, and an `errors` list. `plan` and `context` enforce
the same gate automatically. Exit status 2 means not ready: `plan` writes its
readiness report to stderr and publishes no new plan. Exit status 1 means a
syntax/runtime error. See [the readiness rules](docs/READINESS.md).

Use Python 3.10+ with compatible dependencies:

```bash
python -m pip install -r requirements.txt
export GROQ_API_KEY='your-key'
python app.py plan --input examples/architecture.json --output generated/plan.json
```

Hybrid retrieval uses BM25, embeddings and a cross-encoder; its first use can
download the configured models. Groq receives the supplied architecture and
selected knowledge records. Configure model names, paths and retrieval mode in
[config.py](config.py) or its `NET2TF_*` environment variables.
[.env.example](.env.example) lists the available settings; export them in your
process environment. The application does not automatically load `.env` files.

Inspect knowledge retrieval locally, without Groq or embedding dependencies:

```bash
python app.py context --input examples/architecture.json --retrieval lexical
```

Use `--retrieval lexical` on `plan` as well for BM25 retrieval with only the `groq`
package installed. JSON results go to stdout and optionally `--output`; runtime
errors go to stderr with a nonzero exit status. Check the exit status before
passing an output file to a generator.

## Input and output

[examples/architecture.json](examples/architecture.json) defines an example:
`PC1—SW1—R1—R2—SW2—PC2`, with an HTTP server on SW2, OSPF on both routers,
explicit interface addresses and an Ansible package task on the server.
[The JSON contract](docs/JSON_CONTRACT.md) explains the suggested fields and
output shape. The readiness gate checks required identities, links and IPv4
addressing; it does not validate every protocol, service or generator capability.

```python
from app import plan_architecture

plan = plan_architecture(architecture_dict)
# plan["cloud_plan"], plan["ansible_plan"], plan["architecture"]
```

The output contains cloud mapping, networking intentions, Ansible targets/tasks,
limitations, supporting rule IDs, selected knowledge references and the complete
original architecture. The model is instructed to preserve supplied settings and
intentional failures. Preserving the source JSON is deterministic; correctness of
the generated plan still requires evaluation and downstream checks.

## Educational artifact generators

Two separate Python generators now implement the opt-in
`aws_single_host_docker_v1` backend:

- [Generator terraform](<Generator terraform/README.md>): native `.tf` files for
  one ARM AWS worker, with an editable `t4g.nano` educational default.
- [Generator ansible](<Generator ansible/README.md>): a playbook, isolated device
  containers, explicit cables/switches, routing and supported service configuration.

```bash
python -m pip install -r 'Generator ansible/requirements.txt'
python 'Generator terraform/generator.py' --input examples/generator_plan.json --output generated/terraform
python 'Generator ansible/generator.py' --input examples/generator_plan.json --output generated/ansible
```

The checked-in plan is a hand-authored offline example. To use the RAG, translate
[the generator-profile input](examples/generator_architecture.json) with `app.py plan`
and pass its output to both generators. They accept the
[concrete generator contract](docs/GENERATOR_CONTRACT.md), reject unsupported
features, and write new output directories. They never deploy during generation.
Their generated READMEs explain explicit deployment and cleanup.

The default shares a worker across the whole lab. Tiny memory and CPU credits
limit capacity; larger labs need a larger T4g size. Public IPv4, EBS and transfer
can add costs. This is an educational backend with a defined feature subset;
company readiness and live network fidelity require separate validation.

## Project files and checks

- [app.py](app.py): Python API and JSON CLI.
- [readiness.py](readiness.py): deterministic input gate and structured issue reports.
- [retriever.py](retriever.py): retrieval and content-aware caching.
- [planner.py](planner.py): one model call producing a JSON plan.
- [prompts/planner.txt](prompts/planner.txt): planning instructions and output shape.
- [contracts.py](contracts.py): static types and the injectable retrieval interface.
- [json_io.py](json_io.py): JSON parsing and atomic output/cache writes.
- [kb/](kb/): atomic networking, service and Ansible knowledge records.
- [RAG guide](docs/RAG_KNOWLEDGE_GUIDE.md): context, caching and evaluation.
- [Network specification](docs/NETWORK_TRANSLATION_SPEC.md): behavior the plan must preserve.
- [Implementation status](docs/IMPLEMENTATION_GAPS.md): boundaries and unverified capabilities.
- [legacy/](legacy/): archived original intake, validators and generators; unused by the active API.

```bash
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m ruff format --check .
python tools/validate_knowledge_base.py
python -m pytest -q
```

The knowledge checker checks documents, references and inventory hashes,
not input architecture fields. After reviewed KB edits, refresh the inventory with
`python tools/validate_knowledge_base.py --refresh-manifest`.

See [CONTRIBUTING.md](CONTRIBUTING.md) for code responsibilities and the offline
development workflow. GitHub Actions is configured to run lint, formatting,
knowledge checks and regression tests without model credentials or deployments.
