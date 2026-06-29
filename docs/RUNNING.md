# Running the harness

## 1. Provide an isolated, migrated eval database

The nous server verifies its schemas exist (it does **not** create them) and then
applies `sql/migrations/*` itself on startup. So provision a **fresh** Postgres+
pgvector DB that is NOT your dev/prod nous DB, apply `sql/init.sql`, and let nous
migrate the rest. A pre-existing populated eval DB can fail startup if its legacy
data violates a newer migration's constraints — use a fresh DB.

Bring up a pgvector server on 5433 (the nous eval container, e.g.
`nous-eval-scratch`, or `docker-compose --profile eval`), then:

```bash
# creates an empty DB + applies init.sql; nous migrates the rest on first boot
scripts/provision_eval_db.sh nous_mab nous-eval-scratch ../nous
export MAB_DB_NAME=nous_mab
```

Connection defaults: `127.0.0.1:5433`, user `nous`, password `nous_eval`, db
`nous_eval_scratch`. Override with `MAB_DB_HOST/PORT/USER/PASSWORD/NAME`.

> Each MAB instance run uses a unique `NOUS_AGENT_ID`, so instances are isolated
> within one DB and never collide. `mab.wipe.wipe_agent` is optional housekeeping.
>
> **Verified:** the M0 smoke test passes end-to-end against a DB provisioned this
> way (launch → ingest → session-end → consolidation → recall → grade).

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
