# Knowledge ownership and maintenance

Corpus version: 4.0.0.

`kb` is machine-facing domain knowledge. `docs` is human-facing application
documentation. They are not interchangeable: the retriever recursively reads
Markdown under `kb`, and never reads `docs`. The former long network specification
has been consolidated into the existing rule families instead of maintaining a
second copy of the same networking policies.

## Canonical domain rules

| Subject | Canonical KB file |
| --- | --- |
| Preservation and AWS JSON-only boundary | [Translation contract](../kb/rules/translation_contract.md) |
| Input prerequisites | [Input contract](../kb/rules/input_contract.md) |
| Source-to-AWS mapping | [Mapping rules](../kb/rules/mapping_rules.md) |
| AWS routing transport | [AWS patterns](../kb/rules/aws_network_patterns.md) |
| Isolated network stacks and explicit links | [Runtime requirements](../kb/rules/real_router_appliance_rules.md) |
| VLANs, local traffic and loops | [Layer 2](../kb/rules/layer2_patterns.md) |
| Address preservation | [Addressing](../kb/rules/addressing_rules.md) |
| Forwarding and return paths | [Routing](../kb/rules/routing_rules.md) |
| Static routes | [Static routing](../kb/rules/routing_static.md) |
| RIP | [RIPv2](../kb/rules/routing_ripv2.md) |
| OSPF | [OSPFv2](../kb/rules/routing_ospfv2.md) |
| HTTP and HTTPS | [Application services](../kb/rules/application_services.md) |
| Declarative configuration and management | [Operations](../kb/rules/configuration_operations.md) |
| Access and internet | [Access](../kb/rules/access_patterns.md), [internet](../kb/rules/internet_patterns.md) |
| Firewall semantics | [Security](../kb/rules/security_patterns.md) |
| Plan versus execution | [Plan boundaries](../kb/rules/plan_boundaries.md) |
| Predicted versus observed behavior | [Verification](../kb/rules/verification_rules.md) |

[KB examples](../kb/examples) express behavioral requirements for retrieval.
[Runnable JSON examples](../examples) exercise the application boundary. They serve
different purposes; a text scenario is not accepted in place of architecture JSON.

## Record format

Every Markdown heading begins one atomic rule/example, with a stable Rule-ID,
kind, mode, phase, target status, keywords, applicability, requirements, prohibitions,
expected behavior, verification notes, source IDs and related rule IDs. A record
must fit the actual configured chunk limit. Do not put README-style guides in the
KB: the integrity checker requires the rule-card format for every Markdown file.

`target_specification` describes desired behavior, not an implemented or tested
cloud runtime. The [source register](../kb/sources.json) maps reference IDs to
primary documentation. PROJECT identifies design requirements rather than
independent platform evidence. References need review when relevant technologies
change; the manifest does not verify remote source freshness.

## Translation phase

Every card has `Phase: topology` or `Phase: configuration`. The initial RAG only
retrieves topology cards in behavioral/all mode. Protocol/service/operation cards
remain reference material for the later stage; they are not instructions to
configure a newly created topology. Unknown source fields cannot change the phase
or select cloud-native migration. Device/link runtime mapping and isolation rules
are mandatory context, independent of ranking or `top_k`.

The conceptual scenarios still include configured-network cases. They document
later behavioral expectations, not accepted initial configuration inputs or live
provider evaluation results. Executable tests use the current devices/links JSON
fixtures and explicitly assert topology preservation and deferred configuration.

## Updating knowledge

Edit the relevant rule card as the single source of domain truth. Update affected
examples, conceptual scenarios and regression expectations. For a semantic change,
bump `CORPUS_VERSION` in `tools/validate_knowledge_base.py` and this guide, then run:

```bash
python tools/validate_knowledge_base.py --refresh-manifest
python tools/validate_knowledge_base.py
python -m pytest -q
```

The generated [manifest](../kb/manifest.json) inventories files/records and their
hashes; its repetition is intentional machine metadata, not another rule source.
The checker validates record structure, actual chunking, references, local links
and hashes. It does not judge a rule's factual accuracy or a model's answers.
Runtime cache fingerprints automatically detect corpus changes.
