"""ICL exemplar-gathering ceiling sim, EMBEDDING variant (text-embedding-3-large
@1536 to match nous). Requires OPENAI_API_KEY. Embeddings cached under the
session scratchpad (icl_emb_cache/) so re-runs are free.

Result (2026-07-19, nous_mab_baseline agents): 1-NN 0.76, maj@5 0.82,
strict-plurality@25 0.81, gold-in-top25 0.99 vs corrected live 0.555
(paired maj@5 +70/-17, sign p=8e-9). See
docs/nous-icl-exemplar-mode-requirements.md.
"""

from __future__ import annotations

import os
import re
import sys
import time
from collections import Counter

import httpx
import numpy as np
import psycopg

from mab.datasets import Competency, load_competency

DB = dict(host="127.0.0.1", port=5433, user="nous", password="nous_eval", dbname="nous_mab_baseline")
CACHE = os.environ.get(
    "ICL_EMB_CACHE",
    r"C:\Users\User\AppData\Local\Temp\claude\E--Projects-nous-memoryAgentBench\7e017c50-bf6e-4ef0-86a8-a079044f9ef4\scratchpad\icl_emb_cache",
)
AGENTS = {
    "icl_banking77_5900shot_balance": "mab-eval-paper-c90e89a7",
    "icl_clinic150_7050shot_balance": "mab-eval-paper-53378b33",
    "icl_nlu_8296shot_balance": "mab-eval-paper-4ed65584",
    "icl_trec_coarse_6600shot_balance": "mab-eval-paper-933d1c23",
    "icl_trec_fine_6400shot_balance": "mab-eval-paper-356d5486",
}
PAIR = re.compile(r"([^\n]{3,300})\nlabel:\s*(\d+)")


def embed(texts: list[str], tag: str) -> np.ndarray:
    os.makedirs(CACHE, exist_ok=True)
    f = os.path.join(CACHE, tag + ".npy")
    if os.path.exists(f):
        a = np.load(f)
        if len(a) == len(texts):
            return a
    key = os.environ["OPENAI_API_KEY"]
    out: list = []
    with httpx.Client(timeout=120) as cl:
        for i in range(0, len(texts), 1000):
            batch = [t[:2000] for t in texts[i:i + 1000]]
            for attempt in range(5):
                r = cl.post(
                    "https://api.openai.com/v1/embeddings",
                    headers={"Authorization": f"Bearer {key}"},
                    json={"model": "text-embedding-3-large", "input": batch, "dimensions": 1536},
                )
                if r.status_code == 200:
                    break
                time.sleep(5 * (attempt + 1))
            r.raise_for_status()
            out.extend(d["embedding"] for d in r.json()["data"])
    a = np.array(out, dtype=np.float32)
    np.save(f, a)
    return a


def main() -> int:
    insts = {i.source: i for i in load_competency(Competency.TEST_TIME_LEARNING, max_questions_per_instance=40)
             if i.source.startswith("icl_")}
    conn = psycopg.connect(**DB)
    tot: Counter = Counter()
    for src, agent in AGENTS.items():
        rows = conn.execute("select content from heart.episode_chunks where agent_id=%s", (agent,)).fetchall()
        exemplars = list(dict.fromkeys(p for (c,) in rows for p in PAIR.findall(c or "")))
        labels = [l for _, l in exemplars]
        E = embed([u for u, _ in exemplars], f"ex_{src}")
        E = E / np.linalg.norm(E, axis=1, keepdims=True)
        qs = insts[src].questions
        Q = embed([q.prompt for q in qs], f"q_{src}")
        Q = Q / np.linalg.norm(Q, axis=1, keepdims=True)
        sims = Q @ E.T
        s: Counter = Counter()
        for qi, q in enumerate(qs):
            gold = q.gold_answers[0].strip()
            tl = [labels[i] for i in np.argsort(-sims[qi])[:25]]
            s["n"] += 1
            s["nn1"] += tl[0] == gold
            s["maj5"] += Counter(tl[:5]).most_common(1)[0][0] == gold
            mc = Counter(tl).most_common()
            s["plur25"] += mc[0][0] == gold and (len(mc) == 1 or mc[0][1] > mc[1][1])
            s["in25"] += gold in tl
        tot.update(s)
        print(f"{src}: 1-NN {s['nn1']}/{s['n']} ({s['nn1']/s['n']:.2f}) | maj@5 {s['maj5']/s['n']:.2f} | "
              f"strict-plur@25 {s['plur25']/s['n']:.2f} | gold-in25 {s['in25']/s['n']:.2f}")
    n = tot["n"]
    print(f"TOTAL: 1-NN {tot['nn1']/n:.2f} | maj@5 {tot['maj5']/n:.2f} | strict-plur@25 {tot['plur25']/n:.2f} | "
          f"gold-in25 {tot['in25']/n:.2f}")
    print("refs: lexical 1-NN 0.67 | corrected live 0.555 | 2026 leader 0.840")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
