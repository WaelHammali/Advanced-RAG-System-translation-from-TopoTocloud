## [INPUT-001] Consume architecture JSON without losing configuration
Rule-ID: INPUT-001
Kind: rule
Mode: all
Status: target_specification
Keywords: JSON, components, edges, interfaces, routing, services, Ansible
Applies: Translating architecture JSON after the application's deterministic readiness check.
Required: Before retrieval/model calls, block missing IDs/types/interfaces, isolated components, invalid link references and missing/invalid IPv4 prefixes on non-L2 interfaces. Keep supplied fields unchanged after readiness passes.
Forbidden: Do not invent addresses/names, connect isolated components, discard unknown configuration or ask model-led clarification questions.
Expected: One plan covering both network configuration and application services on their specified targets, with unresolved implementation requirements in limitations.
Verify: Readiness errors identify JSON paths. Switch/bridge/hub ports need no IP. Readiness does not prove routing correctness or generator capability.
Sources: PROJECT
Related: CORE-002, TF-001
