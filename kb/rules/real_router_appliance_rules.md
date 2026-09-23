## [BACKEND-001] Isolate every lab device's forwarding stack
Rule-ID: BACKEND-001
Kind: rule
Mode: behavioral_lab
Phase: topology
Status: target_specification
Keywords: router appliance, namespace, container, EC2, FRR
Applies: Implementing behavioral_lab on AWS workers.
Required: Use one namespace per PC/server/router and one bridge per source switch/bridge. Runtime IDs and configuration_targets must match the deterministic plan. Isolate filesystem/process configuration for later FRR or service instances as well as routes/interfaces.
Forbidden: Do not share one routing table between routers or use automatic container host/default networking.
Expected: Interfaces and routing state belong to the intended node.
Verify: Inspect namespaces, bridge ports, process configuration and node routes.
Sources: PROJECT, LINUX-NETNS
Related: BACKEND-002, BACKEND-003

## [BACKEND-002] Realize each cable and switch port explicitly
Rule-ID: BACKEND-002
Kind: rule
Mode: behavioral_lab
Phase: topology
Status: target_specification
Keywords: virtual link, veth, VXLAN, unicast, router cable
Applies: Constructing local or cross-worker lab links.
Required: Current educational placement uses local veth pairs with exact endpoint runtime/interface IDs. Preserve per-link IPs and source prefixes. Cross-worker tunnels require a separate validated profile; do not introduce them into the current shared-worker plan.
Forbidden: Do not rely on outer AWS multicast for inner protocol traffic or merge separate cables.
Expected: Protocol and endpoint packets follow actual lab links; unrelated transport routes create no lab edges.
Verify: Capture inner frames at both ends; test ARP, protocol packets and link-down behavior.
Sources: PROJECT, LINUX-VXLAN, LINUX-LINK
Related: L2-003, MAP-002, VERIFY-003

## [BACKEND-003] Prevent transport and management forwarding bypass
Rule-ID: BACKEND-003
Kind: rule
Mode: behavioral_lab
Phase: topology
Status: target_specification
Keywords: underlay, overlay, shortcut, no bypass, default route
Applies: AWS or containers host the lab.
Required: Separate transport and lab prefixes. Prevent unintended worker routing, proxy ARP and masquerading between lab segments. Test traffic must originate in the intended node and use its lab routes.
Forbidden: Do not expose raw lab prefixes through AWS local/peering/TGW routes or container management egress.
Expected: Removing the only lab route/link breaks remote traffic even while workers stay manageable.
Verify: Inspect route namespaces and prove negative cases with captures.
Sources: PROJECT, LINUX-NETNS
Related: CORE-001, AWS-001, VERIFY-002

## [BACKEND-004] Verify router software and configuration readiness
Rule-ID: BACKEND-004
Kind: rule
Mode: behavioral_lab
Phase: configuration
Status: target_specification
Keywords: FRRouting, bootstrap, package, daemon, readiness
Applies: Provisioning router stacks.
Required: Pin and validate OS/FRR. Verify package access, installation, requested daemons, persisted config, interface state and forwarding. Enable only requested protocols.
Forbidden: Do not suppress setup errors or assume installed FRR means configured routing.
Expected: Readiness is separate from deployment and convergence; failed setup stops behavioral verification.
Verify: Record versions/configuration checks, then inspect live protocol/routes.
Sources: PROJECT, LINUX-SYSCTL
Related: PLAN-002, RIP-001, OSPF-001
