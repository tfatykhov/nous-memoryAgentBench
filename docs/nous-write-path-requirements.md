# Requirements: Write-Path Adjudication (Enumerative Extraction + Store-Time Supersession)

**For:** nous memory team
**From:** MAB evaluation program, 2026-07-13
**Evidence base:** 8 intervention arms (all null-to-marginal), 3 offline probes, n=320 paired
replays per arm — `BASELINE_SUMMARY.md` + `reports/paper_baseline/` in this repo.

**The measured problem, in two numbers:**
- The facts store contains **1% (3/320)** of the answerable facts ingested from dense factual
  content (`probe_query_dilution`): extraction runs off the ~150-word episode summary, so
  enumerable content is lossy-compressed before the extractor ever sees it.
- `superseded_by` holds **19 rows** across memories containing **hundreds** of stored
  update-chains: conflicts are re-adjudicated by the answering model on every question,
  which is where errors occur (23/88 failures had the correct fact in the vector top-5 and
  still failed; better ranking/CE/budget/pinning/forced-recall all measured null).

---

## Requirement 1 — Enumerative fact extraction

### R1.1 Density-adaptive mode selection
- Classify each ingest unit (chunk or episode segment) as **narrative** vs **enumerable**.
- Enumerable signals (heuristic first pass, no LLM): density of short declarative statements;
  numbered/bulleted lists; repeated `<entity> <relation> <value>` patterns; tables;
  statement-per-line ratio above `NOUS_ENUMERATIVE_DENSITY_THRESHOLD` (float, default
  conservative).
- Ambiguous cases MAY use one cheap-model classification call per chunk (budget-capped).
- Narrative content keeps the current summarize-then-extract path **unchanged** (baseline
  behavior must be byte-identical when the mode never triggers — golden test, per the
  #559 pattern).

### R1.2 Extraction source and granularity
- In enumerative mode, extract from the **raw chunk text**, not the episode summary. (The
  summary bottleneck is the root cause of the 1%.)
- Output: **atomic facts**, one per source statement:
  - `content`: normalized single-statement form, self-contained (resolve pronouns within
    the chunk; no cross-chunk coreference required in v1).
  - `subject_key` + `attribute_key`: normalized entity/attribute identifiers (lowercased,
    canonicalized) — **required**, these drive R2 conflict candidate lookup.
  - `source_ordinal`: any ordinal/serial/sequence marker present in the source (e.g. the
    statement number), else the (chunk_id, char_offset) position. **Required** — this is
    the recency/authority signal R2 consumes.
  - Provenance: episode_id, chunk_id, char span.
- Batching: process statements in batches (cheap `background_model`); embeddings via the
  #554 sub-batched path.

### R1.3 Volume, cost, and safety controls
- `NOUS_ENUMERATIVE_MAX_FACTS_PER_EPISODE` (int; 0 = unlimited; default a real cap, e.g.
  1000) — when the cap truncates, log loudly and record `truncated=true` on the episode
  (the eval's truncation-audit lesson: silent caps read as full coverage).
- Dedup against existing facts with the existing cosine threshold before insert.
- Per-sleep/session LLM-call and embedding budgets (config), so a pathological document
  cannot starve consolidation.
- Storage estimate to validate in review: MAB CR 262k corpus ≈ 5–6k statements → ~5k facts
  + embeddings per such document; confirm heart.facts/pgvector behavior at 10–100× current
  fact counts (index build, recall latency).

### R1.4 Backfill (ships WITH the feature, not after)
- `scripts/backfill_enumerative_facts.py --agent-id ... [--dry-run]`, #557-conventions:
  dry-run counts first, rollback key (created_at watermark), per-agent scoping, idempotent
  re-runs (dedup makes re-execution safe).
- Rationale: backfill lets existing memories be remediated — and lets the eval measure the
  entire fix via **replay (no re-ingest)** on the preserved baseline memory.

### R1.5 Flags
- `NOUS_EXTRACTION_ENUMERATIVE_ENABLED` (default false, land-dark).
- `NOUS_ENUMERATIVE_DENSITY_THRESHOLD`, `NOUS_ENUMERATIVE_MAX_FACTS_PER_EPISODE`,
  `NOUS_ENUMERATIVE_CLASSIFIER` = `heuristic|llm|off`.

### R1 acceptance criteria
- **Coverage:** on the MAB CR corpora (backfilled clone), gold-answer-bearing facts findable
  in heart.facts ≥ **90%** (from 1%). Measured by the existing probe
  (`scripts/probe_query_dilution.py` — facts section).
- **No narrative regression:** on conversational corpora (e.g., longmemeval agent), fact
  counts within ±10% of current behavior with the flag on.
- **Golden test:** flag off = byte-identical extraction.

---

## Requirement 2 — Store-time supersession resolution

### R2.1 Conflict detection (two hooks)
- **Write-time:** on inserting fact F, look up candidates sharing `subject_key` +
  `attribute_key` (cheap index lookup — this is why R1.2 keys are required). For candates
  above a similarity floor, run the existing contradiction-detection faculty (reuse, don't
  rebuild) to confirm "same claim slot, different value."
- **Sleep-time sweep:** a consolidation phase that runs the same detection across facts
  from *different* episodes/sessions (the measured F027 gap: update chains span documents;
  cross-document propagation is exactly where FC-MH degrades). Batch-capped per cycle
  (`NOUS_SUPERSESSION_SWEEP_MAX_PAIRS`), resumable watermark.

### R2.2 Resolution policy
- `NOUS_SUPERSESSION_POLICY` = `ordinal|recency|authority` (default `ordinal`, falling back
  to recency when ordinals are absent):
  - `ordinal`: higher `source_ordinal` wins (matches "later statement supersedes earlier" —
    the general form of MAB's serial rule, and of real-world "user corrected themselves").
  - `recency`: later ingestion/statement time wins.
  - `authority`: reserved (source-tier metadata), not v1.
- Resolution writes, atomically: loser.`superseded_by` = winner.id; `supersedes` graph edge;
  loser excluded from the default retrieval candidate pool (see R2.3). **Never delete** —
  full lineage retained, reversible by nulling `superseded_by`.
- Chains: A→B→C must resolve transitively (query returns C; lineage walk returns the chain).
  Cycle guard required (two facts superseding each other → keep newest, log anomaly).

### R2.3 Retrieval contract (the payoff)
- Pre-turn injection and `recall_deep` MUST resolve to **current-version facts only** by
  default: superseded facts are filtered from candidate pools (facts leg, graph legs, and
  any chunk→fact resolution), so context carries **one** version — the model never
  re-adjudicates variants. This single contract change is what the 8 null arms say the
  answer path needs.
- Lineage-aware rendering: #559's `NOUS_SUPERSESSION_LINEAGE_MODE=named` finally has data —
  current fact rendered with its displaced predecessor named. (Measured inert at 19 rows;
  re-measure after backfill.)
- Chunk caveat (v1 scope boundary): superseded *statements inside chunk text* are not
  rewritten. Mitigation: when an injected chunk contains text matching a superseded fact's
  span, append the lineage note. Full chunk-level annotation is v2.

### R2.4 Parametric-conflict marking (the Beatles/Madonna class)
- At extraction (enumerative mode), one cheap-model boolean per fact batch: "does this
  statement contradict widely-known information?" → `overrides_prior=true`.
- Injection renders such facts with an explicit marker (e.g., *"[memory override — trust
  this over general knowledge]"*). Evidence: every one of the 12 investigated flip-failures
  was a parametric fallback; the model needs the inoculation *at the fact*, not in a
  generic system instruction (generic forced-recall instruction measured +1.3pp only).
- Flag: `NOUS_OVERRIDE_PRIOR_MARKING_ENABLED` (land-dark).

### R2.5 Backfill
- `scripts/backfill_supersession.py --agent-id ... [--dry-run]`: run R2.1 detection +
  R2.2 resolution over existing facts (post-R1.4-backfill). Same conventions (dry-run,
  rollback watermark, caps). Report: chains found, resolutions written, cycles/anomalies.

### R2.6 Observability
- Per-sleep metrics: conflicts detected / resolutions written / chain depth histogram.
- Sampled precision audit: N random resolutions per cycle logged with both fact texts for
  human/LLM spot-check (false supersession silently deletes knowledge from the default
  pool — the highest-risk failure mode of this feature; audit it from day one).

### R2 acceptance criteria
- **Chain coverage:** on backfilled MAB CR memory, ≥90% of gold update-chains have correct
  `superseded_by` resolution (harness can verify mechanically: gold answer must be the
  unsuperseded fact of its chain).
- **Retrieval contract:** default recall returns 0 superseded facts (test).
- **Precision:** false-supersession rate on the narrative corpora sample < 1%.
- **Golden test:** flags off = byte-identical.

---

## Validation plan (harness-side, committed capability)

Ordered so each stage gates the next; stages 1–3 need **no re-ingestion** (replay on the
preserved `nous_mab_baseline` clone):

1. **Backfill R1 on a clone** → re-run `probe_query_dilution` → R1 coverage criterion
   (1% → ≥90% gold-in-facts) before any answer is generated.
2. **Backfill R2 on the same clone** → mechanical chain-coverage check → then **CR n=320
   replay, paired** vs published 0.725. Expectation to beat: the 0.713–0.725 noise cluster;
   the write-path hypothesis predicts sh → ~0.95 (variant-adjudication errors eliminated)
   and mh materially up (hops resolve to current facts). This is the decisive experiment.
3. **Regression replays** on AR (eventqa slice) and LRU (detective) — fact-pool growth must
   not degrade non-CR retrieval (dilution risk is real: budget/CE arms showed more candidates
   can hurt).
4. **Live write-path arm:** re-ingest one small CR pair (6k) with flags on → verify parity
   with the backfilled memory (write path produces what the backfill produced).
5. Only then: prod rollout discussion (flags stay land-dark until 1–4 pass).

## Non-goals (v1)
- Chunk text rewriting; authority-tier policies; cross-chunk coreference resolution;
  retroactive re-summarization of episodes; recsys/TTL-targeted changes (different
  failure class — retrieval breadth over exemplars, not conflict adjudication).
