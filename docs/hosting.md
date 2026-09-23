# Educational AWS hosting policy

`net2cloud/hosting.py` selects one shared x86-64 Linux worker. Each source PC,
server and router will need its own isolated namespace; each source switch/bridge
will need its own isolated Linux bridge. Native ENIs are not allocated per lab
cable. Hub and unknown device semantics are unsupported, not silently approximated.

The reviewed [catalog](../net2cloud/data/educational_instances.json) contains Linux
On-Demand offers in **us-east-1** from the [official T3/T3a table](https://aws.amazon.com/ec2/instance-types/t3/).
Selection minimizes the catalog's hourly compute estimate among offers meeting the
memory reservation and USD 0.04/hour compute cap. It does not search all AWS
families/regions or promise the current global minimum price. Recheck prices and
availability before deployment; the snapshot date and source travel in the plan.

Reservations are 512 MiB for the worker plus 128 per PC, 256 per server/router,
and 64 per switch/bridge. These are provisional planning allowances, not measured
capacity. The profile stops at 16 devices/24 links or when no catalog offer fits;
it never silently increases the cap. Later packages, traffic load and protocol
requirements need a new capacity review.

The worker uses an 8 GiB encrypted gp3 root volume, no public IPv4, and Standard
CPU credit mode. [Standard mode](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-performance-instances-standard-mode.html)
limits bursting to available credits. No NAT gateway, Transit Gateway, peering,
bastion or internet gateway is added by this profile.

Storage, network, management access and taxes are excluded from the compute
estimate. A Linux AMI, management/bootstrap path and package delivery remain
explicit deployment dependencies. Private placement alone does not provide
Ansible/SSM connectivity. No cloud resources are created here and AWS is not
claimed to be free. Update the reviewed catalog/profile explicitly to support
another region, capacity or backend.
