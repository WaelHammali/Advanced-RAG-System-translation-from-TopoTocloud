# Contributing

Keep the boundary: prepared architecture JSON in, AWS plan JSON out. Readiness
validation, knowledge retrieval and model planning belong here. Deployment,
Terraform/Ansible rendering, cloud SDK execution and network probes do not.

## Checks

```bash
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m ruff format --check .
python tools/validate_knowledge_base.py
python -m pytest -q
```

Tests use provider/model doubles and local fixtures. They require no API keys,
cloud credentials, paid requests or deployed infrastructure. CI runs the same
checks on supported Python versions; it has no infrastructure-generation job.

## Code ownership

All application modules are in `net2cloud/`. `app.py` at repository root is only a
compatibility launcher. See [architecture](docs/architecture.md) for module roles.
Preserve source values, intentional routing failures and unknown extension fields.
Return structured readiness errors before retrieval; never infer missing IPs or
repair routes. The model returns only the documented AWS envelope.

Use [kb/rules](kb/rules) for canonical networking/AWS knowledge and
[kb/examples](kb/examples) for behavioral illustrations. `docs/` contains app guides,
not duplicate network rules. Follow [knowledge maintenance](docs/knowledge-base.md)
when changing rule cards or the generated manifest. Keep runnable JSON examples
and their regression tests consistent with [the contract](docs/json-contract.md).
