# Generated educational Ansible project

Use a Linux controller with Python 3.11-3.13 and compatible `ansible-core`, and the
inventory exported by the matching Terraform project. No community collections
are required; the playbook uses Ansible built-ins and the worker's Docker CLI.

```bash
python -m pip install -r requirements.txt
ansible-playbook -i /path/to/terraform/inventory.json site.yml --syntax-check
ansible-playbook -i /path/to/terraform/inventory.json site.yml --private-key ~/.ssh/id_ed25519
```

The first actual run installs Docker and builds Debian 12 images, which downloads
packages. A tiny worker in Standard CPU-credit mode may take considerable time.
Increase its instance size if memory or CPU is insufficient. Generation and syntax
checks do not require cloud credentials or contact the worker.

The worker connects through SSH. Within it, source devices are labelled containers
with separate filesystems/network stacks and exactly the requested veth cables.
A switch is a VLAN-filtering Linux bridge inside its own container. Containers
have no management/data bypass, Docker bridge attachment or exposed host ports.
Privileged networking capabilities are needed for the lab; this design is for a
trusted educational worker, not hostile multi-tenant isolation.

`files/lab.json` maps each original component ID to its opaque runtime container
name. Inspect from the worker, substituting those names:

```bash
sudo docker exec PC1_CONTAINER ip address
sudo docker exec PC1_CONTAINER ping -c 3 PC2_LAB_IP
sudo docker exec ROUTER_CONTAINER vtysh -c 'show ip route'
sudo docker exec ROUTER_CONTAINER vtysh -c 'show ip ospf neighbor'
sudo docker exec WEB_CONTAINER curl http://WEB_LAB_IP/
```

Do not test lab reachability by pinging from the worker's management namespace.
A router daemon starting is not evidence of convergence or a valid return path.
HTTP remains reachable only over the lab's actual routing and filtering behavior.
No routes or fallback protocols are created to make tests pass.

A generated systemd unit starts the lab after Docker on reboot. Reapplying an
unchanged project leaves the running lab intact; manually changed routes/processes
are not continuously reconciled. Restarting the generated `net2cloud-LAB.service`
recreates this lab's containers and discards their writable state. Updating copied
assets also restarts that lab. Only resources bearing its ownership label/alias
are removed. Use distinct lab names for separate projects.

The manager does not measure conformance, recover every daemon failure, or promise
hardware/vendor parity. Test positive and negative flows after convergence.
Containers, Debian packages, kernel behavior and mutable image tags must be pinned
and integration-tested before making stronger reproducibility claims.
