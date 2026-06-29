# nous-memory-agent-bench

A [MemoryAgentBench](https://github.com/HUST-AI-HYZ/MemoryAgentBench) (MAB, ICLR 2026 — arXiv
2507.05257) benchmark harness for the [nous](../nous) agent.

For each **configuration** (a named set of `NOUS_*` environment overrides), the harness boots a
real nous HTTP server against an isolated local memory database under a fresh `NOUS_AGENT_ID`,
ingests a MAB task's context incrementally, drives session-end + sleep consolidation, asks the
task's questions, and grades the agent's answers — then reports a comparison across configs so
different memory approaches can be ranked.

**Status:** in development. v1 targets the **Accurate Retrieval** competency end-to-end,
architected so Test-Time Learning, Long-Range Understanding, and Conflict Resolution plug in
behind the same interfaces.

See the design spec: [`docs/superpowers/specs/2026-06-29-mab-harness-design.md`](docs/superpowers/specs/2026-06-29-mab-harness-design.md).

## Requirements

- A reachable nous checkout (default `../nous`) launchable via `python -m nous.main`.
- A migrated local eval Postgres+pgvector DB (the nous `docker-compose --profile eval` DB on
  `127.0.0.1:5433` works out of the box).
- `ANTHROPIC_API_KEY` (or `ANTHROPIC_AUTH_TOKEN`) and `OPENAI_API_KEY` for the nous server.

## Usage (planned)

```bash
pip install -e ".[dev]"
mab run --configs baseline,retrieval_graph_off --competency accurate_retrieval --sample-size 5
```
