## [INPUT-001] Consume architecture JSON without losing configuration
Rule-ID: INPUT-001
Kind: rule
Mode: all
Status: target_specification
Keywords: JSON, devices, links, network, addressing
Applies: Translating a devices/links topology JSON after the application's deterministic readiness check.
Required: Before retrieval/model calls, check device IDs/names/types, no isolated devices, a pc has exactly one link, valid links referencing real device IDs, and each device/link network object. A device carries at most one network block, used for every link it has; every link also carries its own network block, which must agree with the prefix/mask/network_address it declares and with any addressed device at either end. Preserve supplied fields after readiness passes.
Forbidden: Do not invent addresses/names, connect isolated devices, silently accept an inconsistent mask or a link/device address mismatch, or ask model-led clarification questions.
Expected: One plan covering the source devices and links, with unresolved implementation requirements in limitations.
Verify: Readiness errors identify JSON paths. Switch/bridge/hub devices may leave their network fields null. Readiness does not prove routing correctness or implementation capability.
Sources: PROJECT
Related: CORE-002, PLAN-001
