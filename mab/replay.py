"""Answer-only replay.

Re-answer an EXISTING agent's already-built memory under a different prompt and
grader, WITHOUT re-ingesting the context. Used to compare our answer prompt +
grader against the paper's on the *same* built memory (see mab.paper_prompts /
mab.grading.paper_grader). The memory must already be persisted in the eval DB
for the given agent_id (e.g. from a prior `run` — the server is torn down but the
facts/chunks/episodes persist).
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from mab.adapter import NousMemoryMethod
from mab.config import Config, HarnessSettings
from mab.datasets import MabInstance
from mab.grading import Grader
from mab.instance import NousInstance
from mab.runner import frame_prompt


@dataclass
class ReplayResult:
    source: str
    instance_id: str
    qa_pair_id: str | None
    prompt: str
    answer: str
    golds: list[str]
    correct: bool
    error: str | None = None
    # Fractional score for non-binary sources (infbench_sum summarization f1);
    # None for binary-graded sources. correct is set from score>=0.5 as a proxy.
    score: float | None = None
    # Ingest self-audit (None on answer-only replay and on pre-2026-07-04 records):
    # headline reports must SPLIT OUT any instance with chunks_truncated > 0 — a
    # wrong answer on a truncated instance may mean the answer-bearing text was
    # never ingested, which is an infra failure, not a memory failure.
    chunks_sent: int | None = None
    chunks_truncated: int | None = None


async def answer_only(
    method: NousMemoryMethod, inst: MabInstance, instruction: str, grader: Grader
) -> list[ReplayResult]:
    """Answer each question under ``instruction`` and grade with ``grader``.

    No ingest/consolidate: the bound agent's memory must already exist.
    """
    results: list[ReplayResult] = []
    for q in inst.questions:
        try:
            ans = await method.answer(frame_prompt(instruction, q.prompt))
            correct = grader.grade(ans.text, q.gold_answers).correct
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


async def replay_agent(
    settings: HarnessSettings, config: Config, agent_id: str,
    inst: MabInstance, instruction: str, grader: Grader,
) -> list[ReplayResult]:
    """Launch a server bound to an EXISTING ``agent_id`` (no ingest) and answer."""
    async with NousInstance(settings, config, agent_id) as running:
        async with httpx.AsyncClient() as client:
            method = NousMemoryMethod(client, running.base_url, settings)
            return await answer_only(method, inst, instruction, grader)
