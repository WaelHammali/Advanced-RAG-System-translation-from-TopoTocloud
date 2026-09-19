"""Configuration for the architecture-JSON to plan-JSON RAG service."""

from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
KB_DIR = Path(os.environ.get("NET2TF_KB_DIR", ROOT_DIR / "kb"))
INDEX_DIR = Path(os.environ.get("NET2TF_INDEX_DIR", ROOT_DIR / "index"))
PLAN_MODEL = os.environ.get("NET2TF_PLAN_MODEL", "llama-3.3-70b-versatile")
EMBED_MODEL = os.environ.get("NET2TF_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
RERANK_MODEL = os.environ.get("NET2TF_RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
RETRIEVAL_BACKEND = os.environ.get("NET2TF_RETRIEVAL_BACKEND", "hybrid")
TOP_K = 8
MAX_CHARS_PER_CHUNK = 1800
EMBED_MAX_TOKENS = 512
CORE_RULE_IDS = ("CORE-001", "CORE-002", "CORE-003")
