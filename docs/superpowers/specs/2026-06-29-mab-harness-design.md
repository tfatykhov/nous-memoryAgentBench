# MemoryAgentBench Harness for nous — Design Spec

**Date:** 2026-06-29
**Status:** Draft (pending independent review + user sign-off)
**Decision:** FORGE `ffe21de3`

## 1. Goal

A standalone benchmark tool (repo: `e:\Projects\nous-memoryAgentBench`) that evaluates the
**nous** agent against [MemoryAgentBench (MAB)](https://github.com/HUST-AI-HYZ/MemoryAgentBench)
(ICLR 2026, arXiv 2507.05257). For each **configuration** — a named set of `NOUS_*` env
overrides — the harness:

1. Boots a real nous HTTP server against an isolated local memory database under a fresh
   `NOUS_AGENT_ID`.
2. Ingests a MAB task's context incrementally (chunks → `/chat` turns).
3. Triggers and awaits memory consolidation (sleep).
4. Asks the task's questions via `/chat` and grades the **answer text**.
5. Emits a comparative report so different memory approaches can be ranked.

**v1 scope:** one vertical slice — the **Accurate Retrieval** competency — built so the other
three competencies (Test-Time Learning, Long-Range Understanding, Conflict Resolution) plug in
behind the same interfaces.

## 2. Locked decisions (from user)

| Axis | Decision |
|------|----------|
| Drive model | **Full HTTP server per run** — launch `python -m nous.main`, talk HTTP. |
| DB isolation | **Persistent local eval DB + fresh `NOUS_AGENT_ID`**, wiped between configs. |
| v1 scope | **One vertical slice** (Accurate Retrieval), architected for all four. |
| Compare axes | retrieval/graph · consolidation/sleep · contradiction detection · embeddings/model. |

## 3. Why server-driven is correct (fidelity)

The F051 review (`fd69ffe1`) found that production retrieval faculties — graph expansion,
spreading activation, contradiction detection — are gated in `nous/api/tools.py`'s `recall_deep`
dispatcher, **not** in `heart.recall()`. Driving the full `/chat` path exercises the real
faculties end-to-end and avoids measuring a truncated pipeline. This is the central reason the
HTTP-server model beats an in-process `heart.recall()` harness.

## 4. nous HTTP contract (verified against code)

- **Startup:** `python -m nous.main`; binds `NOUS_HOST:NOUS_PORT` (default `0.0.0.0:8000`).
- **Health:** `GET /health` → `{"status":"healthy"}` (200) / `503` when unhealthy.
- **Chat:** `POST /chat` body `{"message": str, "session_id": str?, "debug": bool}`; response
  `{"response": str, "session_id": str, "usage": {input_tokens, output_tokens, tool_calls},
  "debug": {recalled_fact_ids, recalled_episode_ids, ...}}` (debug only when `debug=true`).
- **Sleep:** `POST /sleep/trigger` → `{"status":"started"}`; **fire-and-forget** (spawns an
  asyncio task; no synchronous completion).
- **Status:** `GET /status` exposes a `memory` section with fact/episode/decision counts.
- **Ingestion is asynchronous:** facts are extracted post-turn via the event bus
  (`episode_summarized` → `FactExtractor`), gated by `episode_summary_enabled` and
  `event_bus_enabled`. Episodes are created from turns. So a turn returns before its memory is
  fully written.
- **Scoping:** every memory table filters `WHERE agent_id = :agent_id`; fresh `NOUS_AGENT_ID`
  ⇒ clean memory space within the same DB.
- **Auth:** none by default. `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` are upstream LLM creds.

### 4.1 Determinism strategy (the key risk)

Because ingestion and sleep are asynchronous, the harness must **settle** rather than fire-and-pray:

- **After ingest:** poll `GET /status` memory counts until they stabilize across N consecutive
  polls (or a max-wait timeout), so async fact extraction has flushed.
- **Consolidation:** `POST /sleep/trigger`, then poll `GET /status` until counts stabilize again
  (or timeout). Optionally confirm via a direct read-only DB query on `agent_id`.
- All timeouts/poll-intervals are config knobs with conservative defaults; every wait logs what
  it waited for and whether it timed out (no silent truncation).

## 5. Components (each independently testable)

```
mab/
  datasets/        # 1. MAB dataset loader + MabInstance schema
  instance.py      # 2. nous server lifecycle (env build, subprocess, health wait, teardown, wipe)
  adapter.py       # 3. nous "memory method": ingest() / consolidate() / answer()
  grading/         # 4. per-competency graders (substring-EM, EM, Recall@5, LLM-judge)
  config.py        # 5a. HarnessSettings (pydantic-settings) + Config presets
  runner.py        # 5b. config x task matrix loop
  report.py        # 6. markdown + JSON comparative reports
  cli.py           # entry point: `python -m mab.cli run --configs ... --tasks ...`
```

1. **Dataset loader** — downloads `ai-hyz/MemoryAgentBench` from HuggingFace; normalizes each
   task to `MabInstance{task, competency, context_chunks: list[str],
   questions: list[Question{prompt, gold_answers: list[str], metric}]}`. v1 implements the
   Accurate Retrieval tasks (`event_qa`, `ruler_qa1`, `ruler_qa2`).
2. **Instance manager** — `NousInstance` context manager: builds env dict (DB → eval DB, fresh
   `NOUS_AGENT_ID`, config overrides), launches the server subprocess on a free port, waits for
   `/health`, yields a base URL, tears down on exit; `wipe(agent_id)` deletes that agent's rows.
3. **Adapter** — `NousMemoryMethod` implementing the MAB-style interface:
   `ingest(chunks)` (each chunk → `/chat` turn + settle), `consolidate()` (sleep + settle),
   `answer(question) -> str`. This is the single seam where nous plugs into MAB.
4. **Graders** — `Grader` protocol `score(answer, gold_answers) -> bool/float`. v1:
   `SubstringExactMatch` (AR/CR). Stubs registered for `ExactMatch` (TTL/LRU), `RecallAtK`
   (recsys), `LlmJudge` (longmemeval/infbench) — the latter optionally delegating to MAB's own
   `llm_based_eval` for published-number comparability.
5. **Config + runner** — `Config{name, env: dict[str,str], description}`; built-in presets per
   compare axis. `run_matrix(configs, instances)` loops configs (restart server each), runs all
   task instances, collects `QuestionResult{config, task, question, answer, gold, correct}`.
6. **Reporter** — markdown table (per-config accuracy, per-competency breakdown, deltas vs
   baseline) + JSON (full per-question grid) written to `reports/<utc>_<configs>.{md,json}`.

## 6. Data flow per (config, task)

```
build env(config) -> launch nous server (eval DB, fresh agent_id) -> wait /health
  -> ingest context_chunks as /chat turns -> settle (poll /status)
  -> POST /sleep/trigger -> settle
  -> for each question: POST /chat -> grade(answer, gold, metric)
  -> aggregate -> teardown server -> wipe agent_id
```

## 7. Config presets (built-in)

- `baseline` — nous defaults.
- `retrieval_graph_off` — `NOUS_GRAPH_RECALL_ENABLED=false`.
- `retrieval_spreading_off` — `NOUS_SPREADING_ACTIVATION_ENABLED=false`.
- `retrieval_ce_on` — `NOUS_CROSS_ENCODER_ENABLED=true`.
- `consolidation_sleep_off` — `NOUS_SLEEP_ENABLED=false` (skip the sleep step).
- `contradiction_off` — `NOUS_CONTRADICTION_DETECTION=false`.
- `model_haiku` — `NOUS_MODEL=claude-haiku-4-5-20251001`.

Each preset = baseline env + a few overrides. Presets are data, not code, so adding axes is a
dict edit.

## 8. Configuration (HarnessSettings, `MAB_` env prefix)

- `MAB_NOUS_REPO` (path to `../nous`), `MAB_NOUS_PYTHON` (interpreter).
- Eval DB: `MAB_DB_HOST/PORT/USER/PASSWORD/NAME` (defaults match the nous eval DB: `127.0.0.1:5433`).
- `MAB_SAMPLE_SIZE` (questions per task; small default for cost), `MAB_DATASET_DIR`,
  `MAB_REPORT_DIR`, `MAB_SETTLE_TIMEOUT_S`, `MAB_SETTLE_POLL_S`, `MAB_SLEEP_TIMEOUT_S`.
- `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` passed through to the server env.

## 9. Open risks & mitigations

| Risk | Mitigation |
|------|------------|
| Async ingest/sleep nondeterminism | Settle-by-polling `/status` with timeouts; log every wait. |
| Token cost of full agent loop | Small configurable `MAB_SAMPLE_SIZE`; v1 = one competency. |
| Ingestion fidelity (docs as dialogue) | Feed chunks as `/chat` turns; document the mapping; allow chunk batching. |
| Eval DB must exist & be migrated | Reuse nous `Dockerfile.eval-db` / `docker-compose --profile eval` (port 5433); harness preflights `/health` + DB reachability and fails loudly with setup instructions. |
| Port collisions across configs | Allocate a free ephemeral port per server launch. |

## 10. Out of scope (v1)

- TTL / LRU / CR graders beyond stubs (interfaces only).
- recsys / longmemeval / infbench tasks.
- Statistical significance testing across configs.
- CI gating (the nous `eval_runs` gate pattern can be added later).

## 11. Testing strategy

- Unit: dataset normalization, grader correctness (table-driven), config→env merge, settle logic
  (mock `/status`), report rendering. No live server needed.
- Integration (opt-in, marked, needs live eval DB + keys): one tiny task through the full
  pipeline against a real nous server.
