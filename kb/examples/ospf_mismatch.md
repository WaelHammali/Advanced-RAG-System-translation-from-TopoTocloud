## [EX-OSPF-BAD] OSPF area mismatch keeps the remote LAN unreachable
Rule-ID: EX-OSPF-BAD
Kind: example
Mode: behavioral_lab
Phase: configuration
Status: target_specification
Keywords: OSPF area mismatch, no adjacency, expected failure
Applies: PC1=10.10.10.10/24 gw 10.10.10.1; R1 LAN=10.10.10.1/24 WAN=10.255.0.1/30; R2 WAN=10.255.0.2/30 LAN=10.20.20.1/24; PC2=10.20.20.20/24 gw 10.20.20.1.
Required: Links and forwarding work, ICMP/OSPF allowed. Preserve WAN area 0 on R1 versus area 1 on R2. LANs advertised locally; no remote/default/static/other-protocol routes. Start from settled fresh configuration.
Forbidden: Do not change areas or add fallback routing unless the user requests a repair.
Expected: Required WAN adjacency is absent and PC1-to-PC2 ping fails.
Verify: Check mismatch, neighbor state and missing remote routes; distinguish expected failure from setup failure.
Sources: PROJECT
Related: OSPF-003, VERIFY-001
