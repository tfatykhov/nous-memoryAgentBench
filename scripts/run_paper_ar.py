"""Paper-faithful Accurate-Retrieval run.

Ingests AR instances, answers with the paper's per-source prompt, grades with the
paper's per-source grader (eventqa recall / ruler substring / longmemeval gpt-4o
judge). Prints raw accuracy per source.

Usage:  ./.venv/Scripts/python.exe scripts/run_paper_ar.py <sources_csv> <max_instances> <max_questions>
        (defaults: eventqa_65536  1  8)
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
    sources = (sys.argv[1].split(",") if len(sys.argv) > 1 else ["eventqa_65536"])
    max_inst = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    max_q = int(sys.argv[3]) if len(sys.argv) > 3 else 8

    settings = HarnessSettings()
    config = config_from_env_file("configs/prod_memory.env")
    instances = load_competency(
        Competency.ACCURATE_RETRIEVAL, sources=sources, max_questions_per_instance=max_q
    )[:max_inst]
    nq = sum(len(i.questions) for i in instances)
    print(f"sources={sources} instances={len(instances)} questions={nq}", flush=True)

    async with httpx.AsyncClient() as judge_client:
        completer = openai_completer(_openai_key(), judge_client)
        results = await run_paper_faithful(settings, config, instances, completer)

    by: dict[str, list[int]] = {}
    for r in results:
        b = by.setdefault(r.source, [0, 0, 0])
        b[0] += 1 if r.correct else 0
        b[1] += 1
        b[2] += 1 if r.error else 0
    for src, (c, t, e) in by.items():
        print(f"  {src:<24} PAPER {c}/{t} = {c / t:.3f}   errored={e}", flush=True)
    tc = sum(v[0] for v in by.values())
    tt = sum(v[1] for v in by.values())
    print(f"\nAR paper-faithful: {tc}/{tt} = {tc / tt:.3f}" if tt else "no results", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
