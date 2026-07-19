"""ICL exemplar-gathering ceiling sim (zero LLM) — prices the proposed nous
test-time-learning retrieval mode before any build.

For each ICL question (5 sources x 40q, persisted agents in nous_mab_baseline):
parse stored `utterance\nlabel: N` exemplars from heart.episode_chunks, rank by
lexical similarity (stopword-filtered token overlap / Jaccard) to the question,
and score: 1-NN label accuracy, majority@5/@25, and gold-label-in-top-25
(the gatherability ceiling an LLM reader could exploit).

Validations built in (2026-07-19): storage loss 0.2-2.0% by same-parser
context-vs-stored diff (apparent 'missing' exemplars were dataset resampling
repeats); exact-question leakage 7/200.

Reference points: nous live ICL 0.571; 2026 leader 0.840.
"""

from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict

import psycopg

from mab.datasets import Competency, load_competency

DB = dict(host="127.0.0.1", port=5433, user="nous", password="nous_eval", dbname="nous_mab_baseline")

AGENTS = {
    "icl_banking77_5900shot_balance": "mab-eval-paper-c90e89a7",
    "icl_clinic150_7050shot_balance": "mab-eval-paper-53378b33",
    "icl_nlu_8296shot_balance": "mab-eval-paper-4ed65584",
    "icl_trec_coarse_6600shot_balance": "mab-eval-paper-933d1c23",
    "icl_trec_fine_6400shot_balance": "mab-eval-paper-356d5486",
}
PAIR = re.compile(r"([^\n]{3,300})\nlabel:\s*(\d+)")
STOP = set("the a an of is was in on at to for and or by with from i my me you your what how can do does it this that".split())


def toks(s: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9']+", s.lower()) if w not in STOP]


def main() -> int:
    insts = {i.source: i for i in load_competency(Competency.TEST_TIME_LEARNING, max_questions_per_instance=40)
             if i.source.startswith("icl_")}
    conn = psycopg.connect(**DB)
    totals = Counter()
    for src, agent in AGENTS.items():
        rows = conn.execute("select content from heart.episode_chunks where agent_id=%s", (agent,)).fetchall()
        exemplars = list(dict.fromkeys(p for (c,) in rows for p in PAIR.findall(c or "")))
        inv: dict[str, set[int]] = defaultdict(set)
        ex_toks = []
        for idx, (u, _l) in enumerate(exemplars):
            t = set(toks(u))
            ex_toks.append(t)
            for w in t:
                inv[w].add(idx)
        s = Counter()
        for q in insts[src].questions:
            gold = q.gold_answers[0].strip()
            qt = set(toks(q.prompt))
            cand: Counter = Counter()
            for w in qt:
                for idx in inv.get(w, ()):
                    cand[idx] += 1
            scored = sorted(cand.items(), key=lambda kv: (-kv[1] / max(1, len(qt | ex_toks[kv[0]])), kv[0]))[:25]
            top = [exemplars[i][1] for i, _ in scored]
            s["n"] += 1
            if top:
                s["nn1"] += top[0] == gold
                s["maj5"] += Counter(top[:5]).most_common(1)[0][0] == gold
                s["maj25"] += Counter(top).most_common(1)[0][0] == gold
                s["in25"] += gold in top
        totals.update(s)
        print(f"{src}: exemplars {len(exemplars)} | 1-NN {s['nn1']}/{s['n']} ({s['nn1']/s['n']:.2f}) | "
              f"maj@5 {s['maj5']/s['n']:.2f} | maj@25 {s['maj25']/s['n']:.2f} | gold-in-top25 {s['in25']/s['n']:.2f}")
    n = totals["n"]
    print(f"TOTAL: 1-NN {totals['nn1']}/{n} ({totals['nn1']/n:.2f}) | maj@5 {totals['maj5']/n:.2f} | "
          f"maj@25 {totals['maj25']/n:.2f} | gold-in-top25 {totals['in25']/n:.2f}")
    print("reference: nous live ICL 0.571; 2026 leader 0.840")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
