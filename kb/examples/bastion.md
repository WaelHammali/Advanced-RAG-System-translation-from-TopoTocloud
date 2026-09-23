## [EX-BASTION] Bastion-only SSH has a required negative test
Rule-ID: EX-BASTION
Kind: example
Mode: behavioral_lab
Phase: configuration
Status: target_specification
Keywords: bastion, SSH only, private host
Applies: A user requests management access to S1 through bastion B1 only.
Required: Use the declared management plane, working private management routing and credentials. Allow S1 TCP/22 from B1's intended path; remove other effective SSH permissions.
Forbidden: Do not open all VPC sources or add lab links for management convenience.
Expected: SSH through B1 passes; SSH from an unauthorized otherwise reachable management source fails. Lab ping is evaluated independently.
Verify: Test authorized and unauthorized SSH plus lab isolation.
Sources: PROJECT
Related: ACCESS-001, SEC-002
