# Requirements: Exemplar-Gathering Retrieval Mode (Test-Time Learning / ICL)

**For:** nous memory team
**From:** MAB evaluation program, 2026-07-19
**Targets:** the program's sole decidable loss vs the 2026 field — ICL 0.555 vs leader 0.840.
**Method note:** all numbers below survived an independent methodology review that corrected
two of our own first-pass claims (see "Honesty ledger" at the end).

## The measured chain

1. **Corrected live baseline: ICL 0.555** (200 q, 5 sources; our earlier 0.571 double-counted
   40 duplicated rows from a concatenated smoke run — harness-side hygiene issue, fixed in the
   accounting). Live per-source: banking77 .54 / clinic150 .50 / nlu .44 / trec_coarse .90 /
   trec_fine .48. Live transcripts show the failure shape directly: the agent finds *a*
   similar stored example over chunk retrieval and copies its label ("Found the direct match
   → label: 67", gold 28).
2. **Storage is not the problem** (validated): the ~400k-char exemplar streams
   (`utterance\nlabel: N`) persist essentially losslessly into `heart.episode_chunks`
   (0.2–2.0% loss, chunk-boundary splits; apparent larger gaps were dataset resampling
   repeats). Question-text leakage into the store: 7–8/200 (~4pp of 1-NN; reported, not
   load-bearing).
3. **Zero-LLM gathering simulations on the persisted agents** (scripts/probe_icl_exemplar_knn.py,
   probe_icl_exemplar_emb.py):
   - Lexical (Jaccard) 1-NN over all stored exemplars: **0.67** — beats live, paired
     +55/−32, p=0.018. The floor.
   - **Embedding kNN (text-embedding-3-large @1536, exemplar granularity): 1-NN 0.76,
     majority-vote@5 = 0.82, strict-plurality@25 = 0.81, gold-in-top25 = 0.99.**
     Paired vs live: **+70/−17, p=8×10⁻⁹.**
   - Per-source maj@5: banking77 .93 / clinic150 .88 / nlu .85 / trec_coarse .82 /
     trec_fine .62.
4. Interpretation: a **deterministic, zero-LLM rule** (embed the query, fetch the 5 nearest
   stored exemplars at exemplar granularity, majority label) already performs at the 2026
   leader's level (0.82 vs 0.84) on nous's stored memory. The live system loses 26pp not to
   storage or to model capability but to **retrieval granularity**: chunks bury ~40
   exemplars each, so chunk-level search returns *a* similar region, not the *k nearest
   labeled examples*. Program precedent says live results with an LLM reader tend to land
   at-or-above these static sims (twice-confirmed on CR: sims lower-bounded both keyed-leg
   arms).

## R-ICL.1 Exemplar-granularity index (write path) — the core requirement

- When an episode's content is example-shaped (regular `text → label` structure; a cheap
  regex/heuristic classifier at ingest, analogous to the R1 enumerative-density heuristic),
  store each exemplar as an individually-embedded row (option A: a dedicated
  `exemplar(agent_id, text, label, embedding)` table; option B: reuse the facts store with
  `source='exemplar_extractor'`, `attribute_key='label'`, value=label — nous's choice).
- No LLM required at ingest: the pairs are parsed, not generated. Batch-embed (the
  established sub-batching conventions).
- Caps + loud truncation per the R1.3 convention. Backfill for existing agents follows the
  standard dry-run/watermark/rollback conventions.

## R-ICL.2 Exemplar retrieval mode (read path, land-dark)

- Flag: `NOUS_EXEMPLAR_MODE_ENABLED` (default false).
- Trigger: the agent's store contains exemplar rows AND the incoming query is
  classification-shaped (short utterance, no interrogative about stored content — v1
  heuristic; mis-triggering is cheap because the leg is additive and bounded).
- Action: embed the query, fetch top-K exemplars by cosine (K default 25, config), inject
  as labeled examples in a dedicated context block ("Nearest stored examples: …"), bounded
  allotment so the block cannot displace other channels (the −5.0pp lesson).
- The LLM answers; it may use the majority label or override it (trec_coarse shows why
  override matters: the model's parametric classification is already 0.90 there — the
  injected examples must inform, not force. The F083 lesson: injection informs; forcing
  confabulates).
- Provenance `retrieval_leg='exemplar'`, telemetry surfaced in a log line (v1/v2 lesson:
  internal-only telemetry makes live verification needlessly hard).

## Acceptance gates (cost order)

1. **Free, already green:** the embedding-kNN sim above IS gate 1 (maj@5 0.82 ≥ bar 0.75 on
   the persisted eval agents). If the shipped index/normalization differs from the sim
   (different embedding model/dims, different parsing), re-run the sim against the
   implementation's own index before building the read path.
2. **Free:** displacement check — non-exemplar retrieval unchanged when the mode triggers
   falsely (bounded block, band ordering).
3. **Paid, decisive:** TTL ICL n=200 replay on the persisted agents, mode on vs corrected
   0.555. Prediction: 0.75–0.85 (sim 0.82 ± LLM-reader effects, which program precedent
   says are net-positive). trec_fine will lag (0.62 sim ceiling; 50 fine labels).
4. nous-side regression on non-ICL workloads (mode dark → byte-identical; mode on →
   trigger-precision check).

## Non-goals (v1)

Multi-round exemplar gathering (single embedding round already reaches 0.82; iterate only
if the replay shows conversion loss); LLM-based trigger classification; recsys (data-blocked);
label-space reasoning beyond injection.

## Honesty ledger (from the independent review)

- Our first-pass baseline (0.571) was corrupted by duplicated rows — corrected to 0.555.
- Our first-pass ceiling claim ("gold-in-top25 0.92 → headroom to 0.84") was REFUTED as
  stated: presence is not identifiability (lexical gold-plurality was only 0.64). The
  embedding-granularity result above answers the objection with an implementable rule
  (strict-plurality 0.81, maj@5 0.82) rather than an oracle metric.
- trec_fine's stored-exemplar surplus (3,643 unique vs 3,008 in context) is chunk-overlap
  fragments (533k chars stored vs 394k context; overlapping windows create truncated
  variants). Fragments carry their true labels; harmless to ranking, noted for the parser.
