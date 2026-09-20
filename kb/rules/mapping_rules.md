## [MAP-001] Map source devices to behavioral roles
Rule-ID: MAP-001
Kind: rule
Mode: behavioral_lab
Status: target_specification
Keywords: PC, server, router, switch, firewall, mapping
Applies: Translating a physical network in behavioral_lab mode.
Required: Host: isolated network stack. Router: isolated forwarding stack with requested routing. Switch: bridge with declared ports/VLANs. Firewall: policy at its declared point. AWS resources host transport.
Forbidden: Do not equate router with VPC, switch with AWS subnet, or inline firewall with SG. Do not invent a lab router merely to own a VPC.
Expected: No-router same-LAN input remains a lab without a router; router-dependent traffic traverses router stacks.
Verify: Map every source object to its runtime and separate transport placement.
Sources: PROJECT, LINUX-NETNS, LINUX-BRIDGE
Related: BACKEND-001, L2-001

## [MAP-002] Preserve exact links and disconnected components
Rule-ID: MAP-002
Kind: rule
Mode: behavioral_lab
Status: target_specification
Keywords: topology graph, chain, ring, disconnected, direct host
Applies: A topology contains multiple routers, switch ports or disconnected components.
Required: Represent links by endpoint interfaces. Keep separate router-to-host cables separate. Preserve source graph components, switch ports and cable identities regardless of worker placement.
Forbidden: Do not merge direct hosts into one LAN or connect every VPC because there are three routers.
Expected: Disconnected components stay disconnected; a chain retains required intermediate routers unless an explicit alternative exists.
Verify: Compare source/realized adjacency; probe forbidden pairs and declared faults.
Sources: PROJECT
Related: BACKEND-002, EX-ISOLATED, EX-DIRECT

## [MAP-003] Declare behavioral lab or cloud-native migration mode
Rule-ID: MAP-003
Kind: rule
Mode: all
Status: target_specification
Keywords: migration, emulation, cloud native, mode
Applies: Selecting the translation's promised level of equivalence.
Required: Use behavioral_lab for real routing exercises. cloud_native may use AWS-managed routing when its connectivity-only scope and differences are accepted.
Forbidden: Do not label peering or TGW reachability as preserved router paths, Ethernet, RIP or OSPF.
Expected: Behavioral mode preserves supported protocol/path conditions. Cloud-native mode reports adaptations and no router-failure equivalence.
Verify: Record mode and unsupported properties before declaring a plan ready.
Sources: PROJECT, AWS-ROUTES
Related: CORE-001, AWS-001
