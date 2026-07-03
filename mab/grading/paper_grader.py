"""Paper-faithful graders, vendored verbatim from MemoryAgentBench.

Source: https://github.com/HUST-AI-HYZ/MemoryAgentBench  (utils/eval_other_utils.py)
License: MIT (c) 2026 Yuanzhe Hu.

These reproduce the paper's exact scoring so nous answers can be graded on the
*same* yardstick as the published benchmark. Difference from our own graders
(mab.grading.graders): the paper's ``normalize_answer`` strips articles (a/an/the)
and ALL punctuation, and there is NO abstention-scope rejection — a plain
normalized substring / equality check. Use these only for paper-comparison runs.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass

from mab.grading.graders import GradeResult


# --- verbatim from MemoryAgentBench utils/eval_other_utils.py -----------------
def normalize_answer(answer_text: str) -> str:
    text = answer_text.lower()
    text = "".join(char for char in text if char not in string.punctuation)
    text = re.sub(r"\b(a|an|the)\b", " ", text)
    text = " ".join(text.split())
    return text


def substring_exact_match_score(prediction: str, ground_truth: str) -> bool:
    return normalize_answer(ground_truth) in normalize_answer(prediction)


def drqa_exact_match_score(prediction: str, ground_truth: str) -> bool:
    return normalize_answer(prediction) == normalize_answer(ground_truth)


# --- Grader-protocol wrappers (max over the gold list) ------------------------
@dataclass(frozen=True)
class PaperSubstringExactMatch:
    metric: str = "paper_substring_exact_match"

    def grade(self, answer: str, gold_answers: list[str]) -> GradeResult:
        for gold in gold_answers:
            if substring_exact_match_score(answer, gold):
                return GradeResult(True, gold, "paper substring match")
        return GradeResult(False, None, "no paper substring match")


@dataclass(frozen=True)
class PaperExactMatch:
    metric: str = "paper_exact_match"

    def grade(self, answer: str, gold_answers: list[str]) -> GradeResult:
        for gold in gold_answers:
            if drqa_exact_match_score(answer, gold):
                return GradeResult(True, gold, "paper exact match")
        return GradeResult(False, None, "no paper exact match")


PAPER_GRADERS = {g.metric: g for g in (PaperSubstringExactMatch(), PaperExactMatch())}
