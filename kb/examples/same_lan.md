## [EX-LAN] Local ping survives unrelated router failure
Rule-ID: EX-LAN
Kind: example
Mode: behavioral_lab
Status: target_specification
Keywords: same switch, same LAN, no routing, PC1, PC2
Applies: PC1 and PC2 attach to SW1 VLAN 10. SW1 also connects R1, which connects R2.
Required: PC1=10.10.10.10/24; PC2=10.10.10.20/24. Unique addresses, active switch ports and permitted ARP/ICMP. No gateways or routing protocols are needed for this local probe.
Forbidden: Do not make this flow depend on R1/R2 or add remote routes.
Expected: PC1 to 10.10.10.20 passes. Stopping R1/R2 does not break it; disabling the PC1 switch port does.
Verify: Probe lab addresses; inspect ARP/bridge forwarding and the two fault cases.
Sources: PROJECT
Related: L2-001, VERIFY-002
