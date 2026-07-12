"""AR/LRU coverage replay: answer ALL available questions against persisted memory.

Retrieval-only (no re-ingest): replays every question of the given sources
against the agents whose memory was built in the baseline runs, with
CONTENT-VERIFIED agent mapping (probe strings from each instance's context or
haystack turns must be found verbatim in the agent's stored episode_chunks;
most-recent agent wins when several runs built the same context). Answers use
the paper's per-source prompt and are graded with the paper's per-source
grader (longmemeval -> gpt-4o judge).

Usage:
    ./.venv/Scripts/python.exe scripts/replay_ar_coverage.py <competency> <source> [max_q]
e.g.
    ... replay_ar_coverage.py accurate_retrieval eventqa_65536 100
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys

import httpx
import psycopg

from mab.adapter import NousMemoryMethod
from mab.config import HarnessSettings, config_from_env_file
from mab.datasets import Competency, load_competency
from mab.grading.paper_llm_judge import openai_completer
from mab.instance import NousInstance
from mab.paper_prompts import prompt_for_source
from mab.paper_run import _persist, grade_paper
from mab.replay import ReplayResult
from mab.runner import frame_prompt


def _conn(s: HarnessSettings):
    return psycopg.connect(host=s.db_host, port=s.db_port, user=s.db_user,
                           password=s.db_password, dbname=s.db_name)


def _probes(inst) -> list[str]:
    """Raw TAIL probe strings verbatim-present in the ingested text.

    Tail-biased because eventqa sizes are NESTED truncations of the same books
    (a mid-context probe of a bigger size can sit inside a smaller size's
    memory, or vice versa); the tail is unique to this size. For haystack
    sources take late-turn slices (packing joins turns with a newline, so
    cross-turn slices of `context` may not exist verbatim).
    """
    out = []
    if inst.haystack_turns:
        turns = [str(t.get("content", "")) for t in inst.haystack_turns if len(str(t.get("content", ""))) > 120]
        for k in ((9 * len(turns)) // 10, (4 * len(turns)) // 5, (7 * len(turns)) // 10):
            out.append(turns[k][20:80])
    else:
        n = len(inst.context)
        for frac in (0.97, 0.93, 0.88):
            out.append(inst.context[int(n * frac): int(n * frac) + 60])
    return [p for p in out if len(p) >= 40]


def _map_agent(s: HarnessSettings, inst, exclude: set[str] | None = None) -> str | None:
    """Most-recent persisted agent whose chunks contain this instance's TAIL probes.

    ``exclude``: agents already assigned to LARGER nested instances — callers
    must map instances in descending context-length order so a smaller size
    can never be served by a superset (bigger-truncation) memory.
    """
    conn = _conn(s)
    cands = [r[0] for r in conn.execute(
        "select e.agent_id, max(e.created_at) mx from heart.episodes e "
        "where e.agent_id like 'mab-eval-%' and e.agent_id not like '%-ctl' "
        "group by e.agent_id order by mx desc"
    ).fetchall()]
    if exclude:
        cands = [a for a in cands if a not in exclude]
    hit = None
    for probe in _probes(inst):
        found = [a for a in cands if conn.execute(
            "select 1 from heart.episode_chunks where agent_id=%s and position(%s in content)>0 limit 1",
            (a, probe)).fetchone()]
        if found:
            hit = found[0]  # cands are recency-ordered -> most recent build
            break
    conn.close()
    return hit


async def main() -> int:
    competency = Competency(sys.argv[1])
    source = sys.argv[2]
    max_q = int(sys.argv[3]) if len(sys.argv) > 3 else 100

    settings = HarnessSettings()
    config = config_from_env_file("configs/prod_memory.env")
    instances = [i for i in load_competency(competency, sources=[source],
                                            max_questions_per_instance=max_q)]
    results_path = f"reports/paper_baseline/results_{source.replace('*', '_')}_replay_full.jsonl"
    os.makedirs("reports/paper_baseline", exist_ok=True)
    open(results_path, "w").close()

    def _key():
        if os.environ.get("OPENAI_API_KEY"):
            return os.environ["OPENAI_API_KEY"]
        for line in open("../nous/.env", encoding="utf-8", errors="ignore"):
            if line.startswith("OPENAI_API_KEY"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
        return None

    # eventqa sizes are nested truncations of the same books ACROSS sources:
    # map globally, largest context first, excluding assigned agents, so a
    # smaller size can never be served by a superset (bigger) memory.
    agent_map: dict[str, str] = {}
    if source.startswith("eventqa"):
        family = []
        for src in ("eventqa_full", "eventqa_131072", "eventqa_65536"):
            family.extend(load_competency(competency, sources=[src], max_questions_per_instance=1))
        assigned: set[str] = set()
        family_map: dict[str, str] = {}
        for fi in sorted(family, key=lambda i: len(i.context), reverse=True):
            a = _map_agent(settings, fi, exclude=assigned)
            if a:
                family_map[fi.instance_id] = a
                assigned.add(a)
        premap = family_map
    else:
        premap = None

    all_rows: list[ReplayResult] = []
    async with httpx.AsyncClient() as judge_client:
        key = _key()
        completer = openai_completer(key, judge_client) if key else None
        for inst in instances:
            agent_id = premap.get(inst.instance_id) if premap is not None else _map_agent(settings, inst)
            if not agent_id:
                print(f"[{inst.instance_id}] NO MEMORY FOUND — skipping (needs ingest)", flush=True)
                continue
            agent_map[inst.instance_id] = agent_id
            prompt = prompt_for_source(inst.source)
            print(f"[{inst.instance_id}] agent={agent_id[-12:]} questions={len(inst.questions)}", flush=True)
            async with NousInstance(settings, config, agent_id) as running:
                async with httpx.AsyncClient() as client:
                    method = NousMemoryMethod(client, running.base_url, settings)
                    rows: list[ReplayResult] = []
                    for q in inst.questions:
                        try:
                            ans = await method.answer(frame_prompt(prompt, q.prompt))
                            correct = await grade_paper(inst.source, q, ans.text, completer)
                            rows.append(ReplayResult(inst.source, inst.instance_id, q.qa_pair_id,
                                                     q.prompt, ans.text, q.gold_answers, correct))
                        except Exception as exc:
                            rows.append(ReplayResult(inst.source, inst.instance_id, q.qa_pair_id,
                                                     q.prompt, "", q.gold_answers, False,
                                                     f"{type(exc).__name__}: {exc}"))
            _persist(results_path, rows)
            all_rows.extend(rows)
            c = sum(r.correct for r in rows); e = sum(1 for r in rows if r.error)
            print(f"  -> {c}/{len(rows)} correct, errored={e}", flush=True)

    with open(results_path + ".meta.json", "w", encoding="utf-8") as mf:
        json.dump({"mode": "replay_no_reingest_coverage", "source": source,
                   "max_questions_per_instance": max_q, "agent_map": agent_map,
                   "grader": "paper grade_paper dispatch"}, mf, indent=2)
    ok = [r for r in all_rows if not r.error]
    if ok:
        c = sum(r.correct for r in ok); n = len(ok)
        p = c / n; hw = 1.96 * math.sqrt(p * (1 - p) / n)
        print(f"\n{source} coverage replay: {c}/{n} = {p:.3f} CI [{p - hw:.3f},{min(1, p + hw):.3f}]"
              f" errored={len(all_rows) - n}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
