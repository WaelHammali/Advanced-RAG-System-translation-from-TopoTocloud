## [SEC-001] Preserve firewall placement and policy semantics
Rule-ID: SEC-001
Kind: rule
Mode: behavioral_lab
Phase: configuration
Status: target_specification
Keywords: ACL, firewall, deny, allow, stateful, ICMP
Applies: Source topology includes host filters, router ACLs or inline firewalls.
Required: Model placement, direction, ordering, statefulness, default action and protocols. Enforce inner policy on the actual lab device; evaluate replies.
Forbidden: Do not substitute allow-all VPC CIDRs or treat an unattached SG as an enforced firewall.
Expected: Correct routes may coexist with intentionally failed ping; permitted SSH does not imply permitted ICMP.
Verify: Probe allowed/denied flows and inspect matching rules/counters.
Sources: PROJECT
Related: SEC-002, SEC-003, VERIFY-001

## [SEC-002] Separate outer transport security from inner lab security
Rule-ID: SEC-002
Kind: rule
Mode: all
Phase: configuration
Status: target_specification
Keywords: security group, NACL, outer packet, inner packet
Applies: AWS carries encapsulated lab packets.
Required: Use AWS controls for worker/tunnel/management traffic; enforce inner policies on modeled lab devices. SGs are stateful allow controls; NACLs are stateless ordered subnet controls.
Forbidden: Do not assume outer SG permissions reproduce inner ACLs. A restrictive SG does not cancel other SG allow rules.
Expected: Transport delivery and lab policy are separate requirements and failure causes.
Verify: Record transport permission checks separately from inner policy probes.
Sources: AWS-SG, AWS-NACL, PROJECT
Related: BACKEND-003, SEC-001

## [SEC-003] Ping and routing-protocol permissions are separate
Rule-ID: SEC-003
Kind: rule
Mode: behavioral_lab
Phase: configuration
Status: target_specification
Keywords: ICMP echo, OSPF 89, RIP 520, SSH
Applies: Creating or testing traffic filtering.
Required: Evaluate ICMP request/reply and application flows separately. Permit requested routing protocols only on intended links: OSPF IP protocol 89; RIPv2 UDP 520.
Forbidden: Do not infer ICMP permission from SSH access or model OSPF as TCP/UDP port 89.
Expected: Routes may be learned while ICMP is blocked; permitted ICMP may still lack routing.
Verify: Capture data/protocol traffic and verify expected flows independently.
Sources: PROJECT, FRR-OSPF, RFC-RIP
Related: RIP-001, OSPF-001
