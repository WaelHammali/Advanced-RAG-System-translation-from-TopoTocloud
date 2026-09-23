## [INPUT-001] Consume architecture JSON without losing configuration
Rule-ID: INPUT-001
Kind: rule
Mode: all
Phase: topology
Status: target_specification
Keywords: JSON, devices, links, network, addressing
Applies: Translating a devices/links topology JSON after the application's deterministic readiness check.
Required: Before retrieval/model calls, check device IDs/names/types, no isolated devices, a pc has exactly one link, valid links referencing real device IDs, and each device/link network object. Each link's network also holds source_ip and target_ip, the address each end uses on that link, inside the link's network; a router joining two subnets has a different address per link, and a device's own ip_address must be one of its link addresses. Preserve supplied fields after readiness passes.
Forbidden: Do not invent addresses/names, connect isolated devices, silently accept an inconsistent mask or a link address outside its link's network, or ask model-led clarification questions.
Expected: One plan covering the source devices and links, with unresolved implementation requirements in limitations.
Verify: Blocking tuples use entity ID and exact JSON Pointer; advisory warnings are separate. Explicit corrections require the source revision and revalidation. Missing OSPF/RIP/services never blocks this initial stage. Readiness is not runtime support or ping proof.
Sources: PROJECT
Related: CORE-002, PLAN-001
