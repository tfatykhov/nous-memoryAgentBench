# Prod Deployment Plan: nous #559 → #567 (F084/F085/F086 + Gate-1 fixes)

**For:** nous prod instance (192.168.1.141, `nous-default` agent)
**From:** MAB evaluation program, 2026-07-21
**Current prod:** #559. **Target:** `30bd24b` (#567).
**Validated results behind this plan:** CR 0.725 → **0.812** (rounds=2 keyed leg, p=0.00076),
ICL exemplar-mode arm — see §6 (result pending at time of drafting; gate 0.80 vs 0.75 bar).

## What lands (7 commits)

| PR | What | Default behavior change on deploy? |
|---|---|---|
| #561 F084 | Enumerative extraction + store-time supersession (land-dark) | No (flags dark) |
| #562 | Backfill liveness fix (script-only) | No |
| #563 F085 | Entity-key index + canonical normalizer + keyed leg (land-dark) | No (flags dark); migration 065 |
| #564 | **Correctness: CONTRADICTION by statement order + same-slot dedup routing** | **YES — `same_slot_conflict_routing_enabled` defaults ON (intended: it stops the classifier destroying user corrections and dedup swallowing stated updates)** |
| #565 | Backfill histogram fix (script-only) | No |
| #566 R3v2 | Iterative keyed round (land-dark, rounds=1 byte-identical) | No |
| #567 F086 | Exemplar mode write+read (land-dark) | No; migration 066 |

Migrations 064/065/066 are additive (new columns/tables/indexes, `IF NOT EXISTS`) and
apply on server boot. **Field lesson (hit us on the eval clone): scripts do NOT apply
migrations — if you ever run a backfill against a DB no post-deploy server has booted
on, it fails on missing columns (or worse, no-ops). Boot/restart first, verify schema
(step 2), then backfill.**

## Step 0 — Preflight

1. `pg_dump` full backup of the prod DB. Record the dump path + size.
2. Note current `.env` (diff later): the flags this plan flips are absent today, so
   the effective values are code defaults.
3. Maintenance window: none strictly required (deploy is flag-dark except #564's
   correctness fix), but schedule the backfills (steps 3–4) for a quiet period —
   they generate embedding traffic and classifier calls.

## Step 1 — Deploy + restart

```
git fetch && git checkout 30bd24b        # or main if pinned == 30bd24b
uv sync                                   # nous venv uses uv, NOT pip
# restart the nous service/container as usual
```

## Step 2 — Verify schema + dark flags

```sql
-- all three must return a row:
SELECT 1 FROM information_schema.columns WHERE table_schema='heart' AND table_name='facts' AND column_name='entity_keys_extracted_at';
SELECT 1 FROM information_schema.tables  WHERE table_schema='heart' AND table_name='fact_entity_keys';
SELECT 1 FROM pg_indexes WHERE schemaname='heart' AND indexname LIKE '%exemplar%';
```
Confirm in logs: no migration errors; normal traffic unchanged (all new legs dark).
#564's routing fix is live at this point — new same-slot updates now resolve by
statement order instead of being swallowed/mis-adjudicated. That is the intended
correctness behavior; no action needed.

## Step 3 — Backfill: supersession repair (fixes historical wrong winners)

Re-resolves existing same-key conflict chains under the statement-order policy.
Chains whose update-variant was dedup-swallowed pre-#564 cannot be recovered (the
variant was never stored) — they heal forward as users restate facts.

```
cd /path/to/nous && export PYTHONPATH=$PWD
.venv/bin/python scripts/backfill_supersession.py --agent-id nous-default --dry-run
# review pair counts, then:
.venv/bin/python scripts/backfill_supersession.py --agent-id nous-default --classifier-budget 0
```
- **Record the printed `ROLLBACK KEY (updated_at watermark)`.**
- Cost: ~1 Haiku call per conflict pair (dry-run gives the count).
- Rollback: the SQL in the script docstring (agent- and watermark-scoped).

## Step 4 — Backfill: entity keys (REQUIRED before the keyed leg)

```
.venv/bin/python scripts/backfill_r3_entity_keys.py --agent-id nous-default --dry-run
.venv/bin/python scripts/backfill_r3_entity_keys.py --agent-id nous-default --phase all
```
- Phases: normalize (idempotent) → seed (no LLM) → extract (value-side keys,
  batch LLM ~40 facts/call, DB-clock watermark, resumable).
- **Record the rollback key** (`--phase rollback --watermark <key>` is supported).
- Verify: `SELECT count(*) FROM heart.fact_entity_keys WHERE agent_id='nous-default';`
  ≈ 1.5–2× active fact count.
- Cost: extract phase ≈ (facts lacking value keys)/40 Sonnet-class calls.

## Step 5 — Optional backfills (dry-run first; run only if counts warrant)

- `backfill_enumerative_facts.py --agent-id nous-default --dry-run` — conversational
  episodes rarely clear the density threshold; expect ~0 qualifying. Only relevant
  if prod has ingested dense reference documents. If run live, keep the DEFAULT
  caps (the uncapped mode is an offline-clone setting).
- `backfill_exemplar_facts.py --agent-id nous-default --dry-run` — only relevant if
  prod has stored `utterance\nlabel: N`-shaped training streams; expect 0 episodes
  classified otherwise. **Footguns (both hit us in the field):** the default
  `exemplar_max_per_episode=5000` truncates larger streams (raise via
  `NOUS_EXEMPLAR_MAX_PER_EPISODE`, e.g. 20000 — and note `0` means "truncate to
  nothing" in this helper, NOT unlimited); and a live run silently writes 0 rows
  if the schema is pre-066 (step 2 prevents this).

## Step 6 — Flip the validated flags (.env) + restart

```
# The 0.812-validated stack (CR +8.7pp, question-level significant):
NOUS_KEYED_FACT_LEG_ENABLED=true
NOUS_KEYED_FACT_LEG_ROUNDS=2
# leave NOUS_KEYED_FACT_LEG_K / _K2 / _SCORE / fan-out guards at defaults (8/8/0.55/32/256)

# Recommended, gated on your regression suite (write-time resolution;
# eval-validated via the backfill path, live-write path covered by #564 tests):
NOUS_SUPERSESSION_KEY_RESOLUTION_ENABLED=true

# Only if step-5 exemplar dry-run found real exemplar data AND the eval replay
# confirmed the arm (see §6):
# NOUS_EXEMPLAR_MODE_ENABLED=true

# Confirm these remain OFF / absent (validated negative or superseded):
# spreading activation OFF; retrieval-time cross-encoder OFF;
# F084 injection flags (pin/format/lineage/backstop) absent/dark;
# NOUS_EXTRACTION_ENUMERATIVE_ENABLED absent/dark for conversational workloads.
```

## Step 7 — Post-deploy verification

1. In-process smoke (no traffic needed):
   `Settings().keyed_fact_leg_enabled/rounds` resolve correctly;
   `FactManager.entity_key_vocabulary()` non-empty;
   `fetch_by_entity_keys(['<known entity>'])` returns that entity's facts.
2. Watch the keyed_r2 telemetry log line on real queries (`n_keyed`, `n_keyed_r2`,
   `keyed_r2_truncated`). If `keyed_r2_truncated` fires often, the fan-out guards
   are binding — report it; do not raise the caps ad hoc.
3. Latency: the keyed legs are two indexed fetches; budget <20ms each. If recall
   latency regresses more than that, investigate before leaving flags on.
4. A few known-entity recall spot checks ("what did I say about X") — the
   later-stated value must win where you've corrected something historically.

## Rollback plan (fastest first)

1. **Flags off** (`NOUS_KEYED_FACT_LEG_ENABLED=false` etc.) + restart — read path
   reverts instantly; backfilled data is inert without the flags.
2. **Backfill rollbacks** — each run's recorded key/manifest:
   supersession (docstring SQL, watermark-scoped), entity keys (`--phase rollback`),
   exemplars (`--phase rollback --manifest <file>`, exact-id manifest preferred).
3. **Code rollback** to #559 — migrations are additive; leaving the new columns/
   tables in place is safe. Note #564's correctness change reverts too (updates
   resume being swallowed) — treat code rollback as last resort.

## Order matters (from eval-field experience)

- Restart (migrations) BEFORE any backfill — scripts don't migrate, and at least
  one (exemplar) fails soft when schema is missing.
- Supersession backfill BEFORE enabling write-time resolution — the store should
  be consistent under the new policy before live writes extend the chains.
- Entity-key backfill BEFORE flipping the keyed leg — the leg silently no-ops on
  an empty vocabulary (it will "work" and retrieve nothing).
- Flags LAST, verification immediately after.

## §6 F086 exemplar mode — prod verdict (finalized 2026-07-21)

Decisive ICL n=200 replay: **0.695 vs corrected 0.555 baseline (+52/−24 paired,
p=0.0018)** — the largest single-competency gain of the program, though below the
0.80 gate. Decomposition: when the agent's answer followed the injected exemplar
majority it scored 0.83 (= the gate); when it overrode (64/200 cases) it scored
0.41 while the ignored majority was ~73% right. The mode retrieves correctly; the
reader over-trusts itself. nous-side v1.1 lever: strengthen the exemplar block
framing ("nearest labeled examples; prefer their majority label unless clearly
inapplicable") — note this is the OPPOSITE of the F083 episodic-injection lesson,
and that is fine: labeled exemplars are evidence-dense in a way episodes are not.

**Prod verdict: enable `NOUS_EXEMPLAR_MODE_ENABLED=true` only where the step-5
dry-run finds real exemplar data** (measured +14pp on such data even with the v1
framing). For a conversational prod agent with no exemplar streams: leave both
F086 flags dark — the mode triggers on exemplar presence, so this is moot until
such data exists. The write-path flag (`NOUS_EXEMPLAR_EXTRACTION_ENABLED`) may be
enabled at ingest time if labeled-example workloads are expected; it is zero-LLM.
