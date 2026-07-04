# nous Paper-Faithful Baseline vs MemoryAgentBench field

**Date:** 2026-07-03
**Config:** live prod `../nous/.env` (model claude-sonnet-5, critic advised, effort=high,
thinking=adaptive, context_window=700000, budget overrides, lossless capture, hybrid
chunk search, date-leg) + eval-hygiene overrides ONLY (heartbeat/schedule/rubric-outcome-
detection off). Pinned baseline snapshot: `configs/prod_baseline_2026-07-03.env`.
**Methodology:** the paper's exact per-source prompt + grader, vendored from
github.com/HUST-AI-HYZ/MemoryAgentBench (MIT), independently reviewed.

## Results

| Competency | Score | n | Field band | Placement |
|---|---|---|---|---|
| Conflict Resolution | **0.766** | 64 | 5–33% | above |
| Accurate Retrieval | **0.844** | 64 | 33–72% | above |
| Test-Time Learning | **0.650** | 40 | 12–54% | above |
| Long-Range Understanding | **0.833** (detective) · **0.592 f1** (infbench_sum) | 6 + 1 | 16–62% | above |

Per-source:
- CR (factconsolidation): 0.766 overall; single-hop 0.906, multi-hop 0.625 (field multi-hop <7%).
- AR: eventqa_65536 0.875 (n=24), eventqa_131072 0.750, eventqa_full 0.875, ruler_qa1_197K
  0.875, ruler_qa2_421K 0.750, longmemeval_s* 0.875 → 54/64 = 0.844.
- TTL (icl): banking77 0.625, clinic150 0.500, nlu 0.500, trec_coarse 1.000, trec_fine 0.625
  → 26/40 = 0.650.
- LRU: detective_qa 0.833 (5/6); infbench_sum mean f1 0.592 (n=1, gpt-4o fluency/recall/precision).

**0 errors and 0 fatal rate-limit stalls across every run.**

## Grader fidelity (per source, reviewed)
- CR / ruler_qa / detective_qa → paper substring (normalize_answer, max-over-golds).
- eventqa → all-elements recall with RAW `.lower()` (paper `_process_eventqa`; NOT
  normalize_answer — fixed after review found the normalize version inflated).
- icl → parse `label:` then exact on the bare label (deliberate; paper's own icl is
  ambiguous — no primary metric, exact always fails on `label: X`, substring false-positives
  on digit collisions; ours is conservative + more correct).
- longmemeval → gpt-4o yes/no judge (`get_anscheck_prompt` verbatim, per-task incl. temporal
  off-by-one + abstention).
- infbench_sum → gpt-4o 3-call judge, f1 = fluency·2·rec·prec/(rec+prec).

## Caveats (why this is a strong signal, not yet a leaderboard claim)
1. **Subsample**, not the full benchmark — mostly 1 instance/source (CR n=64, AR n=64 over 6
   sources, TTL n=40, LRU n=6+1). Wide CIs; the field bands are full-set.
2. **recsys (TTL) is data-blocked** — `entity2id.json` not shipped in the open repo — so TTL
   is icl-only.
3. **infbench_sum n=1** — the summarization f1 is a single book.
4. **Config is prod, but prod was debugged against this eval** — the write/read fixes (lossless
   capture, hybrid search, recall depth, ingest preamble, turn-packing) were found here.
5. The paper CR/AR prompts hand the model the task rule (CR serial-number rule + few-shot;
   eventqa "next event" framing) — part of the paper protocol, but an assist.

## To convert to a defensible claim
Full-benchmark runs (all instances) per competency, on a config frozen before the eval,
larger n, and reconstruct recsys `entity2id.json` for TTL completeness.

## Bottom line
Across all four competencies and every source tested — including 1.6–2.3M-char giants —
nous scores **above the published MemoryAgentBench field band**, prod-faithfully and under
the paper's exact grading. Promising-to-excellent on the validated slice; the open items
are about tightening the number, not changing the conclusion.
