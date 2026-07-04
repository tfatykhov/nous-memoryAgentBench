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
    "do not recall", "don't remember", "do not remember", "can't recall",
    "cannot recall", "can't find", "cannot find", "couldn't find", "could not find",
    "no information", "nothing about", "nothing on", "not in my memory",
    "not in our memory", "no memory of", "no recollection", "no idea",
    "not in our conversation", "haven't discussed", "have nothing", "unable to find",
)
_CLAUSE_LOOKBACK = 80  # cap chars scanned back from a gold occurrence
# Abstention scope resets only at a strong boundary or a CONTRASTIVE conjunction
# ("but the answer is Paris" introduces an affirmative counterpoint). LISTING
# conjunctions (and/or/nor) do NOT reset it: "I don't know whether France or
# Belgium" keeps both options under the abstention.
_SCOPE_RESET = re.compile(r"[.;:!?]|\b(?:but|though|although|however|whereas|yet)\b")
# A clause break for the gold-then-cue check ends at punctuation or ANY
# conjunction, so "Belgium and I don't recall the date" keeps the cue off the gold.
_CLAUSE_BREAK = re.compile(
    r"[.,;:!?]|\b(?:but|and|or|nor|so|yet|though|although|however|whereas)\b"
)


def _has_cue(text: str) -> bool:
    return any(cue in text for cue in _ABSTENTION_CUES)


def _gold_present_outside_abstention(norm_answer: str, norm_gold: str) -> bool:
    """True if `norm_gold` occurs in `norm_answer` outside an abstention's scope.

    For each occurrence, reject it if an abstention cue leads into it within the
    current scope (back to the last strong/contrastive boundary), if a cue is
    attached to it in the same clause (gold-then-cue), or if the gold is a bare
    echo immediately followed by a refusal clause. Any clean occurrence counts.
    """
    start = 0
    prev_end = 0
    while True:
        idx = norm_answer.find(norm_gold, start)
        if idx == -1:
            return False
        gold_end = idx + len(norm_gold)

        # BEFORE: cue leading into the gold, within the live abstention scope.
        lo = max(prev_end, idx - _CLAUSE_LOOKBACK)
        before = norm_answer[lo:idx]
        reset = None
        for reset in _SCOPE_RESET.finditer(before):
            pass  # keep the last scope reset before the gold
        before_scope = before[reset.end():] if reset else before

        # AFTER: cue attached to the gold in the same clause (gold-then-cue).
        after = norm_answer[gold_end:gold_end + _CLAUSE_LOOKBACK]
        brk = _CLAUSE_BREAK.search(after)
        after_scope = after[: brk.start()] if brk else after

        # ECHO: a bare gold ("Paris?") immediately followed by a refusal clause.
        next_clause = ""
        if brk:
            rest = after[brk.end():]
            nbrk = _CLAUSE_BREAK.search(rest)
            next_clause = rest[: nbrk.start()] if nbrk else rest
        bare = not before_scope.strip() and not after_scope.strip(" ?!.,")

        if not (_has_cue(before_scope) or _has_cue(after_scope)
                or (bare and _has_cue(next_clause))):
            return True  # a clean (non-abstaining) occurrence
        # Floor the next scan so this occurrence's scope can't bleed into a later one.
        prev_end = gold_end
        start = idx + 1


class Grader(Protocol):
    metric: str

    def grade(self, answer: str, gold_answers: list[str]) -> GradeResult: ...


@dataclass(frozen=True)
class SubstringExactMatch:
    """Correct if any gold is a substring of the answer (after normalization).

    DEVIATION from official MAB SubEM: this grader rejects gold occurrences
    inside an abstention scope ("I don't know if it was Paris" does not count
    as answering Paris). That is stricter than the paper's containment check
    and is intended for INTERNAL memory-lift attribution. Headline paper-
    comparable numbers must use mab.grading.paper_grader instead.

    The metric key stays "substring_exact_match" because dataset rows carry it
    as the grader-registry lookup key; the semantic deviation is documented
    here and in the baseline report rather than encoded in the key.
    """

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
