## [RIP-001] Configure RIPv2 on actual lab links
Rule-ID: RIP-001
Kind: rule
Mode: behavioral_lab
Status: target_specification
Keywords: RIP, RIPv2, UDP 520, 224.0.0.9
Applies: Architecture routing configuration requests or supplies RIPv2.
Required: Set version, participating lab interfaces, passive behavior and advertised LANs. Honor filters/authentication; run the protocol inside the isolated router stack.
Forbidden: Do not treat the word RIP as learned routes, enable explicitly excluded RIP, or add static fallback.
Expected: Remote ping can pass after usable RIP routes exist in both directions and data policy permits it.
Verify: Check updates, remote prefixes and route origin. RIP has no OSPF-style Full adjacency.
Sources: RFC-RIP, FRR-RIP, PROJECT
Related: RIP-002, EX-RIP

## [RIP-002] Check RIP updates and convergence
Rule-ID: RIP-002
Kind: rule
Mode: behavioral_lab
Status: target_specification
Keywords: passive interface, metric 16, hop limit, update loss
Applies: Validating RIPv2 or a RIP failure exercise.
Required: Permit declared update transport. RIPv2 uses UDP 520 and multicast 224.0.0.9; FRR can use explicit unicast neighbors. Set passive behavior and honor timers/filters.
Forbidden: Do not assume immediate convergence or inject static routes after learned routes expire.
Expected: Metric 16 is unreachable. Blocked updates can remove reachability after aging; explicit alternatives may change the outcome.
Verify: Observe learning/expiry within declared bounds and retest data traffic.
Sources: RFC-RIP, FRR-RIP
Related: VERIFY-003, RIP-001
