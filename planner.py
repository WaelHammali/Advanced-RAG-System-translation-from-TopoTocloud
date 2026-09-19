"""Produce one JSON plan from caller-owned architecture and retrieved knowledge."""

from __future__ import annotations

from typing import Any

from config import PLAN_MODEL, ROOT_DIR
from contracts import JSONObject, KnowledgeRecord
from json_io import dumps_json, loads_json
from readiness import require_ready

SYSTEM_PROMPT = (ROOT_DIR / "prompts" / "planner.txt").read_text(encoding="utf-8")

PLAN_SECTION_TYPES = {
    "cloud_plan": dict,
    "ansible_plan": dict,
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
    if client is None:
        try:
            from groq import Groq
        except ImportError as error:
            raise RuntimeError(
                "Planning requires the groq package; install requirements.txt."
            ) from error
        client = Groq()  # GROQ_API_KEY is supplied by the caller's environment.

    context = [
        {"rule_id": c["rule_id"], "source": c["source"], "heading": c["heading"], "text": c["text"]}
        for c in retrieved_chunks
    ]
    response = client.chat.completions.create(
        model=PLAN_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": dumps_json(
                    {"architecture": architecture, "knowledge": context},
                    indent=2,
                ),
            },
        ],
    )
    return _parse_plan(_response_content(response))
