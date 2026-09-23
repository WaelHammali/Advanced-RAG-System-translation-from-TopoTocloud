"""Exercise the JSON boundary without a live model, cloud or generator."""

import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from net2cloud import app, planner
from net2cloud.config import CORE_RULE_IDS
from net2cloud.plan_contract import required_cloud_plan, validate_cloud_plan
from net2cloud.planner import plan_with_rag
from net2cloud.retriever import KnowledgeRetriever

ROOT = Path(__file__).resolve().parents[1]


def valid_response(architecture, rules=None):
    return {
        "cloud_plan": required_cloud_plan(architecture),
        "rule_ids": rules if rules is not None else ["CORE-001"],
        "limitations": [],
    }


class ModelClient:
    def __init__(self, payload, *, finish_reason="stop"):
        self.payload = payload
        self.finish_reason = finish_reason
        self.calls = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **request):
        self.calls.append(request)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self.payload),
                    finish_reason=self.finish_reason,
                )
            ]
        )


@pytest.fixture
def architecture():
    return json.loads((ROOT / "examples/architecture.json").read_text())


@pytest.fixture
def retrieval(tmp_path):
    return KnowledgeRetriever(backend="lexical", index_dir=tmp_path / "index")


def test_mixed_configuration_reaches_model_and_input_remains_unchanged(architecture, retrieval):
    architecture["custom"] = {"unicode": "réseau", "values": [False, None, 0]}
    before = deepcopy(architecture)
    model_plan = valid_response(architecture, ["MAP-001", "L2-003"])
    model_plan.update(architecture={"invented": True}, knowledge=[])
    client = ModelClient(json.dumps(model_plan))
    output = app.plan_architecture(architecture, client=client, retriever=retrieval)
    assert architecture == before == output["architecture"]
    output["architecture"]["custom"]["values"].append("mutation")
    assert architecture == before
    (request,) = client.calls
    supplied = json.loads(request["messages"][1]["content"])
    assert supplied["architecture"] == before
    ids = {chunk["rule_id"] for chunk in supplied["knowledge"]}
    assert {*CORE_RULE_IDS, "MAP-001", "L2-003"} <= ids
    assert output["cloud_plan"] == model_plan["cloud_plan"]
    assert request["response_format"] == {"type": "json_object"}
    assert {item["rule_id"] for item in output["knowledge"]} == ids


def test_arbitrary_extra_fields_are_preserved_on_ready_input(architecture, retrieval):
    architecture["custom_device_format"] = {"strange_field": "kept"}
    client = ModelClient(json.dumps(valid_response(architecture)))
    output = app.plan_architecture(architecture, client=client, retriever=retrieval)
    assert output["architecture"] == architecture
    assert len(client.calls) == 1


def test_many_routers_do_not_override_model_plan(retrieval):
    # A flat chain on one shared subnet: each router has at most one address,
    # used consistently across however many links it has.
    architecture = {
        "devices": [
            {
                "id": f"edge-{i}",
                "type": "router",
                "name": f"Edge-{i}",
                "network": {
                    "ip_address": f"10.254.0.{i + 1}",
                    "prefix_length": 24,
                    "subnet_mask": "255.255.255.0",
                    "network_address": "10.254.0.0",
                },
            }
            for i in range(9)
        ],
        "links": [],
    }
    for index in range(8):
        left, right = architecture["devices"][index : index + 2]
        architecture["links"].append(
            {
                "id": f"cable-{index}",
                "source": left["id"],
                "target": right["id"],
                "network": {
                    "network_address": "10.254.0.0",
                    "prefix_length": 24,
                    "subnet_mask": "255.255.255.0",
                    "source_ip": left["network"]["ip_address"],
                    "target_ip": right["network"]["ip_address"],
                },
            }
        )
    expected = valid_response(architecture)
    output = app.plan_architecture(
        architecture, client=ModelClient(json.dumps(expected)), retriever=retrieval
    )
    assert output["cloud_plan"] == expected["cloud_plan"]


@pytest.mark.parametrize("payload", ["not JSON", "```json\n{}\n```", "[]", "null"])
def test_invalid_model_envelope_is_an_error_not_a_fallback(payload, architecture):
    with pytest.raises(ValueError):
        plan_with_rag(architecture, [], client=ModelClient(payload))


def test_truncated_model_response_is_rejected_even_if_it_parses(architecture):
    with pytest.raises(RuntimeError, match="truncated"):
        plan_with_rag(architecture, [], client=ModelClient("{}", finish_reason="length"))


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"questions": ["Which IP address?"]},
        {"cloud_plan": [], "rule_ids": [], "limitations": []},
        {
            "cloud_plan": {"provider": "aws"},
            "rule_ids": [],
            "limitations": [],
            "questions": ["Confirm deployment?"],
        },
        {
            "cloud_plan": {"provider": "aws"},
            "rule_ids": [],
            "limitations": [],
            "files": {"main.tf": "model-generated code"},
        },
    ],
)
def test_non_plan_model_objects_are_rejected(payload, architecture):
    with pytest.raises(ValueError):
        plan_with_rag(architecture, [], client=ModelClient(json.dumps(payload)))


def test_model_transport_errors_are_not_hidden(retrieval, architecture):
    class BrokenClient(ModelClient):
        def create(self, **request):
            raise RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError, match="provider unavailable"):
        app.plan_architecture(architecture, client=BrokenClient("{}"), retriever=retrieval)


def test_cli_context_is_json_and_requires_no_client(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        app,
        "KnowledgeRetriever",
        lambda **kw: KnowledgeRetriever(index_dir=tmp_path / "index", **kw),
    )
    monkeypatch.setattr(app, "plan_with_rag", lambda *a, **kw: pytest.fail("unexpected model call"))
    output = tmp_path / "result.json"
    status = app.main(
        [
            "context",
            "--input",
            str(ROOT / "examples/architecture.json"),
            "--retrieval",
            "lexical",
            "--output",
            str(output),
        ]
    )
    captured = capsys.readouterr()
    assert status == 0 and captured.err == ""
    assert json.loads(captured.out) == json.loads(output.read_text())
    assert "MAP-001" in {r["rule_id"] for r in json.loads(captured.out)["knowledge"]}


def test_cli_plan_writes_only_json_artifact(tmp_path, monkeypatch, capsys, architecture):
    import sys

    client = ModelClient(json.dumps(valid_response(architecture)))

    def make_client(**options):
        assert options == {"max_retries": 0}
        return client

    monkeypatch.setitem(sys.modules, "groq", SimpleNamespace(Groq=make_client))
    monkeypatch.setattr(
        app,
        "KnowledgeRetriever",
        lambda **kw: KnowledgeRetriever(index_dir=tmp_path / "index", **kw),
    )
    output = tmp_path / "generated" / "plan.json"
    status = app.main(
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
    captured = capsys.readouterr()
    assert status == 0 and not captured.err
    assert json.loads(captured.out) == json.loads(output.read_text())
    assert list(output.parent.iterdir()) == [output]
    assert len(client.calls) == 1


@pytest.mark.parametrize("content", ["invalid", "[]"])
def test_cli_bad_json_envelope_fails_cleanly(tmp_path, capsys, content):
    path = tmp_path / "input.json"
    path.write_text(content)
    assert app.main(["plan", "--input", str(path)]) == (2 if content == "[]" else 1)
    captured = capsys.readouterr()
    assert captured.out == ""
    report = json.loads(captured.err)
    assert report.get("error") or report.get("status") == "not_ready"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "",
        '{"cloud_plan": {"provider": "aws"}, "rule_ids": [], "limitations": [NaN]}',
        '{"cloud_plan": {"provider": "aws"}, "cloud_plan": {"provider": "aws"}, "rule_ids": [], "limitations": []}',
    ],
)
def test_empty_or_ambiguous_provider_content_is_rejected(payload, architecture):
    with pytest.raises(ValueError):
        plan_with_rag(architecture, [], client=ModelClient(payload))


@pytest.mark.parametrize("reason", [None, "content_filter", "tool_calls"])
def test_non_completion_finish_reason_is_an_error(reason, architecture):
    with pytest.raises(ValueError, match="did not complete"):
        plan_with_rag(architecture, [], client=ModelClient("{}", finish_reason=reason))


def test_provider_with_no_choices_has_a_clear_error(architecture):
    class EmptyClient(ModelClient):
        def create(self, **request):
            return SimpleNamespace(choices=[])

    with pytest.raises(ValueError, match="no completion"):
        plan_with_rag(architecture, [], client=EmptyClient("{}"))


def test_cli_cannot_overwrite_input(tmp_path, capsys):
    path = tmp_path / "architecture.json"
    original = '{"devices": []}'
    path.write_text(original, encoding="utf-8")
    assert app.main(["context", "--input", str(path), "--output", str(path)]) == 1
    assert path.read_text() == original
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "must differ" in json.loads(captured.err)["error"]


def test_falsey_injected_retriever_is_still_used(architecture):
    class InjectedRetriever:
        def __bool__(self):
            return False

        def retrieve(self, architecture):
            return [
                {
                    "rule_id": "CORE-001",
                    "source": "injected",
                    "heading": "core",
                    "text": "preserve",
                    "mode": "all",
                }
            ]

    client = ModelClient(json.dumps(valid_response(architecture)))
    result = app.plan_architecture(architecture, retriever=InjectedRetriever(), client=client)
    assert result["knowledge"][0]["source"] == "injected"


def test_cli_context_runs_outside_checkout_without_optional_dependencies(tmp_path):
    environment = {
        **os.environ,
        "NET2TF_INDEX_DIR": str(tmp_path / "index"),
        "NET2TF_KB_DIR": str(ROOT / "kb"),
    }
    output = tmp_path / "context.json"
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            str(ROOT / "app.py"),
            "context",
            "--retrieval",
            "lexical",
            "--input",
            str(ROOT / "examples/architecture.json"),
            "--output",
            str(output),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stderr
    context = json.loads(result.stdout)
    assert context == json.loads(output.read_text(encoding="utf-8"))
    assert {"MAP-001", "L2-003"} <= {r["rule_id"] for r in context["knowledge"]}


@pytest.mark.parametrize("model", ["openai/gpt-oss-120b", "openai/gpt-oss-20b"])
def test_gpt_oss_request_preserves_input_and_bounds_completion(model, architecture, monkeypatch):
    monkeypatch.setattr(planner, "PLAN_MODEL", model)
    client = ModelClient(json.dumps(valid_response(architecture)))
    records = [
        {"rule_id": "CORE-001", "source": "test", "heading": "test", "text": "test", "mode": "all"}
    ]
    plan_with_rag(architecture, records, client=client)
    (request,) = client.calls
    assert request["model"] == model
    assert request["max_completion_tokens"] == 4096
    assert request["reasoning_effort"] == "medium"
    assert request["include_reasoning"] is False
    assert "reasoning_format" not in request
    content = request["messages"][1]["content"]
    supplied = json.loads(content)
    assert supplied["architecture"] == architecture
    assert supplied["required_cloud_plan"] == required_cloud_plan(architecture)
    assert "\n" not in content


@pytest.mark.parametrize("model", ["llama-3.3-70b-versatile", "unknown-model"])
def test_unapproved_model_is_rejected_before_provider_call(model, architecture, monkeypatch):
    monkeypatch.setattr(planner, "PLAN_MODEL", model)
    client = ModelClient("{}")
    with pytest.raises(ValueError, match="other models are disabled"):
        plan_with_rag(architecture, [], client=client)
    assert client.calls == []


@pytest.mark.parametrize("status, message", [(429, "quota reached"), (413, "request limit")])
def test_provider_limits_fail_once_and_preserve_existing_output(
    status, message, tmp_path, monkeypatch, capsys
):
    attempts = []

    class LimitedClient(ModelClient):
        def create(self, **request):
            attempts.append(request)
            error = RuntimeError("provider limit")
            error.status_code = status
            raise error

    monkeypatch.setitem(sys.modules, "groq", SimpleNamespace(Groq=lambda **kw: LimitedClient("{}")))
    monkeypatch.setattr(
        app,
        "KnowledgeRetriever",
        lambda **kw: KnowledgeRetriever(index_dir=tmp_path / "index", **kw),
    )
    output = tmp_path / "plan.json"
    output.write_text('{"previous": true}\n')
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
    captured = capsys.readouterr()
    assert captured.out == ""
    assert message in json.loads(captured.err)["error"]
    assert output.read_text() == '{"previous": true}\n'
    assert len(attempts) == 1


@pytest.mark.parametrize("provider", [None, "", "azure", "gcp", [], {}])
def test_non_aws_model_output_is_rejected(provider, architecture):
    response = {"cloud_plan": {"provider": provider}, "rule_ids": [], "limitations": []}
    with pytest.raises(ValueError, match="provider must be aws"):
        plan_with_rag(architecture, [], client=ModelClient(json.dumps(response)))


@pytest.mark.parametrize("section", ["ansible_plan", "terraform_plan", "automation_plan", "files"])
def test_deployment_sections_cannot_reenter_the_output(section, architecture):
    response = {"cloud_plan": {"provider": "aws"}, "rule_ids": [], "limitations": [], section: {}}
    with pytest.raises(ValueError, match="Unexpected model response sections"):
        plan_with_rag(architecture, [], client=ModelClient(json.dumps(response)))


def test_later_configuration_targets_match_all_source_devices(architecture, retrieval):
    response = valid_response(architecture)
    output = app.plan_architecture(
        architecture, client=ModelClient(json.dumps(response)), retriever=retrieval
    )
    targets = output["cloud_plan"]["configuration_targets"]
    assert {t["device_id"] for t in targets} == {d["id"] for d in architecture["devices"]}
    assert output["cloud_plan"]["initial_configuration"]["routing_protocols"] == []
    assert output["architecture"] == architecture


@pytest.mark.parametrize(
    "case",
    [
        "two_pcs_direct",
        "two_pcs_31",
        "two_pcs_32",
        "separate_pairs",
        "switch_loop",
        "router_chain_no_routes",
    ],
)
def test_edge_case_translation_preserves_the_source_graph(case, tmp_path):
    architecture = json.loads((ROOT / "examples/edge_cases" / (case + ".json")).read_text())
    response = valid_response(architecture)
    before = deepcopy(architecture)
    result = app.plan_architecture(
        architecture,
        client=ModelClient(json.dumps(response)),
        retriever=KnowledgeRetriever(backend="lexical", index_dir=tmp_path),
    )
    assert result["architecture"] == architecture == before
    validate_cloud_plan(result["cloud_plan"], before)
    assert [link["link_id"] for link in result["cloud_plan"]["networking"]["links"]] == [
        link["id"] for link in before["links"]
    ]


def test_package_cli_and_compatibility_launcher_agree_without_dependencies():
    commands = [
        [sys.executable, "-S", "-m", "net2cloud"],
        [sys.executable, "-S", str(ROOT / "app.py")],
    ]
    results = []
    for command in commands:
        result = subprocess.run(
            [*command, "check", "--input", str(ROOT / "examples/architecture.json")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        results.append(json.loads(result.stdout))
    assert results[0] == results[1]
    assert results[0]["ready"] and results[0]["issues"] == []


def test_documented_aws_example_matches_the_response_boundary():
    example = json.loads((ROOT / "examples/aws_plan.json").read_text())
    model_response = {key: example[key] for key in ("cloud_plan", "rule_ids", "limitations")}
    assert planner._parse_plan(json.dumps(model_response)) == model_response
    from net2cloud.readiness import check_readiness

    assert check_readiness(example["architecture"])["ready"]


@pytest.mark.parametrize(
    "section,value",
    [
        ("rule_ids", [None]),
        ("rule_ids", [{}]),
        ("rule_ids", [""]),
        ("rule_ids", ["CORE-001", "CORE-001"]),
        ("limitations", [False]),
        ("limitations", [123]),
        ("limitations", [" "]),
    ],
)
def test_malformed_citations_and_limitations_are_rejected(section, value, architecture):
    payload = {"cloud_plan": {"provider": "aws"}, "rule_ids": [], "limitations": []}
    payload[section] = value
    with pytest.raises(ValueError, match=section):
        plan_with_rag(architecture, [], client=ModelClient(json.dumps(payload)))


def test_model_cannot_claim_rules_it_was_not_given(architecture):
    payload = {"cloud_plan": {"provider": "aws"}, "rule_ids": ["FAKE-001"], "limitations": []}
    with pytest.raises(ValueError, match="outside the supplied context"):
        plan_with_rag(architecture, [], client=ModelClient(json.dumps(payload)))
