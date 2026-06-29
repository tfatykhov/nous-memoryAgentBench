"""Per-competency answer graders.

MemoryAgentBench grades the agent's answer *text* against a list of acceptable
gold answers:

- ``substring_exact_match`` (Accurate Retrieval, Conflict Resolution): correct
  if any normalized gold appears as a substring of the normalized answer.
- ``exact_match`` (Test-Time Learning, Long-Range Understanding): strict —
  correct only if the normalized answer equals a normalized gold. MAB notes
  this is strict ("43" vs "label: 43" counts wrong), so normalization is light
  (case-fold + whitespace collapse only); no substring leniency.

Recall@5 / LLM-judge graders (recsys, longmemeval, infbench) will register here
behind the same :class:`Grader` protocol.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class GradeResult:
    correct: bool
    matched_gold: str | None = None
    detail: str = ""


def _normalize(text: str) -> str:
    """Case-fold and collapse whitespace. Shared by both metrics."""
    return re.sub(r"\s+", " ", text.strip().casefold())


class Grader(Protocol):
    metric: str

    def grade(self, answer: str, gold_answers: list[str]) -> GradeResult: ...


@dataclass(frozen=True)
class SubstringExactMatch:
    """Correct if any gold is a substring of the answer (after normalization)."""

    metric: str = "substring_exact_match"

    def grade(self, answer: str, gold_answers: list[str]) -> GradeResult:
        norm_answer = _normalize(answer)
        for gold in gold_answers:
            norm_gold = _normalize(gold)
            if norm_gold and norm_gold in norm_answer:
                return GradeResult(True, gold, "substring hit")
        return GradeResult(False, None, "no gold substring in answer")


@dataclass(frozen=True)
class ExactMatch:
    """Correct only if the normalized answer equals a normalized gold (strict)."""

    metric: str = "exact_match"

    def grade(self, answer: str, gold_answers: list[str]) -> GradeResult:
        norm_answer = _normalize(answer)
        for gold in gold_answers:
            if _normalize(gold) == norm_answer:
                return GradeResult(True, gold, "exact equality")
        return GradeResult(False, None, "answer does not exactly equal any gold")


GRADERS: dict[str, Grader] = {
    g.metric: g for g in (SubstringExactMatch(), ExactMatch())
}


def get_grader(metric: str) -> Grader:
    try:
        return GRADERS[metric]
    except KeyError:
        raise ValueError(
            f"No grader registered for metric {metric!r}. "
            f"Known: {sorted(GRADERS)}"
        ) from None
