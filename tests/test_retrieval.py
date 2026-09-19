"""Offline knowledge retrieval and cache regressions."""

import json
import shutil
from copy import deepcopy
from pathlib import Path

import pytest

import retriever
from config import CORE_RULE_IDS
from retriever import KnowledgeRetriever

ROOT = Path(__file__).resolve().parents[1]


def test_protocol_service_and_task_coverage_survives_different_names_and_ips(tmp_path):
    raw = (ROOT / "examples/architecture.json").read_text()
    for old, new in [
        ("R1", "EdgeWest"),
        ("R2", "EdgeEast"),
        ("WEB1", "ShopServer"),
        ("10.10.10.", "172.20.1."),
        ("10.20.20.", "172.20.2."),
    ]:
        raw = raw.replace(old, new)
    architecture = json.loads(raw)
    before = deepcopy(architecture)
    records = KnowledgeRetriever(backend="lexical", index_dir=tmp_path).retrieve(architecture)
    assert architecture == before
    ids = [r["rule_id"] for r in records]
    assert ids[:3] == list(CORE_RULE_IDS)
    assert {"MAP-001", "OSPF-001", "SVC-HTTP", "AUTO-001"} <= set(ids)
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("protocol, rule", [("rip", "RIP-001"), ("ospf", "OSPF-001")])
def test_named_routing_protocol_has_a_rule(tmp_path, protocol, rule):
    architecture = {
        "components": [
            {"id": "any-name", "routing": {"protocols": [{"name": protocol, "enabled": True}]}}
        ]
    }
    records = KnowledgeRetriever(backend="lexical", index_dir=tmp_path).retrieve(architecture)
    assert rule in {r["rule_id"] for r in records}


def test_cloud_native_mode_excludes_behavioral_candidates(tmp_path):
    records = KnowledgeRetriever(backend="lexical", index_dir=tmp_path).retrieve(
        {"translation_mode": "cloud_native", "components": [{"services": [{"protocol": "http"}]}]}
    )
    assert all(
        r["mode"] in {"all", "cloud_native"} for r in records if r["rule_id"] not in CORE_RULE_IDS
    )
    assert "SVC-HTTP" in {r["rule_id"] for r in records}


@pytest.mark.parametrize(
    "routes", [[], [{"destination": "172.20.2.0/24", "via": "10.255.0.2", "interface": "wan0"}]]
)
def test_static_routing_retrieves_return_path_rule_without_repairing_input(tmp_path, routes):
    architecture = json.loads((ROOT / "examples/architecture.json").read_text())
    for component in architecture["components"]:
        if component["type"] == "router":
            component["routing"]["protocols"] = []
            component["routing"]["static_routes"] = deepcopy(routes)
    before = deepcopy(architecture)
    records = KnowledgeRetriever(backend="lexical", index_dir=tmp_path).retrieve(architecture)
    assert "STATIC-001" in {r["rule_id"] for r in records}
    assert architecture == before


def test_same_switch_input_retrieves_local_forwarding_knowledge(tmp_path):
    architecture = {
        "components": [
            {"id": "A", "type": "pc", "interfaces": [{"id": "eth0", "ipv4": "192.168.8.10/24"}]},
            {"id": "B", "type": "pc", "interfaces": [{"id": "eth0", "ipv4": "192.168.8.20/24"}]},
            {
                "id": "Switch",
                "type": "switch",
                "interfaces": [{"id": "p1", "access_vlan": 10}, {"id": "p2", "access_vlan": 10}],
            },
        ],
        "edges": [
            {
                "source": {"component": "A", "interface": "eth0"},
                "target": {"component": "Switch", "interface": "p1"},
            },
            {
                "source": {"component": "B", "interface": "eth0"},
                "target": {"component": "Switch", "interface": "p2"},
            },
        ],
    }
    records = KnowledgeRetriever(backend="lexical", index_dir=tmp_path).retrieve(architecture)
    assert {"L2-001", "EX-LAN"} & {r["rule_id"] for r in records}


def test_content_and_filename_changes_refresh_cache_without_file_count_change(tmp_path):
    kb = tmp_path / "kb"
    shutil.copytree(ROOT / "kb", kb)
    engine = KnowledgeRetriever(backend="lexical", kb_dir=kb, index_dir=tmp_path / "index")
    old_records, old_hash = engine._documents()
    path = kb / "application_services.md"
    path.write_text(path.read_text().replace("HTTP services", "HTTP applications"))
    new_records, new_hash = engine._documents()
    assert old_hash != new_hash
    assert old_records != new_records
    path.rename(kb / "renamed_services.md")
    moved_records, moved_hash = engine._documents()
    assert new_hash != moved_hash
    assert (
        next(r for r in moved_records if r["rule_id"] == "SVC-HTTP")["source"]
        == "kb/renamed_services.md"
    )
    assert engine._documents() == (moved_records, moved_hash)
    (tmp_path / "index" / "documents.json").write_text("{broken")
    assert engine._documents() == (moved_records, moved_hash)
    # Syntactically valid JSON can also contain an unusable record cache.
    cache = tmp_path / "index" / "documents.json"
    cache.write_text(json.dumps({"fingerprint": moved_hash, "records": [{}]}))
    assert engine._documents() == (moved_records, moved_hash)


def test_hybrid_windows_cache_and_reranking_without_model_download(tmp_path, monkeypatch):
    np = pytest.importorskip("numpy")

    class Tokenizer:
        def encode(self, text, **kwargs):
            return text.split()

        def decode(self, tokens):
            return " ".join(tokens)

    class Embedder:
        tokenizer = Tokenizer()

        def __init__(self):
            self.document_calls = 0

        def encode(self, texts, **kwargs):
            if texts[0].startswith("## "):
                self.document_calls += 1
            vectors = np.array(
                [[1, t.lower().count("ospf"), t.lower().count("http")] for t in texts], dtype=float
            )
            return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)

    class Reranker:
        def __init__(self):
            self.queries = []

        def predict(self, pairs, **kwargs):
            self.queries.extend(q for q, text in pairs)
            return [len(set(q.lower().split()) & set(text.lower().split())) for q, text in pairs]

    embedder, reranker = Embedder(), Reranker()
    monkeypatch.setattr(retriever, "_models", lambda: (embedder, reranker))
    engine = KnowledgeRetriever(backend="hybrid", index_dir=tmp_path)
    architecture = {
        "a_long_description": "filler " * 600 + "tail_marker",
        "services": [{"protocol": "http"}],
    }
    first = engine.retrieve(architecture)
    assert "SVC-HTTP" in {r["rule_id"] for r in first}
    assert any("tail_marker" in q for q in reranker.queries)
    assert engine.retrieve(architecture) == first
    assert embedder.document_calls == 1
    # A corrupt NumPy cache rebuilds rather than silently changing retrieval.
    (cache,) = tmp_path.glob("embeddings-*.npy")
    cache.write_bytes(b"invalid")
    assert engine.retrieve(architecture) == first
    assert embedder.document_calls == 2
    # A valid .npy file containing invalid vectors must also be rebuilt.
    cached_shape = np.load(cache, allow_pickle=False).shape
    with cache.open("wb") as handle:
        np.save(handle, np.full(cached_shape, np.nan))
    assert engine.retrieve(architecture) == first
    assert embedder.document_calls == 3
