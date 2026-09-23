"""Bounded educational placement; estimates are not deployment or price guarantees."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from .json_io import loads_json
from .readiness import require_ready

CATALOG = Path(__file__).parent / "data" / "educational_instances.json"
# Planning reservations, deliberately explicit and not a measured performance SLA.
MEMORY_MIB = {"pc": 128, "server": 256, "router": 256, "switch": 64, "bridge": 64}


class UnsupportedTopology(ValueError):
    """A complete source requires capabilities outside the selected lab profile."""


def select_hosting(architecture: dict) -> dict:
    """Choose the cheapest fitting reviewed catalog offer, without a paid API call."""
    require_ready(architecture)
    roles = [d["type"].lower() for d in architecture["devices"]]
    unsupported = sorted(set(roles) - MEMORY_MIB.keys())
    if unsupported:
        raise UnsupportedTopology("Unsupported runtime device types: " + ", ".join(unsupported))
    if len(roles) > 16 or len(architecture["links"]) > 24:
        raise UnsupportedTopology("Educational profile supports at most 16 devices and 24 links.")
    catalog = loads_json(CATALOG.read_text(encoding="utf-8"))
    required = 512 + sum(MEMORY_MIB[role] for role in roles)
    offers = [
        offer
        for offer in catalog["offers"]
        if offer["memory_mib"] >= required
        and Decimal(offer["hourly_compute_usd"]) <= Decimal(catalog["max_hourly_compute_usd"])
    ]
    if not offers:
        raise UnsupportedTopology(
            "No educational catalog instance fits the memory reservation and cost cap."
        )
    chosen = min(
        offers, key=lambda offer: (Decimal(offer["hourly_compute_usd"]), offer["instance_type"])
    )
    return {
        "profile": catalog["profile"],
        "region": catalog["region"],
        "architecture": catalog["architecture"],
        "instance_count": 1,
        "instance_type": chosen["instance_type"],
        "memory_mib": chosen["memory_mib"],
        "reserved_memory_mib": required,
        "cpu_credits": "standard",
        "root_volume": {"type": "gp3", "size_gib": 8, "encrypted": True},
        "public_ipv4": False,
        "cost": {
            "currency": catalog["currency"],
            "hourly_compute_estimate": chosen["hourly_compute_usd"],
            "hourly_compute_cap": catalog["max_hourly_compute_usd"],
            "basis": "lowest_fitting_offer_in_reviewed_catalog",
            "reviewed_on": catalog["reviewed_on"],
            "source": catalog["source"],
            "recheck_before_deployment": True,
            "excludes": ["storage", "network", "management_access", "taxes"],
        },
    }
