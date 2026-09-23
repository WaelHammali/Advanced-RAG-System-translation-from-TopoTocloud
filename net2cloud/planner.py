"""Produce one JSON plan from caller-owned architecture and retrieved knowledge."""

from __future__ import annotations

from typing import Any

from .config import PLAN_MAX_COMPLETION_TOKENS, PLAN_MODEL, ROOT_DIR, SUPPORTED_PLAN_MODELS
from .contracts import JSONObject, KnowledgeRecord
from .json_io import dumps_json, loads_json
from .plan_contract import required_cloud_plan, required_limitations, validate_cloud_plan
from .readiness import require_ready

SYSTEM_PROMPT = (ROOT_DIR / "net2cloud" / "prompts" / "planner.txt").read_text(encoding="utf-8")

PLAN_SECTION_TYPES = {
    "cloud_plan": dict,
    "rule_ids": list,
    "limitations": list,
}


class PlanResponseError(ValueError):
    """The provider returned an incomplete or unusable JSON plan envelope."""


def _response_content(response: Any) -> str:
    choices = getattr(response, "choices", None)
    if not choices:
        raise PlanResponseError("The model returned no completion.")
    choice = choices[0]
    finish_reason = getattr(choice, "finish_reason", None)
    if finish_reason == "length":
        raise RuntimeError("Model output was truncated; no complete plan was returned.")
    if finish_reason != "stop":
        raise PlanResponseError(
            f"The model did not complete a plan (finish_reason={finish_reason!r})."
        )
    content = getattr(getattr(choice, "message", None), "content", None)
    if not isinstance(content, str) or not content.strip():
        raise PlanResponseError("The model returned no JSON plan content.")
    return content


def _parse_plan(content: str) -> JSONObject:
    """Check the response envelope only; nested plan semantics remain external."""
    try:
        plan = loads_json(content)
    except ValueError as error:
        raise PlanResponseError("The model returned invalid or ambiguous JSON.") from error
    if not isinstance(plan, dict):
        raise PlanResponseError("The model response must be a JSON object.")
    for section, expected_type in PLAN_SECTION_TYPES.items():
        if not isinstance(plan.get(section), expected_type):
            raise PlanResponseError(
                f"The model plan requires {section} as {expected_type.__name__}."
            )
    if plan["cloud_plan"].get("provider") != "aws":
        raise PlanResponseError("cloud_plan.provider must be aws.")
    for section in ("rule_ids", "limitations"):
        if any(not isinstance(item, str) or not item.strip() for item in plan[section]):
            raise PlanResponseError(f"{section} must contain nonempty strings.")
    if len(set(plan["rule_ids"])) != len(plan["rule_ids"]):
        raise PlanResponseError("rule_ids must not contain duplicates.")
    unexpected = set(plan) - PLAN_SECTION_TYPES.keys() - {"architecture", "knowledge"}
    if unexpected:
        raise PlanResponseError(
            "Unexpected model response sections: " + ", ".join(sorted(unexpected))
        )
    # app.py attaches source architecture and knowledge from authoritative data.
    return {section: plan[section] for section in PLAN_SECTION_TYPES}


def plan_with_rag(
    architecture: JSONObject,
    retrieved_chunks: list[KnowledgeRecord],
    *,
    client: Any = None,
) -> JSONObject:
    """Translate a ready architecture without dialogue or topology overrides."""
    require_ready(architecture)
    required_plan = required_cloud_plan(architecture)
    if PLAN_MODEL not in SUPPORTED_PLAN_MODELS:
        raise ValueError(
            "NET2TF_PLAN_MODEL must be one of "
            + ", ".join(SUPPORTED_PLAN_MODELS)
            + ". Use a Groq Free-plan account; other models are disabled."
        )
    if client is None:
        try:
            from groq import Groq
        except ImportError as error:
            raise RuntimeError(
                "Planning requires the groq package; install requirements.txt."
            ) from error
        # GROQ_API_KEY comes from the caller. Quota failures must not trigger retries.
        client = Groq(max_retries=0)

    context = [
        {"rule_id": c["rule_id"], "source": c["source"], "heading": c["heading"], "text": c["text"]}
        for c in retrieved_chunks
    ]
    try:
        response = client.chat.completions.create(
            model=PLAN_MODEL,
            temperature=0,
            max_completion_tokens=PLAN_MAX_COMPLETION_TOKENS,
            reasoning_effort="medium",
            include_reasoning=False,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": dumps_json(
                        {
                            "architecture": architecture,
                            "knowledge": context,
                            "required_cloud_plan": required_plan,
                        }
                    ),
                },
            ],
        )
    except Exception as error:
        if getattr(error, "status_code", None) == 429:
            raise RuntimeError(
                "Groq quota reached. Wait for the applicable limit to reset before retrying. "
                "For a request exceeding the token limit, reduce its size. "
                "No automatic retry or model fallback was attempted."
            ) from error
        if getattr(error, "status_code", None) == 413:
            raise RuntimeError(
                "The architecture and retrieved context exceed Groq's request limit. "
                "Use a smaller lab or fewer retrieved records; no plan was generated."
            ) from error
        raise
    plan = _parse_plan(_response_content(response))
    unknown_rules = set(plan["rule_ids"]) - {record["rule_id"] for record in retrieved_chunks}
    if unknown_rules:
        raise PlanResponseError(
            "Model cited rules outside the supplied context: " + ", ".join(sorted(unknown_rules))
        )
    if not plan["rule_ids"]:
        raise PlanResponseError("The plan must cite at least one retrieved rule.")
    validate_cloud_plan(plan["cloud_plan"], architecture, expected=required_plan)
    plan["limitations"] = list(
        dict.fromkeys([*required_limitations(architecture), *plan["limitations"]])
    )
    return plan
