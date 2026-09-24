"""Compact, source-derived facts for the model's knowledge review."""

from __future__ import annotations

from .contracts import JSONObject, KnowledgeRecord

_METADATA = (
    "#",
    "Rule-ID:",
    "Kind:",
    "Mode:",
    "Phase:",
    "Status:",
    "Keywords:",
    "Sources:",
    "Related:",
)


def review_context(
    architecture: JSONObject, plan: JSONObject, records: list[KnowledgeRecord]
) -> JSONObject:
    """Keep every endpoint's semantics without sending labels or duplicating the plan.

    Numeric node references are local to this review; the public plan keeps the
    original IDs/names and full source JSON. Unknown values never become prompts.
    Rule conditions, requirements, prohibitions, expectations and checks remain
    verbatim. Only indexing/provenance metadata is removed from the model context.
    """
    nodes = {device["id"]: index for index, device in enumerate(architecture["devices"])}
    knowledge = []
    for record in records:
        text = "\n".join(
            line
            for line in record["text"].splitlines()
            if line.strip() and not line.startswith(_METADATA)
        )
        if not text:
            raise ValueError("Retrieved knowledge must contain rule content.")
        knowledge.append({"rule_id": record["rule_id"], "text": text})
    return {
        "topology": {
            "devices": [
                {
                    "node": nodes[device["id"]],
                    "type": device["type"].lower(),
                    "ip_address": device["network"]["ip_address"],
                    "prefix_length": device["network"]["prefix_length"],
                }
                for device in architecture["devices"]
            ],
            "links": [
                {
                    "source": nodes[link["source"]["device_id"]],
                    "target": nodes[link["target"]["device_id"]],
                    "network_address": link["network"]["network_address"],
                    "prefix_length": link["network"]["prefix_length"],
                    **{
                        f"{side}_{field}": link[side][field]
                        for side in ("source", "target")
                        for field in ("ip_address", "prefix_length")
                    },
                }
                for link in plan["networking"]["links"]
            ],
        },
        "hosting": {"workers": 1, "instance_type": plan["hosting"]["instance_type"]},
        "knowledge": knowledge,
    }
