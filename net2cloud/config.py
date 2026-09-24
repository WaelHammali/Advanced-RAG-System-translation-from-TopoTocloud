"""Configuration for the architecture-JSON to plan-JSON RAG service."""

from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
KB_DIR = Path(os.environ.get("NET2TF_KB_DIR", ROOT_DIR / "kb"))
INDEX_DIR = Path(os.environ.get("NET2TF_INDEX_DIR", ROOT_DIR / ".cache" / "net2cloud"))
# Listed on Groq's Free plan; billing still depends on the caller's account tier.
SUPPORTED_PLAN_MODELS = ("openai/gpt-oss-120b", "openai/gpt-oss-20b")
PLAN_MODEL = os.environ.get("NET2TF_PLAN_MODEL", SUPPORTED_PLAN_MODELS[0])
PLAN_MAX_COMPLETION_TOKENS = 4096
EMBED_MODEL = os.environ.get("NET2TF_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
RERANK_MODEL = os.environ.get("NET2TF_RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
RETRIEVAL_BACKEND = os.environ.get("NET2TF_RETRIEVAL_BACKEND", "hybrid")
TOP_K = 2  # Optional ranked records, in addition to required topology rules.
MAX_CHARS_PER_CHUNK = 1800
EMBED_MAX_TOKENS = 512
CORE_RULE_IDS = ("CORE-001", "CORE-002", "CORE-003")

TOPOLOGY_RULE_IDS = (
    *CORE_RULE_IDS,
    "MAP-001",
    "MAP-002",
    "BACKEND-001",
    "BACKEND-002",
    "BACKEND-003",
    "PLAN-001",
    "PLAN-002",
    "ADDR-001",
    "ADDR-002",
)
