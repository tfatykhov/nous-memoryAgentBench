"""Offline ceiling simulation for the proposed KEYED-LOOKUP retrieval leg (R3).

For each CR question: round-1 = fetch active enumerative facts whose
subject_key appears (word-bounded) in the question; round-2 (iterative,
models keyed lookup inside a recall loop) = keys appearing in round-1 fact
contents. Gold check = gold string in a retrieved fact. Zero LLM calls.

Answers: can exact-key selection find the gold fact where embedding search
(findability@top15 = 0.50) cannot — and are candidate sets small enough to
inject?
"""

from __future__ import annotations

import json
import re
import statistics
import sys

import psycopg

from mab.datasets import Competency, load_competency

DB = dict(host="127.0.0.1", port=5433, user="nous", password="nous_eval", dbname="nous_mab_wp")


def main() -> int:
    meta = json.load(open("reports/paper_baseline/results_conflict_resolution_replay_n320.jsonl.meta.json"))
    agent_map = meta["agent_map"]
    instances = load_competency(Competency.CONFLICT_RESOLUTION, max_questions_per_instance=40)

    conn = psycopg.connect(**DB)
    stats = {"sh": {"r1": 0, "r2": 0, "n": 0, "sizes": []}, "mh": {"r1": 0, "r2": 0, "n": 0, "sizes": []}}
    for inst in instances:
        agent = agent_map[inst.source]
        rows = conn.execute(
            "select subject_key, lower(content) from heart.facts "
            "where agent_id=%s and source='enumerative_extractor' and active and subject_key is not null",
            (agent,)).fetchall()
        by_key: dict[str, list[str]] = {}
        for k, c in rows:
            by_key.setdefault(k, []).append(c or "")
        keys = [k for k in by_key if len(k) >= 4]
        hop = "mh" if "_mh_" in inst.source else "sh"
        for q in inst.questions:
            ql = q.prompt.lower()
            gold = q.gold_answers[0].lower()
            r1_keys = [k for k in keys if re.search(rf"\b{re.escape(k)}\b", ql)]
            r1_facts = [c for k in r1_keys for c in by_key[k]]
            hit1 = any(gold in c for c in r1_facts)
            # round 2: keys mentioned inside round-1 fact contents
            joined = " ".join(r1_facts)
            r2_keys = [k for k in keys if k not in r1_keys and re.search(rf"\b{re.escape(k)}\b", joined)] if r1_facts else []
            r2_facts = [c for k in r2_keys for c in by_key[k]]
            hit2 = hit1 or any(gold in c for c in r2_facts)
            s = stats[hop]
            s["n"] += 1
            s["r1"] += hit1
            s["r2"] += hit2
            s["sizes"].append(len(r1_facts))
    conn.close()

    print("=========== KEYED-LOOKUP SIMULATION (zero LLM) ===========")
    tot_r1 = tot_r2 = tot_n = 0
    for hop in ("sh", "mh"):
        s = stats[hop]
        tot_r1 += s["r1"]; tot_r2 += s["r2"]; tot_n += s["n"]
        print(f"  {hop}: round-1 gold {s['r1']}/{s['n']} ({s['r1']/s['n']:.2f}) | "
              f"+iterative round-2 {s['r2']}/{s['n']} ({s['r2']/s['n']:.2f}) | "
              f"round-1 candidate facts median {statistics.median(s['sizes'])}, p90 {sorted(s['sizes'])[int(.9*len(s['sizes']))]}")
    print(f"  TOTAL: round-1 {tot_r1}/{tot_n} ({tot_r1/tot_n:.2f}) | round-2 {tot_r2}/{tot_n} ({tot_r2/tot_n:.2f})")
    print(f"  reference: embedding findability@top15 = 0.50; chunk channel = 0.63-0.67")
    return 0


if __name__ == "__main__":
    sys.exit(main())
