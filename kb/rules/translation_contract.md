## [CORE-001] Preserve network behavior and intentional failures
Rule-ID: CORE-001
Kind: rule
Mode: behavioral_lab
Phase: topology
Status: target_specification
Keywords: real pattern, translation, traduction, ping, isolation
Applies: Any translation claiming the same forwarding behavior as a source network.
Required: Preserve device/link IDs, names, types and addressing. Build isolated runtimes and exact cables with connected routes only. Routes, protocols and services are configured in a later user/NLP stage. AWS transport must not bypass the lab.
Forbidden: Do not add bridges, routes, full connectivity or redistribution just to make ping succeed.
Expected: Ping passes only when the configured lab permits request AND reply. Same-LAN traffic has no unrelated router dependency.
Verify: Compare expected successes/failures, route provenance and packet traversal.
Sources: PROJECT
Related: CORE-002, CORE-003, VERIFY-001

## [CORE-002] Unspecified configuration differs from explicitly absent configuration
Rule-ID: CORE-002
Kind: rule
Mode: behavioral_lab
Phase: topology
Status: target_specification
Keywords: missing, no routes, not configured, preserve, inference
Applies: The caller's architecture JSON supplies, omits or disables configuration.
Required: Check topology readiness before translation. Return blocking issues by entity ID and JSON Pointer, with separate warnings. Apply only explicit revision-bound corrections, then revalidate. Missing OSPF/RIP/services is not a readiness error; configuration occurs later.
Forbidden: Do not interpret automatic addressing as permission to add routing, or 'no OSPF' as an OSPF request.
Expected: Absent remote routing stays absent. Unknown settings stay unresolved; omitted fields do not authorize inventing routes or services.
Verify: Audit generated links, routes and protocols against input provenance.
Sources: PROJECT
Related: INPUT-001, STATIC-001

## [CORE-003] Return only an AWS architecture JSON plan
Rule-ID: CORE-003
Kind: rule
Mode: all
Phase: topology
Status: target_specification
Keywords: AWS, JSON, cloud_plan, configuration, translation, boundaries
Applies: Every architecture JSON translation request.
Required: Return the exact supplied required_cloud_plan with contract_version 1.0, AWS hosting, device_mapping, networking and configuration_targets. Python verifies all fields against source-derived requirements; attach source/provenance outside the model.
Forbidden: No deployment code, files, dialogue, validation reports or fabricated runtime results. Deterministic readiness errors are a separate response before translation.
Expected: One JSON object with cloud_plan, rule_ids and limitations; architecture and knowledge are attached by the app. Dependencies describe requirements, not completed work.
Verify: Reject changed devices, links, addresses, references, hosting choices or added initial routing. A conforming plan is not a live connectivity measurement.
Sources: PROJECT
Related: VERIFY-001, PLAN-002
