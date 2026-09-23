## [AUTO-001] Preserve declarative configuration operations and target bindings
Rule-ID: AUTO-001
Kind: rule
Mode: all
Phase: configuration
Status: target_specification
Keywords: automation, tasks, operation, parameters, package, service, file, user, firewall
Applies: The later external NLP/configuration stage receives user requests after topology planning.
Required: Resolve an approved operation ID and its required parameters against the later generator catalog. Bind the request to an exact device_id and the plan configuration_targets runtime/interface references. This initial topology RAG does not implement that catalog or execute requests.
Forbidden: Do not emit executable code, activate disabled settings, replace custom operations or target all hosts by guesswork.
Expected: An external configuration request targeting the existing lab device; unfamiliar operations require clarification, not invented commands.
Verify: Compare task targets, dependencies and parameters with the source. Execution is outside the translator.
Sources: PROJECT
Related: AUTO-002, INPUT-001, SVC-HTTP

## [AUTO-002] Keep management access symbolic and separate from lab traffic
Rule-ID: AUTO-002
Kind: rule
Mode: all
Phase: configuration
Status: target_specification
Keywords: automation, connection, ssh, management, runtime, resource reference
Applies: Planning configuration of cloud-hosted source components.
Required: Preserve supplied access settings and secret references as JSON. Use symbolic references for unknown management endpoints. Associate tasks with source components and proposed hosting resources.
Forbidden: Do not invent public IPs, credentials, SSH reachability or a bastion. Do not confuse a worker management address with a lab interface address.
Expected: Access requirements are explicit without creating shortcuts between isolated lab networks.
Verify: Actual access, privileges and runtime targeting need external implementation and validation.
Sources: PROJECT
Related: AUTO-001, BACKEND-001, INPUT-001
