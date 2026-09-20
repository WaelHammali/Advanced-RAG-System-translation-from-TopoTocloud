"""Confidence tiers, candidate decisions and confidence combination.

One implementation of "accept / flag / leave null" and of "ambiguous" is shared by every
association pass, so behaviour is uniform and the thresholds live only in configuration.
"""

from __future__ import annotations

import math
from collections.abc import Hashable, Iterable
from dataclasses import dataclass, field
from typing import Any

from ..config.thresholds import TierThresholds

ACCEPTED = "accepted"  # score >= high
FLAGGED = "flagged"  # medium <= score < high: stored, marked low_confidence
UNRESOLVED = "unresolved"  # score < medium: field stays null
AMBIGUOUS = "ambiguous"  # runner-up too close to call: field stays null
NO_CANDIDATES = "no_candidates"

STORED = (ACCEPTED, FLAGGED)


def tier_of(score: float | None, t: TierThresholds) -> str:
    if score is None:
        return UNRESOLVED
    if score >= t.high:
        return ACCEPTED
    if score >= t.medium:
        return FLAGGED
    return UNRESOLVED


def combine(*values: float | None) -> float | None:
    """Geometric mean of the non-null values (``None`` when there are none).

    A geometric mean means one weak link in a chain of evidence drags the whole chain down,
    which is the behaviour wanted for "text -> device -> link -> network -> address".
    """
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    if any(v <= 0 for v in vals):
        return 0.0
    return math.exp(sum(math.log(v) for v in vals) / len(vals))


@dataclass
class Decision:
    status: str
    #: winning candidate key; only set when status is accepted / flagged
    key: Hashable | None
    score: float | None
    best_key: Hashable | None = None
    best_score: float | None = None
    runner_up_key: Hashable | None = None
    runner_up_score: float | None = None
    breakdown: dict[str, float] = field(default_factory=dict)

    @property
    def stored(self) -> bool:
        return self.status in STORED

    def to_dict(self) -> dict[str, Any]:
        r = lambda v: None if v is None else round(v, 4)  # noqa: E731
        return {
            "status": self.status,
            "score": r(self.score),
            "best_candidate": self.best_key,
            "best_score": r(self.best_score),
            "runner_up": self.runner_up_key,
            "runner_up_score": r(self.runner_up_score),
            "breakdown": {k: round(v, 4) for k, v in self.breakdown.items()},
        }


def decide(
    scored: Iterable[tuple[Hashable, float, dict[str, float]]], t: TierThresholds
) -> Decision:
    """Pick the winner among ``(key, score, breakdown)`` candidates, or refuse.

    * no candidate with a positive score          -> ``no_candidates``
    * best < ``medium``                           -> ``unresolved``
    * runner-up >= ``medium`` and within ``ambiguity_margin`` of the best -> ``ambiguous``
    * otherwise ``accepted`` (>= high) or ``flagged`` (>= medium)
    """
    ranked = sorted(((k, s, b) for k, s, b in scored if s > 0), key=lambda x: (-x[1], str(x[0])))
    if not ranked:
        return Decision(NO_CANDIDATES, None, None)
    best_k, best_s, best_b = ranked[0]
    ru_k, ru_s = (ranked[1][0], ranked[1][1]) if len(ranked) > 1 else (None, None)
    base = dict(
        best_key=best_k,
        best_score=best_s,
        runner_up_key=ru_k,
        runner_up_score=ru_s,
        breakdown=best_b,
    )
    if best_s < t.medium:
        return Decision(UNRESOLVED, None, best_s, **base)
    if ru_s is not None and ru_s >= t.medium and (best_s - ru_s) < t.ambiguity_margin:
        return Decision(AMBIGUOUS, None, best_s, **base)
    return Decision(tier_of(best_s, t), best_k, best_s, **base)
