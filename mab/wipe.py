"""Optional FK-safe wipe of one agent_id from the eval DB.

Isolation is provided by a UNIQUE agent_id per run, so wiping is housekeeping
(keeps the shared eval DB from growing across runs), never a correctness
dependency. Requires `psycopg` (optional dep); imported lazily.

Deletion order is FK-safe per the verified schema: children of episodes and
decisions cascade or are deleted first, then facts (non-cascade FKs), then the
agent_id-scoped tables.
"""

from __future__ import annotations

import logging

from mab.config import HarnessSettings

logger = logging.getLogger("mab.wipe")

# Tables to delete (in FK-safe order) that carry an agent_id column.
_AGENT_SCOPED_ORDER = [
    "heart.episode_chunks",       # CASCADE from episodes, but explicit is safe
    "heart.facts",                # source_episode_id / source_decision_id (non-cascade)
    "brain.decisions",            # cascades thoughts/tags/reasons/bridge/episode_decisions
    "heart.episodes",             # cascades episode_chunks/episode_decisions/episode_procedures
    "brain.graph_edges",
    "heart.procedures",
    "heart.censors",
    "heart.working_memory",
    "heart.conversation_state",
    "heart.subtasks",
    "heart.schedules",
    "heart.tool_cache",
    "brain.guardrails",
    "brain.calibration_snapshots",
    "nous_system.events",
    "nous_system.frames",
    "nous_system.agent_identity",
]


def wipe_agent(settings: HarnessSettings, agent_id: str) -> dict[str, int]:
    """Delete all rows for ``agent_id``. Returns {table: rows_deleted}."""
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - optional dep
        raise RuntimeError(
            "wipe_agent requires the 'psycopg' package (pip install psycopg[binary])."
        ) from exc

    dsn = (
        f"host={settings.db_host} port={settings.db_port} dbname={settings.db_name} "
        f"user={settings.db_user} password={settings.db_password}"
    )
    deleted: dict[str, int] = {}
    with psycopg.connect(dsn, autocommit=False) as conn:
        with conn.cursor() as cur:
            for table in _AGENT_SCOPED_ORDER:
                try:
                    cur.execute(f"DELETE FROM {table} WHERE agent_id = %s", (agent_id,))
                    deleted[table] = cur.rowcount
                except psycopg.errors.UndefinedTable:
                    conn.rollback()
                    logger.warning("table %s missing; skipping", table)
        conn.commit()
    logger.info("wiped agent_id=%s: %s", agent_id, deleted)
    return deleted
