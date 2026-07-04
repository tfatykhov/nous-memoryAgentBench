"""Replay the persisted CR memory under the PAPER's answer prompt + grader.

Re-answers each CR instance's already-built memory (from the last `run`) with the
MemoryAgentBench factconsolidation prompt, graded by the paper's grader — no
re-ingest. Prints per-source accuracy and the side-by-side vs our own run.

Usage (from repo root, with the eval DB up):
    MAB_NOUS_REPO=../nous MAB_NOUS_PYTHON=... MAB_DB_NAME=nous_mab \
    MAB_CONTROL_ARM_ENABLED=false MAB_DIAGNOSTICS_ENABLED=false MAB_TURN_DELAY_S=5 \
    ./.venv/Scripts/python.exe scripts/replay_paper_prompt.py
"""

from __future__ import annotations

import asyncio
import glob
import json
import sys

import psycopg

from mab.config import HarnessSettings, config_from_env_file
from mab.datasets import Competency, load_competency
from mab.grading.paper_grader import PaperSubstringExactMatch
from mab.paper_prompts import PAPER_CR_PROMPT
from mab.replay import replay_agent


def _bucket(chunks: int) -> str:
    return "262k" if chunks > 1500 else "64k" if chunks > 400 else "32k" if chunks > 150 else "6k"


def _agents_by_size(settings: HarnessSettings) -> dict[str, list[str]]:
    """The 8 most-recent CR memory agents, bucketed by context size (chunk count)."""
    conn = psycopg.connect(
        host=settings.db_host, port=settings.db_port, user=settings.db_user,
        password=settings.db_password, dbname=settings.db_name,
    )
    rows = conn.execute(
        "select e.agent_id, max(e.created_at) mx, count(distinct ec.id) chunks "
        "from heart.episodes e "
        "left join heart.episode_chunks ec on ec.agent_id=e.agent_id "
        "where e.agent_id like 'mab-eval-prod_memory-%' and e.agent_id not like '%-ctl' "
        "group by e.agent_id order by mx desc limit 8"
    ).fetchall()
    conn.close()
    by: dict[str, list[str]] = {}
    for agent_id, _mx, chunks in rows:
        by.setdefault(_bucket(chunks), []).append(agent_id)
    return by


def _our_run_by_source() -> dict[str, tuple[int, int]]:
    """Our latest CR run's correct/total per source (our prompt + our grader)."""
    files = sorted(glob.glob("reports/cr_rebaseline_v2/*.json"))
    if not files:
        return {}
    d = json.load(open(files[-1]))
    out: dict[str, list[int]] = {}
    for q in d["per_question"]:
        c = out.setdefault(q["source"], [0, 0])
        c[0] += 1 if q["correct"] else 0
        c[1] += 1
    return {k: (v[0], v[1]) for k, v in out.items()}


async def main() -> int:
    settings = HarnessSettings()
    config = config_from_env_file("configs/prod_memory.env")
    # Match the run's sampling exactly (cr_rebaseline_v2 used --max-questions 8 ->
    # first 8 questions per instance). WITHOUT this cap each CR instance carries
    # ~100 questions, which is both non-comparable and ~12x the work.
    instances = load_competency(
        Competency.CONFLICT_RESOLUTION, max_questions_per_instance=8
    )[:8]
    nq = sum(len(i.questions) for i in instances)
    print(f"instances={len(instances)} questions={nq} (expect 64 to match cr_rebaseline_v2)")
    if nq != 64:
        print(f"  WARNING: question count {nq} != 64; comparison won't be apples-to-apples")

    by_size = _agents_by_size(settings)
    grader = PaperSubstringExactMatch()
    ours = _our_run_by_source()

    print(f"agents by size: { {k: len(v) for k, v in by_size.items()} }")
    per_source: dict[str, tuple[int, int]] = {}
    for inst in instances:
        size = inst.source.split("_")[-1]
        pool = by_size.get(size, [])
        if not pool:
            print(f"  SKIP {inst.source}: no persisted agent for size {size}")
            continue
        agent_id = pool.pop(0)  # sh/mh share context; either agent of the size works
        try:
            results = await replay_agent(settings, config, agent_id, inst, PAPER_CR_PROMPT, grader)
        except Exception as exc:  # server launch / boot failure
            print(f"  ERROR {inst.source} on {agent_id[-8:]}: {type(exc).__name__}: {exc}")
            continue
        correct = sum(1 for r in results if r.correct)
        errored = sum(1 for r in results if r.error)
        per_source[inst.source] = (correct, len(results))
        o = ours.get(inst.source)
        otxt = f"ours {o[0]}/{o[1]}" if o else "ours ?"
        print(f"  {inst.source:<28} agent={agent_id[-8:]}  PAPER {correct}/{len(results)}"
              f"  ({otxt})  errored={errored}")

    tc = sum(c for c, _ in per_source.values())
    tt = sum(t for _, t in per_source.values())
    oc = sum(ours.get(s, (0, 0))[0] for s in per_source)
    ot = sum(ours.get(s, (0, 0))[1] for s in per_source)
    print(f"\nPAPER prompt+grader: {tc}/{tt} = {tc / tt:.3f}" if tt else "no results")
    if ot:
        print(f"OUR   prompt+grader: {oc}/{ot} = {oc / ot:.3f}  (same memory, same questions)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
