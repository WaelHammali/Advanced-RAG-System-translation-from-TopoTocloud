## [CORE-001] Preserve network behavior and intentional failures
Rule-ID: CORE-001
Kind: rule
Mode: behavioral_lab
Status: target_specification
Keywords: real pattern, translation, traduction, ping, isolation
Applies: Any translation claiming the same forwarding behavior as a source network.
Required: Preserve links, VLANs, addresses, selected routes, filtering, required transit nodes and declared failures. AWS transport carries the lab without alternate lab forwarding.
Forbidden: Do not add bridges, routes, full connectivity or redistribution just to make ping succeed.
Expected: Ping passes only when the configured lab permits request AND reply. Same-LAN traffic has no unrelated router dependency.
Verify: Compare expected successes/failures, route provenance and packet traversal.
Sources: PROJECT
Related: CORE-002, CORE-003, VERIFY-001

## [CORE-002] Unspecified configuration differs from explicitly absent configuration
Rule-ID: CORE-002
Kind: rule
Mode: behavioral_lab
Status: target_specification
Keywords: missing, no routes, not configured, preserve, inference
Applies: The caller's architecture JSON supplies, omits or disables configuration.
Required: The application checks input readiness before translation. Preserve explicit values, intentional failures and absent routes after that gate. Clarification remains caller-owned; no model-generated repairs.
Forbidden: Do not interpret automatic addressing as permission to add routing, or 'no OSPF' as an OSPF request.
Expected: Absent remote routing stays absent. Unknown settings stay unresolved; omitted fields do not authorize inventing routes or services.
Verify: Audit generated links, routes and protocols against input provenance.
Sources: PROJECT
Related: INPUT-001, STATIC-001

## [CORE-003] Return only a JSON plan for a separate generator
Rule-ID: CORE-003
Kind: rule
Mode: all
Status: target_specification
Keywords: JSON, plan, generator, Ansible, Terraform, boundaries
Applies: Every architecture JSON planning request.
Required: Describe cloud mapping and Ansible task intentions with exact input targets and parameters. Preserve the source architecture. A separate generator renders files and resolves runtime references.
Forbidden: The translation model emits no dialogue, field-validation report, executable code, deployment status or fabricated test results. Application readiness errors are a separate response before translation.
Expected: One JSON plan with cloud_plan, ansible_plan, rule_ids and limitations. Backend dependencies describe requirements, not completed work.
Verify: The application blocks incomplete identities, links and interface addresses; the downstream generator checks its capabilities and resulting artifacts.
Sources: PROJECT
Related: VERIFY-001, TF-002
