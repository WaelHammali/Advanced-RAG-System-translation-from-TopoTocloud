"""Retrieve networking and automation knowledge for a prepared architecture JSON."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import (
    CORE_RULE_IDS,
    EMBED_MAX_TOKENS,
    EMBED_MODEL,
    INDEX_DIR,
    KB_DIR,
    MAX_CHARS_PER_CHUNK,
    RERANK_MODEL,
    RETRIEVAL_BACKEND,
    TOP_K,
)
from .contracts import JSONObject, KnowledgeRecord
from .json_io import atomic_path, dumps_json, loads_json, write_json


@dataclass
class KBChunk:
    source: str
    heading: str
    text: str


def _chunk_markdown(path: str) -> list[KBChunk]:
    with open(path, encoding="utf-8") as f:
        content = f.read()

    lines = content.splitlines()
    chunks: list[KBChunk] = []
    current_heading = "root"
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        txt = "\n".join(buffer).strip()
        if txt:
            while len(txt) > MAX_CHARS_PER_CHUNK:
                split_at = txt.rfind("\n", 0, MAX_CHARS_PER_CHUNK)
                if split_at == -1 or split_at < MAX_CHARS_PER_CHUNK // 2:
                    split_at = MAX_CHARS_PER_CHUNK

                part = txt[:split_at].strip()
                if part:
                    chunks.append(
                        KBChunk(
                            source=path,
                            heading=current_heading,
                            text=part,
                        )
                    )

                txt = txt[split_at:].strip()

            if txt:
                chunks.append(
                    KBChunk(
                        source=path,
                        heading=current_heading,
                        text=txt,
                    )
                )

        buffer = []

    for line in lines:
        if line.startswith("#"):
            flush()
            current_heading = line.strip()
            buffer.append(line)
        else:
            buffer.append(line)

    flush()
    return chunks


def _field(text: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}: (.+)$", text, re.MULTILINE)
    return match.group(1) if match else ""


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _json(value: Any) -> str:
    return dumps_json(value, sort_keys=True)


def _subject_query(subject: str, entry: Any) -> str:
    """Focus retrieval on features, without substituting their configuration."""
    if isinstance(entry, dict):
        if subject == "protocols" and entry.get("name"):
            return str(entry["name"])
        if subject == "services" and entry.get("protocol"):
            return f"{entry['protocol']} {entry.get('implementation', '')}"
        if subject == "tasks":
            return "automation tasks " + str(entry.get("operation", entry.get("module", "")))
        if subject in {"routing", "automation"}:
            fields = " ".join(key for key, value in entry.items() if value)
            return f"{subject} {fields.replace('_', ' ')}"
    return _json({subject: entry})


def _configuration_queries(architecture: dict[str, Any]) -> list[str]:
    """Retain service/routing/task subjects for retrieval, not input validation."""
    queries: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                subject = key.lower()
                if subject == "static_routes":
                    # Even an explicit empty list needs the no-invented-routes
                    # and return-path rules; this does not add any routes.
                    queries.append("static routing next hop return route")
                if subject == "components" and isinstance(item, list):
                    roles = [
                        str(component.get("type", ""))
                        for component in item
                        if isinstance(component, dict)
                    ]
                    queries.append("component mapping " + " ".join(dict.fromkeys(roles)))
                    if "switch" in roles or "bridge" in roles:
                        queries.append("switch chain bridge STP loop switching paths")
                if subject == "ipv4" and isinstance(item, str) and item.endswith(("/31", "/32")):
                    queries.append("point-to-point /31 /32 host route prefix")
                if subject in {"routing", "protocols", "services", "automation", "tasks"}:
                    entries = item if isinstance(item, list) else [item]
                    for entry in entries:
                        if not entry:
                            continue
                        # Focus on the requested feature rather than matching
                        # example IP addresses or device names. The complete
                        # configuration remains in the main query/model input.
                        queries.append(_subject_query(subject, entry))
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(architecture)
    components = architecture.get("components", [])
    edges = architecture.get("edges", [])
    if isinstance(components, list) and isinstance(edges, list):
        hosts = {
            node["id"]
            for node in components
            if isinstance(node, dict)
            and isinstance(node.get("id"), str)
            and node.get("type") in ("pc", "server")
        }
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            endpoints = [edge.get(side) for side in ("source", "target")]
            if all(
                isinstance(end, dict)
                and isinstance(end.get("component"), str)
                and end["component"] in hosts
                for end in endpoints
            ):
                queries.append("two directly cabled PCs local traffic peer")
                break
    return list(dict.fromkeys(queries))


class _BM25Index:
    """Build term statistics once for all queries in a retrieval request."""

    def __init__(self, documents: list[str]) -> None:
        self.bags = [Counter(_tokens(document)) for document in documents]
        self.lengths = [sum(bag.values()) for bag in self.bags]
        self.average = sum(self.lengths) / max(len(self.lengths), 1) or 1.0
        self.frequencies = Counter(term for bag in self.bags for term in bag)

    def score(self, query: str) -> list[float]:
        scores = [0.0] * len(self.bags)
        for term in set(_tokens(query)):
            count = self.frequencies[term]
            if not count:
                continue
            inverse = math.log(1 + (len(self.bags) - count + 0.5) / (count + 0.5))
            for index, bag in enumerate(self.bags):
                frequency = bag[term]
                if frequency:
                    denominator = frequency + 1.5 * (
                        0.25 + 0.75 * self.lengths[index] / self.average
                    )
                    scores[index] += inverse * frequency * 2.5 / denominator
        return scores


def _rank(scores: list[float]) -> list[int]:
    return sorted(range(len(scores)), key=lambda index: (-scores[index], index))


def _valid_records(records: Any) -> bool:
    """Check internal cache structure before it becomes planning context."""
    fields = {"rule_id", "source", "heading", "text", "mode"}
    if not isinstance(records, list) or not records:
        return False
    if any(
        not isinstance(record, dict)
        or any(not isinstance(record.get(field), str) or not record[field] for field in fields)
        for record in records
    ):
        return False
    ids = [record["rule_id"] for record in records]
    return len(set(ids)) == len(ids) and set(CORE_RULE_IDS) <= set(ids)


@lru_cache(maxsize=1)
def _models():
    try:
        from sentence_transformers import CrossEncoder, SentenceTransformer
    except ImportError as error:
        raise RuntimeError(
            "Hybrid retrieval requires requirements.txt; use --retrieval lexical "
            "for retrieval without embedding models."
        ) from error
    embedder = SentenceTransformer(EMBED_MODEL)
    embedder.max_seq_length = EMBED_MAX_TOKENS
    return embedder, CrossEncoder(RERANK_MODEL, max_length=512)


class KnowledgeRetriever:
    """BM25 or BM25 + embeddings + reranking. No architecture decisions."""

    def __init__(
        self,
        *,
        kb_dir: str | Path = KB_DIR,
        index_dir: str | Path = INDEX_DIR,
        backend: str = RETRIEVAL_BACKEND,
        top_k: int = TOP_K,
    ) -> None:
        if backend not in {"hybrid", "lexical"}:
            raise ValueError("retrieval backend must be hybrid or lexical")
        if top_k < 1:
            raise ValueError("top_k must be positive")
        self.kb_dir = Path(kb_dir)
        self.index_dir = Path(index_dir)
        self.backend = backend
        self.top_k = top_k

    def _documents(self) -> tuple[list[KnowledgeRecord], str]:
        paths = sorted(self.kb_dir.rglob("*.md"))
        if not paths:
            raise RuntimeError(f"No knowledge documents found in {self.kb_dir}")
        identity = {
            "format": 2,
            "max_characters": MAX_CHARS_PER_CHUNK,
            "source_prefix": self.kb_dir.name,
            "chunker": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "files": [
                (str(p.relative_to(self.kb_dir)), hashlib.sha256(p.read_bytes()).hexdigest())
                for p in paths
            ],
        }
        fingerprint = hashlib.sha256(_json(identity).encode()).hexdigest()
        cache = self.index_dir / "documents.json"
        try:
            stored = loads_json(cache.read_text(encoding="utf-8"))
            if stored["fingerprint"] == fingerprint and _valid_records(stored["records"]):
                return stored["records"], fingerprint
        except (OSError, ValueError, KeyError, TypeError):
            pass

        records: list[KnowledgeRecord] = []
        for path in paths:
            for chunk in _chunk_markdown(str(path)):
                rule_id = _field(chunk.text, "Rule-ID")
                if not rule_id:
                    raise RuntimeError(f"Knowledge record lacks Rule-ID: {chunk.heading}")
                records.append(
                    {
                        "rule_id": rule_id,
                        "source": path.relative_to(self.kb_dir.parent).as_posix(),
                        "heading": chunk.heading,
                        "text": chunk.text,
                        "mode": _field(chunk.text, "Mode"),
                    }
                )
        ids = [record["rule_id"] for record in records]
        if len(set(ids)) != len(ids):
            raise RuntimeError("Duplicate or split rule IDs in the knowledge corpus")
        if set(CORE_RULE_IDS) - set(ids):
            raise RuntimeError("The knowledge corpus is missing mandatory core rules")
        write_json(cache, {"fingerprint": fingerprint, "records": records})
        return records, fingerprint

    def _hybrid_rank(
        self,
        records: list[KnowledgeRecord],
        queries: list[str],
        lexical_scores: list[float],
        fingerprint: str,
    ) -> list[int]:
        import numpy as np

        embedder, reranker = _models()
        texts = [record["text"] for record in records]
        # Do not silently lose the end of a rule to embedding truncation.
        for record, text in zip(records, texts):
            if len(embedder.tokenizer.encode(text)) > EMBED_MAX_TOKENS:
                raise RuntimeError(
                    f"Knowledge record exceeds embedding token limit: {record['rule_id']}"
                )
        identity = _json(
            [fingerprint, EMBED_MODEL, EMBED_MAX_TOKENS, [record["rule_id"] for record in records]]
        )
        cache_key = hashlib.sha256(identity.encode()).hexdigest()
        cache = self.index_dir / f"embeddings-{cache_key}.npy"
        try:
            embeddings = np.load(cache, allow_pickle=False)
            if (
                embeddings.ndim != 2
                or embeddings.shape[0] != len(records)
                or embeddings.shape[1] == 0
                or not np.issubdtype(embeddings.dtype, np.number)
                or not np.isfinite(embeddings).all()
            ):
                raise ValueError("Invalid embedding cache dimensions")
        except (OSError, ValueError):
            embeddings = embedder.encode(
                texts,
                normalize_embeddings=True,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
            with atomic_path(cache) as temporary:
                with temporary.open("wb") as handle:
                    np.save(handle, embeddings, allow_pickle=False)

        # Token windows retain large JSON queries without truncating their tail.
        windows = []
        for query in queries:
            ids = embedder.tokenizer.encode(query, add_special_tokens=False)
            for start in range(0, len(ids), 160):
                windows.append(embedder.tokenizer.decode(ids[start : start + 160]))
        query_vectors = embedder.encode(
            windows,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        semantic_scores = (query_vectors @ embeddings.T).max(axis=0).tolist()
        # Reciprocal-rank fusion avoids mixing incompatible score scales.
        fused = [0.0] * len(records)
        for ranking in [_rank(lexical_scores), _rank(semantic_scores)]:
            for position, index in enumerate(ranking, 1):
                fused[index] += 1 / (60 + position)
        candidates = _rank(fused)[: max(self.top_k * 3, 16)]
        pairs = [[window, texts[index]] for index in candidates for window in windows]
        values = np.asarray(reranker.predict(pairs, show_progress_bar=False))
        scores = values.reshape(len(candidates), len(windows)).max(axis=1)
        return [candidates[index] for index in _rank(scores.tolist())]

    def retrieve(self, architecture: JSONObject) -> list[KnowledgeRecord]:
        records, fingerprint = self._documents()
        by_id = {record["rule_id"]: record for record in records}
        core = [by_id[rid] for rid in CORE_RULE_IDS]
        mode = architecture.get("translation_mode", "behavioral_lab")
        candidates = [
            record
            for record in records
            if record["rule_id"] not in CORE_RULE_IDS and record["mode"] in {mode, "all"}
        ]
        if not candidates:
            return core
        texts = [record["text"] for record in candidates]
        lexical = _BM25Index(texts)
        query = _json(architecture)
        scores = lexical.score(query)
        subjects = _configuration_queries(architecture)
        ranking = (
            self._hybrid_rank(candidates, [query, *subjects], scores, fingerprint)
            if self.backend == "hybrid"
            else _rank(scores)
        )
        # Give each explicit service/routing/task subject a relevant record.
        # This selects knowledge only; it never enables or repairs configuration.
        selected: list[int] = []
        for subject in subjects:
            subject_scores = lexical.score(subject)
            best = _rank(subject_scores)[0]
            if subject_scores[best] > 0 and best not in selected:
                selected.append(best)
        for index in ranking:
            if len(selected) >= self.top_k:
                break
            if index not in selected:
                selected.append(index)
        return core + [candidates[index] for index in selected]


def retrieve_context(architecture: JSONObject, **options: Any) -> list[KnowledgeRecord]:
    """Convenience entry point; the JSON input is never normalized or mutated."""
    return KnowledgeRetriever(**options).retrieve(architecture)
