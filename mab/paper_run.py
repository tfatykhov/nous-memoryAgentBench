"""Paper-faithful run/grade path.

Ingest each instance, answer with the paper's per-source prompt
(:func:`mab.paper_prompts.prompt_for_source`), and grade with the paper's
per-source grader (:func:`mab.grading.paper_grader.grader_for_source`), routing
longmemeval to the gpt-4o yes/no LLM judge. Reports RAW accuracy per source (the
paper's metric) — no control arm / memory-lift.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import uuid

import httpx

from mab.adapter import NousMemoryMethod
from mab.config import Config, HarnessSettings
from mab.datasets import MabInstance, Question
from mab.grading.paper_grader import NeedsLLMJudge, grader_for_source
from mab.grading.paper_llm_judge import Completer, LongmemJudge
from mab.grading.paper_summarization_judge import SummarizationJudge
from mab.instance import NousInstance
from mab.paper_prompts import prompt_for_source
from mab.replay import ReplayResult
from mab.runner import frame_prompt

logger = logging.getLogger(__name__)


async def grade_paper(source: str, q: Question, answer: str, completer: Completer | None = None) -> bool:
    """Grade one answer with the paper's exact per-source technique."""
    try:
        return grader_for_source(source).grade(answer, q.gold_answers).correct
    except NeedsLLMJudge:
        if "longmemeval" not in source.lower():
            raise
        if completer is None:
            raise RuntimeError(f"{source} requires an LLM-judge completer (gpt-4o)")
        gold = q.gold_answers[0] if q.gold_answers else ""
        task = q.question_type or "multi-session"
        abstention = "_abs" in (q.qa_pair_id or "")  # paper: abstention iff '_abs' in id
        result = await LongmemJudge(completer).judge(q.prompt, gold, answer, task, abstention)
        return result.correct


async def run_instance_paper(
    method: NousMemoryMethod, inst: MabInstance, completer: Completer | None = None
) -> list[ReplayResult]:
    """Ingest + consolidate + answer(paper prompt) + grade(paper) for one instance."""
    prompt = prompt_for_source(inst.source)
    is_summ = "infbench_sum" in inst.source.lower()
    await method.ingest(inst)
    await method.consolidate()  # runs settings.sleep_cycles internally
    results: list[ReplayResult] = []
    for q in inst.questions:
        try:
            ans = await method.answer(frame_prompt(prompt, q.prompt))
            if is_summ:  # summarization: fractional f1 (not binary), via the 3-call judge
                if completer is None:
                    raise RuntimeError(f"{inst.source} requires an LLM-judge completer")
                gold = q.gold_answers[0] if q.gold_answers else ""
                sc = await SummarizationJudge(completer).score(ans.text, inst.keypoints, gold)
                results.append(ReplayResult(
                    inst.source, inst.instance_id, q.qa_pair_id, q.prompt,
                    ans.text, q.gold_answers, sc.f1 >= 0.5, score=sc.f1,
                ))
                continue
            correct = await grade_paper(inst.source, q, ans.text, completer)
            results.append(ReplayResult(
                inst.source, inst.instance_id, q.qa_pair_id, q.prompt,
                ans.text, q.gold_answers, correct,
            ))
        except Exception as exc:  # never silently zero-score
            results.append(ReplayResult(
                inst.source, inst.instance_id, q.qa_pair_id, q.prompt,
                "", q.gold_answers, False, f"{type(exc).__name__}: {exc}",
            ))
    return results


def _persist(results_path: str | None, rows: list[ReplayResult]) -> None:
    """Append one instance's results as JSONL so a killed/rate-limited run keeps
    the sources it already finished."""
    if not results_path:
        return
    with open(results_path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(dataclasses.asdict(r)) + "\n")


async def run_paper_faithful(
    settings: HarnessSettings, config: Config, instances: list[MabInstance],
    completer: Completer | None = None, results_path: str | None = None,
) -> list[ReplayResult]:
    """Full paper-faithful run: a fresh server/agent per instance.

    ``results_path`` (optional JSONL) is appended after EACH instance, so a
    rate-limited tail or a kill can't lose already-completed sources.
    """
    results: list[ReplayResult] = []
    for inst in instances:
        agent_id = f"{settings.agent_id_prefix}-paper-{uuid.uuid4().hex[:8]}"
        try:
            async with NousInstance(settings, config, agent_id) as running:
                async with httpx.AsyncClient() as client:
                    method = NousMemoryMethod(client, running.base_url, settings)
                    rows = await run_instance_paper(method, inst, completer)
        except Exception as exc:
            logger.exception("paper run instance %s failed", inst.instance_id)
            rows = [ReplayResult(
                inst.source, inst.instance_id, q.qa_pair_id, q.prompt,
                "", q.gold_answers, False, f"{type(exc).__name__}: {exc}",
            ) for q in inst.questions]
        results.extend(rows)
        _persist(results_path, rows)  # flush this instance before the next one
    return results
