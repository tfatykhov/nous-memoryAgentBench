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

## F053-remediation A/B (2026-07-12, nous @ 3a381b2)

nous #557: the F053 sleep-prune had ERASED the episode graph layer (closed
episodes treated as dead) — 0 anchor edges in all eval agents, bug active
during every baseline build. Remediated a CLONE (nous_mab_f053) with the
official backfill (7,987 anchors restored + 324 densified related_to), then
replayed CR n=320 with spreading FORCED ON. 2x2 result (identical questions):
baseline (broken graph, SA off) **0.725** > SA-only 0.703 > f053+SA **0.684**
(FC-SH 0.863, FC-MH 0.506). **Monotonic: every graph-amplification step hurts
CR.** Conclusions: (1) published numbers stand — best arm; (2) FC-MH is NOT
connectivity-limited — restoring the hypothesized-missing edges made it worse
(hub explosion: episode anchors activate wrong-serial sibling facts); the
lever is supersession-aware retrieval/reasoning; (3) keep SA gated off for
dense-fact QA even post-F053 (replicates the backfill script's own prod
warning at n=320). Evidence: `results_conflict_resolution_replay_n320_f053_spreadON.jsonl`.

## #558 retest (2026-07-12, nous @ b3c97eb, design-reviewed pre-launch)

Two arms, replay-only, review-fixed before launch (session-timeout via
MAB_SESSION_TIMEOUT_BACKSTOP — the config-file NOUS_ knob is reserved+overwritten;
ANALYZE after pg_restore; meta config_file fix). ARM1 (current nous, prod path,
SA off, pristine memory): **0.716 vs published 0.725 — no regression**; published
numbers describe current nous (compound #555-558 check, not single-PR). ARM2
(new SA stack on repaired graph): **0.691 vs old SA stack 0.684 (+0.7pp, noise)**
— #558's SUM->MAX does NOT measurably cure the graph-amplification penalty.
5-arm story: SA-off best (0.72); every SA-on variant clusters 0.68-0.70.

**Variance finding (changes how we read cell-level A/Bs):** ARM1's mh_6k "-8"
investigated: answers were parametric fallbacks (real-world facts instead of
stored counterfactuals), but **9/12 recovered on single re-ask** — pre-turn
injection missed the counterfactual fact and the agent stochastically skips
agentic recall. Per-instance deltas of +-3-8 are run variance; only ~n=320
aggregates are interpretable. Actionable nous lever: supersession-aware
pre-turn injection reliability (not graph scoring). Evidence:
results_*_558regress.jsonl, results_*_f053_spreadON_558.jsonl, probe_6k_lost.log.

## #559 injection-fix A/B + 4th cell (2026-07-13, nous @ d624bb3)

Full matrix closed (all n=320, same questions, same preserved memory):
non-SA arms cluster **0.713-0.725** — published 0.725, replicate 0.716,
anchors-only (4th cell) 0.713, anchors+#559-flags (current-prod approx) 0.713;
flags-on-erased-graph 0.675 (lone outlier, most plausibly variance since
anchors were proven null and D=C exactly). **#559 stack = null on CR**: the
pin guarantees top-K of a search already ranking wrong-serial facts (the
failures were never top-K — that's why injection missed); the backstop never
fires (injection is non-empty-but-wrong, not empty); lineage data-starved
(19 superseded_by rows). Probes' 9/12 recovery came from AGENTIC recall
(multi-step query reformulation) which the pin can't replicate. NOUS LEVERS:
threshold-based backstop (weak/ambiguous top-hit, not empty), agentic-style
query reformulation in pre-turn retrieval, supersession backfill for lineage
density. Current prod state scores ~= published; flags safe to keep land-dark.
Evidence: results_*_559on.jsonl, results_*_f053_flagsoff.jsonl,
results_*_f053_559on.jsonl.

## Read-path program CLOSED (2026-07-13): six levers, convergent null

Probes: query dilution REFUTED (bare vs full query ~equal); facts store holds
1% of CR golds (extraction coverage = root cause); gold lives in chunks
(top-30 hit 78%, top-5 45%). Levers measured end-to-end (CR n=320, same
memory): budget 13k->33k **0.716 null**; CE rerank ON **0.681 null/neg** —
despite an offline-verified +41 gold@top-5 ceiling (probe_ce_sim) — because
CE ranks by relevance and wrong-serial siblings are equally relevant; #559
pin/lineage/backstop 0.675; anchors 0.713; spreading 0.68-0.70. Combined with
23/88 failures already having gold in vector top-5: **gold-in-context is not
the binding constraint — answer-time adjudication of near-duplicate variants
is.** VERDICT: read path saturated; prod right to keep CE off at retrieval;
the fix is WRITE-PATH adjudication (enumerative extraction + supersession
resolution at store time -> context carries ONE current fact). Evidence:
probe_query_dilution.*, probe_ce_sim.*, results_*_budget33k/_ceON.jsonl.

## Forced-recall arm + program close (2026-07-13)

Prompt-forced recall_deep verification (stand-in for a server-side pre-turn
call): **0.738 vs 0.725 (+1.3pp; sh identical 142/142, mh +4)** — the only arm
above baseline, but marginal. METHOD CORRECTION: the earlier "9/12 recoverable"
estimate was regression-to-the-mean (re-asking only LOST questions samples a
stochastic flip one-sidedly); the true deterministic-recall effect is the net
+1-4 questions. VERDICT: behavior path saturated too; pre-turn recall_deep not
worth building for accuracy. **Eight arms measured; write-path adjudication
(enumerative extraction + store-time supersession) is the sole remaining lever
with headroom.** Evidence: results_*_forcedrecall.jsonl.

## Write-path validation (2026-07-14..17, nous F084/#561) — audited negative

R1 enumerative backfill: facts store 1% -> ~90% gold existence (46k facts;
liveness bug found in the backfill and fixed upstream as #562; default caps
truncate dense docs — clone remediation needs caps=0; 32k pair gap caught by
independent audit, fixed, re-tested). R2 supersession: ~4.5k resolutions, 0
budget stops, losers deactivated. Post-R2 probe: fact findability@top15
UNCHANGED at 0.50 (crowding is cross-entity, not chain-mates). **DECISIVE ARM
(audited, coverage-fixed): 0.675 vs 0.725 (-5.0pp; paired +28/-45).**
Mechanism probed both ways: enumerated fact injected -> correct; facts
displacing gold-bearing chunks (65% carrier) with a 50%-findable channel ->
net harm. **Write path fixed EXISTENCE, not SELECTION** — embedding search
cannot discriminate 46k near-identical facts. Completing piece: KEYED LOOKUP
retrieval leg over subject_key/attribute_key (R1 created the keys; a free
offline simulation of its ceiling is the queued next step). Forecast records:
predicted median 0.78/0.75 — actual 0.675; the dilution tail (5-10%) was the
outcome. Caveat: per-instance mh/sh attribution label-confounded across runs;
aggregate-only causal reads. Evidence: results_*_writepath*.jsonl,
backfill_*.log, probe_coverage_gate/post_r2.log.

## Keyed-lookup ceiling simulation (2026-07-17, zero LLM) — negative, with diagnosis

Naive exact-key retrieval over R1's subject_key: gold retrieval 0.20-0.23 total
(sh 0.41 round-1; mh 0.00, +iterative 0.04) — WORSE than embedding findability
(0.50@15) and far below the chunk channel (0.65). Diagnosis (miss sampling):
key MATCHING works; the INDEX is deficient — (a) single-sided keying: facts
keyed by grammatical subject, questions ask by the other entity ("author of
Figaro" -> fact keyed 'thomas_kyd', the unknown); (b) inconsistent
normalization (underscores vs spaces in the same store); (c) noisy keys.
R3 REVISION for nous: bidirectional entity indexing + single normalization at
write time, THEN a keyed leg — ceiling re-simulatable for free post-re-keying.
Third consecutive proposed fix evaluated by zero-token simulation before build
(distillation killed, naive keys killed, CE caught). Evidence:
scripts/probe_keyed_lookup_sim.py output in this section.

## F085 (R3) GATE 1 — failed for upstream reasons; two nous bugs isolated (2026-07-17)

nous #563 shipped R3 faithfully (bidirectional entity keys, canonical
normalizer, land-dark bounded keyed leg). Migration 065 + R3 backfill on the
WP clone: 75,611 entity-key rows, 0 warnings, batch-mode extraction (~40
facts/call — the R1 cost lesson fixed). **GATE 1 (free sim): sh keyed gold
0.48 vs the >=0.80 bar — FAILED, but not by the index.** Decomposition:
1. **R2 conflict-classifier PARAMETRIC BIAS (21/160 sh golds deactivated):**
   restoring inactive facts lifts sh 0.48->0.61. R2 kept "author of Figaro =
   Beaumarchais" (world-true) and superseded "= Thomas Kyd" (the stated
   update/gold) — the classifier adjudicates by plausibility, reproducing the
   exact failure mode the benchmark tests. FIX: UPDATE conflicts resolve by
   ordinal/recency ONLY; any classifier involvement must ask "which was
   stated later", never "which is true".
2. **True answer-fact existence ~0.61 sh, not ~90% (measurement correction):**
   earlier existence figures counted INCIDENTAL gold-string mentions. ~39% of
   sh answer statements are absent from the fact store despite being verbatim
   in transcripts — prime suspect: R1 cosine dedup dropping update-variants
   (value-entity-only diffs embed near-identically). Needs nous dedup audit.
The keyed index retrieves what exists+active faithfully. Pipeline: fix
classifier bias -> dedup audit -> re-backfill -> free sim -> gate. mh keyed
ceiling remains ~0 (composition, separate problem). No replay spend.

## #564 repair + keyed-leg decisive arm — 0.759, first arm above the noise band (2026-07-19)

nous 7cbc10a (#564) implemented the Gate-1 fix spec exactly: D1 CONTRADICTION
resolves by statement order (classifier advisory-only; same-episode ordinal ->
learned_at -> KEEP-BOTH), D2 same-slot value-variants route past dedup into
conflict resolution (flag default ON). Repair on nous_mab_wp (order corrected:
rollback FIRST — 4,435 wrongly-superseded facts reactivated via docstring SQL,
watermark 2026-07-16T03:21:11Z — then per-agent R1 re-run caps=0, R2 re-run,
R3 all; scripts/run_repair_564_detached.cmd; one nous bug found+patched
mid-flight: #564's chain-depth histogram passed the watermark as str to
asyncpg — report-only, after commit; upstream-worthy).

**Free gates after repair (scripts/probe_keyed_entity_sim.py):**
- sh keyed gold retrieval **0.85** (136/160) vs 0.48 pre-fix — GATE PASSED
  (bar 0.80); answer-fact existence 0.61 -> ~0.97–1.00; candidates median
  1.5, p90 6 (inside the K=8 allotment — displacement-safe by construction).
- mh single-round keyed 0.02 (expected; composition). **Iterative round-2 sim
  on the repaired store: mh 0.02 -> 0.49** (pre-fix: round-2 added ~nothing)
  — first mechanical evidence the mh plateau is addressable (R3 v2).

**DECISIVE ARM (CR n=320, same memory/questions, minimal delta = baseline
config + NOUS_KEYED_FACT_LEG_ENABLED=true, flag verified live in-process
pre-launch; configs/prod_memory_keyedleg.env):**

    0.759 (243/320), CI [0.713, 0.806], 0 errored
    sh 0.900 (144/160, was 0.887) | mh 0.619 (99/160, was 0.562)
    cells: sh .850/.900/.925/.925 | mh .725/.625/.700/.425 (6k/32k/64k/262k)
    paired vs 0.725 baseline: +36/-25 (net +11), sign test p=0.20

Reads, honestly stated: 0.759 exceeds every one of the 12 prior arms
(0.675–0.738) — the first configuration above the historical arm
distribution, with a mechanically grounded cause. Question-level sign test is
not individually significant (p=0.20); the claim rests on the arm-distribution
comparison + the causal chain (store repaired -> gate passed -> arm improved).
FORECAST SCORECARD (pre-registered ~0.74, P(>0.725)=70%): direction and
magnitude right (0.759), composition WRONG — predicted sh-driven (+5-7 sh,
mh flat); actual mh-driven (mh +9 net, sh +2 net). Best explanation: the
agent's own agentic recall is already iterative, and the repaired store makes
its round-2 lookups land on correct active facts (consistent with the 0.49
iterative sim); sh was nearer ceiling than the rescue-candidate count implied.
mh 262k still degrades (.425) — scale x composition remains the frontier.

Recommendations shipped to nous: enable keyed leg (bounded K=8) once entity
keys are backfilled; R3 v2 = one bounded iterative keyed round (0.49 mh sim
ceiling); keep F084 injection flags land-dark (displacement lesson stands).
Note: AR regression gate is inert on this eval (no entity keys on AR agents ->
leg no-ops); prod enablement still needs nous-side regression per R3 spec.

## R3 v2 (rounds=2) decisive arm — 0.812, first question-level-significant gain (2026-07-19)

nous #566 shipped R3 v2 spec-faithfully (flags/defaults exact; ranking policy
carries a documented sim-parity contract; K2 selection at assembly with
cross-leg dedup; surfaced telemetry). #565 = our histogram fix upstreamed.
Acceptance gate 1 run against the IMPLEMENTATION's own functions (in-process,
zero LLM): mh keyed-composition coverage **0.42 @ K2=8** vs 0.35 bar — PASSED
(6k .57 / 32k .38 / 64k .53 / 262k .23; exact entity-row derivation beats the
design sim's content scanning). Gate 2 (band ordering/displacement) holds by
construction + #566's tests.

**DECISIVE ARM (CR n=320, sole delta vs the 0.759 arm = NOUS_KEYED_FACT_LEG_
ROUNDS=2; configs/prod_memory_keyedleg_r2.env):**

    0.812 (260/320), CI [0.770, 0.855], 0 errored
    sh 0.938 (150/160) | mh 0.688 (110/160)
    cells: sh .925/.925/.950/.950 | mh .900/.725/.650/.475 (6k/32k/64k/262k)
    paired vs rounds=1 (0.759): +39/-22 net +17, sign p=0.040
    paired vs baseline (0.725): +47/-19 net +28, sign p=0.00076

FIRST QUESTION-LEVEL-SIGNIFICANT improvement of the program (all prior claims
rested on arm-distribution reads). CI lower bound (0.770) clears the published
baseline, the 12-arm noise band, AND the rounds=1 point estimate. mh_6k 0.900
is the highest multi-hop cell ever recorded here; mh_262k improved least
(.425->.475) exactly as the 0.23 gate coverage predicted — scale x composition
remains the residual frontier. FORECAST SCORECARD (pre-registered 0.78+-0.02,
P(>=0.78)=40%): actual 0.812 ABOVE the band — underconfident, and the same
direction of miss as rounds=1: sh ALSO gained (+6 net, 0.900->0.938) though
the sim said round-2 adds ~nothing to sh retrieval. Twice-confirmed lesson:
retrieval-substrate improvements compound through the agent's whole iterative
loop; static coverage sims lower-bound the live effect.

Program position: CR 0.725 -> 0.812 (+8.7pp) across the write-path program,
now within 2.4pp of the 2026 leader's OVERALL benchmark average (0.836 —
different metric, their strongest cells included); on CR itself the field
best is 0.295 published / leader FC 0.580 (sh 0.81/mh 0.35): nous mh 0.688
nearly doubles the leader's conceded-weakness cell.

## ICL exemplar-mode program opens: sim 0.82 vs corrected live 0.555 (2026-07-19)

Free-gate program for the sole decidable 2026-field loss (ICL). Independent
review (fresh agent) audited the first-pass sim and CORRECTED two claims,
both now on the record: (1) live ICL baseline 0.571 was corrupted by 40
duplicated rows (n=8 smoke concatenated with n=200 run) -> deduped 0.555;
(2) lexical gold-in-top25 0.92 was an ORACLE metric (presence != identifiability;
lexical gold-plurality only 0.64) -> the claim as stated was refuted. Response
to review: measured the IMPLEMENTABLE rules. Lexical 1-NN 0.67 (paired vs live
+55/-32 p=0.018) = floor. EMBEDDING kNN at exemplar granularity
(text-embedding-3-large @1536): **1-NN 0.76, maj@5 0.82, strict-plurality@25
0.81, gold-in25 0.99; paired vs live +70/-17, p=8e-9** — a deterministic
zero-LLM rule at the 2026 leader's level (0.84). Root cause of the live 26pp
gap: retrieval GRANULARITY (chunks bury ~40 exemplars each; chunk search finds
a similar region, not the k nearest labeled examples). Storage validated
lossless (0.2-2%); leakage 7-8/200 (~4pp, reported). Requirements delivered:
docs/nous-icl-exemplar-mode-requirements.md (exemplar-granularity index +
land-dark bounded injection mode; gate 1 pre-green at bar 0.75; replay
prediction 0.75-0.85). Evidence: scripts/probe_icl_exemplar_knn.py,
scripts/probe_icl_exemplar_emb.py.

## F086 exemplar-mode decisive arm — ICL 0.695 vs 0.555 (2026-07-21)

nous #567 (F086) shipped spec-faithfully: parse-only exemplar extraction,
land-dark bounded read leg (top_k 25, cosine floor 0.30, 64-word query gate),
backfill with exact-id rollback manifest. Validation on clone **nous_mab_icl**
(nous_mab_baseline pristine): TWO field bugs found — clone lacked migrations
064-066 (backfill wrote 0 facts SILENTLY; scripts don't migrate; fixed by
applying 064/065/066 directly) and exemplar_max_per_episode=5000 truncates
banking77's 6,402 pairs (and 0 = truncate-to-NOTHING, not unlimited — inverted
vs the R1 cap convention; used 20000). Backfill: 31,607 exemplar facts / 5
agents / 0 skipped. GATE 1 vs the implementation's own fetch_exemplars_by_vector:
**maj@5 0.80 (bar 0.75) — PASSED** (gold-in-25 0.99).

**DECISIVE ARM (ICL n=200, answer-only replay driver scripts/replay_icl_n200.py,
sole delta NOUS_EXEMPLAR_MODE_ENABLED=true; configs/prod_memory_exemplar.env):**

    0.695 (139/200), CI [0.631, 0.759], 0 errored
    banking77 .575 / clinic150 .725 / nlu .675 / trec_coarse .875 / trec_fine .625
    paired vs corrected 0.555 baseline: +52/-24 (net 28), sign p=1.8e-3

Largest single-competency gain of the program (+14pp; the sole 2026-field loss
narrows from -28.5pp to -14.5pp vs leader 0.840) — but the FIRST arm to land
BELOW its gate (0.80). CONVERSION DECOMPOSITION (per-question join of live
answers vs injected maj@5): answer FOLLOWED injected majority 136/200 -> 0.83
accuracy (= the gate); answer OVERRODE 64/200 -> 0.41, while the ignored
majority was ~73% right. Following-always ~= 0.80. THE LEAK IS READER OVERRIDE,
not retrieval. nous v1.1 lever: exemplar-block framing nudge (prefer the
majority label) — opposite of the F083 episodic lesson, appropriately (labeled
exemplars are evidence-dense). Harness-side confirmation available cheaply: a
prompt-arm replay with a follow-the-examples instruction. FORECAST SCORECARD
(0.75-0.85 predicted): MISS LOW for the first time — injection arms convert
BELOW static sims (reader discretion), the mirror image of substrate arms
converting ABOVE (loop compounding). Both lessons now on record.

## sh key-miss taxonomy + mh_262k triage — one root cause (2026-07-21)

**sh taxonomy (24 keyed misses, nous_mab_wp):** 20/24 = FACT-SIDE KEY COVERAGE
— the question matches vocabulary keys fine, but the gold fact is not keyed
under the asked entity (e.g. "Who founded Church of Scotland?" -> gold fact
keyed [john knox, edinburgh], no 'church of scotland'). Cap analysis: 0/20
cap-bound (all facts carry <8 keys) -> the entity_keys_max_per_fact=8 cap is
INNOCENT; R3.1's value-side extractor simply never emitted the asked entity.
Remaining: 3 punctuation-variant partials ("Burnley F.C." vs key "burnley fc"
— probe used raw regex; nous's normalizer likely already catches these), 1
paraphrase-class gold (catholic/catholicism). NOUS ACTION: extractor recall
pass (emit ALL named entities per statement), not cap tuning.

**mh_262k triage (40 q, per-question round-2 decomposition via #566's own
functions):** hit r1+r2 9/40 (=0.23 gate); **unreachable-in-2-keyed-hops
20/40 (the DOMINANT constraint)**; rank-miss (in 256-candidate pool, below
K2=8) 5/40; candidate-cap-miss (256 LIMIT excluded gold; key dilution at 16k
facts) 5/40; r1-empty 1/40. Fan-out guards account for only 10/40 — the wall
is 2-hop KEY COVERAGE, the same extractor-recall gap as sh COMPOUNDED across
hops (each hop needs the bridge entity keyed on the bridge fact). CONVERGENT
NOUS ACTION: the sh fix (value-side extractor recall) is also the mh_262k
fix, multiplicatively; secondary levers (rank features, per-key candidate
quotas) worth ~10/40 at most. Free re-sim after any extractor change.
