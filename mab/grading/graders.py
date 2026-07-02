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
    """Case-fold, unify typographic apostrophes, and collapse whitespace.

    Models emit curly apostrophes (U+2019 etc.), so map them to ASCII ' before
    matching — otherwise ASCII cue strings like "don't" miss "don't".
    """
    text = text.translate({0x2019: "'", 0x2018: "'", 0x02BC: "'"})
    return re.sub(r"\s+", " ", text.strip().casefold())


# Abstention cues (normalized form). If a gold token appears only inside a clause
# led by one of these, the agent is declining, not answering — e.g. "I have
# nothing about Italy" must NOT count as gold "Italy". A clean occurrence in
# another clause (e.g. "the country is Belgium, though I don't recall the date")
# still counts.
_ABSTENTION_CUES = (
    "don't know", "do not know", "don't have", "do not have", "don't recall",
    "do not recall", "can't find", "cannot find", "couldn't find", "could not find",
    "no information", "nothing about", "nothing on", "not in my memory",
    "not in our memory", "no memory of", "not in our conversation",
    "haven't discussed", "have nothing", "unable to find",
)
_CLAUSE_LOOKBACK = 80  # cap chars scanned back when no clause boundary is found
# A clause ends at punctuation OR a coordinating conjunction — "... but the
# answer is Paris" starts a new (affirmative) clause even without a comma.
_CLAUSE_BREAK = re.compile(r"[.,;:!?]|\b(?:but|though|although|however|yet|whereas)\b")


def _clause_around(norm_answer: str, idx: int, gold_len: int, lo_floor: int) -> tuple[str, str]:
    """Return (enclosing clause, next clause) for the gold occurrence at `idx`.

    A clause is bounded by the nearest clause breaks (punctuation or a
    coordinating conjunction) on each side, capped at ``_CLAUSE_LOOKBACK``. The
    "next clause" is the following clause after the enclosing one — used to catch
    an echo-then-refuse pattern ("Paris? I do not know.").
    """
    gold_end = idx + gold_len
    lo = max(lo_floor, idx - _CLAUSE_LOOKBACK)
    before = norm_answer[lo:idx]
    last = None
    for last in _CLAUSE_BREAK.finditer(before):
        pass  # keep the final break before the gold
    cstart = lo + last.end() if last else lo

    after = norm_answer[gold_end:gold_end + _CLAUSE_LOOKBACK]
    brk = _CLAUSE_BREAK.search(after)
    clause = norm_answer[cstart:gold_end + (brk.start() if brk else len(after))]

    next_clause = ""
    if brk:
        rest = after[brk.end():]
        nbrk = _CLAUSE_BREAK.search(rest)
        next_clause = rest[: nbrk.start()] if nbrk else rest
    return clause, next_clause


def _gold_present_outside_abstention(norm_answer: str, norm_gold: str) -> bool:
    """True if `norm_gold` occurs in `norm_answer` outside an abstention clause.

    For each occurrence, examine the full enclosing clause (both sides of the
    gold). Reject the occurrence if that clause contains an abstention cue, or if
    the clause is a bare echo of the gold ("Paris?") immediately followed by a
    refusal clause. Any clean occurrence makes the whole answer count.
    """
    start = 0
    prev_end = 0
    while True:
        idx = norm_answer.find(norm_gold, start)
        if idx == -1:
            return False
        clause, next_clause = _clause_around(norm_answer, idx, len(norm_gold), prev_end)
        clause_has_cue = any(cue in clause for cue in _ABSTENTION_CUES)
        bare_echo = clause.strip(" ?!.,") == norm_gold and any(
            cue in next_clause for cue in _ABSTENTION_CUES
        )
        if not clause_has_cue and not bare_echo:
            return True  # a clean (non-abstaining) occurrence
        # Floor the next scan at this occurrence's end so its clause can't bleed
        # into a later occurrence.
        prev_end = idx + len(norm_gold)
        start = idx + 1


class Grader(Protocol):
    metric: str

    def grade(self, answer: str, gold_answers: list[str]) -> GradeResult: ...


@dataclass(frozen=True)
class SubstringExactMatch:
    """Correct if any gold is a substring of the answer (after normalization)."""

    metric: str = "substring_exact_match"

    def grade(self, answer: str, gold_answers: list[str]) -> GradeResult:
        norm_answer = _normalize(answer)
        abstained = False
        for gold in gold_answers:
            norm_gold = _normalize(gold)
            if not norm_gold or norm_gold not in norm_answer:
                continue
            if _gold_present_outside_abstention(norm_answer, norm_gold):
                return GradeResult(True, gold, "substring hit")
            abstained = True  # gold present, but only inside an abstention clause
        detail = (
            "gold present only inside an abstention clause"
            if abstained else "no gold substring in answer"
        )
        return GradeResult(False, None, detail)


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
