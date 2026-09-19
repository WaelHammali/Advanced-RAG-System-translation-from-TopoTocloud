## [EX-NAT] Private workload egress preserves lab routing
Rule-ID: EX-NAT
Kind: example
Mode: behavioral_lab
Status: target_specification
Keywords: private server, internet, NAT, no public PC
Applies: A private S1 explicitly requires outbound access through its configured lab egress router.
Required: Preserve S1's LAN/gateway and permitted egress path; configure lab NAT only if required. If the outer design chooses a zonal public AWS NAT gateway, build its public subnet/IGW/private routes even with no public workload host.
Forbidden: Do not split S1's original lab LAN or use internet egress to connect isolated lab LANs.
Expected: Authorized external traffic can pass through the configured edge. Other flows retain their original permissions and routing dependencies.
Verify: Probe a controlled external endpoint, verify return/NAT state and test isolated internal destinations.
Sources: PROJECT
Related: NAT-001, NAT-002
