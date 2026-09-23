## [NAT-001] Internet requires an explicit lab egress design
Rule-ID: NAT-001
Kind: rule
Mode: behavioral_lab
Phase: configuration
Status: target_specification
Keywords: internet, outbound, NAT, default route
Applies: Source intent explicitly requires external access or NAT.
Required: Model the egress edge, permitted destinations, route/NAT policy and replies. Separate lab NAT from AWS NAT for worker provisioning.
Forbidden: Do not add internet/NAT to repair internal routing or let egress connect isolated lab components.
Expected: Authorized external traffic may pass while internal isolation and required router traversal persist.
Verify: Probe a controlled external endpoint and forbidden internal pairs; inspect translation state.
Sources: PROJECT
Related: NAT-002, EX-NAT

## [NAT-002] Complete the chosen private-workload NAT infrastructure
Rule-ID: NAT-002
Kind: rule
Mode: all
Phase: configuration
Status: target_specification
Keywords: private subnet, zonal public NAT gateway, IGW
Applies: The chosen transport/cloud-native egress uses a zonal public AWS NAT gateway.
Required: Provide a suitable public NAT subnet, IGW path, public allocation and private routes even when no workload host is public. Scope this rule to that NAT form.
Forbidden: Do not skip NAT because there is no public PC, or use AWS NAT instead of lab router routes.
Expected: Egress infrastructure is complete; policies and endpoint response still determine reachability. Other NAT forms require separate reviewed patterns.
Verify: Check dependencies/routes and probe a controlled reachable destination.
Sources: AWS-ROUTES, PROJECT
Related: NAT-001
