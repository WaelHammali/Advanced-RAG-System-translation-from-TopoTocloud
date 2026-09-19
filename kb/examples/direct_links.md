## [EX-DIRECT] Two router-to-host cables are separate segments
Rule-ID: EX-DIRECT
Kind: example
Mode: behavioral_lab
Status: target_specification
Keywords: direct host, router ports, separate LAN
Applies: PC1 connects R1:lan0 and PC2 connects R1:lan1 on distinct cables; no switch joins them.
Required: PC1=10.10.10.10/24 gw 10.10.10.1; lan0=10.10.10.1/24; lan1=10.20.20.1/24; PC2=10.20.20.20/24 gw 10.20.20.1. Links up; forwarding and ICMP permitted.
Forbidden: Do not merge PC1/PC2 into one R1_DIRECT LAN.
Expected: Ping passes through R1's connected routing; turning off R1 forwarding makes it fail.
Verify: Verify separate link identities, L2 domains and packet traversal.
Sources: PROJECT
Related: MAP-002, ROUTE-001
