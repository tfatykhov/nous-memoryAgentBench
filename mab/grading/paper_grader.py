"""Paper-faithful graders, vendored from MemoryAgentBench.

Source: https://github.com/HUST-AI-HYZ/MemoryAgentBench  (utils/eval_other_utils.py)
License: MIT (c) 2026 Yuanzhe Hu.

Reproduces the paper's exact scoring so nous answers can be graded on the same
yardstick as the published benchmark. The paper grades PER SUB-DATASET (see its
``post_process``), not per competency — ``grader_for_source`` mirrors that
dispatch. Scoring functions below are ported verbatim; ROUGE is omitted (not a
headline metric for the sources we grade). LLM-judge sources (longmemeval,
infbench_sum) and recsys Recall@k are handled elsewhere (they are not simple
string matches) — ``grader_for_source`` raises for them.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass
from typing import Callable

from mab.grading.graders import GradeResult


# --- verbatim scoring primitives (utils/eval_other_utils.py) ------------------
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


def drqa_metric_max_over_ground_truths(
    metric_function: Callable[[str, str], bool], prediction: str, ground_truths
) -> bool:
    if isinstance(ground_truths, str):
        gts = [ground_truths]
    elif ground_truths and isinstance(ground_truths[0], list):
        gts = [gt for sub in ground_truths for gt in sub]
    else:
        gts = ground_truths
    return max((metric_function(prediction, gt) for gt in gts), default=False)


def parse_output(output_text: str, answer_prefix: str = "Answer:") -> str | None:
    """Extract the answer portion after ``answer_prefix`` (icl / label tasks)."""
    patterns = [
        re.compile(f"(?:{answer_prefix})(.*)(?:\n|$)", flags=re.IGNORECASE),
        re.compile(r"(?:^)(.*)(?:\n|$)"),
    ]
    for pattern in patterns:
        match = pattern.search(output_text)
        if match:
            extracted = match[1].strip()
            return re.sub(f"^{re.escape(answer_prefix)}", "", extracted, flags=re.IGNORECASE).strip()
    return None


# --- Grader-protocol wrappers (per paper sub-dataset) -------------------------
@dataclass(frozen=True)
class PaperSubstringExactMatch:
    """AR (ruler_qa), CR (factconsolidation), LRU (detective_qa): normalized substring."""

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


@dataclass(frozen=True)
class EventqaRecall:
    """AR eventqa: correct iff EVERY gold element is present (binary recall).

    Paper-exact: uses raw ``element.lower() in prediction.lower()`` — NOT
    normalize_answer (no punctuation/article stripping). `_process_eventqa`:
    ``recall = sum(el.lower() in pred.lower())/len(answer); binary = int(recall==1)``.
    (Using normalize_answer here would false-positive on punctuation, e.g.
    "J.K. Rowling" vs "JK Rowling", and on article-only elements.)
    """

    metric: str = "paper_eventqa_recall"

    def grade(self, answer: str, gold_answers: list[str]) -> GradeResult:
        if not gold_answers:
            return GradeResult(False, None, "no golds")
        pred = answer.lower()
        hit = all(g.lower() in pred for g in gold_answers)
        return GradeResult(hit, None, "all gold elements present" if hit else "missing gold element")


@dataclass(frozen=True)
class IclExactMatch:
    """TTL in-context-learning: parse the label after 'label:'/'Answer:' then exact-match.

    NOTE — deliberate interpretation, not byte-faithful to the paper. The paper's
    _process_icl calls parse_output(pred) with the default 'Answer:' prefix (which
    on a 'label: 5' output returns the whole line), then reports calculate_metrics
    (substring + exact + f1) with NO single primary metric — its exact_match always
    fails on 'label: X' and its substring false-positives on digit collisions
    (gold '5' matches 'label: 15'). We parse the 'label:' the prompt forces and
    exact-match the bare label: agrees with the paper on well-formed output and is
    strictly more correct on collisions (so our TTL number is conservative).
    """

    metric: str = "paper_icl_exact_match"

    def grade(self, answer: str, gold_answers: list[str]) -> GradeResult:
        parsed = parse_output(answer, "label:") or parse_output(answer) or answer
        for gold in gold_answers:
            if drqa_exact_match_score(parsed, gold):
                return GradeResult(True, gold, "icl label exact match")
        return GradeResult(False, None, "icl label mismatch")


class NeedsLLMJudge(Exception):
    """Raised for sources the paper scores with an LLM judge (longmemeval, infbench_sum)."""


class NeedsRecsysData(Exception):
    """Raised for recsys (Recall@k against the paper's entity2id.json)."""


def grader_for_source(source: str):
    """Mirror the paper's post_process dispatch: pick the grader by sub-dataset."""
    s = source.lower()
    if "icl" in s:
        return IclExactMatch()
    if "eventqa" in s:
        return EventqaRecall()
    if "longmemeval" in s or "infbench" in s:
        raise NeedsLLMJudge(f"{source} is scored by an LLM judge (see paper_llm_judge)")
    if "recsys" in s:
        raise NeedsRecsysData(f"{source} uses Recall@k with entity2id.json")
    # ruler_qa, factconsolidation, detective_qa, and default -> substring
    return PaperSubstringExactMatch()


PAPER_GRADERS = {
    g.metric: g for g in (
        PaperSubstringExactMatch(), PaperExactMatch(), EventqaRecall(), IclExactMatch(),
    )
}
