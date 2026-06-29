# Running the harness

## 1. Provide an isolated, migrated eval database

The nous server verifies the schema exists but does not create it, so point the
harness at a **migrated** Postgres+pgvector DB that is NOT your dev/prod nous DB.
The nous repo ships one via its eval profile:

```bash
# in the nous checkout
docker-compose --profile eval up -d nous-eval-db   # 127.0.0.1:5433, db nous_eval
```

Override connection details with `MAB_DB_HOST/PORT/USER/PASSWORD/NAME` if needed
(defaults: `127.0.0.1:5433`, user `nous`, password `nous_eval`, db `nous_eval`).

> Each run uses a unique `NOUS_AGENT_ID`, so runs are isolated within one DB and
> never collide. `mab.wipe.wipe_agent` is optional housekeeping.

## 2. Point the harness at a runnable nous

```bash
export MAB_NOUS_REPO=../nous
export MAB_NOUS_PYTHON=/path/to/python-with-nous-installed   # NOT the harness venv
```

## 3. Credentials (required)

```bash
export OPENAI_API_KEY=...        # mandatory: without it nous has no embeddings
export ANTHROPIC_API_KEY=...     # or ANTHROPIC_AUTH_TOKEN
```

## 4. Plumbing smoke test (cheap) — M0

```bash
MAB_RUN_INTEGRATION=1 pytest -m integration tests/test_smoke_integration.py
```

Confirms launch → ingest → session-end + settle → sleep → recall → grade on a
single synthetic fact before spending money on real MAB contexts.

## 5. First real run — M1 (Accurate Retrieval)

```bash
# preview cost without running
mab run --competency accurate_retrieval --configs baseline,episode_chunks_on \
        --sources eventqa_65536 --max-questions 5 --dry-run

# run it
mab run --competency accurate_retrieval --configs baseline,episode_chunks_on \
        --sources eventqa_65536 --max-questions 5
```

Reports land in `./reports/<utc>_<competency>_<configs>.{md,json}`.

`mab presets` lists config presets; `mab sources --competency <c>` lists sources
and their context sizes.

## Cost notes

MAB Accurate-Retrieval contexts are large (eventqa_65536 ≈ 285K chars; some
exceed 2M). Ingest is bounded by `MAB_MAX_INGEST_CHUNKS` (default 60 chunks ×
`MAB_CHUNK_CHARS` 4000 = up to 240K chars/instance) — dropped chunks are logged.
`--dry-run` prints an agent-turn estimate. Scores are **nous-relative**, not
comparable to MemoryAgentBench published numbers.
