## [EX-RIP] Two-router RIPv2 learns both remote LANs
Rule-ID: EX-RIP
Kind: example
Mode: behavioral_lab
Phase: configuration
Status: target_specification
Keywords: RIPv2, dynamic routing, learned routes
Applies: PC1--R1--R2--PC2 uses isolated Ethernet lab links.
Required: PC1=10.10.10.10/24 gw 10.10.10.1; R1 LAN=10.10.10.1/24 WAN=10.255.0.1/30; R2 WAN=10.255.0.2/30 LAN=10.20.20.1/24; PC2=10.20.20.20/24 gw 10.20.20.1. Links/forwarding up; allow ICMP and RIP. Enable RIPv2 LAN/WAN participation, passive LANs, active WANs; no fallback routes.
Forbidden: Do not add remote static routes or require OSPF-style Full neighbors.
Expected: Ping passes after both remote LANs are learned and selected. Block updates and wait for route expiry: ping fails without alternatives.
Verify: Inspect received updates, RIP route provenance, forwarding entries and bounded failure/recovery.
Sources: PROJECT
Related: RIP-001, RIP-002
