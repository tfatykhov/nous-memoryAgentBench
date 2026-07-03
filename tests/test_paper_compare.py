"""Paper-faithful grader + answer-only replay (paper-comparison path)."""

from __future__ import annotations

import pytest

from mab.adapter import AnswerResult
from mab.datasets import Competency, MabInstance, Question
from mab.grading import ExactMatch, SubstringExactMatch
from mab.grading.paper_grader import (
    PaperExactMatch,
    PaperSubstringExactMatch,
    normalize_answer,
    substring_exact_match_score,
)
from mab.paper_prompts import PAPER_CR_PROMPT, PAPER_PROMPTS
from mab.replay import ReplayResult, answer_only


# --- paper grader is verbatim MemoryAgentBench --------------------------------
def test_normalize_strips_articles_and_punctuation():
    # their normalize_answer: lower + drop punctuation + drop a/an/the + ws
    assert normalize_answer("The Answer, is: France!") == "answer is france"
    assert normalize_answer("a United  Kingdom.") == "united kingdom"


def test_paper_substring_is_plain_and_max_over_golds():
    assert substring_exact_match_score("It is in France.", "france") is True
    assert PaperSubstringExactMatch().grade("answer: Paris", ["London", "Paris"]).correct


@pytest.mark.parametrize(
    "answer,gold",
    [
        ("France is not in my memory.", "France"),   # gold inside abstention
        ("I don't remember, maybe Italy", "Italy"),
    ],
)
def test_paper_grader_differs_from_ours_on_abstention(answer, gold):
    # Paper's plain substring ACCEPTS gold echoed inside a refusal; ours REJECTS it.
    assert PaperSubstringExactMatch().grade(answer, [gold]).correct is True
    assert SubstringExactMatch().grade(answer, [gold]).correct is False


def test_paper_exact_match_strips_punctuation_unlike_ours():
    # "France." vs "France": paper strips the period (match); ours keeps it (no match).
    assert PaperExactMatch().grade("France.", ["France"]).correct is True
    assert ExactMatch().grade("France.", ["France"]).correct is False


def test_cr_prompt_registered_with_paper_grader():
    prompt, metric = PAPER_PROMPTS["conflict_resolution"]
    assert prompt is PAPER_CR_PROMPT
    assert "serial number" in prompt and "{question}" in prompt
    assert metric == "paper_substring_exact_match"


# --- answer-only replay -------------------------------------------------------
class _FakeMethod:
    """Records answer prompts; has NO ingest/consolidate (answer-only must not call them)."""

    def __init__(self, reply="It is paris."):
        self.prompts: list[str] = []
        self._reply = reply

    async def answer(self, prompt):
        self.prompts.append(prompt)
        return AnswerResult(text=self._reply, input_tokens=5, output_tokens=2)


def _inst():
    return MabInstance(
        competency=Competency.CONFLICT_RESOLUTION, source="factconsolidation_sh_6k",
        instance_id="factconsolidation_sh_6k#0",
        context="ctx",
        questions=[
            Question(prompt="capital of France?", gold_answers=["Paris"], metric="substring_exact_match"),
            Question(prompt="capital of Italy?", gold_answers=["Rome"], metric="substring_exact_match"),
        ],
    )


@pytest.mark.asyncio
async def test_answer_only_answers_each_question_under_paper_prompt():
    method = _FakeMethod(reply="Paris")
    results = await answer_only(method, _inst(), PAPER_CR_PROMPT, PaperSubstringExactMatch())
    assert len(results) == 2
    # both questions were framed with the PAPER prompt (serial-number rule present)
    assert all("serial number" in p for p in method.prompts)
    assert "capital of France?" in method.prompts[0]
    # graded: Q0 gold Paris -> correct; Q1 gold Rome -> wrong (answer was "Paris")
    assert results[0].correct is True and results[1].correct is False
    assert results[0].golds == ["Paris"]


@pytest.mark.asyncio
async def test_answer_only_records_error_not_silent_zero():
    class Boom:
        async def answer(self, prompt):
            raise RuntimeError("recall failed")

    results = await answer_only(Boom(), _inst(), PAPER_CR_PROMPT, PaperSubstringExactMatch())
    assert len(results) == 2
    assert all(r.error and not r.correct for r in results)
    assert "recall failed" in results[0].error
