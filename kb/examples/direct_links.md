## [EX-DIRECT] Two router-to-host cables are separate segments
Rule-ID: EX-DIRECT
Kind: example
Mode: behavioral_lab
Phase: configuration
Status: target_specification
Keywords: direct host, router ports, separate LAN
Applies: PC1 connects R1:lan0 and PC2 connects R1:lan1 on distinct cables; no switch joins them.
Required: PC1=10.10.10.10/24 gw 10.10.10.1; lan0=10.10.10.1/24; lan1=10.20.20.1/24; PC2=10.20.20.20/24 gw 10.20.20.1. Links up; forwarding and ICMP permitted.
Forbidden: Do not merge PC1/PC2 into one R1_DIRECT LAN.
Expected: Ping passes through R1's connected routing; turning off R1 forwarding makes it fail.
Verify: Verify separate link identities, L2 domains and packet traversal.
Sources: PROJECT
Related: MAP-002, ROUTE-001

## [EX-PC-DIRECT] Two directly cabled PCs need no router for local traffic
Rule-ID: EX-PC-DIRECT
Kind: example
Mode: behavioral_lab
Phase: topology
Status: target_specification
Keywords: two PCs, direct cable, no router, peer, same subnet
Applies: PC1 eth0=10.0.0.1/24 and PC2 eth0=10.0.0.2/24 share one direct active cable with unique addresses and permitted ARP/ICMP.
Required: Preserve the one cable as a veth pair and both host stacks. Neither host needs a gateway or dynamic routing for this local destination.
Forbidden: Do not insert a switch, router, default gateway, static route, RIP or OSPF process.
Expected: Local ping can pass. Different subnets without routes or an inactive interface/cable can make it fail; retain those configurations.
Verify: Readiness checks IDs, addresses and both endpoints; actual ping requires runtime observation.
Sources: RFC-HOST, PROJECT
Related: L2-001, ROUTE-001

## [EX-STANDALONE] A standalone component is outside the current readiness policy
Rule-ID: EX-STANDALONE
Kind: example
Mode: behavioral_lab
Phase: topology
Status: target_specification
Keywords: single PC, one router, isolated node, standalone, empty topology
Applies: An architecture has a single component or an extra component with no valid link to another component.
Required: The deterministic input gate reports missing links or isolated_device before retrieval or model calls, even if all IP fields are supplied.
Forbidden: Do not fabricate a peer, switch or router to make input ready. Do not describe standalone computers as invalid in real networking.
Expected: No translation plan under the current no-isolated-components project policy. Two directly connected PCs can satisfy that policy.
Verify: Offline check returns not_ready; a self-link does not count as attachment.
Sources: PROJECT
Related: INPUT-001, EX-PC-DIRECT

## [EX-PREFIX31] Point-to-point prefix boundaries must not trigger invented routing
Rule-ID: EX-PREFIX31
Kind: example
Mode: behavioral_lab
Phase: topology
Status: target_specification
Keywords: /31, /32, point-to-point, direct PCs, host route
Applies: Two supporting IPv4 stacks share a direct point-to-point cable with 10.0.0.0/31 and 10.0.0.1/31.
Required: Preserve both /31 endpoint addresses; both are host addresses in this point-to-point context.
Forbidden: Do not reserve one endpoint as network/broadcast or widen the prefix. Do not assume two different /32 host addresses automatically provide peer routes.
Expected: With active links and permitted traffic the /31 peer path can work. A /32-only pair without peer routing is a distinct failure case.
Verify: Inspect connected routes and run bidirectional probes. Readiness accepts syntax; it does not prove reachability or support on every device.
Sources: RFC-P2P31, PROJECT
Related: EX-PC-DIRECT, ROUTE-001
