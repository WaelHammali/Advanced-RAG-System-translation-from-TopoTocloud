## [EX-STATIC] Two routers with complete static routing
Rule-ID: EX-STATIC
Kind: example
Mode: behavioral_lab
Status: target_specification
Keywords: static routes, PC1 R1 R2 PC2, reverse route
Applies: PC1--R1--R2--PC2; each end is a different LAN.
Required: PC1=10.10.10.10/24 gw 10.10.10.1; R1 LAN=10.10.10.1/24, WAN=10.255.0.1/30; R2 WAN=10.255.0.2/30, LAN=10.20.20.1/24; PC2=10.20.20.20/24 gw 10.20.20.1. R1 routes 10.20.20.0/24 via 10.255.0.2; R2 routes 10.10.10.0/24 via 10.255.0.1. Links/up, forwarding/on, ICMP/allowed.
Forbidden: Do not add an AWS path bypassing R1 or R2.
Expected: Ping passes through R1 then R2; reply traverses R2 then R1.
Verify: Inspect selected static routes and capture both directions on both routers.
Sources: PROJECT
Related: STATIC-001, VERIFY-002
