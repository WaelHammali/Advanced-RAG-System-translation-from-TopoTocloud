## [EX-OSPF] Two-router point-to-point OSPFv2
Rule-ID: EX-OSPF
Kind: example
Mode: behavioral_lab
Phase: configuration
Status: target_specification
Keywords: OSPF, area 0, Full, point-to-point
Applies: PC1--R1--R2--PC2 uses isolated lab links.
Required: PC1=10.10.10.10/24 gw 10.10.10.1; R1 LAN=10.10.10.1/24 WAN=10.255.0.1/30; R2 WAN=10.255.0.2/30 LAN=10.20.20.1/24; PC2=10.20.20.20/24 gw 10.20.20.1. Interfaces/forwarding up, ICMP/protocol 89 allowed. IDs 1.1.1.1/2.2.2.2; WANs point-to-point area 0, matching timers; advertise LANs passively in area 0. No fallback routes.
Forbidden: Do not claim success from installed FRR or AWS transport alone.
Expected: Full WAN adjacency and selected remote OSPF routes permit ping through both routers.
Verify: Inspect adjacency, LAN advertisements, kernel routes and required packet traversal.
Sources: PROJECT
Related: OSPF-001, OSPF-002
