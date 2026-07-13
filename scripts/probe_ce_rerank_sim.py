"""Offline simulation: would retrieval-time cross-encoder reranking (F042,
bge-reranker-v2-m3, top-30 candidates — nous's exact config) fix the chunk
ranking gap?

For each CR question: fetch top-30 chunk candidates by vector (bare-question
query), rerank with the CE, and compare gold@K before vs after. Target class =
the 24 wrong answers whose gold ranked 6-30 (probe 2026-07-13). No nous server.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import httpx
import psycopg

from mab.datasets import Competency, load_competency

DB = dict(host="127.0.0.1", port=5433, user="nous", password="nous_eval", dbname="nous_mab_baseline")
CE_MODEL = "BAAI/bge-reranker-v2-m3"  # nous cross_encoder_model default
TEXT_LIMIT = 512                       # nous cross_encoder_text_limit (chars)


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
                             json={"model": "text-embedding-3-large", "input": texts[i:i + 100],
                                   "dimensions": 1536}, timeout=120.0)
            r.raise_for_status()
            out.extend(d["embedding"] for d in r.json()["data"])
    return out


def main() -> int:
    from sentence_transformers import CrossEncoder
    print("loading CE model (first run downloads ~2.3GB)...", flush=True)
    ce = CrossEncoder(CE_MODEL, max_length=512)

    meta = json.load(open("reports/paper_baseline/results_conflict_resolution_replay_n320.jsonl.meta.json"))
    agent_map = meta["agent_map"]
    verdict = {}
    for line in open("reports/paper_baseline/results_conflict_resolution_replay_n320.jsonl"):
        r = json.loads(line)
        verdict[(r["source"], r["prompt"][:80])] = r["correct"]

    instances = load_competency(Competency.CONFLICT_RESOLUTION, max_questions_per_instance=40)
    items = [(inst.source, agent_map[inst.source], q.prompt, q.gold_answers[0],
              verdict.get((inst.source, q.prompt[:80])))
             for inst in instances for q in inst.questions]
    print(f"{len(items)} questions; embedding queries...", flush=True)
    vecs = asyncio.run(embed_all([it[2] for it in items]))

    conn = psycopg.connect(**DB)
    before = {"r": [], "label": []}
    after = {"r": [], "label": []}
    for i, (src, agent, q, gold, corr) in enumerate(items):
        rows = conn.execute(
            "select content from heart.episode_chunks where agent_id=%s and embedding is not null "
            "order by embedding <=> %s::vector limit 30",
            (agent, json.dumps(vecs[i]))).fetchall()
        cands = [r[0] or "" for r in rows]
        g = gold.lower()
        def rank(lst):
            return next((j + 1 for j, c in enumerate(lst) if g in c.lower()), None)
        before["r"].append(rank(cands)); before["label"].append(corr)
        # CE rerank: (query, passage[:512]) pairs, exactly the F042 shape
        scores = ce.predict([(q, c[:TEXT_LIMIT]) for c in cands], show_progress_bar=False)
        reranked = [c for _, c in sorted(zip(scores, cands), key=lambda t: -t[0])]
        after["r"].append(rank(reranked)); after["label"].append(corr)
        if (i + 1) % 40 == 0:
            print(f"  {i + 1}/{len(items)}", flush=True)
    conn.close()

    def hit(d, k, label=None):
        rs = [r for r, lb in zip(d["r"], d["label"]) if label is None or lb is label]
        return sum(1 for r in rs if r and r <= k), len(rs)

    print("\n============ CE RERANK SIMULATION ============")
    for k in (3, 5, 10, 15):
        b, n = hit(before, k); a, _ = hit(after, k)
        print(f"  gold@top{k:<2}: vector {b}/{n} ({b/n:.2f}) -> CE {a}/{n} ({a/n:.2f})  [{a-b:+d}]")
    print("\n  target class (published-WRONG answers only):")
    for k in (3, 5, 10, 15):
        b, n = hit(before, k, False); a, _ = hit(after, k, False)
        print(f"  gold@top{k:<2}: vector {b}/{n} -> CE {a}/{n}  [{a-b:+d}]")
    json.dump({"before": before, "after": after}, open("reports/paper_baseline/probe_ce_sim.json", "w"))
    print("\nraw -> reports/paper_baseline/probe_ce_sim.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
