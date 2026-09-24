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
    EMBED_MAX_TOKENS,
    EMBED_MODEL,
    INDEX_DIR,
    KB_DIR,
    MAX_CHARS_PER_CHUNK,
    RERANK_MODEL,
    RETRIEVAL_BACKEND,
    TOP_K,
    TOPOLOGY_RULE_IDS,
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


def _topology_queries(architecture: dict[str, Any]) -> list[str]:
    """Retrieval-only feature queries for a devices/links topology.

    This selects knowledge only; it never enables, repairs or invents
    configuration. Labels and uninterpreted extensions cannot steer retrieval.
    """
    queries: list[str] = []
    devices = architecture.get("devices", [])
    links = architecture.get("links", [])

    if isinstance(devices, list):
        roles = sorted(
            {
                str(device.get("type", "")).lower()
                for device in devices
                if isinstance(device, dict)
                and str(device.get("type", "")).lower()
                in {"pc", "server", "router", "switch", "bridge", "hub"}
            }
        )
        if roles:
            queries.append("device mapping " + " ".join(dict.fromkeys(roles)))
        if "switch" in roles or "bridge" in roles:
            queries.append("switch chain bridge STP loop switching paths")

    # A /31 or /32 on either a device's own address or a link's network.
    for item in [
        *(devices if isinstance(devices, list) else []),
        *(links if isinstance(links, list) else []),
    ]:
        network = item.get("network") if isinstance(item, dict) else None
        if isinstance(network, dict) and network.get("prefix_length") in (31, 32):
            queries.append("point-to-point /31 /32 host route prefix")
            break

    if isinstance(devices, list) and isinstance(links, list):
        hosts = {
            device["id"]
            for device in devices
            if isinstance(device, dict)
            and isinstance(device.get("id"), str)
            and str(device.get("type", "")).lower() in ("pc", "server")
        }
        switches = {
            device["id"]
            for device in devices
            if isinstance(device, dict)
            and isinstance(device.get("id"), str)
            and str(device.get("type", "")).lower() in {"switch", "bridge", "hub"}
        }
        host_switch_links: dict[str, int] = {}
        for link in links:
            if not isinstance(link, dict):
                continue
            if link.get("source") in hosts and link.get("target") in hosts:
                queries.append("two directly cabled PCs local traffic peer")
            for switch_id, host_id in (
                (link.get("target"), link.get("source")),
                (link.get("source"), link.get("target")),
            ):
                if switch_id in switches and host_id in hosts:
                    host_switch_links[switch_id] = host_switch_links.get(switch_id, 0) + 1
        if any(count >= 2 for count in host_switch_links.values()):
            queries.append("same switch same VLAN local ping ARP")
    return list(dict.fromkeys(queries))


def topology_rule_ids(architecture: JSONObject) -> list[str]:
    """Select mandatory cards from graph facts, never lexical coincidences."""
    required = list(TOPOLOGY_RULE_IDS)
    devices = {
        d["id"]: d
        for d in architecture.get("devices", [])
        if isinstance(d, dict) and isinstance(d.get("id"), str)
    }
    roles = {key: str(d.get("type", "")).lower() for key, d in devices.items()}
    if set(roles.values()) & {"switch", "bridge", "hub"}:
        required.extend(["L2-001", "L2-003"])
    if "router" in roles.values():
        required.append("ROUTE-001")
    neighbors = {key: set() for key in devices}
    links = [link for link in architecture.get("links", []) if isinstance(link, dict)]
    for link in links:
        a, b = link.get("source"), link.get("target")
        if a in devices and b in devices and a != b:
            neighbors[a].add(b)
            neighbors[b].add(a)
            if roles[a] in {"pc", "server"} and roles[b] in {"pc", "server"}:
                required.append("EX-PC-DIRECT")
    if any(
        roles[key] in {"switch", "bridge", "hub"}
        and sum(roles[n] in {"pc", "server"} for n in peers) >= 2
        for key, peers in neighbors.items()
    ):
        required.append("EX-LAN")
    if any(
        isinstance(item.get("network"), dict) and item["network"].get("prefix_length") in (31, 32)
        for item in [*devices.values(), *links]
    ):
        required.append("EX-PREFIX31")
    if any(not peers for peers in neighbors.values()):
        required.append("EX-STANDALONE")
    unseen = set(devices)
    components = 0
    while unseen:
        components += 1
        pending = [unseen.pop()]
        while pending:
            new = neighbors[pending.pop()] & unseen
            unseen.difference_update(new)
            pending.extend(new)
    if components > 1:
        required.append("EX-ISOLATED")
    return list(dict.fromkeys(required))


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
    fields = {"rule_id", "source", "heading", "text", "mode", "phase"}
    if not isinstance(records, list) or not records:
        return False
    if any(
        not isinstance(record, dict)
        or any(not isinstance(record.get(field), str) or not record[field] for field in fields)
        for record in records
    ):
        return False
    ids = [record["rule_id"] for record in records]
    return (
        len(set(ids)) == len(ids)
        and set(TOPOLOGY_RULE_IDS) <= set(ids)
        and all(record["mode"] in {"all", "behavioral_lab", "cloud_native"} for record in records)
        and all(record["phase"] in {"topology", "configuration"} for record in records)
        and all(
            record["phase"] == "topology"
            for record in records
            if record["rule_id"] in TOPOLOGY_RULE_IDS
        )
    )


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
        if not isinstance(backend, str) or backend not in {"hybrid", "lexical"}:
            raise ValueError("retrieval backend must be hybrid or lexical")
        if type(top_k) is not int or top_k < 1:
            raise ValueError("top_k must be a positive integer")
        self.kb_dir = Path(kb_dir)
        self.index_dir = Path(index_dir)
        self.backend = backend
        self.top_k = top_k

    def _documents(self) -> tuple[list[KnowledgeRecord], str]:
        paths = sorted(self.kb_dir.rglob("*.md"))
        if not paths:
            raise RuntimeError(f"No knowledge documents found in {self.kb_dir}")
        identity = {
            "format": 3,
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
                        "phase": _field(chunk.text, "Phase"),
                    }
                )
        ids = [record["rule_id"] for record in records]
        if len(set(ids)) != len(ids):
            raise RuntimeError("Duplicate or split rule IDs in the knowledge corpus")
        if set(TOPOLOGY_RULE_IDS) - set(ids):
            raise RuntimeError("The knowledge corpus is missing mandatory core rules")
        if not _valid_records(records):
            raise RuntimeError("The knowledge corpus contains invalid record fields or modes")
        write_json(cache, {"fingerprint": fingerprint, "records": records})
        return records, fingerprint

    def _hybrid_rank(
        self,
        records: list[KnowledgeRecord],
        queries: list[str],
        lexical_scores: list[float],
        fingerprint: str,
    ) -> list[int]:
        from zipfile import BadZipFile

        import numpy as np

        embedder, reranker = _models()
        texts = [record["text"] for record in records]
        # Do not silently lose the end of a rule to embedding truncation.
        for record, text in zip(records, texts):
            if len(embedder.tokenizer.encode(text)) > EMBED_MAX_TOKENS:
                raise RuntimeError(
                    f"Knowledge record exceeds embedding token limit: {record['rule_id']}"
                )
        # Encode queries first so a cached document matrix can be checked against
        # the actual model dimension, not just its row count.
        windows = []
        for query in queries:
            ids = embedder.tokenizer.encode(query, add_special_tokens=False)
            for start in range(0, len(ids), 160):
                windows.append(embedder.tokenizer.decode(ids[start : start + 160]))

        def valid_vectors(value, rows, columns=None):
            return (
                isinstance(value, np.ndarray)
                and value.ndim == 2
                and value.shape[0] == rows
                and value.shape[1] > 0
                and (columns is None or value.shape[1] == columns)
                and np.issubdtype(value.dtype, np.floating)
                and np.isfinite(value).all()
                and np.all(np.any(value != 0, axis=1))
            )

        if not windows:
            raise RuntimeError("Embedding tokenizer produced no query tokens")
        query_vectors = embedder.encode(
            windows, normalize_embeddings=True, show_progress_bar=False, convert_to_numpy=True
        )
        if not valid_vectors(query_vectors, len(windows)):
            raise RuntimeError("Embedding model returned invalid query vectors")
        dimension = query_vectors.shape[1]
        identity = _json(
            [fingerprint, EMBED_MODEL, EMBED_MAX_TOKENS, [record["rule_id"] for record in records]]
        )
        cache_key = hashlib.sha256(identity.encode()).hexdigest()
        cache = self.index_dir / f"embeddings-{cache_key}.npy"
        try:
            embeddings = np.load(cache, allow_pickle=False)
            if not isinstance(embeddings, np.ndarray):
                embeddings.close()  # np.load can return an archive rather than an array.
                raise ValueError("Expected one embedding array")
            if not valid_vectors(embeddings, len(records), dimension):
                raise ValueError("Invalid embedding cache dimensions")
        except (OSError, ValueError, EOFError, BadZipFile):
            embeddings = embedder.encode(
                texts,
                normalize_embeddings=True,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
            if not valid_vectors(embeddings, len(records), dimension):
                raise RuntimeError("Embedding model returned invalid document vectors")
            with atomic_path(cache) as temporary:
                with temporary.open("wb") as handle:
                    np.save(handle, embeddings, allow_pickle=False)

        semantic_scores = (query_vectors @ embeddings.T).max(axis=0).tolist()
        # Reciprocal-rank fusion avoids mixing incompatible score scales.
        fused = [0.0] * len(records)
        for ranking in [_rank(lexical_scores), _rank(semantic_scores)]:
            for position, index in enumerate(ranking, 1):
                fused[index] += 1 / (60 + position)
        candidates = _rank(fused)[: max(self.top_k * 3, 16)]
        pairs = [[window, texts[index]] for index in candidates for window in windows]
        values = np.asarray(reranker.predict(pairs, show_progress_bar=False))
        if (
            values.size != len(pairs)
            or not np.issubdtype(values.dtype, np.floating)
            and not np.issubdtype(values.dtype, np.integer)
            or not np.isfinite(values).all()
        ):
            raise RuntimeError("Reranker returned invalid scores")
        scores = values.reshape(len(candidates), len(windows)).max(axis=1)
        return [candidates[index] for index in _rank(scores.tolist())]

    def retrieve(self, architecture: JSONObject) -> list[KnowledgeRecord]:
        records, fingerprint = self._documents()
        by_id = {record["rule_id"]: record for record in records}
        # Source extensions cannot change the fixed behavioral topology phase.
        pinned = topology_rule_ids(architecture)
        if any(
            rid not in by_id
            or by_id[rid]["phase"] != "topology"
            or by_id[rid]["mode"] not in {"all", "behavioral_lab"}
            for rid in pinned
        ):
            raise RuntimeError("The knowledge corpus is missing applicable topology rules")
        core = [by_id[rid] for rid in pinned]
        mode = "behavioral_lab"
        candidates = [
            record
            for record in records
            if record["rule_id"] not in pinned
            and record["mode"] in {mode, "all"}
            and record["phase"] == "topology"
            # Current examples have explicit applicability predicates above.
            # An unrelated scenario must not enter via a generic word like PC.
            and not record["rule_id"].startswith("EX-")
        ]
        if not candidates:
            return core
        texts = [record["text"] for record in candidates]
        lexical = _BM25Index(texts)
        subjects = _topology_queries(architecture)
        query = "IPv4 behavioral lab topology connected routes later configuration " + " ".join(
            subjects
        )
        scores = lexical.score(query)
        ranking = (
            self._hybrid_rank(candidates, [query, *subjects], scores, fingerprint)
            if self.backend == "hybrid"
            else _rank(scores)
        )
        selected = ranking[: self.top_k]
        return core + [candidates[index] for index in selected]


def retrieve_context(architecture: JSONObject, **options: Any) -> list[KnowledgeRecord]:
    """Convenience entry point; the JSON input is never normalized or mutated."""
    return KnowledgeRetriever(**options).retrieve(architecture)
