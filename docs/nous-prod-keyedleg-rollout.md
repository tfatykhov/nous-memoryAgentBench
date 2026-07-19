# Prod Rollout: #564 Store Semantics + Keyed Fact Leg — Recommended Settings & Backfill Runbook

**For:** nous memory team
**From:** MAB evaluation program, 2026-07-19
**Evidence:** CR n=320 decisive arm **0.759 vs 0.725 baseline** (sh 0.900, mh 0.619) on the
#564-repaired store with the keyed leg enabled — the first configuration above the program's
12-arm noise distribution (0.675–0.738). Free gates: sh keyed retrieval 0.48 → **0.85**,
answer-fact existence 0.61 → **~1.0**. Full evidence: `BASELINE_SUMMARY.md` (PR #28).

---

## 1. Recommended prod settings

### Enable (the validated winners)

| Setting | Value | Why |
|---|---|---|
| `NOUS_SAME_SLOT_CONFLICT_ROUTING_ENABLED` | `true` (default) | Gate-1 D2 correctness fix — same-slot value-variants must reach conflict resolution, never dedup-drop. **Do not turn off.** |
| `NOUS_KEYED_FACT_LEG_ENABLED` | `true` — **only after the entity-key backfill (§2) completes** | The decisive arm's sole delta vs baseline. Inert (empty vocabulary) if flipped before keys exist — it will silently measure as a no-op. |
| `NOUS_KEYED_FACT_LEG_K` | `8` (default) | Bounded allotment. Eval candidate sets were median 1.5 / p90 6 — K=8 admits everything useful while structurally preventing chunk-channel displacement (the −5.0pp failure mode of unbounded fact injection). Do not raise without re-measuring. |
| `NOUS_KEYED_FACT_LEG_SCORE` | `0.55` (default) | Keyed hits merge below the direct-hit head; validated as-is. |

### Recommended, pending nous-side regression (not eval-validated end-to-end)

| Setting | Value | Why |
|---|---|---|
| `NOUS_SUPERSESSION_KEY_RESOLUTION_ENABLED` | `true` | R2.1 write-time resolution. With D2 routing ON but R2.1 OFF, same-slot pairs accumulate KEEP-BOTH until the sleep sweep — safe but unmerged. The eval validated the fixed resolution semantics via the backfill path (same runtime functions); the live write-time path is covered by #564's regression tests but not by an eval arm. Enable with your test suite as the gate. |
| `NOUS_SUPERSESSION_POLICY` | `ordinal` (default) | Statement-order winner rule — the semantics the fix pair restores. |

### Keep OFF / land-dark (validated negative or unproven)

| Setting | Value | Why |
|---|---|---|
| `NOUS_SPREADING_ACTIVATION_ENABLED` | `false` | Measured negative at n=320 on dense-fact stores (0.703 / 0.684 vs 0.725), three independent arms. |
| Retrieval-time cross-encoder | `false` (current prod) | Live arm 0.681 — CE promotes wrong-serial siblings (relevance ≠ currency). Sleep-consolidation CE stays as-is. |
| `NOUS_EXTRACTION_ENUMERATIVE_ENABLED` | `false` (default) for conversational agents | R1 enumerative extraction was built for document-dense ingestion. On conversational prod episodes the density heuristic should rarely trigger, but leaving the flag dark until you want document workloads keeps the write path unchanged. If enabled, keep the default caps (`*_MAX_FACTS_PER_EPISODE=1000` etc.) — the uncapped mode is an offline-clone remediation setting only. |
| F084 injection flags (pin/format/lineage/backstop) | defaults (dark) | All measured null-to-negative on CR; the keyed leg supersedes their purpose with bounded precision. |

---

## 2. Backfill runbook (order matters)

All scripts live in `nous/scripts/`. Established conventions apply: **dry-run first, per
agent, record the printed ROLLBACK KEY**, run from the repo root with the venv python.
Reference cost ratios from the eval clone (Sonnet 4.6 background / Haiku 4.5 classifier):
~1 extraction call per ~2.3k transcript chars (batch mode); R3 value-side extraction ~40
facts/call; R2 ~1 Haiku call/conflict pair.

### Step 0 — preconditions
- Deploy ≥ `7cbc10a` (#564). Migration `065_fact_entity_keys.sql` applied.
- Snapshot/backup the DB. `ANALYZE` after any restore.

### Step 1 — supersession backfill (repairs existing wrong-winner chains)
```
python scripts/backfill_supersession.py --agent-id <agent> --dry-run
python scripts/backfill_supersession.py --agent-id <agent> --classifier-budget 0
```
- Record the printed `ROLLBACK KEY (updated_at watermark)`.
- What it fixes: any historical same-key conflict resolved by the old truth-biased
  classifier now re-resolves by statement order. Pairs whose update-variant was
  dedup-swallowed before #564 cannot be repaired (the variant was never stored) —
  those heal forward as users restate facts, via D2 routing.
- Rollback: the SQL in the script docstring (facts reset + `supersedes`/`contradicts`
  edge delete, agent-scoped, watermark-scoped).

### Step 2 — entity-key backfill (REQUIRED before the keyed leg)
```
python scripts/backfill_r3_entity_keys.py --agent-id <agent> --dry-run
python scripts/backfill_r3_entity_keys.py --agent-id <agent> --phase all
```
- Phases: `normalize` (canonicalize existing keys, idempotent) → `seed` (subject-key
  rows, no LLM) → `extract` (value-side keys, batch LLM, DB-clock watermark, resumable).
- Record the rollback key; `--phase rollback --watermark <key>` is supported here.
- Verify: `SELECT count(*) FROM heart.fact_entity_keys WHERE agent_id='<agent>';`
  should be ≈ 1.5–2× the agent's active fact count.

### Step 3 — flip the leg + smoke
- Set `NOUS_KEYED_FACT_LEG_ENABLED=true`, restart.
- Smoke (in-process, no traffic needed): `Settings().keyed_fact_leg_enabled` is True;
  `FactManager.entity_key_vocabulary()` non-empty; `fetch_by_entity_keys()` on a known
  entity returns its facts. (This exact probe caught nothing wrong on the eval —
  but the leg logs only on failure, so don't infer activation from silence.)
- Suggested telemetry before wide rollout: surface `keyed_leg_used` / `n_keyed` from
  `PipelineOutcome` into a log line or metric — today they are internal-only, which
  makes prod verification needlessly hard.

### Step 4 — regression gate (nous-side)
- Your standard retrieval regression suite with the leg on vs off. The eval's AR/LRU
  agents have no entity keys, so our harness cannot regress-test the leg on non-CR
  workloads — this gate is yours. Expected risk: low (bounded K, score-banded,
  id-deduped against other legs), but "expected" is not "measured".

---

## 3. What NOT to expect

- The keyed leg improves **exact-entity factual recall**. It does not address
  multi-hop composition (our mh gain came from the *repaired store* feeding the
  agent's own iterative recall, not from the single-round leg — keyed single-round
  mh ceiling measured 0.02). The composition lever is R3 v2 (one bounded iterative
  keyed round; simulated ceiling mh 0.02 → 0.49 on a repaired store) — separate
  requirements doc to follow.
- Fully-repaired-store numbers (sh keyed 0.85) assume the backfills ran. A prod store
  with pre-#564 history that skips Step 1 keeps its wrong-winner chains.
