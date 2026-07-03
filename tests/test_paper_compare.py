"""Paper-faithful grader + answer-only replay (paper-comparison path)."""

from __future__ import annotations

import pytest

from mab.adapter import AnswerResult
from mab.datasets import Competency, MabInstance, Question
from mab.grading import ExactMatch, SubstringExactMatch
from mab.grading.paper_grader import (
    EventqaRecall,
    IclExactMatch,
    NeedsLLMJudge,
    NeedsRecsysData,
    PaperExactMatch,
    PaperSubstringExactMatch,
    grader_for_source,
    normalize_answer,
    substring_exact_match_score,
)
from mab.paper_prompts import (
    PAPER_CR_PROMPT,
    PAPER_EVENTQA_PROMPT,
    PAPER_ICL_PROMPT,
    PAPER_PROMPTS,
    prompt_for_source,
)
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


# --- per-source graders (AR/TTL/LRU) ------------------------------------------
def test_eventqa_recall_needs_all_gold_elements():
    # AR eventqa: binary recall -> correct only if EVERY gold element is present.
    assert EventqaRecall().grade("A then B then C happened", ["A", "B", "C"]).correct is True
    assert EventqaRecall().grade("A then B happened", ["A", "B", "C"]).correct is False


def test_icl_parses_label_then_exact_matches():
    # TTL icl: parse the label after 'label:' then exact-match the numeric label.
    assert IclExactMatch().grade("label: 5", ["5"]).correct is True
    assert IclExactMatch().grade("label: 12", ["5"]).correct is False
    # a verbose answer that doesn't emit the strict 'label: X' form -> wrong (as paper intends)
    assert IclExactMatch().grade("I think the intent is 5.", ["5"]).correct is False


def test_grader_for_source_mirrors_paper_dispatch():
    assert isinstance(grader_for_source("eventqa_65536"), EventqaRecall)
    assert isinstance(grader_for_source("icl_banking77_5900shot_balance"), IclExactMatch)
    assert isinstance(grader_for_source("ruler_qa1_197K"), PaperSubstringExactMatch)
    assert isinstance(grader_for_source("factconsolidation_sh_262k"), PaperSubstringExactMatch)
    assert isinstance(grader_for_source("detective_qa"), PaperSubstringExactMatch)


def test_grader_for_source_flags_llm_and_recsys():
    import pytest as _pytest
    with _pytest.raises(NeedsLLMJudge):
        grader_for_source("longmemeval_s*")
    with _pytest.raises(NeedsLLMJudge):
        grader_for_source("infbench_sum_eng_shots2")
    with _pytest.raises(NeedsRecsysData):
        grader_for_source("recsys_redial_full")


def test_prompt_for_source_maps_each_competency():
    assert prompt_for_source("eventqa_131072") is PAPER_EVENTQA_PROMPT
    assert prompt_for_source("icl_trec_coarse_6600shot_balance") is PAPER_ICL_PROMPT
    assert prompt_for_source("factconsolidation_mh_6k") is PAPER_CR_PROMPT
    assert "label: {label}" in PAPER_ICL_PROMPT  # illustrative, not a {question} sub
    import pytest as _pytest
    with _pytest.raises(KeyError):
        prompt_for_source("unknown_source")


# --- LLM judge (longmemeval), fully offline -----------------------------------
def test_get_anscheck_prompt_dispatches_by_task():
    from mab.grading.paper_llm_judge import get_anscheck_prompt
    base = get_anscheck_prompt("multi-session", "Q?", "GOLD", "RESP")
    assert "Q?" in base and "GOLD" in base and "RESP" in base and "yes or no only" in base.lower()
    temporal = get_anscheck_prompt("temporal-reasoning", "Q?", "18", "19")
    assert "off-by-one" in temporal  # temporal task tolerates off-by-one
    abst = get_anscheck_prompt("multi-session", "Q?", "expl", "RESP", abstention=True)
    assert "unanswerable" in abst
    import pytest as _pytest
    with _pytest.raises(NotImplementedError):
        get_anscheck_prompt("bogus-task", "Q", "A", "R")


@pytest.mark.asyncio
async def test_longmem_judge_maps_yes_no():
    from mab.grading.paper_llm_judge import LongmemJudge
    seen = {}

    async def fake_yes(prompt, model):
        seen["prompt"], seen["model"] = prompt, model
        return "Yes"

    async def fake_no(prompt, model):
        return "No, the response is incorrect."

    j_yes = LongmemJudge(fake_yes, model="gpt-4o")
    r = await j_yes.judge("Where?", "Paris", "It is Paris.", "multi-session")
    assert r.correct is True and r.matched_gold == "Paris"
    assert "Paris" in seen["prompt"] and seen["model"] == "gpt-4o"  # question/gold/answer + model wired

    r2 = await LongmemJudge(fake_no).judge("Where?", "Paris", "I don't know.", "multi-session")
    assert r2.correct is False


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
