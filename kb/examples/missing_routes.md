## [EX-NOROUTE] Missing remote or return routes correctly prevent ping
Rule-ID: EX-NOROUTE
Kind: example
Mode: behavioral_lab
Status: target_specification
Keywords: no routes, missing return route, ping fails
Applies: PC1=10.10.10.10/24 gw 10.10.10.1 connects R1 LAN=10.10.10.1/24; R1 WAN=10.255.0.1/30 connects R2 WAN=10.255.0.2/30; R2 LAN=10.20.20.1/24 connects PC2=10.20.20.20/24 gw 10.20.20.1.
Required: Links up, forwarding enabled, ICMP permitted. Explicitly no remote static/default/dynamic routes. In the return-route variant, only R1 has a route to PC2's LAN via R2.
Forbidden: Do not repair the deliberately absent routes or add peering/TGW for raw lab prefixes.
Expected: Both variants fail PC1-to-PC2 ping. R1/R2 can still ping directly connected WAN addresses. This is expected behavior, not a translation defect.
Verify: Inspect missing selected routes and packet path; record predicted fail separately from conformance.
Sources: PROJECT
Related: STATIC-001, VERIFY-001
