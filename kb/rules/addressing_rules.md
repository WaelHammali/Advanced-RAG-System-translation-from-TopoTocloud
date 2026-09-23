## [ADDR-001] Preserve addresses and allocate only authorized missing values
Rule-ID: ADDR-001
Kind: rule
Mode: behavioral_lab
Phase: topology
Status: target_specification
Keywords: CIDR, IP, gateway, automatic addressing
Applies: Planning host, router-interface and link addresses.
Required: Retain every device/link network object and endpoint IP. Runtime IDs are deterministic; use the device prefix for its main IP and the link prefix for its other addresses. Explicit clarification corrections may synchronize redundant address/mask fields before revalidation.
Forbidden: Never allocate missing IPs, widen a /32 host mask, renumber devices or invent a gateway during translation.
Expected: Valid addressing supports intended local/remote decisions; conflicts are reported or retained as deliberate negative labs.
Verify: Check membership, uniqueness, gateway reachability and provenance.
Sources: PROJECT, RFC-HOST
Related: ADDR-002, CORE-002

## [ADDR-002] Separate lab prefixes from AWS transport prefixes
Rule-ID: ADDR-002
Kind: rule
Mode: behavioral_lab
Phase: topology
Status: target_specification
Keywords: overlay, underlay, /30, /31, reserved addresses
Applies: Hosting lab addressing on AWS workers.
Required: Use distinct pools. Apply AWS subnet constraints to actual AWS subnets; apply the selected stack's constraints to virtual lab links.
Forbidden: Do not reject a lab /30 because AWS subnets cannot be that small, or bind lab prefixes to AWS ENIs as a shortcut.
Expected: Lab links retain supported original prefixes over valid transport addressing. /31 requires explicit point-to-point support.
Verify: Validate both address spaces and prove no management route leaks lab traffic.
Sources: PROJECT, AWS-SUBNET
Related: BACKEND-003, ADDR-001
