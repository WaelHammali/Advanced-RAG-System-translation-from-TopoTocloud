## [ROUTE-001] Connected networks need forwarding without a dynamic protocol
Rule-ID: ROUTE-001
Kind: rule
Mode: behavioral_lab
Status: target_specification
Keywords: connected routes, one router, gateway, forwarding
Applies: A router has working addressed interfaces in both endpoint LANs.
Required: Use its connected routes with forwarding enabled. Hosts need a gateway or suitable specific route for the remote subnet. Filters/replies must permit the exchange.
Forbidden: Do not require static routes, RIP or OSPF for directly attached networks.
Expected: PC1--R1--PC2 can pass between attached subnets without dynamic routing; disabled forwarding or missing host routing can cause failure.
Verify: Inspect connected/kernel routes, forwarding, interfaces and host routes.
Sources: RFC-ROUTER, LINUX-SYSCTL
Related: EX-SINGLE, STATIC-001

## [ROUTE-002] Evaluate selected routes in both directions
Rule-ID: ROUTE-002
Kind: rule
Mode: behavioral_lab
Status: target_specification
Keywords: longest prefix, default, route preference, return path
Applies: Predicting reachability through routers.
Required: Evaluate longest-prefix lookup, implementation-specific preference, next-hop resolution, interface state and filters at every hop. Evaluate reply paths independently; asymmetry can be valid.
Forbidden: Do not infer failure solely from absence of a specific route if a usable default/alternative exists.
Expected: Both effective paths are required; a discard or more-specific conflicting route can override a broader path.
Verify: Inspect selected route provenance and kernel forwarding for the tested addresses.
Sources: RFC-ROUTER, FRR-STATIC
Related: STATIC-001, VERIFY-002
