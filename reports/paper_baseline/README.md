# Baseline evidence — provenance notes

Per-question evidence for the paper-faithful baseline reported in
`docs/reviews/2026-07-03-paper-faithful-baseline.md` and the white paper.

## Run settings (all reported runs)

All headline runs used `MAB_CHUNK_CHARS=32000` and `MAB_MAX_INGEST_CHUNKS=80`
(2.56M-char ingest capacity) — NOT the harness defaults. Full-fidelity profile
(`configs/prod_memory.env`, 3 sleep cycles) for moderate contexts; big-context
profile (`configs/prod_memory_bigctx.env`, 1 sleep cycle, bounded summarizer,
15s turn delay) for giants and the detective/eventqa firm-ups.

## Truncation audit

Post-hoc recomputation (2026-07-04) of `chunk_context()` at the run settings for
**all 34 instances in the reported baseline: 0 dropped chunks** — every instance
fully ingested. Largest: eventqa_full#2 at 2,306,899 chars -> 73/80 chunks;
longmemeval_s*#17 packed 1,282 turns -> 50 chunks, 0 truncated.
Runs after 2026-07-04 stamp `chunks_sent`/`chunks_truncated` on every JSONL row
(plus a `.meta.json` companion with the capacity settings), and the driver
excludes truncated instances from the headline. Older rows carry `null` for
these fields; the post-hoc audit above covers them.

## Superseded files

- `longmem.log` — SUPERSEDED. Pre-fix run under one-turn-per-chunk chunking:
  only 80 of 1,282 turns ingested (1,202 dropped, ~6% coverage). Kept for the
  audit trail; not part of the reported baseline.
  `longmem_full.log` + `results_accurate_retrieval_longmemeval_s_.jsonl` are
  the post-fix (turn-packing) run used in the baseline (7/8 = 0.875).
- `results_test_time_learning_icl_*.jsonl` — contains 240 raw rows: the n=200
  TTL run PLUS 40 duplicate rows (5 sources x 8) appended from the earlier n=8
  baseline (the `_persist` append bug, fixed the same day). Dedup on
  `(source, qa_pair_id or prompt)` keeping the last occurrence reproduces the
  reported 111/200 = 0.555 exactly (team-review verified).

## Not JSONL-persisted (pre-persistence runs, evidence in logs)

- CR 49/64 = 0.766 — `../paper_replay/run.log` (paper-prompt replay over the 8
  persisted CR agents).
- ruler_qa1_197K 7/8 = 0.875 — `../paper_ar/ar_full.log`. Not included in the
  consolidated AR n=232 (which uses JSONL-persisted sources only).
