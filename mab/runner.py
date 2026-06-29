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

from mab.adapter import IngestStats, NousMemoryMethod
from mab.config import Config, HarnessSettings
from mab.datasets import MabInstance
from mab.grading import get_grader
from mab.instance import NousInstance

logger = logging.getLogger("mab.runner")


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


@dataclass
class ConfigResult:
    config: Config
    question_results: list[QuestionResult] = field(default_factory=list)
    ingest_stats: list[IngestStats] = field(default_factory=list)
    duration_s: float = 0.0
    error: str | None = None


@dataclass
class RunReport:
    competency: str
    config_results: list[ConfigResult]
    settings: HarnessSettings


async def _run_instance(
    method: NousMemoryMethod, config_name: str, inst: MabInstance, cfg_result: ConfigResult
) -> None:
    stats = await method.ingest(inst)
    cfg_result.ingest_stats.append(stats)
    await method.consolidate()
    for q in inst.questions:
        grader = get_grader(q.metric)
        ans = None
        try:
            ans = await method.answer(q.prompt)
            correct = grader.grade(ans.text, q.gold_answers).correct
            err = None
        except Exception as exc:  # answer failed: record, do not zero-score silently
            correct, err = False, f"{type(exc).__name__}: {exc}"
            logger.warning("answer failed for %s/%s: %s", inst.instance_id, q.qa_pair_id, err)
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
            )
        )


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
    for inst in instances:
        agent_id = f"{settings.agent_id_prefix}-{config.name}-{uuid.uuid4().hex[:8]}"
        try:
            async with NousInstance(settings, config, agent_id) as running:
                async with httpx.AsyncClient() as client:
                    method = NousMemoryMethod(client, running.base_url, settings)
                    await _run_instance(method, config.name, inst, result)
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
