## [AUTO-001] Plan explicit Ansible operations with target bindings
Rule-ID: AUTO-001
Kind: rule
Mode: all
Status: target_specification
Keywords: ansible, tasks, operation, module, package, service, file, user, firewall
Applies: Architecture JSON supplies Ansible tasks or requests configurable services/protocols.
Required: Retain task IDs, target_ids, module/operation, parameters, variables and dependencies. Describe package, file/configuration, service, user or firewall intentions as requested. Scope operations to the component runtime, including a namespace/container when used.
Forbidden: No playbook YAML, execution, guessed all-host targeting, arbitrary replacement of custom tasks or disabled-setting activation.
Expected: A JSON ansible_plan for a separate generator; unfamiliar operations are retained with implementation limitations when necessary.
Verify: The generator resolves modules, privilege and runtime execution before rendering artifacts.
Sources: PROJECT, ANSIBLE-PACKAGE, ANSIBLE-SERVICE, ANSIBLE-TEMPLATE
Related: AUTO-002, INPUT-001, SVC-HTTP

## [AUTO-002] Resolve Ansible management connections at deployment time
Rule-ID: AUTO-002
Kind: rule
Mode: all
Status: target_specification
Keywords: ansible, connection, inventory, ssh, management, runtime, resource reference
Applies: Planning configuration of cloud-hosted source components.
Required: Preserve supplied connection settings and secret references. Use symbolic deployment outputs for unknown management endpoints. Associate each task with both its source component and its proposed runtime/worker.
Forbidden: Do not invent public IPs, credentials, SSH reachability or a bastion. Do not confuse a worker's management address with a lab interface address.
Expected: The generator can resolve worker access and component execution context without creating a shortcut between isolated lab networks.
Verify: Downstream tooling checks access, privileges and runtime targeting before applying tasks.
Sources: PROJECT
Related: AUTO-001, BACKEND-001, INPUT-001
