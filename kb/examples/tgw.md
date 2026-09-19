## [EX-TGW] A three-router chain still depends on its middle router
Rule-ID: EX-TGW
Kind: example
Mode: behavioral_lab
Status: target_specification
Keywords: TGW, three router chain, R2 failure, transit
Applies: PC1--R1--R2--R3--PC3 has distinct endpoint LANs and no alternate lab links.
Required: Supply usable host gateways and static or correctly converged dynamic routes in both directions. Links/forwarding/ICMP work. TGW may connect worker transport endpoints, but actual lab links remain R1-R2 and R2-R3.
Forbidden: Do not create an R1-R3 lab route through TGW that bypasses R2.
Expected: Baseline PC1-to-PC3 ping passes. Disabling R2 forwarding or its only required link makes ping fail after the relevant state settles.
Verify: Capture inner traffic at R2 and test the declared fault, then restore baseline.
Sources: PROJECT
Related: AWS-003, VERIFY-002
