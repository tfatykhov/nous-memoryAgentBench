"""Config x instance matrix runner.

For each config: launch an isolated nous server, and for each MAB instance
ingest -> consolidate -> answer each question -> grade. Per-instance failures
are recorded as errors (never silently zero-scored).
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

import httpx

from mab.adapter import AnswerResult, IngestStats, NousMemoryMethod
from mab.config import Config, HarnessSettings
from mab.datasets import MabInstance
from mab.diagnostics import DiagnosticsUnavailable, classify, gold_in_memory
from mab.grading import get_grader
from mab.instance import NousInstance

logger = logging.getLogger("mab.runner")


def frame_prompt(instruction: str, question: str) -> str:
    """Apply the answer-framing instruction to a raw question.

    '{question}' in the template is substituted (literally, so other braces in a
    custom instruction are left untouched); if absent, the question is appended.
    An empty instruction sends the bare question. The SAME framing is used for
    the memory and control arms so lift isolates the ingested content.
    """
    if not instruction:
        return question
    if "{question}" in instruction:
        return instruction.replace("{question}", question)
    return f"{instruction}\n\n{question}"


@dataclass
class QuestionResult:
    config_name: str
    source: str
    instance_id: str
    qa_pair_id: str | None
    prompt: str
    answer: str
    golds: list[str]
    metric: str
    correct: bool
    error: str | None = None
    answer_input_tokens: int = 0
    answer_output_tokens: int = 0
    recalled_fact_ids: list[str] = field(default_factory=list)
    recalled_episode_ids: list[str] = field(default_factory=list)
    # Failure attribution (Phase 0): success | synthesis_error | retrieval_miss
    # | write_loss | None (unknown / diagnostics disabled).
    attribution: str | None = None
    # No-memory control arm: the same question answered on the EMPTY agent
    # before ingest. control_correct is None when the control arm is disabled or
    # the control answer errored (so it can't be paired for memory-lift).
    control_answer: str = ""
    control_correct: bool | None = None
    control_error: str | None = None
    control_input_tokens: int = 0
    control_output_tokens: int = 0


@dataclass
class ConfigResult:
    config: Config
    question_results: list[QuestionResult] = field(default_factory=list)
    ingest_stats: list[IngestStats] = field(default_factory=list)
    # Per-instance sleep-consolidation settle status (False = /sleep/trigger never
    # signalled completion within the timeout). Surfaced as consolidate_timeouts;
    # a False does NOT error the instance (facts are already durable from ingest,
    # and a miss biases lift downward — see review 2026-06-30).
    consolidate_settled: list[bool] = field(default_factory=list)
    duration_s: float = 0.0
    error: str | None = None


@dataclass
class RunReport:
    competency: str
    config_results: list[ConfigResult]
    settings: HarnessSettings


async def _run_instance(
    method: NousMemoryMethod,
    config_name: str,
    inst: MabInstance,
    cfg_result: ConfigResult,
    settings: HarnessSettings,
    agent_id: str,
    diagnostics_on: bool,
) -> bool:
    """Run one instance; returns whether diagnostics stayed enabled."""
    instr = settings.answer_instruction

    # No-memory control arm: answer every question on the still-EMPTY agent
    # before ingest. These ask-sessions are never closed and the server is torn
    # down after the run, so they cannot leak content into the memory arm.
    control: list[AnswerResult | Exception | None] = [None] * len(inst.questions)
    if settings.control_arm_enabled:
        for i, q in enumerate(inst.questions):
            try:
                control[i] = await method.answer(frame_prompt(instr, q.prompt))
            except Exception as exc:
                control[i] = exc
                logger.warning("control answer failed for %s/%s: %s",
                               inst.instance_id, q.qa_pair_id, exc)

    # Memory arm: ingest the context, consolidate, then answer.
    stats = await method.ingest(inst)
    cfg_result.ingest_stats.append(stats)
    if not stats.settled:
        logger.warning("ingest never settled for %s (questions may run against "
                       "incompletely-written memory)", inst.instance_id)
    # Append pessimistically before the call so a raising consolidate() leaves
    # consolidate_settled aligned with ingest_stats (the instance is errored, but
    # the health count stays consistent).
    cfg_result.consolidate_settled.append(False)
    consolidated = await method.consolidate()
    cfg_result.consolidate_settled[-1] = consolidated
    if not consolidated:
        logger.warning("consolidation never settled for %s (sleep may be incomplete)",
                       inst.instance_id)
    for i, q in enumerate(inst.questions):
        grader = get_grader(q.metric)
        ans = None
        try:
            ans = await method.answer(frame_prompt(instr, q.prompt))
            correct = grader.grade(ans.text, q.gold_answers).correct
            err = None
        except Exception as exc:  # answer failed: record, do not zero-score silently
            correct, err = False, f"{type(exc).__name__}: {exc}"
            logger.warning("answer failed for %s/%s: %s", inst.instance_id, q.qa_pair_id, err)

        attribution = None
        if diagnostics_on and err is None:
            try:
                ingested = gold_in_memory(settings, agent_id, q.gold_answers)
                attribution = classify(correct, ingested)
            except DiagnosticsUnavailable as exc:
                logger.warning("diagnostics disabled for this run: %s", exc)
                diagnostics_on = False  # stop retrying for the rest of the run

        # Pair the control answer (graded under the same metric) for memory-lift.
        c = control[i]
        if isinstance(c, AnswerResult):
            c_answer, c_in, c_out, c_err = c.text, c.input_tokens, c.output_tokens, None
            c_correct = grader.grade(c.text, q.gold_answers).correct
        elif isinstance(c, Exception):
            c_answer, c_in, c_out, c_correct, c_err = "", 0, 0, None, f"{type(c).__name__}: {c}"
        else:  # control disabled
            c_answer, c_in, c_out, c_correct, c_err = "", 0, 0, None, None

        cfg_result.question_results.append(
            QuestionResult(
                config_name=config_name,
                source=inst.source,
                instance_id=inst.instance_id,
                qa_pair_id=q.qa_pair_id,
                prompt=q.prompt,
                answer=ans.text if ans else "",
                golds=q.gold_answers,
                metric=q.metric,
                correct=correct,
                error=err,
                answer_input_tokens=ans.input_tokens if ans else 0,
                answer_output_tokens=ans.output_tokens if ans else 0,
                recalled_fact_ids=ans.recalled_fact_ids if ans else [],
                recalled_episode_ids=ans.recalled_episode_ids if ans else [],
                attribution=attribution,
                control_answer=c_answer,
                control_correct=c_correct,
                control_error=c_err,
                control_input_tokens=c_in,
                control_output_tokens=c_out,
            )
        )
    return diagnostics_on


def _mark_instance_errored(result: ConfigResult, config_name: str, inst: MabInstance, exc: Exception) -> None:
    """Record every question of an instance as errored (never silently zero-scored)."""
    for q in inst.questions:
        result.question_results.append(
            QuestionResult(
                config_name=config_name, source=inst.source,
                instance_id=inst.instance_id, qa_pair_id=q.qa_pair_id,
                prompt=q.prompt, answer="", golds=q.gold_answers,
                metric=q.metric, correct=False,
                error=f"{type(exc).__name__}: {exc}",
            )
        )


async def run_config(settings: HarnessSettings, config: Config, instances: list[MabInstance]) -> ConfigResult:
    """Run all MAB instances for one config.

    Each MAB instance gets its OWN nous server with a unique agent_id, so memory
    is clean per instance (MAB evaluates each context independently — sharing one
    agent_id across instances would let later questions retrieve earlier contexts).
    """
    result = ConfigResult(config=config)
    started = time.monotonic()
    diagnostics_on = settings.diagnostics_enabled
    for inst in instances:
        agent_id = f"{settings.agent_id_prefix}-{config.name}-{uuid.uuid4().hex[:8]}"
        try:
            async with NousInstance(settings, config, agent_id) as running:
                async with httpx.AsyncClient() as client:
                    method = NousMemoryMethod(client, running.base_url, settings)
                    diagnostics_on = await _run_instance(
                        method, config.name, inst, result, settings, agent_id, diagnostics_on
                    )
        except Exception as exc:
            logger.exception("instance %s failed under %s", inst.instance_id, config.name)
            _mark_instance_errored(result, config.name, inst, exc)
    result.duration_s = time.monotonic() - started
    return result


async def run_matrix(
    settings: HarnessSettings, competency: str, configs: list[Config], instances: list[MabInstance]
) -> RunReport:
    results: list[ConfigResult] = []
    for config in configs:
        logger.info("running config %s over %d instances", config.name, len(instances))
        results.append(await run_config(settings, config, instances))
    return RunReport(competency=competency, config_results=results, settings=settings)
