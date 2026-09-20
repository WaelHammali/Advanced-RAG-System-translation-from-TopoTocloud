## [L2-001] Same VLAN and subnet permit local ping without a router
Rule-ID: L2-001
Kind: rule
Mode: behavioral_lab
Status: target_specification
Keywords: same switch, same LAN, meme switch, ping, ARP
Applies: Ordinary IPv4 hosts share an active Ethernet segment/VLAN and compatible on-link addresses.
Required: Resolve the peer locally and use the declared switch path; require unique addresses, up links and permitted request/reply.
Forbidden: Do not require static routes, RIP, OSPF or a default gateway for the local destination.
Expected: Local ping can pass even when attached R1/R2 stop. Same switch alone is insufficient if VLAN/IP conditions differ.
Verify: Probe peer lab IP, inspect ARP and switching, then stop the unrelated router.
Sources: RFC-HOST, PROJECT
Related: L2-002, EX-LAN

## [L2-002] VLAN and IP boundaries must both be modeled
Rule-ID: L2-002
Kind: rule
Mode: behavioral_lab
Status: target_specification
Keywords: VLAN, subnet, access port, trunk, inter-VLAN
Applies: Hosts share a switch but differ in VLAN or IPv4 subnet.
Required: Preserve access/trunk membership. Different IP subnets ordinarily need a usable gateway/route; isolated VLANs require explicit routing or bridging.
Forbidden: Do not connect VLANs because prefixes match or silently add proxy ARP/trunks.
Expected: Same-prefix hosts on isolated VLANs cannot communicate by ordinary ARP. Explicit inter-VLAN routing can permit inter-subnet traffic.
Verify: Check port membership, tagging, on-link decisions and both route directions.
Sources: LINUX-BRIDGE, RFC-HOST
Related: ROUTE-001, EX-VLAN

## [L2-003] Preserve switch ports and switching paths
Rule-ID: L2-003
Kind: rule
Mode: behavioral_lab
Status: target_specification
Keywords: switch chain, bridge, trunk, STP, loop
Applies: Several switches/links form a source LAN.
Required: Realize bridge nodes with declared links/VLANs and port-down behavior. Require a validated STP/loop-control capability when requested; the current educational generator rejects active switch/VLAN cycles because STP is disabled.
Forbidden: Do not universally allocate one subnet per switch or flatten switch chains while claiming identical faults.
Expected: Hosts can share an L2 domain across multiple switches; traffic follows the active switching path.
Verify: Test port failures/VLAN boundaries and report unsupported vendor switching features.
Sources: PROJECT, LINUX-BRIDGE
Related: MAP-002, BACKEND-002
