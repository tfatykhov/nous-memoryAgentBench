# Requirements R3: Keyed Fact Selection (Bidirectional Indexing + Normalization + Keyed Leg)

**For:** nous memory team
**From:** MAB evaluation program, 2026-07-17
**Supersedes/extends:** `docs/nous-write-path-requirements.md` (R1/R2, shipped as F084/#561)

## Why R3 exists — the measured chain

1. R1/R2 fixed **existence** (gold-bearing facts 1% → ~90% of questions) but the decisive
   arm measured **−5.0pp** (0.675 vs 0.725): the enumerated facts are not *selectable* —
   embedding search cannot discriminate ~46k near-identical statements, and the failed
   candidates displace the chunk channel that carried answers (`BASELINE_SUMMARY.md`,
   write-path validation section).
2. The obvious fix — exact lookup on R1's `subject_key` — was **simulated at zero cost
   and failed**: gold retrieval 0.20–0.23 vs embedding's 0.50 (`probe_keyed_lookup_sim`).
3. The miss diagnosis showed the *lookup design is fine; the index is deficient*:
   - **Single-sided keying.** Facts are keyed by the sentence's grammatical subject;
     questions ask by the other participant. "Who is the author of The Marriage of
     Figaro?" → the gold fact is keyed `thomas_kyd` (the answer — which the asker by
     definition doesn't know). Retrieval by "figaro" finds the right bucket but not the
     gold fact.
   - **Inconsistent normalization** in one store: `thomas_kyd` vs `the marriage of figaro`
     (underscores vs spaces), article/casing variance.
   - Noisy keys on a minority of facts (keyed under co-mentioned entities).

R3 = fix the index, then (and only then) add the keyed retrieval leg.

---

## R3.1 Bidirectional entity indexing (write path)

- Every enumerative fact gets an **entity key set**, not a single subject key: all
  participating entities (subject AND object/value entities), each a retrieval key.
  Schema options (nous team's choice): a `fact_entity_keys(fact_id, entity_key)` join
  table (preferred — indexable, n-ary), or an array column with a GIN index.
- The extractor emits entities per statement at extraction time (it already parses both
  sides to build `content`); no second LLM pass required.
- `attribute_key` stays as-is (it is consistent and useful for R2 conflict lookup).
- Value-side keys: index proper-noun/entity values ("thomas kyd", "belgium"); do NOT key
  scalar/common-noun values ("red", "1876") — configurable stop-policy, since keying
  scalars would create giant junk buckets.

## R3.2 Key normalization (single canonical form, enforced at write)

- One canonicalizer used by BOTH the writer and the reader: lowercase; single spaces (no
  underscores); strip leading articles (a/an/the); strip punctuation except intra-word
  hyphens; NFC unicode. Property test: `normalize(normalize(x)) == normalize(x)`.
- Applies to `subject_key`, `attribute_key`, and all R3.1 entity keys.
- Migration/backfill normalizes existing F084 keys in place (idempotent, watermarked,
  per-agent, dry-run counts — the established backfill conventions, PLUS the two
  hardening items from the R1 field experience: **chunk/statement-level resume watermark**
  and **batch-mode extraction** if any re-extraction is needed).

## R3.3 Keyed retrieval leg (read path, land-dark)

- Flag: `NOUS_KEYED_FACT_LEG_ENABLED` (default false).
- On question turns: extract candidate entity strings from the incoming message
  (heuristic NER-lite is acceptable v1: capitalized spans + quoted spans + known-key
  matching against the agent's key vocabulary), normalize, fetch active facts by exact
  key from the entity-key index, and merge into the candidate pool with a
  **bounded allotment** (e.g. top-K keyed facts by recency/ordinal, K≈8) so keyed results
  cannot displace the chunk channel (the −5.0pp lesson).
- Keyed hits carry provenance (`retrieval_leg='keyed'`) for telemetry and eval attribution.
- Multi-hop note (v1 boundary): one keyed round only. Iterative keyed lookup (feed
  round-1 fact entities back as round-2 keys) is v2, pending v1 measurement — the
  simulation shows round-2 adds little until round-1 quality is fixed.

## Acceptance gates (in order; 1–2 are free)

1. **Ceiling simulation (zero LLM, zero nous-runtime):** re-run
   `scripts/probe_keyed_lookup_sim.py` (adapted to the entity-key index) on the re-keyed
   `nous_mab_wp` clone. **Gate: single-hop gold retrieval ≥ 0.80** (vs 0.41 today) with
   median candidate set ≤ ~10 facts. If the gate fails, iterate keying — build no
   retrieval code.
2. **Displacement check (free):** injected-candidate composition on a probe sample must
   show chunk-channel content NOT reduced when the keyed leg contributes (the bounded
   allotment requirement working).
3. **Decisive replay (≈7M tokens, only after 1–2 pass):** CR n=320 on the re-keyed clone,
   flag on vs published 0.725. Prediction to beat: the 0.713–0.725 noise band; the
   existence+selection thesis predicts single-hop → ~0.95.
4. Regression replays (AR eventqa slice, detective) — the keyed leg must not perturb
   non-CR retrieval.

## Non-goals (v1)

Iterative multi-hop keyed lookup; LLM-based entity linking in the read path; scalar-value
keys; chunk-store changes; prod enablement before gates 1–4.
