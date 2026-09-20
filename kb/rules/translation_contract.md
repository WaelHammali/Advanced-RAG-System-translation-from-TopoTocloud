## [CORE-001] Preserve network behavior and intentional failures
Rule-ID: CORE-001
Kind: rule
Mode: behavioral_lab
Status: target_specification
Keywords: real pattern, translation, traduction, ping, isolation
Applies: Any translation claiming the same forwarding behavior as a source network.
Required: Preserve links, VLANs, addresses, selected routes, filtering, required transit nodes and declared failures. AWS transport carries the lab without alternate lab forwarding.
Forbidden: Do not add bridges, routes, full connectivity or redistribution just to make ping succeed.
Expected: Ping passes only when the configured lab permits request AND reply. Same-LAN traffic has no unrelated router dependency.
Verify: Compare expected successes/failures, route provenance and packet traversal.
Sources: PROJECT
Related: CORE-002, CORE-003, VERIFY-001

## [CORE-002] Unspecified configuration differs from explicitly absent configuration
Rule-ID: CORE-002
Kind: rule
Mode: behavioral_lab
Status: target_specification
Keywords: missing, no routes, not configured, preserve, inference
Applies: The caller's architecture JSON supplies, omits or disables configuration.
Required: The application checks input readiness before translation. Preserve explicit values, intentional failures and absent routes after that gate. Clarification remains caller-owned; no model-generated repairs.
Forbidden: Do not interpret automatic addressing as permission to add routing, or 'no OSPF' as an OSPF request.
Expected: Absent remote routing stays absent. Unknown settings stay unresolved; omitted fields do not authorize inventing routes or services.
Verify: Audit generated links, routes and protocols against input provenance.
Sources: PROJECT
Related: INPUT-001, STATIC-001

## [CORE-003] Return only an AWS architecture JSON plan
Rule-ID: CORE-003
Kind: rule
Mode: all
Status: target_specification
Keywords: AWS, JSON, cloud_plan, configuration, translation, boundaries
Applies: Every architecture JSON translation request.
Required: Return cloud_plan with provider aws, resource/component mappings, networking and declarative configuration requirements. Preserve source targets and parameters. The application attaches the original source and selected knowledge metadata.
Forbidden: No deployment code, files, dialogue, validation reports or fabricated runtime results. Deterministic readiness errors are a separate response before translation.
Expected: One JSON object with cloud_plan, rule_ids and limitations; architecture and knowledge are attached by the app. Dependencies describe requirements, not completed work.
Verify: Check input completeness before retrieval and reject non-AWS output or extra top-level sections. A JSON plan does not establish live connectivity.
Sources: PROJECT
Related: VERIFY-001, PLAN-002
