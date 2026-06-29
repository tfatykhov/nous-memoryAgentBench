# MemoryAgentBench Harness for nous — Design Spec

**Date:** 2026-06-29 (rev 2 — post independent review + code verification)
**Status:** Reviewed; incorporates review findings + user direction
**Decision:** FORGE `ffe21de3`

## 1. Goal & framing

A standalone tool (repo: `e:\Projects\nous-memoryAgentBench`) that evaluates the **nous** agent
against [MemoryAgentBench (MAB)](https://github.com/HUST-AI-HYZ/MemoryAgentBench) (ICLR 2026,
arXiv 2507.05257). For each **configuration** — a named set of `NOUS_*` env overrides — the
harness boots a real nous HTTP server against an isolated local memory DB under a fresh
`NOUS_AGENT_ID`, ingests a MAB task's context, drives session-end + consolidation, asks the
task's questions, grades the **answer text**, and reports a comparison across configs.

**Purpose: improve nous's memory.** The benchmark measures *what survives nous's real shipping
memory pipeline*, then lets `NOUS_*` config changes be compared to find what improves recall.
The lossy default ingest path is therefore the **measurement target**, not a flaw to hide.

**Honest scope of the number (review P1-3):** scores are **nous-relative** — "fraction of MAB
questions answerable through nous's real memory pipeline." They are **not comparable to MAB's
published per-method numbers** (nous ingests lossily, runs a full agent loop, and is not one of
MAB's evaluated methods). Reports state this prominently.

## 2. Locked decisions

| Axis | Decision |
|------|----------|
| Drive model | Full HTTP server per run — launch `python -m nous.main`, talk HTTP. |
| DB isolation | Persistent local eval DB (port 5433) + **unique `NOUS_AGENT_ID` per run** (isolation does not depend on wipe). |
| First competency | **Accurate Retrieval** (the path we most want to improve), architected for all four. |
| Ingest mode | Real default `/chat` path (summarize+extract); raw-text recall (`episode_chunks`) is a first-class **comparison preset**, not the default. |
| Compare axes | retrieval/graph · consolidation/sleep · contradiction · embeddings/model — with **ingest/retention knobs** (episode chunks, fact caps, top-k, cross-encoder) as the axis that actually moves AR. |

## 3. Verified nous contract (code-checked)

- **Startup:** `python -m nous.main`; binds `NOUS_HOST:NOUS_PORT` (default `0.0.0.0:8000`).
- **Health:** `GET /health` → `{"status":"healthy"}` (200) / 503.
- **Chat:** `POST /chat` `{message, session_id?, debug?}` → `{response, session_id, frame,
  decision_id, usage{input_tokens,output_tokens,tool_calls}, debug{recalled_fact_ids,...}}`
  (`debug` only when `debug=true`).
- **End session:** `DELETE /chat/{session_id}` → `{"status":"ended"}`. Triggers the durable-write
  chain (see §4).
- **Sleep:** `POST /sleep/trigger` → `{"status":"started"}` (409 if already sleeping; **503 if
  `NOUS_SLEEP_ENABLED=false`** — handler not constructed, so `consolidate()` must branch on config).
- **Events:** `GET /events/stats` → `component_stats.sleep_handler` = `{currently_sleeping,
  total_sleeps, last_sleep_at}`; `GET /events/recent`, `GET /events/modifications` query
  `nous_system.events` (incl. `episode_summarized`, `sleep_completed`).
- **Status:** `GET /status` → `memory{total_facts,total_episodes,total_decisions,...}`.
- **DB env is UNPREFIXED** `DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME` (validation_alias beats
  the `NOUS_` prefix — `NOUS_DB_*` is ignored). The server verifies schema exists but does **not**
  create it ⇒ the eval DB must be pre-migrated (the `docker-compose --profile eval` image is).
- **`OPENAI_API_KEY` is mandatory**: without it nous builds no embedding provider → no vector
  recall/graph/spreading/cross-encoder → silent keyword-only FTS, making config comparison
  meaningless. Hard preflight.
- **No auth** by default.

## 4. The durable-write chain & determinism

Memory is written **post-session**, not post-turn:

```
POST /chat (session S1) xN  →  DELETE /chat/S1
  → session_ended → EpisodeSummarizer (async LLM): ~150-word summary + ≤5 candidate facts
  → episode_summarized → FactExtractor (async LLM): writes facts (5 stable / 15 broadened / 30 event)
  → [if episode_chunks_enabled] raw transcript chunked into heart.episode_chunks (verbatim, recallable)
```

**Settle (deterministic, event-based — review P2-2):**
- **Ingest settle:** after `DELETE`, poll `GET /events/recent` for an `episode_summarized` event
  for our episode, then confirm fact-extraction quiescence (no new `nous_system.events` for our
  agent across N polls), with a max-wait timeout.
- **Consolidate:** read `total_sleeps` from `/events/stats`; `POST /sleep/trigger`; poll until
  `total_sleeps` increments (or `currently_sleeping` flips false with a newer `last_sleep_at`),
  max-wait timeout. (Count-stabilization is rejected: a sleep can complete with 0 new facts.)
- Every wait logs what it waited for and whether it timed out — no silent truncation.
- `NOUS_SESSION_TIMEOUT` set low as a backstop only; `DELETE` is the primary trigger.

## 5. Components (each independently testable)

```
mab/
  datasets/     [DONE] MAB loader + MabInstance schema (HF parquet → normalized instances)
  grading/      [DONE] substring-EM / exact-match graders + registry
  config.py     HarnessSettings (MAB_* env) + Config presets (data, per axis)
  instance.py   NousInstance: env build, free-port subprocess launch, /health wait, teardown
  wipe.py       optional FK-safe wipe-by-agent_id (housekeeping; isolation is via unique agent_id)
  adapter.py    NousMemoryMethod: ingest() / end+settle / consolidate() / answer() over HTTP
  runner.py     config × instance matrix loop; collects per-question results
  report.py     markdown + JSON comparative report (per-config accuracy, per-source, deltas)
  cli.py        `mab run --competency accurate_retrieval --configs ... --sources ... --max-...`
```

1. **datasets** (built): `load_competency()` → `MabInstance{competency, source, context,
   questions[{prompt, gold_answers, metric, qa_pair_id}], haystack_turns}`. AR rows have a
   monolithic `context` (haystack_turns empty) → adapter chunks it. Filters: `sources`,
   `max_context_chars`, `max_questions_per_instance`.
2. **grading** (built): `Grader.grade(answer, gold_answers) -> GradeResult`; registry by metric.
3. **config**: `Config{name, env: dict[str,str], description}`; `HarnessSettings` (`MAB_*` prefix):
   nous repo path/python, eval `DB_*` (default `127.0.0.1:5433` / `nous` / `nous_eval`),
   `MAB_MAX_CONTEXT_CHARS`, `MAB_MAX_INGEST_CHUNKS`, `MAB_CHUNK_CHARS`,
   `MAB_MAX_QUESTIONS_PER_INSTANCE`, settle/sleep timeouts, report dir, API keys pass-through.
4. **instance**: context manager; builds env (eval `DB_*`, unique `NOUS_AGENT_ID`,
   `NOUS_SESSION_TIMEOUT` low, config overrides, keys), launches server on a free port, waits for
   `/health`, yields base URL, terminates the process group on exit (Windows-safe).
5. **adapter** (`NousMemoryMethod`): `ingest(instance)` chunks `context` (≤`MAX_INGEST_CHUNKS`,
   `CHUNK_CHARS` each) as `/chat` turns in one session → `DELETE` → ingest-settle; `consolidate()`
   sleep-trigger + settle (no-op + log if sleep disabled); `answer(question)` asks in a **fresh
   `session_id` per question** (review P2-6), returns `response`.
6. **runner**: for each config → spin `NousInstance`, for each instance → ingest, consolidate,
   answer all questions, grade; collect `QuestionResult{config, source, qa_pair_id, answer,
   correct, golds}`. Records ingest token cost.
7. **report**: per-config accuracy overall + per-source/per-competency; deltas vs `baseline`; JSON
   grid; prominent non-comparability + cost notes.

## 6. Config presets (built-in)

Centered on the levers that actually move AR (review P2-4):
- `baseline` — nous defaults (chunks off; summarize + ≤5 facts).
- `episode_chunks_on` — `NOUS_EPISODE_CHUNKS_ENABLED=true` (**headline**: verbatim raw-text recall).
- `coverage_broadened` — broaden fact extraction (5 → 15 stable facts).
- `cross_encoder_on` — `NOUS_CROSS_ENCODER_ENABLED=true` (preflight downloads bge-reranker).
- `sleep_off` — `NOUS_SLEEP_ENABLED=false` (adapter skips consolidate via the 503 branch).
- `model_haiku` — `NOUS_MODEL=claude-haiku-4-5-20251001` (cost/quality tradeoff).

Presets for the other competencies (contradiction, consolidation) land with those slices, where
they are not inert.

## 7. Cost controls (review P1-4)

AR contexts reach ~1M chars (`ruler_qa2_421K`). Mitigations, all logged:
- `MAB_MAX_CONTEXT_CHARS` (default modest) skips oversized instances; default run starts with the
  smallest source (`eventqa_65536`).
- `MAB_MAX_INGEST_CHUNKS` caps ingest turns per instance; truncation is logged (no silent cap).
- "Inject once, query many": one ingest amortized over many questions (AR rows have up to 100 Qs).
- Pre-run cost estimate printed (≈ chunks×turns + questions, × configs) before execution.

## 8. Milestones

1. **M0 smoke test** (cheap plumbing validation): synthetic "tell nous a short fact → end session
   → settle → recall via /chat → grade" — proves instance + adapter + settle + sleep-completed +
   wipe end-to-end before paying for RULER ingestion.
2. **M1 Accurate Retrieval** on `eventqa_65536` (smallest), configs `baseline` vs
   `episode_chunks_on`, small `MAB_MAX_QUESTIONS_PER_INSTANCE` — first real signal on whether
   episode chunks improve AR.
3. **M2** widen sources/configs; add CR + TTL + LRU loaders/graders (LLM-judge, Recall@5) behind
   the existing interfaces.

## 9. Testing

- Unit (offline, default): dataset normalization [done], graders [done], config→env merge,
  chunker, settle logic (mock `/events`), report rendering, wipe SQL order.
- Integration (`-m integration`, opt-in; needs live eval DB + keys): M0 smoke through the full
  pipeline against a real nous server.

## 10. Out of scope (v1)

LLM-judge/Recall@5 graders beyond stubs; recsys/longmemeval/infbench tasks; significance testing;
CI gating. The nous `eval_runs` persistence pattern can be added later.
