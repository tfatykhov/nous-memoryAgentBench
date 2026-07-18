# Fix Spec: F085 GATE 1 Failures — Supersession Classifier Bias + Learn-Path Dedup Ordering

**For:** nous memory team
**From:** MAB evaluation program, 2026-07-18
**Context:** F085/#563 (R3 keyed selection) shipped faithfully to spec. The pre-replay
acceptance gate (free keyed-retrieval simulation, bar ≥0.80 single-hop) **failed at 0.48 —
for two upstream store-corruption defects, not the keyed index.** Both are in runtime code;
the backfill scripts are innocent (they call the buggy runtime) and become the repair
vehicle once the runtime is fixed.

**Measured impact (CR corpus, 160 single-hop questions, `nous_mab_wp` clone):**
- keyed gold retrieval, active facts only: **0.48**
- including wrongly-deactivated facts: **0.61** → Defect 1 costs **21/160 (13pp)**
- true answer-fact existence ceiling: **~0.61** → Defect 2 costs **~39pp** (statements
  verbatim in transcripts, absent from the fact store)

---

## Defect 1 — Supersession classifier adjudicates by world truth (parametric bias)

### Location
`nous/heart/facts.py` — F027 supersession classifier prompt + schema (consumed at
`facts.py:997` and `facts.py:1174`; shared by write-time resolution, the sleep sweep, and
`scripts/backfill_supersession.py`).

### The three offending fragments
1. Prompt example (~line 78):
   `'Capital of France is Paris' vs 'Capital of France is London' → CONTRADICTION
   (historical/definitional)`
2. Prompt policy (~line 83):
   `For current_fact: … for CONTRADICTION pick the factually correct one.`
3. Schema description:
   `current_fact: "Which fact represents the current/correct state of affairs"`

### Reproduced failure (from the clone)
Corpus statement 271: *"The author of The Marriage of Figaro is Pierre Beaumarchais"*;
later update statement: *"…is Thomas Kyd"* (the benchmark gold). Both were extracted
correctly. The pair pattern-matches the "historical/definitional" example → classified
CONTRADICTION → "pick the factually correct one" → the model consulted world knowledge →
**kept Beaumarchais (active), superseded Thomas Kyd (the stated update)**. DB state
observed: gold fact `active=false, superseded_by set`; original `active=true`.

This is the exact failure mode conflict-resolution memory exists to prevent — a user's
correction ("actually, I moved to Austin") loses to the model's prior — reproduced inside
the supersession machinery itself. 21/160 gold facts were destroyed this way.

### Required fix
1. **Remove truth adjudication entirely.** A memory store resolves *testimony order*, not
   facts-about-the-world. Replace the CONTRADICTION `current_fact` policy with
   source-priority: **later-stated wins** (`source_ordinal`, else `learned_at`); when
   neither orders the pair, **KEEP-BOTH + flag** (the existing fail-open convention).
2. **Reword the schema:** `current_fact` = "which statement was made later / supersedes
   the other" — delete "correct".
3. **Replace the Capital-of-France example** — it teaches the classifier to route
   knowledge revisions (the entire update class) into truth adjudication. A safe
   replacement pair: `'The config file is settings.yaml' vs 'The config file is
   config.toml'` → UPDATE.
4. If a classifier call remains in the path at all, its only legitimate question is
   *relation typing* (UPDATE/REFINEMENT/UNRELATED/duplicate) — never winner selection by
   plausibility.
5. **Invariant preserved:** the F075 date-bypass (differing non-null `event_date` = two
   events, never superseded) and fail-open KEEP-BOTH stay as-is.

### Regression test to add
Pin the Figaro shape: two same-key facts where the later-stated value contradicts world
knowledge → assert the later statement wins and the earlier is superseded, with the
classifier mocked AND live. (The eval can supply more pairs from the CR corpus on request.)

---

## Defect 2 — Learn-path dedup swallows update-variants before conflict detection

### Location
`nous/heart/heart.py` — `Heart.learn` admission path, cosine dedup gated by
`fact_native_cosine_threshold` (see heart.py:110 tuning hook).

### Mechanism
Statements differing only in the **value slot** — *"The author of X is A"* vs *"The author
of X is B"* — embed nearly identically and clear the dedup similarity threshold, so the
**update is silently dropped as a duplicate before conflict detection ever sees the
pair.** Result: ~39% of single-hop answer statements verbatim in transcripts never became
facts (measured existence ceiling 0.61). This also starves R2: chains that were never
stored can never be resolved.

### Required fix
**Ordering/exemption rule in `Heart.learn`:** when an incoming fact and its dedup
candidate share `(subject_key, attribute_key)` **but differ in value**, the pair MUST
route to conflict resolution (F027/F084), never to dedup-drop. Dedup remains correct only
for same-key **same-value** near-duplicates. (With R3.1 keys on every enumerative fact,
the same-key check is an index lookup, not an embedding judgment.)

Note the pleasant composition: Defect-2 fix routes update-variants *into* the resolver;
Defect-1 fix makes the resolver pick the right winner. Shipping only one of the two
leaves golds destroyed — they must land together.

### Regression test to add
Same-key different-value pair above the cosine dedup threshold → assert both stored and
resolved (later wins), not deduped. Same-key same-value → assert deduped as today.

---

## Repair + validation sequence (after both fixes land)

All on the eval clone first; steps 3–5 cost zero tokens.

1. **R1 re-run** (`backfill_enumerative_facts.py`, caps=0): fixed dedup now admits the
   previously-swallowed variants. Idempotent over existing rows.
2. **R2 rollback + re-run** (`backfill_supersession.py --phase rollback --watermark <ts>`,
   then a fresh pass): fixed classifier resolves forward. R3 entity-key backfill
   incremental re-run for the newly admitted facts.
3. **Free simulation gate** (`probe_keyed_lookup_sim.py`, entity-key variant): bar
   **≥0.80 single-hop gold retrieval**. Below bar → iterate here, spend nothing.
4. Free displacement check (bounded-allotment invariant holding).
5. Only past both: the decisive CR n=320 replay (~7M tokens) vs published 0.725.

## Expected value if both fixes work
Single-hop keyed ceiling ≈ existence ceiling ≈ 0.95+ (extraction gaps were the artifact
of Defect 2, not extraction fidelity); combined with the +28-gain flow already
demonstrated in the write-path arm, this is the first configuration with a mechanically
grounded path past the 0.725 plateau. Multi-hop remains a separate (composition) problem
and is out of scope for this fix pair.
