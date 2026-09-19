## [OSPF-001] Derive OSPFv2 configuration from interfaces and topology
Rule-ID: OSPF-001
Kind: rule
Mode: behavioral_lab
Status: target_specification
Keywords: OSPF, protocol 89, area, router ID
Applies: Architecture routing configuration requests or supplies OSPFv2.
Required: Plan FRR OSPF using the supplied router IDs, interface prefixes, areas, network types, costs, timers, authentication and passive LAN settings. Correct operation requires compatible settings and unique router IDs; preserve explicitly supplied errors.
Forbidden: Do not guess prefixes from public IPs, call OSPF TCP/UDP port 89, or enable excluded protocols.
Expected: Remote ping can pass after required OSPF routes are installed and request/reply policies permit it.
Verify: Check protocol 89 on lab links, expected neighbor states and selected kernel routes.
Sources: FRR-OSPF, PROJECT
Related: OSPF-002, OSPF-003, EX-OSPF

## [OSPF-002] Validate OSPF neighbors according to network type
Rule-ID: OSPF-002
Kind: rule
Mode: behavioral_lab
Status: target_specification
Keywords: Full, 2-Way, DR, BDR, point-to-point, multicast
Applies: Checking OSPF readiness on realized links.
Required: Require Full for a two-router point-to-point link. On broadcast LANs evaluate DR/BDR roles; some DROther pairs normally remain 2-Way. Carry required protocol traffic.
Forbidden: Do not require all pairs Full or equate ordinary AWS peering/TGW with Ethernet adjacency.
Expected: Correct adjacency and advertisements can produce routes; adjacency alone cannot prove endpoint ping.
Verify: Inspect interfaces, neighbors, advertisements and selected forward/reverse routes.
Sources: FRR-OSPF, AWS-MULTICAST
Related: BACKEND-002, OSPF-001

## [OSPF-003] Preserve OSPF mismatches and missing advertisements
Rule-ID: OSPF-003
Kind: rule
Mode: behavioral_lab
Status: target_specification
Keywords: area mismatch, passive transit, missing network
Applies: OSPF input contains incompatible link settings, failed links or omitted LANs.
Required: Preserve explicit configuration, mismatches and omissions after input readiness passes. Describe unresolved implementation requirements in limitations; protocol-semantic checks and clarification remain outside the translation model.
Forbidden: Do not change area/cost, add static routes or redistribute other protocols to hide failure.
Expected: With no alternatives, missing required remote forwarding yields failure after state settles; a running daemon is insufficient.
Verify: Check adjacency, prefix advertisement and route withdrawal; distinguish startup and steady state.
Sources: PROJECT, FRR-OSPF
Related: CORE-002, EX-OSPF-BAD
