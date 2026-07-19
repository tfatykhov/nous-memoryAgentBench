"""Post-repair keyed-retrieval gate (F085 Gate-1, nous #564 applied).

Same measurement as the adapted GATE-1 sim (0.48 pre-fix): for each CR
question, retrieve active enumerative facts by word-bounded entity-key match
against the question via heart.fact_entity_keys (bidirectional index).
Gold check = gold string in a retrieved fact's content. Zero LLM calls.

Gate: single-hop >= 0.80.
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
    stats = {"sh": {"r1": 0, "n": 0, "sizes": []}, "mh": {"r1": 0, "n": 0, "sizes": []}}
    for inst in instances:
        agent = agent_map[inst.source]
        rows = conn.execute(
            "select fek.entity_key, lower(f.content) from heart.fact_entity_keys fek "
            "join heart.facts f on f.id = fek.fact_id "
            "where fek.agent_id=%s and f.active and f.source='enumerative_extractor'",
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
            seen: set[int] = set()
            r1_facts = []
            for k in r1_keys:
                for c in by_key[k]:
                    if id(c) not in seen:
                        seen.add(id(c))
                        r1_facts.append(c)
            hit1 = any(gold in c for c in r1_facts)
            s = stats[hop]
            s["n"] += 1
            s["r1"] += hit1
            s["sizes"].append(len(r1_facts))
    conn.close()

    print("=========== KEYED ENTITY-INDEX GATE (zero LLM, post-#564 repair) ===========")
    tot_r1 = tot_n = 0
    for hop in ("sh", "mh"):
        s = stats[hop]
        tot_r1 += s["r1"]; tot_n += s["n"]
        print(f"  {hop}: gold retrieved {s['r1']}/{s['n']} ({s['r1']/s['n']:.2f}) | "
              f"candidate facts median {statistics.median(s['sizes'])}, p90 {sorted(s['sizes'])[int(.9*len(s['sizes']))]}")
    print(f"  TOTAL: {tot_r1}/{tot_n} ({tot_r1/tot_n:.2f})")
    print("  GATE: sh >= 0.80 (pre-fix: 0.48 active-only, 0.61 incl. wrongly-deactivated)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
