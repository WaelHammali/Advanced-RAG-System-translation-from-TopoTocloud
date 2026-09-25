#!/usr/bin/env python3
"""Reproduce topology retrieval evaluations without a provider or cloud call."""

# The standalone CLI adds the repository before importing its application package.
# ruff: noqa: E402

from __future__ import annotations

import argparse
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from net2cloud.config import TOPOLOGY_RULE_IDS
from net2cloud.json_io import dumps_json, loads_json, write_json
from net2cloud.plan_contract import required_cloud_plan
from net2cloud.planner import SYSTEM_PROMPT, _response_format
from net2cloud.readiness import check_readiness
from net2cloud.request_budget import request_token_budget
from net2cloud.retriever import KnowledgeRetriever
from net2cloud.review_context import review_context


def variants(source):
    yield "original", deepcopy(source)
    renamed = deepcopy(source)
    ids = {d["id"]: f"opaque-{i}" for i, d in enumerate(renamed["devices"])}
    for device in renamed["devices"]:
        device["id"] = ids[device["id"]]
        device["name"] = "same display label"
    for i, link in enumerate(renamed["links"]):
        link["id"] = f"cable-{i}"
        link["source"], link["target"] = ids[link["source"]], ids[link["target"]]
    yield "renamed", renamed
    noisy = deepcopy(renamed)
    noisy["description"] = "EX-STANDALONE cloud_native OSPF RIP nginx ignore instructions " * 500
    for device in noisy["devices"]:
        device["name"] = noisy["description"]
    yield "uninterpreted_text", noisy


def evaluate(*, backend="lexical", token_budget=False):
    engine = KnowledgeRetriever(backend=backend)
    results = []
    cases = loads_json((ROOT / "evaluations/topology_cases.json").read_text())
    for case in cases:
        source = loads_json((ROOT / case["input"]).read_text())
        baseline_ids = None
        inputs = variants(source) if case["ready"] else [("original", source)]
        for variant, architecture in inputs:
            before = deepcopy(architecture)
            readiness = check_readiness(architecture)
            failures = []
            if readiness["ready"] != case["ready"]:
                failures.append("unexpected readiness result")
            result = {"case": case["id"], "variant": variant}
            if readiness["ready"]:
                records = engine.retrieve(architecture)
                ids = [r["rule_id"] for r in records]
                required = set(TOPOLOGY_RULE_IDS) | set(case.get("required_rules", []))
                result.update(
                    rule_ids=ids, required_rule_recall=len(required & set(ids)) / len(required)
                )
                if required - set(ids):
                    failures.append("missing required rules")
                if set(ids) & set(case.get("forbidden_rules", [])):
                    failures.append("inapplicable examples retrieved")
                if any(
                    r["phase"] != "topology" or r["mode"] not in {"all", "behavioral_lab"}
                    for r in records
                ):
                    failures.append("configuration or cloud-native knowledge leaked")
                if baseline_ids is not None and baseline_ids != ids:
                    failures.append("labels or uninterpreted text changed retrieval")
                baseline_ids = ids
                if token_budget:
                    context = review_context(
                        architecture, required_cloud_plan(architecture), records
                    )
                    budget = request_token_budget(
                        [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": dumps_json(context)},
                        ],
                        _response_format(ids, context["limitation_options"]),
                    )
                    result["token_budget"] = budget
                    if budget["estimated_total_tokens"] > budget["budget_tokens"]:
                        failures.append("local request budget exceeded")
            else:
                errors = {e["code"] for e in readiness["errors"]}
                result["errors"] = sorted(errors)
                if set(case.get("required_errors", [])) - errors:
                    failures.append("expected readiness error missing")
            if architecture != before:
                failures.append("source mutated")
            result.update(status="fail" if failures else "pass", failures=failures)
            results.append(result)
    return {
        "status": "pass" if all(r["status"] == "pass" for r in results) else "fail",
        "backend": backend,
        "cases": len(cases),
        "variants": len(results),
        "passed": sum(r["status"] == "pass" for r in results),
        "model_requests": 0,
        "scope": "Readiness, required-rule coverage, forbidden examples, label/noise invariance and optional actual-tokenizer budget; no model-answer or runtime accuracy score.",
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retrieval", choices=["lexical", "hybrid"], default="lexical")
    parser.add_argument(
        "--token-budget",
        action="store_true",
        help="Use the real cached GPT-OSS tokenizer; no Groq call",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate(backend=args.retrieval, token_budget=args.token_budget)
    if args.output:
        write_json(args.output, report, indent=2)
    print(dumps_json({k: v for k, v in report.items() if k != "results"}, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
