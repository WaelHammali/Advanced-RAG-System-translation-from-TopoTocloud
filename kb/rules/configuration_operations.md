## [AUTO-001] Preserve declarative configuration operations and target bindings
Rule-ID: AUTO-001
Kind: rule
Mode: all
Status: target_specification
Keywords: automation, tasks, operation, parameters, package, service, file, user, firewall
Applies: Architecture JSON supplies automation tasks or requests configurable services and protocols.
Required: Retain task IDs, target_ids, operation, parameters and dependencies inside cloud_plan.configuration. Bind each operation to the intended source component and proposed runtime.
Forbidden: Do not emit executable code, activate disabled settings, replace custom operations or target all hosts by guesswork.
Expected: Declarative JSON requirements for the AWS architecture; unfamiliar operations remain visible with implementation limitations.
Verify: Compare task targets, dependencies and parameters with the source. Execution is outside the translator.
Sources: PROJECT
Related: AUTO-002, INPUT-001, SVC-HTTP

## [AUTO-002] Keep management access symbolic and separate from lab traffic
Rule-ID: AUTO-002
Kind: rule
Mode: all
Status: target_specification
Keywords: automation, connection, ssh, management, runtime, resource reference
Applies: Planning configuration of cloud-hosted source components.
Required: Preserve supplied access settings and secret references as JSON. Use symbolic references for unknown management endpoints. Associate tasks with source components and proposed hosting resources.
Forbidden: Do not invent public IPs, credentials, SSH reachability or a bastion. Do not confuse a worker management address with a lab interface address.
Expected: Access requirements are explicit without creating shortcuts between isolated lab networks.
Verify: Actual access, privileges and runtime targeting need external implementation and validation.
Sources: PROJECT
Related: AUTO-001, BACKEND-001, INPUT-001
