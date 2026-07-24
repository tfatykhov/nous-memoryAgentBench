# nous Database Schema Reference

**Source of truth:** live production database (`nous`, PostgreSQL 17.8, pgvector), schema
extracted 2026-07-24 from the production snapshot (`nous_prod` copy). 43 tables across
three schemas. Codebase revision at extraction: `30bd24b` (post keyed-retrieval /
exemplar-mode features, migrations through `066`).

---

## 1. Architecture overview

nous persists memory and cognition in three PostgreSQL schemas:

| Schema | Role | Metaphor |
|---|---|---|
| **`heart`** | Memory proper: facts, episodes, transcript chunks, procedures, censors, working memory, plus task/schedule execution state | what the agent *remembers and knows how to do* |
| **`brain`** | Decision records, their reasoning traces, and the typed knowledge graph connecting everything | what the agent *decided and how it links* |
| **`nous_system`** | Infrastructure: agent registry, identity, frames, events, orchestration DAGs, telemetry, migrations | how the organism *runs* |

### Global conventions

- **Multi-tenancy:** nearly every table carries `agent_id varchar(100)` — one database
  hosts many agents; all queries are agent-scoped. (Exception: pure child tables that
  inherit scope through their FK, e.g. `decision_tags`.)
- **Primary keys:** `uuid` with `gen_random_uuid()` default, except natural-key tables
  (`agents.id`, `frames.id`, `config.key`, `schema_migrations.version`,
  `query_expansions.input_hash`).
- **Soft delete:** long-lived memory rows are never hard-deleted in normal operation —
  `active boolean default true` marks liveness; partial indexes keep active-row queries
  fast. `active=false` means retired/superseded/pruned; `ended_at` on episodes marks
  lifecycle completion (an ended episode is *not* inactive).
- **Embeddings:** `vector(1536)` (pgvector) on every searchable content table
  (`facts`, `episodes`, `episode_chunks`, `decisions`, `procedures`, `censors`),
  produced by OpenAI `text-embedding-3-*` at 1536 dimensions, indexed with **HNSW**
  (`vector_cosine_ops`).
- **Full-text search:** `search_tsv tsvector` is a **generated column** (not written by
  the application) on `facts`, `episodes`, `episode_chunks`, `decisions`, `procedures`,
  with GIN indexes. Hybrid retrieval fuses the vector and FTS legs with reciprocal-rank
  fusion.
- **Timestamps:** `created_at`/`updated_at timestamptz default now()`; `updated_at` is
  trigger-maintained on mutation-heavy tables (facts).

### Key relationships (text ER)

```
nous_system.agents 1──* (agent_id, informal) most tables
heart.episodes 1──* heart.episode_chunks         (verbatim transcript chunks)
heart.episodes 1──* heart.facts                  (source_episode_id: provenance)
heart.facts    1──* heart.fact_entity_keys       (bidirectional entity-key index)
heart.facts    *──1 heart.facts                  (superseded_by: version chains)
heart.facts    *──1 heart.facts                  (contradiction_of: KEEP-BOTH pairs)
brain.decisions 1──* brain.decision_reasons / decision_tags / thoughts / decision_bridge
brain.decisions *──1 brain.decisions             (superseded_by)
brain.graph_edges: (source_id, source_type) ── relation ──> (target_id, target_type)
                   node types: decision | fact | episode | procedure | chunk
heart.episode_decisions / episode_procedures     (m:n join tables)
nous_system.execution_dags 1──* dag_nodes 1──* dag_edges;  dag_nodes 1──? heart.subtasks
```

---

## 2. Schema `heart` — memory

### 2.1 `heart.facts` — the semantic store (35 columns)

The central long-term memory table. One row = one atomic learned statement. Facts are
written by session-end extraction, direct user statements, the enumerative extractor
(dense documents), the exemplar extractor (labeled-example streams), reflection, and
consolidation. Conflicting versions of the same statement form supersession chains;
retrieval only ever serves `active = true` rows.

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | uuid | NO | gen_random_uuid() | PK |
| `agent_id` | varchar(100) | NO | | Owning agent |
| `content` | text | NO | | The statement itself (natural language) |
| `category` | varchar(100) | YES | | Typed category (`rule`, `preference`, `person`, `event`, `status`, `exemplar`, …) — drives admission priors and tier-1 profile injection |
| `subject` | varchar(500) | YES | | Free-text grammatical subject of the statement |
| `confidence` | double | YES | 1.0 | Belief strength; decremented −0.2 on an unresolved KEEP-BOTH contradiction |
| `source` | varchar(500) | YES | | Write path that produced the row: `fact_extractor`, `episode_summarizer`, `user_stated`, `reflection`, `enumerative_extractor`, `exemplar_extractor`, `cluster_consolidation`, … Gates admission bypass and source-specific behavior |
| `source_episode_id` | uuid | YES | FK → episodes | Provenance: episode this was learned from |
| `source_decision_id` | uuid | YES | FK → brain.decisions | Provenance: decision this was learned from |
| `learned_at` | timestamptz | NO | now() | When learned — the **statement-order tiebreaker** for conflict resolution across episodes |
| `last_confirmed` | timestamptz | YES | | Last dedup-confirm touch |
| `confirmation_count` | int | YES | 0 | Times a near-duplicate re-assertion confirmed this row |
| `superseded_by` | uuid | YES | FK → facts | Set when a later statement won a conflict; row is simultaneously deactivated. Chains form version history |
| `contradiction_of` | uuid | YES | FK → facts | KEEP-BOTH marker: this row contradicts another but no ordering signal existed; both stay active |
| `embedding` | vector(1536) | YES | | Content embedding (HNSW-indexed) |
| `tags` | text[] | YES | | Free labels (GIN-indexed) |
| `search_tsv` | tsvector | YES | generated | FTS document (GIN) |
| `active` | boolean | YES | true | Liveness; retrieval filters on this |
| `encoded_frame` | varchar(100) | YES | | Frame active when learned (frame-boost retrieval feature) |
| `encoded_censors` | jsonb | YES | | Censors active at encoding time |
| `created_at` / `updated_at` | timestamptz | YES | now() | Row lifecycle; `updated_at` is the supersession-backfill rollback watermark |
| `admission_score` | double | YES | | Composite admission-controller score at write |
| `admission_scores` | jsonb | YES | | Per-dimension breakdown (utility/confidence/novelty/recency/type_prior) |
| `recall_count` | int | YES | 0 | Times served by retrieval (usage boost input) |
| `last_recalled_at` | timestamptz | YES | | Stale-scan input |
| `actionable` | boolean | YES | | Actionability classification (is this a task-relevant instruction?) |
| `actionable_confidence` | real | YES | | Classifier confidence |
| `event_date` | date | YES | | Date the fact's *event* occurred (temporal reasoning); two facts with differing non-null event_dates are distinct events and are **never** deduped or superseded against each other |
| `event_date_classified_at` | timestamptz | YES | | When the date classifier ran (null = pending) |
| `subject_key` | varchar(200) | YES | | **Canonical-normalized** subject entity key (lowercase, article/possessive/punctuation-stripped). Half of the conflict slot |
| `attribute_key` | varchar(100) | YES | | Canonical attribute/relation key (e.g. `author`, `capital`, `label`). The other half of the conflict slot |
| `source_ordinal` | bigint | YES | | Statement position within the source episode — the primary same-episode conflict-order signal |
| `overrides_prior` | boolean | YES | | Statement was phrased as a correction/update |
| `entity_keys_extracted_at` | timestamptz | YES | | Stamp: value-side entity keys fully emitted for this row (entity-key backfill watermark) |

**Conflict-slot semantics** (`subject_key`, `attribute_key`): two active facts sharing
both keys but differing in value are an *update pair*, not duplicates — they route to
conflict resolution, where the later-stated one wins (`source_ordinal` within an
episode, `learned_at` across episodes) and the loser gets `superseded_by` +
`active=false`. Pairs with no ordering signal are kept both, cross-marked via
`contradiction_of`, and flagged with a `contradicts` graph edge.

**Notable indexes:** `idx_facts_embedding` HNSW; `idx_facts_fts` GIN;
`idx_facts_conflict_slot` btree `(agent_id, subject_key, attribute_key) WHERE subject_key
IS NOT NULL AND active` (conflict lookup); `idx_facts_exemplar_embedding` **partial
HNSW** `WHERE source='exemplar_extractor' AND active` (keeps exemplar k-NN off the
global index); `idx_facts_event_date_agent`; `idx_facts_agent_subject_lower`;
`idx_facts_stale_candidates`.

### 2.2 `heart.fact_entity_keys` — bidirectional entity-key index (4 columns)

Exact-lookup retrieval index over facts. Every enumerative/keyed fact gets one row per
participating entity (subject **and** proper-noun values), all in the same canonical
normalization as `subject_key`. This is what makes "Who wrote X?" find a fact keyed
under both `x` and its author. Rows are **not** soft-deleted: they survive supersession,
so reads MUST join `facts` on `active = true`.

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `fact_id` | uuid | NO | FK → facts | PK part 1 |
| `entity_key` | varchar(200) | NO | | Canonical entity key. PK part 2 |
| `agent_id` | varchar(100) | NO | | Scope (denormalized for the covering index) |
| `created_at` | timestamptz | NO | now() | |

**Indexes:** PK `(fact_id, entity_key)`; `idx_fact_entity_keys_agent_key
(agent_id, entity_key)` — the retrieval path.

### 2.3 `heart.episodes` — episodic memory (27 columns)

One row per conversation/work session. Created at session start, finalized at session
close (summary, duration, outcome), then enriched asynchronously (structured summary,
chunking, fact extraction). Episodes are the provenance root of most memory.

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | uuid | NO | gen_random_uuid() | PK |
| `agent_id` | varchar(100) | NO | | |
| `title` | varchar(500) | YES | | LLM-generated episode title |
| `summary` | text | NO | | Narrative summary |
| `detail` | text | YES | | Longer-form detail |
| `started_at` / `ended_at` | timestamptz | | now() / null | Session lifecycle. `ended_at IS NOT NULL` = normally closed. **Liveness ≠ lifecycle:** backfills must include closed episodes |
| `duration_seconds` | int | YES | | |
| `frame_used` | varchar(100) | YES | | Cognitive frame active during the session |
| `trigger` | varchar(100) | YES | | What started the session |
| `participants` | text[] | YES | | |
| `outcome` | varchar(50) | YES | | success/failure/neutral judgment |
| `surprise_level` | double | YES | | Novelty signal from the session |
| `lessons_learned` | text[] | YES | | Extracted `learned:` reflections |
| `embedding` | vector(1536) | YES | | Summary embedding (HNSW) |
| `tags` | text[] | YES | | GIN |
| `search_tsv` | tsvector | YES | generated | GIN |
| `active` | boolean | YES | true | Soft delete (trivial episodes are discarded) |
| `encoded_censors` | jsonb | YES | | |
| `compression_tier` | varchar(20) | YES | 'raw' | Sleep compression state (raw → compressed) |
| `created_at` | timestamptz | YES | now() | |
| `structured_summary` | jsonb | YES | | Machine-readable summary (entities, topics, key events) — GIN-indexed |
| `user_id` / `user_display_name` | varchar(100) | YES | | Human participant identity |
| `compaction_count` | int | NO | 0 | Times the live conversation was compacted mid-session |
| `transcript` | text | YES | | Persisted transcript (capped) |
| `session_id` | varchar(100) | YES | | Chat session correlation key |

**Notable indexes:** HNSW embedding, GIN fts/tags/structured_summary,
`idx_episodes_session_id (agent_id, session_id, started_at DESC)`.

### 2.4 `heart.episode_chunks` — verbatim transcript chunks (10 columns)

Full-fidelity retrieval channel: the episode transcript split into ~600-character
overlapping chunks, each individually embedded and FTS-indexed. In benchmark
measurement this channel carried the majority of answerable content — it is the
lossless complement to summarized/extracted memory.

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | uuid | NO | gen_random_uuid() | PK |
| `agent_id` | varchar(100) | NO | | |
| `episode_id` | uuid | NO | FK → episodes | |
| `chunk_index` | int | NO | | Position in the transcript (unique with episode_id) |
| `content` | text | NO | | Verbatim chunk text |
| `embedding` | vector(1536) | YES | | HNSW |
| `search_tsv` | tsvector | YES | generated | GIN |
| `created_at` | timestamptz | YES | now() | |
| `source_kind` | varchar(32) | NO | 'dialogue' | Content class: `dialogue`, `document`, `code` — lets backfills/retrieval target a class |
| `source_ref` | text | YES | | Optional pointer to external source |

### 2.5 `heart.procedures` — procedural memory / skills (28 columns)

K-line style skill records generalized from successful episodes during sleep: what
worked, which tools/patterns/concepts it used, when to activate it. Injected into
context via a catalog (breadth) + full-body retrieval (depth) and tracked for
effectiveness.

Key columns: `name`, `domain`, `description`, `goals[]`, `core_patterns[]`,
`core_tools[]`, `core_concepts[]`, `implementation_notes[]` (the skill body);
`activation_count` / `success_count` / `failure_count` / `neutral_count` /
`last_activated` (effectiveness telemetry); `related_procedures uuid[]`,
`censor_ids uuid[]` (cross-links); `embedding` (HNSW), `tags[]`, `search_tsv`;
`active`, `superseded_by` (procedure evolution), `archived_at`; `runtime_metadata
jsonb`; `encoded_frame` / `encoded_censors` (encoding context).

### 2.6 `heart.procedure_task_affinity` — procedure↔frame fit (9 columns)

Per-(procedure, frame_type, agent) activation statistics: `activation_count`,
`success_count`, `failure_count`, `last_activated_at`, `active`. Drives graph-primary
procedure selection — which skills get recommended under which cognitive frame.
Unique on `(procedure_id, frame_type, agent_id)`.

### 2.7 `heart.censors` — learned prohibitions/steering rules (23 columns)

Minsky-style censors: patterns the agent must avoid or steer around, learned from bad
outcomes or set manually. Matched per-turn (embedding + pattern), injected as "Active
Censors", and enforced with configurable action.

Key columns: `trigger_pattern` (what activates it), `action` (`steer`/`block`/…),
`action_instruction`, `unblock_pattern`, `trigger_action jsonb`; `reason`, `domain`;
provenance (`learned_from_decision` FK, `learned_from_episode` FK, `created_by`,
`provenance` human/learned); effectiveness (`activation_count`,
`false_positive_count`, `escalation_threshold`, `last_activated`,
`last_false_positive`); `refuse_keep_tools` (on refuse, keep tool access);
`embedding` (HNSW), `active`.

### 2.8 `heart.working_memory` — per-session scratch state (10 columns)

One row per `(agent_id, session_id)` (unique). Holds the current task, active frame,
a bounded `items jsonb` list (`max_items` default 20), and `open_threads jsonb`
(unfinished business surfaced at session start). Injected each turn as the "Working
Memory" section.

### 2.9 `heart.conversation_state` — live transcript state (9 columns)

Rolling conversation buffer for active sessions: `messages jsonb`, `summary` (rolling
compaction summary), `turn_count`, `compaction_count`. Unique on
`(agent_id, session_id)`. Distinct from episodes: this is the *live* state; the
episode is the durable record written at close.

### 2.10 `heart.outcome_signals` — behavioral outcome detection (8 columns)

Rubric-scored outcome signals per episode (`signal_type`, `confidence`, `evidence`,
`self_improvement_scores jsonb`). **FK `agent_id → nous_system.agents`** — one of the
few hard agent FKs; inserts for unregistered agents fail (relevant for ephemeral eval
agents; the eval disables this feature).

### 2.11 `heart.subtasks` — spawned background tasks (29 columns)

Queue + result store for agent-spawned subtasks (the agentic "spawn a worker" path).
Key columns: `task`, `parent_session_id`, `priority`, `status`
(pending/running/completed/failed), `result` / `error` / `report_jsonb` /
`final_outcome`, `worker_id`, `timeout_seconds`, `notify`, `delivered`, retry
`attempts`, token/tool telemetry (`tokens_in/out`, `tool_calls_made`), execution
config (`frame_type`, `model`, `output_format`, `success_criteria`), DAG linkage
(`dag_node_id` FK → `nous_system.dag_nodes`), `payload_schema` (+`_valid`).

### 2.12 `heart.schedules` — timers and cron (23 columns)

Agent-created scheduled tasks: `task` prompt, `schedule_type` (once/interval/cron),
`fire_at` / `interval_seconds` / `cron_expr`, firing state (`last_fired_at`,
`next_fire_at`, `fire_count`, `max_fires`), execution config (`model`, `frame_type`,
`timeout_seconds`, `notify`), and continuation support (`continuation_turns`,
`continuation_session_id`, `continuation_prompt`, `continuation_count`) for
multi-turn scheduled work. Disabled in eval (heartbeat/scheduler off).

### 2.13 `heart.tool_cache` — F020 result cache (9 columns)

Per-session cache of large tool results, compressed out of live context:
`hash_key` (unique with session), `tool_name`, `tool_input jsonb`,
`original_content`, `item_count`. Surfaced as "Cached Results" hints so the agent can
re-reference earlier tool output without re-running the tool.

### 2.14 `heart.query_expansions` — retrieval query-variant cache (7 columns)

LLM-generated query expansion variants keyed by `input_hash` (bytea PK):
`query_text`, `variants jsonb`, `model`, `hit_count`, `last_used_at`. Avoids paying
the expansion model on repeat queries.

### 2.15 `heart.rubric_versions` — evolving self-assessment rubric (9 columns)

Versioned rubric definitions for outcome detection: `version` / `parent_version`
lineage, `dimensions jsonb`, `outcome_correlations jsonb`, `status`, `change_reason`.
FK `agent_id → nous_system.agents`. Sleep-phase rubric evolution writes new versions.

### 2.16 `heart.episode_decisions` / `heart.episode_procedures` — m:n joins

`episode_decisions (episode_id, decision_id)`: which decisions were made during an
episode. `episode_procedures (episode_id, procedure_id, effectiveness)`: which
procedures were applied and how well they worked (feeds procedure statistics).

---

## 3. Schema `brain` — decisions and the knowledge graph

### 3.1 `brain.decisions` — decision records (20 columns)

Every non-trivial decision the agent makes, with calibration tracking. Searchable
(embedding + FTS) and retrievable into context as "Related Decisions".

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | uuid | NO | gen_random_uuid() | PK |
| `agent_id` | varchar(100) | NO | | |
| `description` | text | NO | | The decision statement |
| `context` | text | YES | | Situation at decision time |
| `pattern` | text | YES | | Extracted generalizable principle (if any) |
| `confidence` | double | NO | | Calibrated confidence (post-adjustment) |
| `confidence_raw` | double | YES | | Raw pre-calibration confidence |
| `category` | varchar(50) | NO | | architecture/process/tooling/… |
| `stakes` | varchar(20) | NO | | low/medium/high/critical |
| `quality_score` | double | YES | | Deliberation-quality score (reasons, tags present) |
| `outcome` | varchar(20) | YES | 'pending' | pending/success/failure/partial — the calibration ground truth |
| `outcome_result` | text | YES | | What actually happened |
| `reviewed_at` / `reviewer` | | YES | | Outcome review bookkeeping (partial index on unreviewed) |
| `embedding` | vector(1536) | YES | | HNSW |
| `search_tsv` | tsvector | YES | generated | GIN |
| `session_id` | varchar(100) | YES | | Originating session |
| `superseded_by` | uuid | YES | FK → decisions | Decision revision chain |
| `created_at` / `updated_at` | timestamptz | YES | now() | |

### 3.2 `brain.decision_reasons` — typed reasoning (5 columns)

One row per reason attached to a decision: `type` (analysis, pattern, empirical,
authority, analogy, constraint, elimination, intuition) + `text`. Reason-type mix
feeds decision quality scoring and calibration-by-reason statistics.

### 3.3 `brain.thoughts` — deliberation micro-traces (5 columns)

Streamed atomic deliberation signals (`text`) scoped to a decision
(`decision_id` FK) and agent. The raw thinking trail behind a decision record.

### 3.4 `brain.decision_tags` — decision labels (2 columns)

`(decision_id, tag)` composite PK. Free-form tags for retrieval/analytics.

### 3.5 `brain.decision_bridge` — analogy bridges (3 columns)

Per-decision structure/function abstraction (`structure`, `function` texts):
a normalized restatement of the decision used for cross-domain analogy matching
("this decision has the same *shape* as that one").

### 3.6 `brain.graph_edges` — the typed knowledge graph (14 columns)

Cross-type edges connecting all memory node kinds. The graph serves retrieval
expansion, contradiction surfacing, procedure selection, and consolidation.

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `id` | uuid | NO | gen_random_uuid() | PK |
| `agent_id` | varchar(100) | NO | | |
| `source_id` / `target_id` | uuid | NO | | Endpoint ids (no hard FK — polymorphic) |
| `source_type` / `target_type` | varchar(20) | NO | 'decision' | `decision` \| `fact` \| `episode` \| `procedure` \| `chunk` |
| `relation` | varchar(50) | NO | | `supports`, `contradicts`, `supersedes`, `related_to`, `caused_by`, `informed_by`, `evidence_for`, `discussed_in`, `extracted_from`, `part_of`, `summarized_by`, `happened_before`, `co_occurred` |
| `weight` | double | YES | 1.0 | Edge strength |
| `auto_linked` | boolean | YES | false | Created by automatic linking vs explicit |
| `extraction_method` | varchar(20) | NO | 'heuristic' | `deterministic` \| `heuristic` \| `inferred` \| `co_mention` \| `co_occurrence` — provenance/quality tier |
| `consolidation_state` | text | NO | 'tagged' | Synaptic-consolidation state (tagged → consolidated) |
| `ltp_count` | int | NO | 0 | Long-term-potentiation counter (co-activation) |
| `last_ltp_at` | timestamptz | YES | | |
| `created_at` | timestamptz | YES | now() | Rollback watermark for edge-writing backfills |

**Unique:** `(source_id, target_id, relation)`. Partial index
`idx_graph_edges_stc_tagged (agent_id, ltp_count) WHERE consolidation_state='tagged'`.

### 3.7 `brain.guardrails` — hard decision constraints (11 columns)

Named rule conditions (`condition jsonb`) checked before actions: `severity`
(warn/block), `priority`, activation telemetry, `active`. Unique `(agent_id, name)`.

### 3.8 `brain.calibration_snapshots` — calibration history (11 columns)

Periodic snapshots of decision-calibration state: `total_decisions`,
`reviewed_decisions`, `brier_score`, `accuracy`, confidence mean/stddev, and
per-category / per-reason-type breakdowns (`category_stats`, `reason_stats` jsonb).

### 3.9 `brain.graph_hub_snapshots` — hub-degree history (7 columns)

Periodic top-N node-degree snapshots (`node_id`, `node_type`, `degree`, `rank`) —
telemetry for hub formation (retrieval hot-spots) and its pruning policy.

---

## 4. Schema `nous_system` — infrastructure & orchestration

### 4.1 `nous_system.agents` — agent registry (9 columns)

Natural-key registry (`id varchar(100)` PK): `name`, `description`, `config jsonb`,
`active`, `last_active`, `is_initiated` (identity-protocol completion). Referenced by
hard FK only from `outcome_signals`, `rubric_versions`, `agent_identity`, `frames`;
everything else scopes by convention.

### 4.2 `nous_system.agent_identity` — versioned identity documents (9 columns)

Sectioned identity prompt with full version history: `(agent_id, section, content,
version, is_current, previous_version_id self-FK, updated_by)`. The current sections
compose the identity block injected at the top of every system prompt.

### 4.3 `nous_system.frames` — cognitive frames (15 columns)

Frame definitions (natural-key `id`): `name`, `description`, `activation_patterns[]`,
`questions_to_ask[]`, `agencies_to_activate[]`, `suppressed_frames[]`,
`frame_censors[]`, `default_category` / `default_stakes` (decision defaults), usage
telemetry. The frame selector matches these per turn; the chosen frame shapes
retrieval budgets, prompts, and decision defaults.

### 4.4 `nous_system.events` — event bus journal (9 columns)

Append-only event log: `event_type` (`session_ended`, `episode_summarized`,
`sleep_started`, `fact_rejected`, …), `data jsonb`, `session_id`, and causality
tracing (`event_id`, `trace_id`, `caused_by`). The async write-path handlers
(summarizer, extractors, sleep) subscribe to these events.

### 4.5 `nous_system.context_log` — per-turn context telemetry (29 columns)

One row per LLM call: model, frame, token accounting (`token_breakdown jsonb`,
`total_tokens_est`, `input_tokens_actual`, `output_tokens`, `cache_creation`,
`cache_read`), context composition (`sections_present[]`, `loaded_facts/decisions/
procedures/episodes`, `recent_conversations`), tool surface (`tools_count`,
`tool_names[]`), message stats, `utilization_pct`, `duration_ms`, `stop_reason`.
The primary observability table for context-engineering work.

### 4.6 Orchestration: `execution_dags`, `dag_nodes`, `dag_edges`, `work_queue_items`

- **`execution_dags`** (15 cols): a planned multi-step execution — `name`, `status`,
  `source`, `original_request`, `token_budget` / `tokens_consumed`, `result_summary`,
  `postmortem jsonb`, per-frame concurrency caps.
- **`dag_nodes`** (34 cols): one executable node — `node_type`, `wave` (parallel
  stage), `status`, `instructions`, `tools jsonb`, `frame_type`, `model`, timeout,
  completion checking (`completion_condition`, `completion_check`, check
  attempts/intervals), stall detection (`last_activity_at`,
  `stall_timeout_seconds`), self-repair (`fix_actions jsonb`, `max_fix_attempts`),
  results and token usage. Unique `(dag_id, name)`; `subtask_id` links to the
  executing `heart.subtasks` row.
- **`dag_edges`** (5 cols): dependencies between nodes (`edge_type` default
  `dependency`); unique per (dag, from, to, type).
- **`work_queue_items`** (9 cols): external work intake (`source`, `external_id`
  unique per agent+source) dispatched into DAGs (`dag_id`, `terminal_state`,
  `payload jsonb`).

### 4.7 Consolidation audit: `consolidation_cycles`, `consolidation_actions`

Sleep-cycle audit trail. `consolidation_cycles` (8 cols): one row per sleep run —
`trace_id`, `status`, `phases_run[]`, `totals jsonb`. `consolidation_actions`
(12 cols): every mutation a phase performed — `phase`, `op`, `target_ids[]`,
`before`/`after` jsonb snapshots, `rationale`, `seq`. Answers "what did sleep do to
my memory and why".

### 4.8 Monitoring & self-improvement: `behavior_snapshots`, `dynamic_checks`, `eval_runs`

- **`behavior_snapshots`** (6 cols, serial PK): periodic behavioral metrics
  (`metrics jsonb`) with detected `anomalies jsonb`.
- **`dynamic_checks`** (21 cols): agent-authored recurring health checks — `prompt`,
  `tools[]`, `cron_expr`/`interval_seconds`, `urgent`, run/error telemetry,
  `on_complete_prompt`/`on_complete_tools[]` follow-ups. Unique `(agent_id, name)`.
- **`eval_runs`** (10 cols): recorded retrieval-evaluation runs — `git_sha`,
  `fixture_version`, `configs`/`metrics`/`qrel_counts` jsonb, `report_path`.

### 4.9 Plumbing: `config`, `schema_migrations`, `_backfill_*`

- **`config`**: key→jsonb runtime configuration overrides.
- **`schema_migrations`**: applied migration ledger (`version`, `name`, `checksum`,
  `applied_at`). Migrations are applied at server boot — **scripts never migrate**;
  a backfill against a never-booted database will fail on missing columns.
- **`_backfill_20260724_rule_recat`**: transient backfill working table (id,
  category, subject snapshot); safe to drop after its backfill is verified.

---

## 5. Operational notes

1. **Always filter `active = true`** when reading facts/episodes/procedures/censors
   for retrieval purposes; supersession and pruning deactivate rather than delete.
2. **`fact_entity_keys` has no liveness of its own** — join through `facts.active`.
3. **Two watermark conventions for backfills:** `facts.updated_at` (supersession
   rollback) and `created_at` (insert rollback); every production backfill prints its
   rollback key at start. Exemplar backfills additionally write an exact-id manifest.
4. **The `search_tsv` columns are generated** — never write them; restores recreate
   them automatically.
5. **HNSW indexes dominate restore time**; run `ANALYZE` after any `pg_restore`
   (planner statistics are not contained in dumps).
6. **Polymorphic graph endpoints** (`graph_edges.source_id/target_id`) have no FK —
   integrity is maintained by the application plus a sleep phase that prunes edges
   whose endpoints became inactive.
7. **Hard agent FKs exist only on** `outcome_signals`, `rubric_versions`,
   `agent_identity`, `frames` — creating memory for an unregistered `agent_id`
   works everywhere else (ephemeral eval agents rely on this).
