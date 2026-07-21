"""ICL decisive replay: all 40 Q/source (n=200) against the persisted ICL memory.

Answer-only — NO re-ingest: the 5 ICL agents' memory (nous_mab_icl clone,
F086 exemplar backfill applied) is answered against as-is. Agent mapping is
the content-probe-verified map from the exemplar program (2026-07-19),
re-verified at startup by tail-probe before any replay.

Usage (from repo root, eval DB up):
    MAB_DB_NAME=nous_mab_icl ./.venv/Scripts/python.exe scripts/replay_icl_n200.py \
        [max_q] [tag] [config_env_file]
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys

import psycopg

from mab.config import HarnessSettings, config_from_env_file
from mab.datasets import Competency, load_competency
from mab.grading.paper_grader import grader_for_source
from mab.paper_prompts import prompt_for_source
from mab.paper_run import _persist
from mab.replay import replay_agent

MAX_Q = int(sys.argv[1]) if len(sys.argv) > 1 else 40
TAG = sys.argv[2] if len(sys.argv) > 2 else ""
CONFIG_FILE = sys.argv[3] if len(sys.argv) > 3 else "configs/prod_memory.env"
RESULTS = f"reports/paper_baseline/results_icl_replay_n{MAX_Q * 5}{TAG}.jsonl"

AGENTS = {
    "icl_banking77_5900shot_balance": "mab-eval-paper-c90e89a7",
    "icl_clinic150_7050shot_balance": "mab-eval-paper-53378b33",
    "icl_nlu_8296shot_balance": "mab-eval-paper-4ed65584",
    "icl_trec_coarse_6600shot_balance": "mab-eval-paper-933d1c23",
    "icl_trec_fine_6400shot_balance": "mab-eval-paper-356d5486",
}


def _verify_mapping(settings: HarnessSettings, instances) -> None:
    """Each instance's context tail must be stored verbatim in its mapped agent
    (ICL contexts are DISTINCT datasets, no nesting — a single probe suffices)."""
    conn = psycopg.connect(
        host=settings.db_host, port=settings.db_port, user=settings.db_user,
        password=settings.db_password, dbname=settings.db_name,
    )
    for inst in instances:
        probe = inst.context[-150:]
        hit = conn.execute(
            "select 1 from heart.episode_chunks where agent_id=%s and position(%s in content)>0 limit 1",
            (AGENTS[inst.source], probe),
        ).fetchone()
        if not hit:
            conn.close()
            raise RuntimeError(f"mapping verification FAILED for {inst.source} -> {AGENTS[inst.source]}")
    conn.close()


async def main() -> int:
    settings = HarnessSettings()
    config = config_from_env_file(CONFIG_FILE)
    instances = [i for i in load_competency(Competency.TEST_TIME_LEARNING, max_questions_per_instance=MAX_Q)
                 if i.source in AGENTS]
    assert len(instances) == 5, f"expected 5 ICL instances, got {len(instances)}"
    _verify_mapping(settings, instances)
    print("agent mapping content-verified for all 5 sources", flush=True)

    os.makedirs(os.path.dirname(RESULTS), exist_ok=True)
    done: set[str] = set()
    if os.environ.get("MAB_RESUME") == "1" and os.path.exists(RESULTS):
        done = {json.loads(l)["instance_id"] for l in open(RESULTS, encoding="utf-8") if l.strip()}
        print(f"RESUME: skipping already-persisted instances: {sorted(done)}", flush=True)
    else:
        open(RESULTS, "w").close()

    from mab.cli import _git_sha
    from mab.datasets.loader import dataset_fingerprint
    all_rows = []
    for inst in instances:
        agent_id = AGENTS[inst.source]
        if inst.instance_id in done:
            print(f"[{inst.source}] already persisted — skipping", flush=True)
            continue
        print(f"[{inst.source}] agent={agent_id[-12:]} questions={len(inst.questions)}", flush=True)
        rows = await replay_agent(settings, config, agent_id, inst,
                                  prompt_for_source(inst.source), grader_for_source(inst.source))
        _persist(RESULTS, rows)
        all_rows.extend(rows)
        c = sum(r.correct for r in rows); e = sum(1 for r in rows if r.error)
        print(f"  -> {c}/{len(rows)} correct, errored={e}", flush=True)

    with open(RESULTS + ".meta.json", "w", encoding="utf-8") as mf:
        json.dump({
            "mode": "replay_no_reingest (persisted ICL memory, F086 exemplar backfill applied)",
            "competency": "test_time_learning(icl)", "questions_per_instance": MAX_Q,
            "config_file": CONFIG_FILE, "tag": TAG,
            "prompt": "prompt_for_source(icl)", "grader": "IclExactMatch",
            "agent_map": AGENTS,
            "harness_git_sha": _git_sha(), "nous_git_sha": _git_sha(str(settings.nous_repo)),
            "dataset": dataset_fingerprint(Competency.TEST_TIME_LEARNING),
        }, mf, indent=2)

    ok = [r for r in all_rows if not r.error]
    c = sum(r.correct for r in ok); n = len(ok)
    p = c / n if n else 0.0
    hw = 1.96 * math.sqrt(p * (1 - p) / n) if n else 0.0
    by_src: dict[str, list[int]] = {}
    for r in ok:
        b = by_src.setdefault(r.source, [0, 0]); b[0] += r.correct; b[1] += 1
    print("", flush=True)
    for s in sorted(by_src):
        print(f"  {s:<34} {by_src[s][0]}/{by_src[s][1]} = {by_src[s][0] / by_src[s][1]:.3f}", flush=True)
    print(f"\nICL n{MAX_Q*5} replay: {c}/{n} = {p:.3f}  95% CI [{p - hw:.3f}, {min(1, p + hw):.3f}]"
          f"  errored={len(all_rows) - n}  (corrected live baseline 0.555; 2026 leader 0.840)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
