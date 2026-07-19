# Requirements R3 v2: Bounded Iterative Keyed Retrieval (Multi-Hop Composition)

**For:** nous memory team
**From:** MAB evaluation program, 2026-07-19
**Extends:** `docs/nous-r3-keyed-selection-requirements.md` (R3.1–R3.3, shipped as F085/#563)
and the #564 store-semantics fixes. Deployment prerequisites: `docs/nous-prod-keyedleg-rollout.md`.

## Why R3 v2 exists — the measured chain

1. The v1 keyed leg + repaired store produced the program's first arm above the noise
   band: **CR n=320 = 0.759 vs 0.725** (`BASELINE_SUMMARY.md`, PR #28). The gain was
   **multi-hop-driven** (+9 net mh vs +2 sh) — evidence that composition over the
   repaired store works when retrieval is iterated, because the *agent's own* recall
   loop already iterates.
2. Multi-hop is now the largest headroom pool anywhere in the benchmark: **mh 0.619,
   ~54 unanswered questions**, and the residual sh headroom is key-matching, not
   retrieval design.
3. Zero-LLM simulation on the repaired store (`nous_mab_wp`, 8 agents): single-round
   keyed lookup reaches mh gold for **0.02**; feeding round-1 fact entities back as
   round-2 keys reaches **0.44** (71/160). Per cell: 6k 0.55 / 32k 0.35 / 64k 0.57 /
   262k 0.30. Pre-#564 this simulation showed round-2 adding ~nothing — the repaired
   store is what makes composition possible.
4. **The naive version does not ship.** Unbounded round-2 candidate sets explode with
   store size: p90 = 279 facts at mh_262k (587 at sh_262k). The design below is
   bounded, and the bounded version is simulated: a deterministic attribute-overlap
   rank keeps **0.39 @ K2=8 and 0.42 @ K2=16** of the 0.44 ceiling. Selection, not
   fetching, is the design core.
5. Round-2 is a **multi-hop feature only**: on sh the sim gains +1/160 (0.85→0.86).
   No sh regression path exists if the round-2 band sits below round-1 (see 2.4).

## R3v2.1 Mechanism (read path, land-dark)

Extend Stage 1.6 of `run_recall_pipeline` (the v1 keyed leg) with one additional round:

1. **Trigger:** rounds=2 configured AND round-1 returned ≥1 fact. No other gating —
   the round is cheap (one indexed DB fetch, zero LLM) and the band cap (2.4) makes
   it harmless when unneeded.
2. **Round-2 key set:** entity keys appearing in round-1 fact *contents* (matched
   against the agent's key vocabulary — the same `extract_entity_candidates` +
   vocabulary machinery as v1), MINUS round-1 keys. Prefer value-side keys of
   round-1 facts (the `fact_entity_keys` rows of the round-1 hits themselves) over
   free-text matching where available — it is exact and cheaper.
3. **Fan-out guard:** cap keys examined (suggest 32, config) and hard-cap fetched
   candidates before ranking (suggest 256) — the p90-587 lesson. Log a counter when
   the cap truncates (no silent truncation — R1.3 convention).
4. **Bounded selection — the core requirement.** Rank round-2 candidates
   deterministically, no LLM:
   - primary: attribute-key word overlap with the query;
   - secondary: content word overlap with the query;
   - tie-break: recency (`learned_at`).
   Take top **K2 (default 8, config)**. Merge into the candidate pool in a score
   band **below** the round-1 keyed band (round-1 keyed sits below the direct-hit
   head; round-2 sits below round-1). Id-dedup against all other legs as in v1.
5. **Provenance:** `retrieval_leg='keyed_r2'` on round-2 hits; extend the
   `PipelineOutcome` telemetry (`n_keyed_r2`, `keyed_r2_truncated`) — and this time
   surface the counters in a log line or metric (v1's internal-only telemetry made
   live verification needlessly hard; see rollout doc §3).

## R3v2.2 Flags

- `NOUS_KEYED_FACT_LEG_ROUNDS` — int, default `1` (land-dark; `2` enables this spec).
- `NOUS_KEYED_FACT_LEG_K2` — round-2 allotment, default `8`.
- `NOUS_KEYED_FACT_LEG_R2_MAX_KEYS` / `_R2_MAX_CANDIDATES` — fan-out guards
  (defaults 32 / 256).
- v1 flags unchanged; rounds=1 must be byte-identical to current v1 behavior
  (golden-defaults convention).

## Acceptance gates (in cost order; 1–2 are free)

1. **Bounded-policy simulation (zero LLM), already green on the eval clone:**
   mh gold coverage ≥ **0.35 @ K2=8** (measured 0.39) with the fan-out guards ON.
   Implementation must reproduce ≥ this bar on `nous_mab_wp` before any live code
   review completes — if the shipped ranking differs from the simulated one,
   re-simulate first, build second.
2. **Displacement check (free):** candidate-pool composition on a probe sample —
   chunk-channel content unchanged when round-2 contributes; round-2 never evicts
   round-1 or direct hits (band ordering working).
3. **Decisive replay (≈7M tokens):** CR n=320, rounds=2 vs the 0.759 rounds=1
   result on the same repaired clone. Prediction to beat: mh 0.619; the bounded sim
   ceiling implies mh headroom to ~0.70 if conversion tracks the sh precedent.
   Aggregate prediction ~0.78 ± 0.02.
4. **Non-CR regression:** nous-side retrieval suite rounds=1 vs rounds=2 (the eval's
   AR/LRU agents carry no entity keys; that gate remains nous-side, as in v1).

## Non-goals

- **>2 rounds.** The sim shows round-2 captures the available composition; deeper
  chains are unmeasured and multiply fan-out risk.
- **LLM-based entity linking or round selection.** Everything here is deterministic;
  keep it auditable and free.
- **The sh key-matching gap** (keyed 0.85 vs existence ~1.0 — 24 questions of
  normalizer/alias misses). Separate, cheaper workstream; the eval can supply the
  full miss taxonomy on request.
- **ICL/test-time-learning retrieval mode.** Shares this machinery (iterate, gather,
  bound) but is a different trigger and candidate type; propose after v2 measures.
