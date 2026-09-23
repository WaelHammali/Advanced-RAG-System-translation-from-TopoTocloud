## [AWS-001] AWS local routes do not establish router traversal
Rule-ID: AWS-001
Kind: rule
Mode: all
Phase: configuration
Status: target_specification
Keywords: VPC, local route, appliance routing, bypass
Applies: Using AWS routes alongside a behavioral network.
Required: Treat VPC routes as transport. A native appliance backend needs supported explicit insertion, return routing and evidence of traversal.
Forbidden: Do not assume a router EC2 or disabled source/destination checks redirects workload packets.
Expected: Underlay reachability is separate from lab reachability.
Verify: Inspect route targets and captures; disable required router forwarding and repeat probes.
Sources: AWS-ROUTES, PROJECT
Related: BACKEND-003, MAP-003

## [AWS-002] Peering carries transport without creating lab adjacency
Rule-ID: AWS-002
Kind: rule
Mode: all
Phase: configuration
Status: target_specification
Keywords: two routers, VPC peering, non-transitive
Applies: Transport uses AWS VPC peering.
Required: Validate supported non-overlapping VPC addressing and bidirectional routes; restrict transport to intended endpoints. Realize router lab links separately.
Forbidden: Do not choose peering from router count or route raw lab LANs around routers; do not assume transitive peering.
Expected: Tunnel endpoints may communicate while PC reachability still requires lab routes and policies.
Verify: Test transport and missing-route lab failures separately.
Sources: AWS-PEERING, PROJECT
Related: EX-PEERING, BACKEND-003

## [AWS-003] Transit Gateway must preserve lab isolation and paths
Rule-ID: AWS-003
Kind: rule
Mode: all
Phase: configuration
Status: target_specification
Keywords: three routers, TGW, transit gateway, chain, disconnected
Applies: Transport uses AWS Transit Gateway.
Required: Design attachment/route propagation and endpoint connectivity explicitly. Preserve the independent source graph and its disconnected components.
Forbidden: Do not translate router count into all-to-all lab routes or use TGW as the middle lab router.
Expected: Transport can be hub-connected while PC1--R1--R2--R3--PC3 still depends on required lab routers.
Verify: Prove no R2 bypass and no forbidden connectivity between disconnected lab components.
Sources: AWS-TGW, PROJECT
Related: EX-TGW, EX-ISOLATED

## [AWS-004] Distinguish AWS ENI limits from virtual lab ports
Rule-ID: AWS-004
Kind: rule
Mode: all
Phase: configuration
Status: target_specification
Keywords: ENI, interfaces, t3.medium, instance size
Applies: Selecting native-router or overlay-worker capacity.
Required: Validate actual instance ENI limits. At review, t3.medium and t3.large each list at most three interfaces. Size virtual-port workers separately by workload.
Forbidden: Do not map four/five ports to t3.medium or six-plus to t3.large; virtual lab ports need not each consume an ENI.
Expected: A native instance exceeding required ENI capacity is infeasible; choose a capable backend without merging lab links.
Verify: Recheck the selected instance specifications and record capacity assumptions.
Sources: AWS-ENI, PROJECT
Related: BACKEND-001, CORE-003
