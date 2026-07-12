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
| AR avg (SH-QA/MH-QA/LME/Event) | **84.0** (91.0/81.0/71.7/92.5) | 81.2 | **statistical peer** (+2.8, inside backbone noise) |
| — LME alone (n=60, full set of 1 of 5 ctx) | 71.7 | **79.3** | nominally behind (-7.6); comparability unconfirmed — Infini labels LME a "reconstructed multi-session variant" (matches MAB's own longmemeval_s* naming, question-set identity unverified) |
| FC-SH / FC-MH (conflict) | **89.4 / 56.2** (n=160 each) | 81.0 / 35.0 | FC-MH decidable win; FC-SH backbone-undecidable |
| DetQA (long-range) | **85.3** (n=68) | 77.2 | above (backbone-undecidable) |
| Summ | 59.2 (n=1) | 59.9 | par |
| ICL (test-time learning) | 62.5 (n=200) | **84.0** | **behind (decidable loss)** |

**Verdict (2026-07-06, full coverage of every ingested context):** nous and the
2026 leader are statistical peers overall — one decidable win (FC-MH +21.2pp,
n=160, tri-protocol robust), one decidable loss (ICL -21.5pp, n=200), LME
nominally behind (-7.6pp, comparability unconfirmed), all else within the
~9.7pp backbone band. One dose-response architectural finding: FC-MH degrades
monotonically with context SIZE (length is the x-axis, n=40/point). The
MH-Doc QA and LME revisions were SAMPLING corrections (x-axis was n, on
fixed-length contexts) — not scale effects; reported as such per prod-nous
review #3 (consult 2026-07-06).

Under the official strict graders the same numbers are: AR macro 79.3
(SH-QA 87.0 / MH-QA 71.0 / LME 70.0 / Event 89.3; micro 475/568 = 0.836,
CI [0.806, 0.867]), FC-SH 88.7, FC-MH 56.2, DetQA 82.4, ICL 55.5
(judge-vs-strict delta +0-13pp on verbose-answer tasks, ~0 on short-entity
tasks). Full-coverage correction (2026-07-06): LME 0.875(n=8)->0.700(n=60),
MH-Doc QA 0.750->0.710(n=100), eventqa_131072 0.750->0.860(n=100) UP,
SH-Doc QA held 0.870(n=100) — every thin cell moved when fully sampled. CR total re-priced 0.766
(n=64) -> **0.725** (n=320, CI [0.676, 0.774]) by replaying ALL 40 Q/instance
against the same persisted memory; multi-hop degrades with context size
(0.825/0.600/0.525/0.300 at 6k/32k/64k/262k).

**Backbone-adjusted claims** (per prod-nous review, decision e65cd66b; yardstick =
MAB's own observed backbone swing ~9.7pp): FC-MH margin **+21.2pp -> decidable
win**; AR +2.8pp -> **statistical peer**; FC-SH +8.4pp and DetQA +8.1pp ->
**directionally ahead but backbone-undecidable** (not claimed as architecture
wins); ICL -21.5pp behind (decidable loss). AR "avg" is macro (matches
Infini's method); micro AR = 0.836 official / 0.880 judge.

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
| AR/LRU/TTL gpt-5-judge regrades | 500 | T2* | `reports/judge_regrade/judge_results_*.jsonl` | DetQA 85.3, ICL 62.5 current; the n=8-era AR cells in these files (MH-QA 87.5, LME 100.0, Event 92.1) are SUPERSEDED by the `*_replay_full` rows below |
| **AR 0.836** (475/568, CI [0.806,0.867]) | 568 | T1 | consolidated from the files below | full question coverage of every ingested context (2026-07-06); supersedes AR 0.897 (n=232) |
| — eventqa_65536 0.910 | 200 | T1 | `reports/paper_baseline/results_accurate_retrieval_eventqa_65536.jsonl` | 5 contexts x 40 Q |
| — eventqa_131072 0.860 | 100 | T1 | `.../results_eventqa_131072_replay_full.jsonl` | supersedes 0.750 (n=8) |
| — eventqa_full 0.875 | 8 | T1 | `.../results_accurate_retrieval_eventqa_full.jsonl` | 2.31M chars |
| — MH-Doc QA (ruler_qa2) 0.710 | 100 | T1 | `.../results_ruler_qa2_421K_replay_full.jsonl` | supersedes 0.750 (n=8) |
| — longmemeval_s* 0.700 | 60 | T1 | `.../results_longmemeval_s__replay_full.jsonl` | full set incl. 2 abstention questions (1/2 correct); supersedes 0.875 (n=8) |
| — SH-Doc QA (ruler_qa1) 0.870 | 100 | T1 | `.../results_ruler_qa1_197K_replay_full.jsonl` | supersedes 0.875 (n=8, log-only) |
| **TTL 0.555** (111/200) | 200 | **T2** | `.../results_test_time_learning_icl_*.jsonl` | grader parses `label:` then exact-matches (stricter than the paper's ambiguous icl scoring — conservative). File holds 240 raw rows: dedup on (source, qa_pair_id/prompt) keeping last = 111/200 (40 dup rows — 5 sources x 8 early-run rows — from a fixed append bug) |
| **LRU detective 0.824** (56/68) | 68 | T1 | `.../results_long_range_understanding_detective_qa.jsonl` | all 10 contexts, 0 errors |
| **infbench_sum f1 0.592** | 1 | T1 | `.../results_long_range_understanding_infbench_sum_e.jsonl` | single book — indicative only |
| memory-lift, attribution splits | — | **T3** | root-cause docs under `docs/reviews/` | diagnostic instrumentation; never MAB-comparable |

## Official MAB components NOT covered

Do not read any per-competency number as full-benchmark coverage:

- **TTL:** `recsys` sub-dataset excluded — its grader requires `entity2id.json`,
  which is not shipped in the MAB public repo. TTL = icl family only.
- **AR:** every INGESTED context now at full question coverage (SH/MH-Doc QA
  100 each, LME 60 incl. abstentions, eventqa_131072 100). Still 1 context of
  5 for eventqa_131072/full and longmemeval (context diversity is
  ingest-bound); eventqa_65536 at 200 of 500; eventqa_full at 8 of 100 on its
  ingested context.
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

## Spreading-activation A/B (2026-07-12, nous @ c648008)

nous #555 (SA content fixes) + #556 (heart-fact seeds default) postdate the
baseline. SA is auto-gated at graph density > 3.0; eval agents sit at <= 2.7,
so SA never fired in any published run -> published numbers unaffected. Forced
ON (`configs/prod_memory_spreading_on.env`) and replayed CR n=320 against the
restored baseline memory (`nous_mab_baseline`, from the 2026-07-06 dump — the
live nous_mab was wiped by a nous-side A/B; the backup was the only copy):
**0.703 vs 0.725 baseline (-2.2pp; paired 32 gains / 39 regressions, sign-test
p~0.48 = statistical no-op)**. Multi-hop flat (+1/160) — spreading does NOT
rescue FC-MH, pointing the multi-hop bottleneck at edge FORMATION or reasoning,
not traversal. Single-hop mildly hurt (-8/160, noise injection). Evidence:
`results_conflict_resolution_replay_n320_spreadON.jsonl`.
