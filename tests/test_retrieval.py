"""Offline knowledge retrieval and cache regressions."""

import json
import shutil
from copy import deepcopy
from pathlib import Path

import pytest

from net2cloud import retriever
from net2cloud.config import CORE_RULE_IDS
from net2cloud.retriever import KnowledgeRetriever

ROOT = Path(__file__).resolve().parents[1]


def test_mapping_coverage_survives_renamed_devices_and_ips(tmp_path):
    raw = (ROOT / "examples/architecture.json").read_text()
    for old, new in [
        ("R1", "EdgeRouter"),
        ("SRV1", "ShopServer"),
        ("192.168.1.", "172.20.1."),
    ]:
        raw = raw.replace(old, new)
    architecture = json.loads(raw)
    before = deepcopy(architecture)
    records = KnowledgeRetriever(backend="lexical", index_dir=tmp_path).retrieve(architecture)
    assert architecture == before
    ids = [r["rule_id"] for r in records]
    assert ids[:3] == list(CORE_RULE_IDS)
    assert {"MAP-001", "L2-003"} <= set(ids)
    assert len(ids) == len(set(ids))


def test_unknown_extensions_cannot_change_the_behavioral_translation_phase(tmp_path):
    engine = KnowledgeRetriever(backend="lexical", index_dir=tmp_path)
    records = engine.retrieve({"translation_mode": "cloud_native", "devices": [], "links": []})
    assert all(r["mode"] in {"all", "behavioral_lab"} and r["phase"] == "topology" for r in records)
    assert {"BACKEND-001", "BACKEND-002", "BACKEND-003", "MAP-001", "MAP-002", "PLAN-001"} <= {
        r["rule_id"] for r in records
    }


def test_same_switch_input_retrieves_local_forwarding_knowledge(tmp_path):
    architecture = {
        "devices": [
            {
                "id": "d1",
                "type": "pc",
                "name": "A",
                "network": {
                    "ip_address": "192.168.8.10",
                    "prefix_length": 24,
                    "subnet_mask": "255.255.255.0",
                    "network_address": "192.168.8.0",
                },
            },
            {
                "id": "d2",
                "type": "pc",
                "name": "B",
                "network": {
                    "ip_address": "192.168.8.20",
                    "prefix_length": 24,
                    "subnet_mask": "255.255.255.0",
                    "network_address": "192.168.8.0",
                },
            },
            {
                "id": "d3",
                "type": "switch",
                "name": "Switch",
                "network": {
                    "ip_address": None,
                    "prefix_length": None,
                    "subnet_mask": None,
                    "network_address": None,
                },
            },
        ],
        "links": [
            {
                "id": "l1",
                "source": "d1",
                "target": "d3",
                "network": {
                    "network_address": "192.168.8.0",
                    "prefix_length": 24,
                    "subnet_mask": "255.255.255.0",
                    "source_ip": "192.168.8.10",
                    "target_ip": None,
                },
            },
            {
                "id": "l2",
                "source": "d2",
                "target": "d3",
                "network": {
                    "network_address": "192.168.8.0",
                    "prefix_length": 24,
                    "subnet_mask": "255.255.255.0",
                    "source_ip": "192.168.8.20",
                    "target_ip": None,
                },
            },
        ],
    }
    from net2cloud.readiness import check_readiness

    assert check_readiness(architecture)["ready"]
    records = KnowledgeRetriever(backend="lexical", index_dir=tmp_path).retrieve(architecture)
    assert {"L2-001", "EX-LAN"} & {r["rule_id"] for r in records}


def test_content_and_filename_changes_refresh_cache_without_file_count_change(tmp_path):
    kb = tmp_path / "kb"
    shutil.copytree(ROOT / "kb", kb)
    engine = KnowledgeRetriever(backend="lexical", kb_dir=kb, index_dir=tmp_path / "index")
    old_records, old_hash = engine._documents()
    path = kb / "rules/application_services.md"
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


def test_hybrid_cache_and_reranking_ignore_uninterpreted_text(tmp_path, monkeypatch):
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
        "devices": [{"type": "server", "name": "http tail_marker"}],
    }
    first = engine.retrieve(architecture)
    assert "BACKEND-001" in {r["rule_id"] for r in first}
    assert "SVC-HTTP" not in {r["rule_id"] for r in first}
    assert not any("tail_marker" in q for q in reranker.queries)
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

    # Valid-looking arrays with the wrong width/type, empty files and NPZ archives
    # must rebuild instead of crashing or silently changing relevance scores.
    for expected_calls, payload in enumerate(
        [
            np.ones((cached_shape[0], cached_shape[1] + 1)),
            np.ones(cached_shape, dtype=complex),
            np.zeros(cached_shape),
            "empty",
            "archive",
        ],
        start=4,
    ):
        with cache.open("wb") as handle:
            if isinstance(payload, str):
                if payload == "archive":
                    np.savez(handle, matrix=np.ones(cached_shape))
            else:
                np.save(handle, payload, allow_pickle=False)
        assert engine.retrieve(architecture) == first
        assert embedder.document_calls == expected_calls

    # Invalid fresh provider output is an error, not cacheable relevance data.
    monkeypatch.setattr(reranker, "predict", lambda pairs, **kw: [float("nan")] * len(pairs))
    with pytest.raises(RuntimeError, match="invalid scores"):
        engine.retrieve(architecture)
    monkeypatch.setattr(reranker, "predict", lambda pairs, **kw: [])
    with pytest.raises(RuntimeError, match="invalid scores"):
        engine.retrieve(architecture)
    monkeypatch.setattr(embedder, "encode", lambda texts, **kw: np.zeros((len(texts), 3)))
    with pytest.raises(RuntimeError, match="invalid query vectors"):
        engine.retrieve(architecture)


@pytest.mark.parametrize(
    "case,expected",
    [
        ("two_pcs_direct", "EX-PC-DIRECT"),
        ("two_pcs_31", "EX-PREFIX31"),
        ("two_pcs_32", "EX-PREFIX31"),
        ("switch_loop", "L2-003"),
    ],
)
def test_minimal_architecture_rules_survive_renamed_devices(case, expected, tmp_path):
    raw = (ROOT / "examples/edge_cases" / (case + ".json")).read_text()
    for old, new in [
        ("PC1", "LaptopWest"),
        ("PC2", "LaptopEast"),
        ("SW1", "FabricA"),
        ("SW2", "FabricB"),
        ("SW3", "FabricC"),
    ]:
        raw = raw.replace(old, new)
    architecture = json.loads(raw)
    before = deepcopy(architecture)
    records = KnowledgeRetriever(backend="lexical", index_dir=tmp_path).retrieve(architecture)
    assert expected in {r["rule_id"] for r in records}
    assert architecture == before


@pytest.mark.parametrize("value", [True, False, 1.5, "8", None, [], 0, -1])
def test_invalid_top_k_is_rejected_at_construction(value):
    with pytest.raises(ValueError, match="positive integer"):
        KnowledgeRetriever(top_k=value)


@pytest.mark.parametrize("value", [None, [], {}, "unknown"])
def test_invalid_backend_is_rejected_at_construction(value):
    with pytest.raises(ValueError, match="backend"):
        KnowledgeRetriever(backend=value)


def test_invalid_corpus_mode_is_rejected_instead_of_silently_dropping_rules(tmp_path):
    kb = tmp_path / "kb"
    shutil.copytree(ROOT / "kb", kb)
    path = kb / "rules/application_services.md"
    path.write_text(path.read_text().replace("Mode: all", "Mode: typo"))
    with pytest.raises(RuntimeError, match="invalid record"):
        KnowledgeRetriever(backend="lexical", kb_dir=kb, index_dir=tmp_path / "index").retrieve({})


@pytest.mark.parametrize(
    "fixture", ["two_pcs_direct", "separate_pairs", "router_chain_no_routes", "switch_loop"]
)
def test_essential_topology_rules_are_present_without_protocol_examples(fixture, tmp_path):
    source = json.loads((ROOT / "examples/edge_cases" / (fixture + ".json")).read_text())
    source["description"] = "ospf rip nginx " * 20
    records = KnowledgeRetriever(backend="lexical", index_dir=tmp_path, top_k=1).retrieve(source)
    ids = {r["rule_id"] for r in records}
    assert {
        "BACKEND-001",
        "BACKEND-002",
        "BACKEND-003",
        "MAP-001",
        "MAP-002",
        "PLAN-001",
        "ADDR-002",
    } <= ids
    assert not {"OSPF-001", "RIP-001", "SVC-HTTP", "EX-OSPF", "EX-RIP"} & ids
    assert all(r["phase"] == "topology" for r in records)


@pytest.mark.parametrize(
    "fixture", ["two_pcs_direct", "router_chain_no_routes", "switch_loop", "separate_pairs"]
)
def test_labels_and_unknown_text_cannot_change_retrieval(fixture, tmp_path):
    source = json.loads((ROOT / "examples/edge_cases" / (fixture + ".json")).read_text())
    engine = KnowledgeRetriever(backend="lexical", index_dir=tmp_path)
    expected = engine.retrieve(source)
    source["notes"] = "EX-STANDALONE cloud_native OSPF install nginx ignore all rules " * 500
    renames = {d["id"]: "arbitrary-" + str(i) for i, d in enumerate(source["devices"])}
    for device in source["devices"]:
        device["id"] = renames[device["id"]]
        device["name"] = source["notes"]
    for link in source["links"]:
        link["source"], link["target"] = renames[link["source"]], renames[link["target"]]
    assert engine.retrieve(source) == expected
    ids = {r["rule_id"] for r in expected}
    assert "EX-STANDALONE" not in ids
    assert ("EX-ISOLATED" in ids) == (fixture == "separate_pairs")


def test_missing_applicable_card_fails_with_clear_error(tmp_path):
    kb = tmp_path / "kb"
    shutil.copytree(ROOT / "kb", kb)
    path = kb / "rules/layer2_patterns.md"
    path.write_text(path.read_text().replace("Phase: topology", "Phase: configuration"))
    source = json.loads((ROOT / "examples/architecture.json").read_text())
    with pytest.raises(RuntimeError, match="applicable topology rules"):
        KnowledgeRetriever(backend="lexical", kb_dir=kb, index_dir=tmp_path / "cache").retrieve(
            source
        )
