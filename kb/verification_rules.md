## [VERIFY-001] Separate prediction, observation and conformance
Rule-ID: VERIFY-001
Kind: rule
Mode: behavioral_lab
Status: target_specification
Keywords: expected failure, pass, fail, unknown, unsupported
Applies: Answering reachability questions or evaluating a lab.
Required: Record source/interface, destination lab IP, protocol, predicted result and reason. Observed remains not_run until measured. Compare expectation and measurement independently.
Forbidden: Do not call expected isolation a translation defect, or unexpectedly successful forbidden traffic a success.
Expected: Expected fail plus measured fail can mean conformance pass; prediction is not live proof.
Verify: Probe from the actual lab node; separate utility/worker problems from routing failures.
Sources: PROJECT
Related: VERIFY-002, CORE-003

## [VERIFY-002] Prove packet paths and fault behavior
Rule-ID: VERIFY-002
Kind: rule
Mode: behavioral_lab
Status: target_specification
Keywords: capture, traceroute, router down, route removal
Applies: Checking equivalence beyond reachability.
Required: Inspect both selected routes and captures/counters on required routers. Remove the sole required path and expect failure; preserve legitimate alternatives and test recovery after convergence.
Forbidden: Do not infer router traversal from ping alone, or failure from traceroute stars alone.
Expected: A simple chain fails when its middle path fails; same-LAN traffic survives unrelated router failure.
Verify: Test baseline, inject one fault, wait for state, probe, restore and verify recovery.
Sources: PROJECT
Related: EX-TGW, EX-LAN, ROUTE-002

## [VERIFY-003] Check convergence and effective tunnel MTU
Rule-ID: VERIFY-003
Kind: rule
Mode: behavioral_lab
Status: target_specification
Keywords: MTU, large ping, fragmentation, convergence
Applies: Tunnels or dynamic routing are involved.
Required: Declare readiness conditions and bounded waits. Account for real encapsulation overhead in lab MTU; verify small/large data and required control traffic.
Forbidden: Do not assume inner MTU 1500 fits all tunnels or startup loss proves steady-state failure.
Expected: Supported sizes/states match declared capabilities; observed timing follows configured protocol within tested bounds.
Verify: Record sizes, timeouts, route state, captures and versions.
Sources: PROJECT, LINUX-LINK
Related: BACKEND-002, RIP-002, OSPF-002
