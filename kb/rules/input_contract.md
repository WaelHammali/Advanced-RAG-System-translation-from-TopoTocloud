## [INPUT-001] Consume architecture JSON without losing configuration
Rule-ID: INPUT-001
Kind: rule
Mode: all
Status: target_specification
Keywords: JSON, components, edges, interfaces, routing, services, automation
Applies: Translating architecture JSON after the application's deterministic readiness check.
Required: Before retrieval/model calls, check IDs/types/interfaces, no isolated nodes, valid links, non-L2 IPv4 prefixes, known configuration shapes/references and acyclic automation dependencies. Preserve supplied fields after readiness passes.
Forbidden: Do not invent addresses/names, connect isolated components, discard unknown configuration or ask model-led clarification questions.
Expected: One plan covering both network configuration and application services on their specified targets, with unresolved implementation requirements in limitations.
Verify: Readiness errors identify JSON paths. Switch/bridge/hub ports need no IP. Readiness does not prove routing correctness or implementation capability.
Sources: PROJECT
Related: CORE-002, PLAN-001
