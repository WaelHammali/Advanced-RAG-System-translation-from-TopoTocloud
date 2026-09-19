## [EX-VLAN] Same switch and prefix do not connect different VLANs
Rule-ID: EX-VLAN
Kind: example
Mode: behavioral_lab
Status: target_specification
Keywords: same switch, VLAN 10, VLAN 20, same prefix
Applies: PC1=10.10.10.10/24 is on SW1 access VLAN 10; PC2=10.10.10.20/24 is on SW1 access VLAN 20.
Required: Ports are up and ICMP allowed; no bridge between VLANs, proxy ARP, inter-VLAN routing or alternative path exists.
Forbidden: Do not remove VLAN separation to satisfy the shared prefix or the word switch.
Expected: PC1-to-PC2 ping fails because ordinary peer ARP stays within its VLAN.
Verify: Inspect VLAN membership, ARP and denied cross-VLAN delivery.
Sources: PROJECT
Related: L2-002, SEC-001
