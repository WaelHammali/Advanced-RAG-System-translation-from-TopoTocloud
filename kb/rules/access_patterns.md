## [ACCESS-001] Bastion access must not create lab shortcuts
Rule-ID: ACCESS-001
Kind: rule
Mode: behavioral_lab
Phase: configuration
Status: target_specification
Keywords: bastion, SSH, jump host, private host
Applies: A bastion is explicitly required for management or as a lab device.
Required: Declare its plane. Permit target SSH from the intended bastion path only; provide working credentials/private management. A lab bastion keeps its source links.
Forbidden: Do not infer a bastion from 'no bastion', allow every SSH source, or bridge lab LANs through management.
Expected: Authorized SSH passes; unauthorized direct SSH fails. Lab ping follows its own topology and policy.
Verify: Probe jump access and a denied direct source; inspect plane separation.
Sources: PROJECT, AWS-SG
Related: EX-BASTION, BACKEND-003

## [ACCESS-002] Management exposure must not rewrite lab LANs
Rule-ID: ACCESS-002
Kind: rule
Mode: behavioral_lab
Phase: configuration
Status: target_specification
Keywords: public PC, private server, management, split subnet
Applies: Management/public exposure differs between nodes on one lab LAN.
Required: Keep source LAN/VLAN membership intact. Provide separate management and model explicit lab egress at its declared edge.
Forbidden: Do not make PCs public by default or split a lab LAN merely for SSH access.
Expected: Same-LAN hosts keep local delivery behavior; public worker access does not prove lab reachability.
Verify: Compare L2 membership and test lab/worker IPs separately.
Sources: PROJECT
Related: L2-001, NAT-001
