"""Preflight token budgeting for the two supported GPT-OSS models on Groq."""

from __future__ import annotations

from functools import lru_cache

from .config import PLAN_MAX_COMPLETION_TOKENS, PLAN_REQUEST_TOKEN_BUDGET
from .json_io import dumps_json

# Provider chat/schema framing is not exposed as a stable tokenizer template.
# Count visible content exactly with GPT-OSS's encoding and reserve extra room.
PROVIDER_FRAMING_ALLOWANCE = 256


class RequestBudgetError(RuntimeError):
    """The complete review cannot fit the local budget; no API request was sent."""


@lru_cache(maxsize=1)
def _encoding():
    try:
        import tiktoken
    except ImportError as error:
        raise RuntimeError(
            "Planning token checks require tiktoken; install requirements.txt."
        ) from error
    try:
        return tiktoken.get_encoding("o200k_harmony")
    except Exception as error:
        raise RuntimeError(
            "Cannot load the GPT-OSS tokenizer. Cache o200k_harmony with tiktoken before planning; no Groq request was sent."
        ) from error


def request_token_budget(messages: list[dict], response_format: dict) -> dict[str, int]:
    """Count visible content plus schema, framing allowance and reserved completion.

    This is a local preflight estimate, not a provider quota or remaining-token
    check. Groq's serialization, account limits and concurrent usage may differ.
    Special-token-looking source text is counted as ordinary text.
    """
    encoding = _encoding()
    content = sum(len(encoding.encode_ordinary(message["content"])) for message in messages)
    schema = len(encoding.encode_ordinary(dumps_json(response_format)))
    return {
        "content_tokens": content,
        "schema_tokens": schema,
        "framing_allowance_tokens": PROVIDER_FRAMING_ALLOWANCE,
        "completion_reserve_tokens": PLAN_MAX_COMPLETION_TOKENS,
        "estimated_total_tokens": content
        + schema
        + PROVIDER_FRAMING_ALLOWANCE
        + PLAN_MAX_COMPLETION_TOKENS,
        "budget_tokens": PLAN_REQUEST_TOKEN_BUDGET,
    }


def require_request_budget(messages: list[dict], response_format: dict) -> None:
    usage = request_token_budget(messages, response_format)
    if usage["estimated_total_tokens"] > usage["budget_tokens"]:
        raise RequestBudgetError(
            f"Groq request exceeds the local token budget ({usage['estimated_total_tokens']} estimated including completion; {usage['budget_tokens']} allowed). "
            "Use fewer optional retrieved rules or a smaller supported topology. "
            "No required rule, source device or link was truncated; no API request was sent."
        )
