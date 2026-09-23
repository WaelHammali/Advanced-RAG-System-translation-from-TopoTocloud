## [STATIC-001] Static remote routing requires a usable return path
Rule-ID: STATIC-001
Kind: rule
Mode: behavioral_lab
Phase: configuration
Status: target_specification
Keywords: static routing, two routers, next hop, return route
Applies: PC1--R1--R2--PC2 has distinct endpoint LANs and static routing.
Required: Require host routes/gateways, up router interfaces, forwarding, R1's route toward PC2 and R2's route toward PC1. Valid defaults may satisfy the lookups.
Forbidden: Do not add a missing reverse route or AWS bypass unless completing the configuration is requested.
Expected: Both paths plus permitted ICMP yield pass; one absent direction without an alternative yields fail.
Verify: Check both next hops and capture packets at R1/R2.
Sources: PROJECT, FRR-STATIC
Related: ROUTE-002, EX-STATIC, EX-NOROUTE

## [STATIC-002] Keep unavailable or invalid static next hops visible
Rule-ID: STATIC-002
Kind: rule
Mode: behavioral_lab
Phase: configuration
Status: target_specification
Keywords: wrong next hop, interface down, inactive route
Applies: A supplied static route has an unreachable next hop or failed link.
Required: Preserve intent and report the unusable route. Resolve recursive next hops only through supported routes actually present.
Forbidden: Do not force on-link behavior or replace the next hop just to obtain ping success.
Expected: No alternate usable route means failure even if route configuration text exists.
Verify: Compare configuration, neighbor resolution, selected routes and forwarding entries.
Sources: PROJECT, FRR-STATIC
Related: ROUTE-002, CORE-002
