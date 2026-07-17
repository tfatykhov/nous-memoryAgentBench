"""Offline probe: is the pre-turn injection miss caused by QUERY DILUTION?

For every CR question (8 instances x 40), embed two query variants —
(a) FULL framed prompt (what pre-turn embeds: CR template + few-shot + question)
(b) BARE question text —
and vector-search the agent's heart.facts and heart.episode_chunks directly
(text-embedding-3-large @1536 dims, cosine, matching nous). Gold-bearing item =
content contains the gold answer string (case-insensitive).

Outputs per variant: gold rank distributions, top-K hit rates, and — using the
published run's per-question correct/wrong labels — the score/margin
distributions needed to calibrate a threshold/ambiguity recall backstop.

No nous server, no answer generation: pure embeddings + DB reads.
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys

import httpx
import psycopg

from mab.datasets import Competency, load_competency
from mab.paper_prompts import PAPER_CR_PROMPT
from mab.runner import frame_prompt

DB = dict(host="127.0.0.1", port=5433, user="nous", password="nous_eval", dbname="nous_mab_wp")
EMB_MODEL, DIMS = "text-embedding-3-large", 1536


def _key() -> str:
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"]
    for line in open("../nous/.env", encoding="utf-8", errors="ignore"):
        if line.startswith("OPENAI_API_KEY"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("no key")


async def embed_all(texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    async with httpx.AsyncClient() as c:
        for i in range(0, len(texts), 100):
            r = await c.post("https://api.openai.com/v1/embeddings",
                             headers={"Authorization": f"Bearer {_key()}"},
                             json={"model": EMB_MODEL, "input": texts[i:i + 100], "dimensions": DIMS},
                             timeout=120.0)
            r.raise_for_status()
            out.extend(d["embedding"] for d in r.json()["data"])
            print(f"  embedded {len(out)}/{len(texts)}", flush=True)
    return out


def search(conn, table: str, agent: str, vec: list[float], k: int = 50):
    """Top-k (content, score) by cosine similarity."""
    rows = conn.execute(
        f"select content, 1 - (embedding <=> %s::vector) as score from heart.{table} "
        f"where agent_id=%s and embedding is not null order by embedding <=> %s::vector limit %s",
        (json.dumps(vec), agent, json.dumps(vec), k)).fetchall()
    return rows


def main() -> int:
    meta = json.load(open("reports/paper_baseline/results_conflict_resolution_replay_n320.jsonl.meta.json"))
    agent_map = meta["agent_map"]
    # published-run correctness labels
    verdict: dict[tuple, bool] = {}
    for line in open("reports/paper_baseline/results_conflict_resolution_replay_n320.jsonl"):
        r = json.loads(line)
        verdict[(r["source"], r["prompt"][:80])] = r["correct"]

    instances = load_competency(Competency.CONFLICT_RESOLUTION, max_questions_per_instance=40)
    items = []  # (source, agent, question, gold, published_correct)
    for inst in instances:
        agent = agent_map[inst.source]
        for q in inst.questions:
            items.append((inst.source, agent, q.prompt, q.gold_answers[0],
                          verdict.get((inst.source, q.prompt[:80]))))
    print(f"{len(items)} questions", flush=True)

    full_q = [frame_prompt(PAPER_CR_PROMPT, it[2]) for it in items]
    bare_q = [it[2] for it in items]
    vecs = asyncio.run(embed_all(full_q + bare_q))
    fv, bv = vecs[:len(items)], vecs[len(items):]

    conn = psycopg.connect(**DB)
    stats = {"full": {"fact_rank": [], "chunk_rank": [], "top1": [], "margin": [], "label": []},
             "bare": {"fact_rank": [], "chunk_rank": [], "top1": [], "margin": [], "label": []}}
    for i, (src, agent, q, gold, corr) in enumerate(items):
        for name, vec in (("full", fv[i]), ("bare", bv[i])):
            facts = search(conn, "facts", agent, vec)
            chunks = search(conn, "episode_chunks", agent, vec, k=30)
            g = gold.lower()
            frank = next((j + 1 for j, (c, _) in enumerate(facts) if g in (c or "").lower()), None)
            crank = next((j + 1 for j, (c, _) in enumerate(chunks) if g in (c or "").lower()), None)
            s = stats[name]
            s["fact_rank"].append(frank); s["chunk_rank"].append(crank)
            s["top1"].append(facts[0][1] if facts else 0.0)
            s["margin"].append((facts[0][1] - facts[1][1]) if len(facts) > 1 else 0.0)
            s["label"].append(corr)
        if (i + 1) % 40 == 0:
            print(f"  searched {i + 1}/{len(items)}", flush=True)
    conn.close()

    def hit(ranks, k):
        return sum(1 for r in ranks if r is not None and r <= k) / len(ranks)

    print("\n================ RESULTS ================", flush=True)
    for name in ("full", "bare"):
        s = stats[name]
        print(f"\n--- query = {name.upper()} prompt ---")
        for lbl, ranks in (("facts", s["fact_rank"]), ("chunks", s["chunk_rank"])):
            found = [r for r in ranks if r is not None]
            print(f"  {lbl}: gold found at any rank: {len(found)}/{len(ranks)}"
                  f" | top5 {hit(ranks,5):.2f}  top15 {hit(ranks,15):.2f}  top30 {hit(ranks,30):.2f}"
                  f" | median rank (when found): {statistics.median(found) if found else '-'}")
    # threshold calibration on FULL (the deployed query): hit vs miss score distros
    s = stats["full"]
    grp = {True: {"top1": [], "margin": []}, False: {"top1": [], "margin": []}}
    for t1, mg, lb in zip(s["top1"], s["margin"], s["label"]):
        if lb is None: continue
        grp[lb]["top1"].append(t1); grp[lb]["margin"].append(mg)
    print("\n--- backstop calibration (FULL query, labels = published correctness) ---")
    for lb in (True, False):
        g = grp[lb]
        print(f"  {'CORRECT' if lb else 'WRONG  '} (n={len(g['top1'])}): "
              f"top1 mean {statistics.mean(g['top1']):.3f} median {statistics.median(g['top1']):.3f} | "
              f"margin mean {statistics.mean(g['margin']):.4f} median {statistics.median(g['margin']):.4f}")
    out = "reports/paper_baseline/probe_query_dilution.json"
    json.dump({k: {kk: vv for kk, vv in v.items()} for k, v in stats.items()}, open(out, "w"))
    print(f"\nraw per-question data -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
