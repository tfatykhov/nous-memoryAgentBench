"""CR firm-up: replay ALL 40 Q/instance (n=320) against the persisted CR memory.

Retrieval-only — NO re-ingest: the 8 CR agents' memory (which produced the
published 49/64 = 0.766) is answered against as-is, so this is a pure
sample-size extension on identical memory. Replaces the historical script's
fragile chunk-count bucketing with CONTENT-VERIFIED agent->instance mapping:
each context's probe string (verified unique among the 4 CR contexts) must be
found in the agent's stored episode_chunks.

Usage (from repo root, eval DB up):
    MAB_NOUS_REPO=../nous MAB_NOUS_PYTHON=... MAB_DB_NAME=nous_mab MAB_TURN_DELAY_S=5 \
    ./.venv/Scripts/python.exe scripts/replay_cr_n320.py
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
from mab.grading.paper_grader import PaperSubstringExactMatch
from mab.paper_prompts import PAPER_CR_PROMPT
from mab.paper_run import _persist
from mab.replay import replay_agent

import sys as _sys
MAX_Q = int(_sys.argv[1]) if len(_sys.argv) > 1 else 40
TAG = _sys.argv[2] if len(_sys.argv) > 2 else ""
CONFIG_FILE = _sys.argv[3] if len(_sys.argv) > 3 else "configs/prod_memory.env"
RESULTS = f"reports/paper_baseline/results_conflict_resolution_replay_n{MAX_Q * 8}{TAG}.jsonl"


def _probe_for(ctx: str, larger: list[str], width: int = 60) -> str:
    """A RAW substring of ``ctx``'s tail absent from every LARGER context.

    CR contexts are NESTED (the 6k doc is a prefix of 32k/64k/262k), so no
    substring of a smaller context is globally unique — smaller sizes are
    resolved by elimination (largest first). The probe must be raw (chunks
    store the text verbatim, newlines included).
    """
    n = len(ctx)
    for frac in (0.95, 0.9, 0.85, 0.8):
        p = ctx[int(n * frac): int(n * frac) + width]
        if len(p) >= 40 and not any(p in o for o in larger):
            return p
    raise RuntimeError("no tail probe absent from larger contexts")


def _candidate_agents(settings: HarnessSettings) -> list[str]:
    conn = psycopg.connect(
        host=settings.db_host, port=settings.db_port, user=settings.db_user,
        password=settings.db_password, dbname=settings.db_name,
    )
    rows = conn.execute(
        "select e.agent_id, max(e.created_at) mx from heart.episodes e "
        "where e.agent_id like 'mab-eval-prod_memory-%' and e.agent_id not like '%-ctl' "
        "group by e.agent_id order by mx desc limit 8"
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def _agents_containing(settings: HarnessSettings, agents: list[str], probe: str) -> list[str]:
    """Which candidate agents hold ``probe`` verbatim in stored chunks (position(), no LIKE escaping)."""
    conn = psycopg.connect(
        host=settings.db_host, port=settings.db_port, user=settings.db_user,
        password=settings.db_password, dbname=settings.db_name,
    )
    hits = [a for a in agents if conn.execute(
        "select 1 from heart.episode_chunks where agent_id=%s and position(%s in content)>0 limit 1",
        (a, probe),
    ).fetchone()]
    conn.close()
    return hits


async def main() -> int:
    settings = HarnessSettings()
    config = config_from_env_file(CONFIG_FILE)
    instances = load_competency(Competency.CONFLICT_RESOLUTION, max_questions_per_instance=MAX_Q)
    assert len(instances) == 8, f"expected 8 CR instances, got {len(instances)}"

    # --- content-verified mapping: size-context -> its 2 agents (sh/mh share context)
    by_size: dict[str, list] = {}
    for inst in instances:
        by_size.setdefault(inst.source.rsplit("_", 1)[-1], []).append(inst)
    contexts = {size: pool[0].context for size, pool in by_size.items()}
    agents = _candidate_agents(settings)
    print(f"candidate agents: {[a[-12:] for a in agents]}", flush=True)
    # Elimination, largest context first: nested contexts mean a size's tail
    # probe also hits all LARGER agents — which are already assigned by then.
    pool_by_size: dict[str, list[str]] = {}
    assigned: set[str] = set()
    for size in sorted(contexts, key=lambda s: len(contexts[s]), reverse=True):
        larger = [c for c in contexts.values() if len(c) > len(contexts[size])]
        probe = _probe_for(contexts[size], larger)
        found = [a for a in _agents_containing(settings, agents, probe) if a not in assigned]
        print(f"  {size:>5}: probe {probe[:36]!r}... -> {len(found)} unassigned {[a[-12:] for a in found]}", flush=True)
        if len(found) != 2:
            print(f"ABORT: expected exactly 2 unassigned agents for {size}, got {len(found)}", flush=True)
            return 1
        pool_by_size[size] = found
        assigned.update(found)

    # --- replay instances (fresh results file, or RESUME: skip persisted instances)
    os.makedirs(os.path.dirname(RESULTS), exist_ok=True)
    done: set[str] = set()
    if os.environ.get("MAB_RESUME") == "1" and os.path.exists(RESULTS):
        done = {json.loads(l)["instance_id"] for l in open(RESULTS, encoding="utf-8") if l.strip()}
        print(f"RESUME: skipping already-persisted instances: {sorted(done)}", flush=True)
    else:
        open(RESULTS, "w").close()
    from mab.cli import _git_sha
    from mab.datasets.loader import dataset_fingerprint
    agent_map: dict[str, str] = {}
    grader = PaperSubstringExactMatch()
    all_rows = []
    for inst in instances:
        size = inst.source.rsplit("_", 1)[-1]
        agent_id = pool_by_size[size].pop(0)
        agent_map[inst.source] = agent_id
        if inst.instance_id in done:
            print(f"[{inst.source}] already persisted — skipping", flush=True)
            continue
        print(f"[{inst.source}] agent={agent_id[-12:]} questions={len(inst.questions)}", flush=True)
        rows = await replay_agent(settings, config, agent_id, inst, PAPER_CR_PROMPT, grader)
        _persist(RESULTS, rows)
        all_rows.extend(rows)
        c = sum(r.correct for r in rows); e = sum(1 for r in rows if r.error)
        print(f"  -> {c}/{len(rows)} correct, errored={e}", flush=True)

    with open(RESULTS + ".meta.json", "w", encoding="utf-8") as mf:
        json.dump({
            "mode": "replay_no_reingest (same persisted memory as the published 49/64)",
            "competency": "conflict_resolution", "questions_per_instance": MAX_Q, "config_file": CONFIG_FILE, "tag": TAG,
            "prompt": "PAPER_CR_PROMPT", "grader": grader.metric,
            "agent_map": agent_map,
            "harness_git_sha": _git_sha(), "nous_git_sha": _git_sha(str(settings.nous_repo)),
            "dataset": dataset_fingerprint(Competency.CONFLICT_RESOLUTION),
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
        print(f"  {s:<28} {by_src[s][0]}/{by_src[s][1]} = {by_src[s][0] / by_src[s][1]:.3f}", flush=True)
    print(f"\nCR n320 replay: {c}/{n} = {p:.3f}  95% CI [{p - hw:.3f}, {min(1, p + hw):.3f}]"
          f"  errored={len(all_rows) - n}  (2026 leader 0.836; published n64 was 0.766)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
