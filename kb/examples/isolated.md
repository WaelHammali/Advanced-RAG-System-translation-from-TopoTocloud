## [EX-ISOLATED] Disconnected router components must remain isolated
Rule-ID: EX-ISOLATED
Kind: example
Mode: behavioral_lab
Phase: topology
Status: target_specification
Keywords: three routers, disconnected R3, isolation
Applies: Source graph contains PC1--R1--R2--PC2 and separately R3--PC3, with no link, shared LAN, tunnel or external lab path between components.
Required: Preserve the graph components, regardless of common AWS workers, VPC or TGW. Configure each component only as requested.
Forbidden: Do not create all-to-all lab routes because three routers exist or workers are mutually reachable.
Expected: PC1-to-PC3 ping fails. Internal flows in each component depend on that component's own configuration.
Verify: Probe the forbidden pair and inspect for transport/default-route leaks.
Sources: PROJECT
Related: MAP-002, AWS-003
