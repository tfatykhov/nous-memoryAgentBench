# BASELINE_SUMMARY — every reported number, its evidence, and its tier

Single reconciliation point for the nous / MemoryAgentBench baseline
(white paper: `docs/whitepaper/nous-memoryagentbench-baseline.pdf`;
narrative report: `docs/reviews/2026-07-03-paper-faithful-baseline.md`).
Runs executed 2026-07-03/04.

## Position statement (read this before quoting any number)

On the sampled, paper-aligned slices, nous exceeds every method reported in the
MemoryAgentBench paper on Accurate Retrieval, Conflict Resolution, and
Long-Range Understanding — with lower confidence bounds clearing the paper's
best per-competency averages — and matches the best reported Test-Time
Learning. This is evidence of strong memory behavior on those slices, NOT a
claim of state-of-the-art or official-benchmark superiority: coverage is
partial (recsys and most summarization absent, giant sources at one instance),
the base model is stronger than most field rows, and the comparison target is
the methods in the benchmark paper (2025) — not newer 2026 systems that report
full-benchmark figures (e.g. Infini Memory, arXiv:2606.10677, 64.7% overall),
which are NOT comparable to any partial aggregate of the numbers below.

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
| **CR 0.766** (49/64; sh 0.906, mh 0.625) | 64 | T1 | `reports/paper_replay/run.log` | paper-prompt replay over the 8 persisted CR agents (pre-JSONL run) |
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
- **CR:** first 8 of 100 questions per instance (all 8 instances covered).
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
