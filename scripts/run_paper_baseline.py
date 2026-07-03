"""Paper-faithful baseline runner for ANY competency.

Ingests each instance, answers with the paper's per-source prompt, grades with the
paper's per-source grader (longmemeval -> gpt-4o judge; recsys/infbench_sum not
supported here). Persists per-instance JSONL and prints raw accuracy per source.

Usage:
    ./.venv/Scripts/python.exe scripts/run_paper_baseline.py \
        <competency> <sources_csv> <max_instances_per_source> <max_questions> [config_env_file]

    competency: accurate_retrieval | test_time_learning | long_range_understanding | conflict_resolution
    config_env_file default: configs/prod_memory.env  (use prod_memory_bigctx.env for giants)
"""

from __future__ import annotations

import asyncio
import sys

import httpx

from mab.config import HarnessSettings, config_from_env_file
from mab.datasets import Competency, load_competency
from mab.grading.paper_llm_judge import openai_completer
from mab.paper_run import run_paper_faithful


def _openai_key() -> str:
    for line in open("../nous/.env", encoding="utf-8", errors="ignore"):
        if line.startswith("OPENAI_API_KEY"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("OPENAI_API_KEY not found in ../nous/.env")


async def main() -> int:
    competency = Competency(sys.argv[1])
    sources = sys.argv[2].split(",")
    max_inst = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    max_q = int(sys.argv[4]) if len(sys.argv) > 4 else 8
    config_file = sys.argv[5] if len(sys.argv) > 5 else "configs/prod_memory.env"

    settings = HarnessSettings()
    config = config_from_env_file(config_file)
    loaded = load_competency(competency, sources=sources, max_questions_per_instance=max_q)
    by_src: dict[str, list] = {}
    for inst in loaded:
        by_src.setdefault(inst.source, []).append(inst)
    instances = [i for s in sources for i in by_src.get(s, [])[:max_inst]]
    nq = sum(len(i.questions) for i in instances)
    tag = f"{competency.value}_{'-'.join(s[:14] for s in sources)}"
    results_path = f"reports/paper_baseline/results_{tag}.jsonl"
    print(f"[{competency.value}] config={config_file} instances={len(instances)} questions={nq}", flush=True)
    print(f"persisting to: {results_path}", flush=True)

    import os
    os.makedirs("reports/paper_baseline", exist_ok=True)
    async with httpx.AsyncClient() as judge_client:
        completer = openai_completer(_openai_key(), judge_client)
        results = await run_paper_faithful(settings, config, instances, completer, results_path=results_path)

    by: dict[str, list[int]] = {}
    for r in results:
        b = by.setdefault(r.source, [0, 0, 0])
        b[0] += 1 if r.correct else 0
        b[1] += 1
        b[2] += 1 if r.error else 0
    print("", flush=True)
    for src, (c, t, e) in by.items():
        print(f"  {src:<32} PAPER {c}/{t} = {c / t:.3f}   errored={e}", flush=True)
    tc = sum(v[0] for v in by.values()); tt = sum(v[1] for v in by.values())
    if tt:
        print(f"\n{competency.value} paper-faithful: {tc}/{tt} = {tc / tt:.3f}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
