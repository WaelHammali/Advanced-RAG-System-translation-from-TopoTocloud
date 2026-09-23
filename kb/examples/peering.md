## [EX-PEERING] Peering is only an optional transport between two workers
Rule-ID: EX-PEERING
Kind: example
Mode: behavioral_lab
Phase: configuration
Status: target_specification
Keywords: two routers, VPC peering, transport
Applies: R1 and R2 lab nodes are placed on workers in two peered VPCs.
Required: Configure transport endpoint reachability and an explicit lab link between R1/R2. Keep lab addresses isolated. Endpoint LAN routes must be supplied/learned within the lab.
Forbidden: Do not route PC LAN prefixes directly over peering or infer lab routing from two routers.
Expected: Transport ping can pass while lab PC ping fails for missing routes; valid lab routing can enable the PC flow.
Verify: Probe worker reachability and lab reachability separately; remove a required lab route to prove no bypass.
Sources: PROJECT
Related: AWS-002, STATIC-001
