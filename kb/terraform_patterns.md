## [TF-001] Plan transport and lab configuration for one downstream generator
Rule-ID: TF-001
Kind: rule
Mode: behavioral_lab
Status: target_specification
Keywords: Terraform, Ansible, compiler, intermediate representation
Applies: Planning a behavioral_lab deployment from architecture JSON.
Required: Describe AWS transport/workers in cloud_plan and isolated lab nodes, links, addresses, routing and policy in ansible_plan. A separate generator renders Terraform and Ansible from that plan and the attached architecture.
Forbidden: Do not reconstruct routes from counts, public-IP guesses or an inconsistent second parser.
Expected: Both plan sections agree on component IDs, interfaces, addresses, protocols and dependencies. RAG outputs structured intentions, not files.
Verify: The downstream generator validates its capabilities and artifact references before deployment.
Sources: PROJECT
Related: INPUT-001, TF-002

## [TF-002] Deployment success differs from behavioral verification
Rule-ID: TF-002
Kind: rule
Mode: behavioral_lab
Status: target_specification
Keywords: terraform validate, apply, readiness, status
Applies: Reporting generation or deployment outcomes.
Required: Report artifact validation, provisioning, node/protocol readiness and conformance separately. Fail the relevant stage on errors; leave unmeasured observations as not_run.
Forbidden: Do not claim a working lab from terraform validation/apply or printed neighbor output.
Expected: Negative labs may conform while ping fails. Unimplemented backends are not ready.
Verify: Require measured evidence for each claimed completed behavior.
Sources: PROJECT
Related: CORE-003, VERIFY-001
