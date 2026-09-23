## [EX-SINGLE] One router forwards between its connected LANs
Rule-ID: EX-SINGLE
Kind: example
Mode: behavioral_lab
Phase: configuration
Status: target_specification
Keywords: single router, connected routes, no OSPF, no static
Applies: PC1--R1--PC2 uses separate addressed router interfaces.
Required: PC1=10.10.10.10/24 gateway 10.10.10.1; R1 lan0=10.10.10.1/24, lan1=10.20.20.1/24; PC2=10.20.20.20/24 gateway 10.20.20.1. Interfaces up, forwarding on, filters permit ICMP.
Forbidden: Do not add static/RIP/OSPF routes for these already connected networks or bypass R1.
Expected: Ping passes on connected routes alone. Disabling R1 forwarding prevents cross-LAN ping.
Verify: Inspect connected routes, gateways and captures on both R1 interfaces.
Sources: PROJECT
Related: ROUTE-001, BACKEND-003
