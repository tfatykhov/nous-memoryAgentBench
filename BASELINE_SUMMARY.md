# BASELINE_SUMMARY — every reported number, its evidence, and its tier

Single reconciliation point for the nous / MemoryAgentBench baseline
(white paper: `docs/whitepaper/nous-memoryagentbench-baseline.pdf`;
narrative report: `docs/reviews/2026-07-03-paper-faithful-baseline.md`).
Runs executed 2026-07-03/04.

## Position statement (read this before quoting any number)

On the sampled, paper-aligned slices, nous exceeds every method reported in the
MemoryAgentBench paper (2025 table) on Accurate Retrieval, Conflict Resolution,
and Long-Range Understanding, and matches that table's best Test-Time Learning.

Against the **2026 field** — Infini Memory's Table 1 (arXiv:2606.10677, full
benchmark, gpt-5-mini base, gpt-5 LLM-judge; every row verbatim-extracted and
arithmetic-verified) — compared at **sub-dataset level, with all persisted
nous answers RE-GRADED under a reconstruction of their judge protocol**
(gpt-5, binary; theirs is unpublished):

| Sub-dataset | nous (gpt-5 judge) | Infini-A | |
|---|---|---|---|
| AR avg (SH-QA/MH-QA/LME/Event) | **91.8** (87.5/87.5/100.0/92.1) | 81.2 | above |
| FC-SH / FC-MH (conflict) | **89.4 / 56.2** (n=160 each) | 81.0 / 35.0 | FC-MH decidable win; FC-SH backbone-undecidable |
| DetQA (long-range) | **85.3** (n=68) | 77.2 | above (backbone-undecidable) |
| Summ | 59.2 (n=1) | 59.9 | par |
| ICL (test-time learning) | 62.5 (n=200) | **84.0** | **behind** |

Under the official strict graders the same numbers are: AR 85.1, FC-SH 88.7,
FC-MH 56.2, DetQA 82.4, ICL 55.5 (judge-vs-strict delta +0–12.5pp on
verbose-answer tasks, ~0 on short-entity tasks). CR total re-priced 0.766
(n=64) -> **0.725** (n=320, CI [0.676, 0.774]) by replaying ALL 40 Q/instance
against the same persisted memory; multi-hop degrades with context size
(0.825/0.600/0.525/0.300 at 6k/32k/64k/262k).

**Backbone-adjusted claims** (per prod-nous review, decision e65cd66b; yardstick =
MAB's own observed backbone swing ~9.7pp): FC-MH margin **+21.2pp -> decidable
win**; AR +10.6pp -> marginal; FC-SH +8.4pp and DetQA +8.1pp -> **directionally
ahead but backbone-undecidable** (not claimed as architecture wins); ICL
-21.5pp behind. AR "avg" is macro (matches Infini's method, weak on both
sides: n=8 cells have Wilson CIs ~[0.53,0.98]); micro AR = 0.897 official /
0.922 judge.

**Judge validation (2026-07-05):** reconstructed gpt-5 judge vs official
graders on all n=820 common items: **agreement 0.970, Cohen's kappa 0.918**.
Inter-judge sensitivity (gpt-4o, identical prompt): agreement 0.927, kappa
0.813, aggregate +6.6pp (inside the 5-10pp caution band). Per-family: AR/
LRU/longmem stable (<=1.5pp); **ICL (+7.5pp) and factconsolidation (+12.2pp)
are judge-model-sensitive** -> official-grader numbers remain headline for
those; judge numbers secondary. Robustness of the flagship claim: FC-MH =
0.562 official = 0.562 gpt-5 = 0.469 gpt-4o — **above Infini-A's 0.350 under
all three protocols**. FC-SH ranges 0.744-0.894 across protocols (straddles
their 0.81; consistent with its undecidable status). Evidence:
`reports/judge_regrade/judge_*` (gpt-5) and `judge4o_*` (gpt-4o).

Naming: MAB's official AR sub-dataset names are SH-Doc QA / MH-Doc QA — our
source ids ruler_qa1_197K / ruler_qa2_421K are internal labels for them.
"TTL" figures here are the **TTL–ICL subset** (recsys blocked), everywhere.

Caveats: 2026 numbers as-reported (not re-run); their judge prompt is
unpublished (ours is a disclosed reconstruction, published verbatim in the
white paper appendix); base models differ (claude-sonnet-5 vs gpt-5-mini);
recsys blocked -> nous TTL avg and Overall are n/a. No state-of-the-art or
official-benchmark claim. Never compare any partial aggregate of the numbers
below to full-benchmark "overall" figures.

## Comparability tiers

- **T1 — paper-comparable (transport deviation only):** paper's exact prompt,
  grader/judge, and question set; the one deviation is ingestion transport
  (32,000-char turns vs the paper's 512/4096-token chunks; zero answer text
  lost — see truncation audit below).
- **T2 — paper-aligned with a deliberate grader deviation:** as T1, plus a
  documented grading interpretation choice.
- **T3 — nous-engineering only:** internal instrumentation (memory-lift,
  failure attribution, abstention-scoped grading). Never compare to MAB
  numbers.

## Reported numbers → evidence

| Number | n | Tier | Evidence file | Notes |
|---|---|---|---|---|
| **CR 0.725** (232/320; sh 0.887, mh 0.562) | 320 | T1 | `reports/paper_baseline/results_conflict_resolution_replay_n320.jsonl` | ALL 40 Q/instance replayed on the same persisted memory; content-verified agent mapping. Supersedes the n=64 0.766 (`reports/paper_replay/run.log`, optimistic first-8 draw) |
| CR gpt-5-judge 0.728 (sh 0.894, mh 0.562) | 320 | T2* | `reports/judge_regrade/judge_results_conflict_resolution_replay_n320.jsonl` | 2026-protocol regrade (reconstructed judge) |
| AR/LRU/TTL gpt-5-judge regrades | 500 | T2* | `reports/judge_regrade/judge_results_*.jsonl` | Event 92.1, MH-QA 87.5, LME 100.0, DetQA 85.3, ICL 62.5 |
| **AR 0.897** (208/232) | 232 | T1 | consolidated from the five files below | eventqa_65536-weighted |
| — eventqa_65536 0.910 | 200 | T1 | `reports/paper_baseline/results_accurate_retrieval_eventqa_65536.jsonl` | 5 contexts x 40 Q |
| — eventqa_131072 0.750 | 8 | T1 | `.../results_accurate_retrieval_eventqa_131072.jsonl` | |
| — eventqa_full 0.875 | 8 | T1 | `.../results_accurate_retrieval_eventqa_full.jsonl` | 2.31M chars |
| — ruler_qa2_421K 0.750 | 8 | T1 | `.../results_accurate_retrieval_ruler_qa2_421K.jsonl` | |
| — longmemeval_s* 0.875 | 8 | T1 | `.../results_accurate_retrieval_longmemeval_s_.jsonl` | gpt-4o judge; no abstention (`_abs`) questions in this sample (they sit at positions 29/31) |
| — ruler_qa1_197K 0.875 | 8 | T1 | `reports/paper_ar/ar_full.log` | log-only (pre-persistence); NOT in the AR 232 consolidation |
| **TTL 0.555** (111/200) | 200 | **T2** | `.../results_test_time_learning_icl_*.jsonl` | grader parses `label:` then exact-matches (stricter than the paper's ambiguous icl scoring — conservative). File holds 240 raw rows: dedup on (source, qa_pair_id/prompt) keeping last = 111/200 (40 dup rows — 5 sources x 8 early-run rows — from a fixed append bug) |
| **LRU detective 0.824** (56/68) | 68 | T1 | `.../results_long_range_understanding_detective_qa.jsonl` | all 10 contexts, 0 errors |
| **infbench_sum f1 0.592** | 1 | T1 | `.../results_long_range_understanding_infbench_sum_e.jsonl` | single book — indicative only |
| memory-lift, attribution splits | — | **T3** | root-cause docs under `docs/reviews/` | diagnostic instrumentation; never MAB-comparable |

## Official MAB components NOT covered

Do not read any per-competency number as full-benchmark coverage:

- **TTL:** `recsys` sub-dataset excluded — its grader requires `entity2id.json`,
  which is not shipped in the MAB public repo. TTL = icl family only.
- **AR:** measured at 1 context for eventqa_131072/full, ruler (each), 1 of 5
  longmemeval instances; longmemeval abstention questions not yet sampled.
- **LRU:** infbench_sum at n=1 book (of 100 available).
- **CR:** first 40 of 100 questions per instance (320 of 800; all 8 instances
  covered). Full coverage (100/instance) is a retrieval-only replay away —
  the persisted memory serves any question count without re-ingest.
- No single aggregate score is published, by policy.

## Provenance (applies to all reported runs)

- Harness: this repo, branch `feat/consolidation-backfill-multicycle` (merged
  as PR #2, `7b22755`), runs executed 2026-07-03/04 as the branch evolved. The
  exact per-run harness SHA was NOT stamped at run time — an honesty gap this
  summary exists to close; runs after 2026-07-04 stamp `harness_git_sha` in
  their `.meta.json`. Graders vendored from
  `github.com/HUST-AI-HYZ/MemoryAgentBench` (MIT), independently reviewed.
- nous under test: `../nous` @ `1e5a04e` (main; includes #552/#553/#554),
  model `claude-sonnet-5`, live prod `.env` + eval-hygiene overrides only
  (`configs/prod_memory.env`; 117-knob reference snapshot pinned in
  `configs/prod_baseline_2026-07-03.env`; big-context profile
  `configs/prod_memory_bigctx.env` for giants — see per-dir README).
- Dataset: HF `ai-hyz/MemoryAgentBench`, revision
  `7ea066982b140a19337e17e60d45d4076e042faf` (all four parquets).
- Judges: gpt-4o (longmemeval yes/no; infbench 3-call f1).
- Truncation audit: all 34 evaluated instances recomputed at run settings
  (32,000 x 80): **0 dropped chunks**. Runs after 2026-07-04 stamp
  `chunks_sent`/`chunks_truncated`/`ingest_settled` per row + a `.meta.json`
  with capacity, config overrides, SHAs, model, and dataset fingerprint.

## Superseded / historical files

| File | Status |
|---|---|
| `reports/paper_baseline/longmem.log` | SUPERSEDED — pre-fix run (one-turn-per-chunk) ingested 80/1282 turns; replaced by `longmem_full.log` + the longmem JSONL |
| `reports/paper_ar/smoke_eventqa.log`, `ar_rest.log` | historical smoke/partial runs; eventqa numbers superseded by the n=200 JSONL |
| `scripts/replay_paper_prompt.py` | HISTORICAL driver (produced CR 0.766); use `scripts/run_paper_baseline.py` for new runs |
| TTL icl JSONL first-8 duplicate rows | superseded by the n=40/source rows in the same file (dedup rule above) |
