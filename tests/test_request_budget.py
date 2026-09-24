"""Oversized requests must stop before a provider call or output publication."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from net2cloud import app, request_budget
from net2cloud.planner import plan_with_rag
from net2cloud.request_budget import RequestBudgetError, require_request_budget
from net2cloud.retriever import KnowledgeRetriever

ROOT = Path(__file__).resolve().parents[1]


def test_budget_includes_schema_and_reserved_completion(monkeypatch):
    messages = [{"role": "user", "content": "réseau <|start|>"}]
    schema = {"type": "json_schema", "description": "extra " * 100}
    total = request_budget.request_token_budget(messages, schema)["estimated_total_tokens"]
    monkeypatch.setattr(request_budget, "PLAN_REQUEST_TOKEN_BUDGET", total)
    require_request_budget(messages, schema)
    monkeypatch.setattr(request_budget, "PLAN_REQUEST_TOKEN_BUDGET", total - 1)
    with pytest.raises(RequestBudgetError, match="no API request was sent"):
        require_request_budget(messages, schema)


def test_oversized_context_never_calls_provider_or_mutates_source():
    source = json.loads((ROOT / "examples/architecture.json").read_text())
    before = json.dumps(source)
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kw: pytest.fail("unexpected provider request")
            )
        )
    )
    records = [
        {
            "rule_id": "CORE-001",
            "text": "Complete untruncated rule " * 10000,
            "phase": "topology",
            "mode": "all",
        }
    ]
    with pytest.raises(RequestBudgetError):
        plan_with_rag(source, records, client=client)
    assert json.dumps(source) == before


def test_budget_failure_keeps_existing_cli_output(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(request_budget, "PLAN_REQUEST_TOKEN_BUDGET", 1)
    monkeypatch.setattr(
        app,
        "KnowledgeRetriever",
        lambda **kw: KnowledgeRetriever(index_dir=tmp_path / "cache", **kw),
    )
    output = tmp_path / "plan.json"
    output.write_text("previous")
    assert (
        app.main(
            [
                "plan",
                "--input",
                str(ROOT / "examples/architecture.json"),
                "--retrieval",
                "lexical",
                "--output",
                str(output),
            ]
        )
        == 1
    )
    assert output.read_text() == "previous"
    assert "local token budget" in capsys.readouterr().err
