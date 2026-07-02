"""No-memory control arm + memory-lift reporting + answer-from-memory framing."""

from __future__ import annotations

import pytest

from mab.adapter import AnswerResult, IngestStats
from mab.config import HarnessSettings, PRESETS
from mab.datasets import Competency, MabInstance, Question
from mab.report import render_json, render_markdown, summarize
from mab.runner import (
    ConfigResult, QuestionResult, RunReport, _run_control_arm, _run_instance, frame_prompt,
)


# --- frame_prompt -----------------------------------------------------------
def test_frame_prompt_substitutes_placeholder():
    out = frame_prompt("Use memory. {question} Answer:", "Where is Paris?")
    assert out == "Use memory. Where is Paris? Answer:"


def test_frame_prompt_appends_when_no_placeholder():
    assert frame_prompt("Use your memory.", "Where?") == "Use your memory.\n\nWhere?"


def test_frame_prompt_empty_instruction_is_bare_question():
    assert frame_prompt("", "Where?") == "Where?"


def test_frame_prompt_leaves_other_braces_untouched():
    # A custom instruction with an unrelated {placeholder} must not raise.
    out = frame_prompt("As {persona}: {question}", "Where?")
    assert out == "As {persona}: Where?"


# --- config defaults --------------------------------------------------------
def test_control_arm_and_instruction_defaults_on():
    s = HarnessSettings()
    assert s.control_arm_enabled is True
    assert "{question}" in s.answer_instruction


# --- runner: control arm ----------------------------------------------------
def _inst():
    return MabInstance(
        competency=Competency.CONFLICT_RESOLUTION, source="s", instance_id="s#0",
        context="ctx", questions=[Question(prompt="capital?", gold_answers=["paris"],
                                           metric="substring_exact_match")],
    )


class _MemoryMethod:
    """Answers the gold; used as the memory arm in _run_instance tests."""

    def __init__(self):
        self.prompts: list[str] = []

    async def answer(self, prompt):
        self.prompts.append(prompt)
        return AnswerResult(text="It is paris.", input_tokens=50, output_tokens=5)

    async def ingest(self, inst):
        return IngestStats(chunks_sent=1, chunks_truncated=0)

    async def consolidate(self):
        return True


class _ControlMethod:
    """Empty-agent control: answers wrong, records the (framed) prompts it saw."""

    def __init__(self):
        self.prompts: list[str] = []

    async def answer(self, prompt):
        self.prompts.append(prompt)
        return AnswerResult(text="I don't know.", input_tokens=30, output_tokens=3)


@pytest.mark.asyncio
async def test_control_arm_answers_each_question_framed():
    ctl = _ControlMethod()
    results = await _run_control_arm(ctl, _inst(), HarnessSettings())
    assert len(results) == 1 and isinstance(results[0], AnswerResult)
    # the control saw the SAME framing the memory arm uses (not the bare prompt).
    assert "capital?" in ctl.prompts[0] and ctl.prompts[0] != "capital?"


@pytest.mark.asyncio
async def test_run_instance_pairs_provided_control():
    method = _MemoryMethod()
    cr = ConfigResult(config=PRESETS["baseline"])
    s = HarnessSettings(diagnostics_enabled=False)
    control = [AnswerResult(text="I don't know.", input_tokens=30, output_tokens=3)]
    await _run_instance(method, "baseline", _inst(), cr, s, "agent", False, control)

    # memory arm used the framed prompt; control was paired and graded.
    assert "capital?" in method.prompts[0] and method.prompts[0] != "capital?"
    r = cr.question_results[0]
    assert r.correct is True and r.control_correct is False
    assert r.control_answer == "I don't know."
    assert r.control_input_tokens == 30 and r.control_output_tokens == 3


@pytest.mark.asyncio
async def test_run_instance_control_none_when_disabled():
    method = _MemoryMethod()
    cr = ConfigResult(config=PRESETS["baseline"])
    s = HarnessSettings(diagnostics_enabled=False)
    await _run_instance(method, "baseline", _inst(), cr, s, "agent", False, [None])
    assert cr.question_results[0].control_correct is None


# --- report: memory lift ----------------------------------------------------
def _qr(correct, control_correct, error=None, control_error=None):
    return QuestionResult(
        config_name="baseline", source="s", instance_id="s#0", qa_pair_id=None,
        prompt="q", answer="a", golds=["a"], metric="substring_exact_match",
        correct=correct, error=error, control_correct=control_correct,
        control_error=control_error,
        control_answer="c", control_input_tokens=10, control_output_tokens=2,
    )


def _lift_report():
    qrs = [
        _qr(True, False),   # memory_win
        _qr(True, True),    # both_right
        _qr(False, False),  # both_wrong
        _qr(False, True),   # memory_regression
        _qr(False, None, error="boom"),  # errored -> unpaired, excluded
    ]
    cr = ConfigResult(config=PRESETS["baseline"], question_results=qrs)
    return RunReport(competency="conflict_resolution", config_results=[cr],
                     settings=HarnessSettings())


def test_summarize_computes_lift_buckets_and_pp():
    c = summarize(_lift_report())["configs"]["baseline"]
    assert c["n_paired"] == 4  # errored question excluded
    assert c["lift_buckets"] == {
        "memory_win": 1, "both_right": 1, "both_wrong": 1, "memory_regression": 1,
    }
    # memory acc = 2/4 = .5; control acc = 2/4 = .5; lift = 0 pp
    assert c["control_accuracy"] == 0.5
    assert c["memory_lift_pp"] == 0.0


def test_paired_memory_accuracy_excludes_control_errored_question():
    # Memory answered (graded) but the CONTROL answer errored -> unpaired.
    # The lift table's memory accuracy must be the PAIRED accuracy, which can
    # differ from the overall accuracy that includes this question.
    qrs = [
        _qr(True, True),    # paired, both right
        _qr(True, None, control_error="timeout"),  # memory right, control errored -> unpaired
    ]
    cr = ConfigResult(config=PRESETS["baseline"], question_results=qrs)
    rep = RunReport(competency="cr", config_results=[cr], settings=HarnessSettings())
    c = summarize(rep)["configs"]["baseline"]
    assert c["accuracy"] == 1.0              # overall: 2/2 graded correct
    assert c["n_paired"] == 1                # only the first question is paired
    assert c["memory_accuracy_paired"] == 1.0
    assert c["control_accuracy"] == 1.0
    assert c["memory_lift_pp"] == 0.0
    # The lift table must render the PAIRED memory accuracy, not 0.700-style drift.
    md = render_markdown(rep)
    assert "| baseline | 1.000 | 1.000 | +0.0 pp | 1 |" in md


def test_positive_lift_when_memory_beats_control():
    qrs = [_qr(True, False), _qr(True, False), _qr(True, False), _qr(False, False)]
    cr = ConfigResult(config=PRESETS["baseline"], question_results=qrs)
    rep = RunReport(competency="cr", config_results=[cr], settings=HarnessSettings())
    c = summarize(rep)["configs"]["baseline"]
    assert c["lift_buckets"]["memory_win"] == 3
    assert c["memory_accuracy_paired"] == 0.75 and c["control_accuracy"] == 0.0
    assert c["memory_lift_pp"] == 75.0


def test_summarize_no_control_data_leaves_lift_null():
    qrs = [QuestionResult(config_name="baseline", source="s", instance_id="s#0",
                          qa_pair_id=None, prompt="q", answer="a", golds=["a"],
                          metric="substring_exact_match", correct=True)]
    cr = ConfigResult(config=PRESETS["baseline"], question_results=qrs)
    rep = RunReport(competency="x", config_results=[cr], settings=HarnessSettings())
    c = summarize(rep)["configs"]["baseline"]
    assert c["n_paired"] == 0
    assert c["control_accuracy"] is None and c["memory_lift_pp"] is None


def test_markdown_renders_lift_section():
    md = render_markdown(_lift_report())
    assert "Memory lift (vs no-memory control)" in md
    assert "memory_win" in md
    assert "+0.0 pp" in md


def test_report_surfaces_consolidate_timeout_and_truncation():
    cr = ConfigResult(
        config=PRESETS["baseline"],
        question_results=[_qr(True, True)],
        ingest_stats=[IngestStats(chunks_sent=5, chunks_truncated=3)],
        consolidate_settled=[False],
    )
    rep = RunReport(competency="cr", config_results=[cr], settings=HarnessSettings())
    c = summarize(rep)["configs"]["baseline"]
    assert c["consolidate_timeouts"] == 1
    assert c["truncated_instances"] == 1 and c["chunks_truncated_total"] == 3
    md = render_markdown(rep)
    assert "Run health caveats" in md
    assert "consolidation never settled" in md and "ingest truncated" in md


def test_report_warns_on_low_paired_coverage():
    qrs = [_qr(True, True), _qr(True, True), _qr(True, True)]            # 3 paired
    qrs += [_qr(True, None, control_error="timeout") for _ in range(7)]  # 7 unpaired
    cr = ConfigResult(config=PRESETS["baseline"], question_results=qrs)
    rep = RunReport(competency="cr", config_results=[cr], settings=HarnessSettings())
    c = summarize(rep)["configs"]["baseline"]
    assert c["n_graded"] == 10 and c["n_paired"] == 3
    assert "memory-lift covers only 3/10" in render_markdown(rep)


def test_report_warns_when_control_attempted_but_all_unpaired():
    # Control was enabled but every control call errored -> 0 paired, memory graded.
    # The report must flag lift as UNMEASURABLE, not silently show raw accuracy.
    qrs = [_qr(True, None, control_error="timeout") for _ in range(4)]
    cr = ConfigResult(config=PRESETS["baseline"], question_results=qrs)
    rep = RunReport(competency="cr", config_results=[cr], settings=HarnessSettings())
    c = summarize(rep)["configs"]["baseline"]
    assert c["control_attempted"] is True and c["n_paired"] == 0
    assert "UNMEASURABLE" in render_markdown(rep)


def test_report_no_unmeasurable_warning_when_control_disabled():
    # No control attempted (control disabled) -> 0 paired is expected, no caveat.
    qrs = [QuestionResult(config_name="baseline", source="s", instance_id="s#0",
                          qa_pair_id=None, prompt="q", answer="a", golds=["a"],
                          metric="substring_exact_match", correct=True)]
    cr = ConfigResult(config=PRESETS["baseline"], question_results=qrs)
    rep = RunReport(competency="cr", config_results=[cr], settings=HarnessSettings())
    c = summarize(rep)["configs"]["baseline"]
    assert c["control_attempted"] is False
    assert "UNMEASURABLE" not in render_markdown(rep)


def test_json_includes_control_fields_and_counts_tokens():
    j = render_json(_lift_report())
    pq = j["per_question"][0]
    assert "control_correct" in pq and "control_answer" in pq
    # control tokens fold into foreground cost: 5 QRs * 10 control_in = 50 exactly
    # (no ingest/answer tokens in the fixture), so an exact check catches drift.
    assert j["configs"]["baseline"]["foreground_input_tokens"] == 50
