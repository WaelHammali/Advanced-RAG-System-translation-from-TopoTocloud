# Generated educational Terraform project

This project provisions one management worker. The Ansible project creates the
actual lab inside isolated containers. Terraform alone does not configure routers,
start HTTP services or prove that ping works.

## Deploy explicitly

Install Terraform >=1.6,<2 and configure AWS credentials through your normal AWS
credential chain. Supply your public SSH key and public administrator IPv4 /32:

```bash
export TF_VAR_ssh_public_key="$(cat ~/.ssh/id_ed25519.pub)"
export TF_VAR_ssh_admin_cidr='YOUR_PUBLIC_IPV4/32'
terraform init
terraform fmt
terraform validate
terraform plan -out=lab.tfplan
terraform apply lab.tfplan
terraform output -json ansible_inventory > inventory.json
```

Use the inventory with the separately generated Ansible project. Terraform does
not read or upload the private SSH key. Verify the new worker's SSH host key before
connecting; host-key verification remains enabled.

`lab.auto.tfvars.json` contains the region, lab name, instance type and disk size
selected from the accepted plan. Optional `ami_id` pins a known Ubuntu 24.04 ARM64
AMI; otherwise Canonical's public SSM parameter supplies the image. Keep the
provider lockfile created by `terraform init` for repeatable provider selection.

## Educational sizing and costs

The default `t4g.nano` has very limited memory. Swap helps installation but is not
additional RAM; large labs or many routing/service processes need a larger worker.
Standard CPU credits avoid Unlimited surplus-credit charges but can substantially
slow installation or sustained load. Resize explicitly:

```bash
terraform plan -var='instance_type=t4g.micro'
terraform apply -var='instance_type=t4g.micro'
```

Public IPv4, EBS storage and applicable data transfer are additional charges.
Free Tier/trial eligibility is not assumed. Spot can cost less but can terminate
the worker; opt in with `-var='use_spot=true'` only if interruption is acceptable.
No fixed universal price or capacity guarantee is built into the generator.

## Remove the lab

```bash
terraform destroy
```

Stopping the instance alone does not remove its EBS volume. Destroying this project
removes its managed volume with the worker and its managed network resources.
Treat lab filesystem changes as disposable. The saved `arch.json` and generated
Ansible project are the reproducible source for rebuilding.
