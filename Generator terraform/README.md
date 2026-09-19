# Terraform generator

A deterministic Python generator for `aws_single_host_docker_v1`. It accepts the
concrete RAG plan described in [the generator contract](../docs/GENERATOR_CONTRACT.md).
It renders native `.tf` files, settings, the source plan and a generation manifest.
Generation makes no model, AWS or Terraform calls and never applies infrastructure.

From the repository root:

```bash
python 'Generator terraform/generator.py' --input examples/generator_plan.json --output generated/terraform
```

Use a new output directory each time; existing Terraform projects and state are
never overwritten. The default is one ARM `t4g.nano` worker, 8 GiB encrypted gp3,
Standard CPU credits, and an automatically assigned public IPv4 for management.
There is no NAT Gateway, Transit Gateway, load balancer or per-device EC2 instance.

Upgrade using `terraform apply -var='instance_type=t4g.micro'` or a larger supported
T4g size. Lab addressing and topology remain independent of worker size.
`use_spot=true` is optional and interruptible; it is not assumed to be cheaper in
every region or to be suitable for uninterrupted exercises.

See [the generated-project instructions](PROJECT_README.md) for deployment,
Ansible inventory export, costs and destruction. This backend is an educational
implementation, not a production reference architecture.
