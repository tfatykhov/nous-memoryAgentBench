# nous-memory-agent-bench

A [MemoryAgentBench](https://github.com/HUST-AI-HYZ/MemoryAgentBench) (MAB, ICLR 2026 — arXiv
2507.05257) benchmark harness for the [nous](../nous) agent.

For each **configuration** (a named set of `NOUS_*` environment overrides), the harness boots a
real nous HTTP server against an isolated local memory database under a fresh `NOUS_AGENT_ID`,
ingests a MAB task's context incrementally, drives session-end + sleep consolidation, asks the
task's questions, and grades the agent's answers — then reports a comparison across configs so
different memory approaches can be ranked.

**Status:** baseline complete across all four competencies (paper-faithful graders, prod nous
config, per-question evidence committed). See [`BASELINE_SUMMARY.md`](BASELINE_SUMMARY.md) for
the full reconciliation (every number → evidence file → comparability tier) and
[`docs/whitepaper/`](docs/whitepaper/) for the white paper (PDF).

## Results (2026-07-05)

nous (claude-sonnet-5, production config), scored with MAB's **official graders** on the
sampled slices — 95% CIs attached, no aggregate score published by policy:

| Competency | Score | n | 95% CI | Best avg. in MAB paper |
|---|---|---|---|---|
| Accurate Retrieval | **0.897** | 232 | [0.86, 0.94] | 0.718 |
| Conflict Resolution | **0.725** (SH 0.887 / MH 0.562) | 320 | [0.68, 0.77] | 0.295 |
| Long-Range Understanding (detective) | **0.824** | 68 | [0.73, 0.91] | 0.622 |
| Test-Time Learning (**ICL subset** — recsys blocked) | 0.555 | 200 | [0.49, 0.62] | 0.539 |

Against the **2026 field** (Infini Memory, arXiv:2606.10677 — full benchmark, gpt-5-mini base,
gpt-5 judge; our answers re-graded under a validated reconstruction of that judge: agreement
0.970 / Cohen's kappa 0.918 vs official graders), with margins graded against the ~9.7pp known
backbone swing:

- **Multi-hop conflict resolution: +21.2pp above the 2026 leader** (0.562 vs 0.350) — holds
  under all three grading protocols; the cell their own paper calls unsolved.
- Retrieval +10.6pp (marginal); single-hop CR and long-range QA +8pp (directionally ahead,
  backbone-undecidable); **ICL −21.5pp behind** — the identified improvement target.
- Discovered en route: multi-hop conflict resolution **degrades with context scale**
  (0.83 → 0.30 from 6k → 262k chars).

Caveats live next to every claim: slices not the full benchmark, base-model confound flagged
per claim, judge reconstruction published verbatim (white paper appendix), no SOTA claim.

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
