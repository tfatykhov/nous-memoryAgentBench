"""Failure attribution: was a wrong answer a write-loss or a stored-but-wrong?

We query the eval DB (the authoritative ground truth) for the run's agent_id and
check whether any gold answer string was actually stored in nous's memory —
independent of nous's retrieval. This localizes a failure:

- ``success``           — the answer was graded correct.
- ``write_loss``        — no gold string is present anywhere in the agent's
                          stored memory (facts/episode_chunks/episodes/decisions);
                          the needle was lost at ingestion/consolidation.
- ``stored_but_wrong``  — a gold string IS stored but the answer was wrong, so the
                          failure is downstream (retrieval ranking or synthesis).
- ``unknown``           — diagnostics unavailable (e.g. psycopg missing).

Content columns (verified against nous schema): heart.facts.content,
heart.episode_chunks.content, heart.episodes.summary + structured_summary::text,
brain.decisions.description — all agent_id-scoped.
"""

from __future__ import annotations

import logging

from mab.config import HarnessSettings

logger = logging.getLogger("mab.diagnostics")

# (schema.table, text-column-expression) pairs to search for a gold substring.
_CONTENT_SOURCES = [
    ("heart.facts", "content"),
    ("heart.episode_chunks", "content"),
    ("heart.episodes", "summary"),
    ("heart.episodes", "structured_summary::text"),
    ("brain.decisions", "description"),
]


class DiagnosticsUnavailable(RuntimeError):
    """Raised when the eval DB cannot be queried (e.g. psycopg missing)."""


def _dsn(settings: HarnessSettings) -> str:
    return (
        f"host={settings.db_host} port={settings.db_port} dbname={settings.db_name} "
        f"user={settings.db_user} password={settings.db_password}"
    )


def gold_in_memory(settings: HarnessSettings, agent_id: str, golds: list[str]) -> bool:
    """True if any gold string is stored in this agent's memory (case-insensitive)."""
    candidates = [g for g in golds if g and g.strip()]
    if not candidates:
        return False
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - optional dep
        raise DiagnosticsUnavailable(
            "psycopg is required for failure attribution (pip install 'psycopg[binary]')."
        ) from exc

    try:
        with psycopg.connect(_dsn(settings), autocommit=True, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                for gold in candidates:
                    pattern = f"%{gold}%"
                    for table, col in _CONTENT_SOURCES:
                        cur.execute(
                            f"SELECT 1 FROM {table} "  # noqa: S608 - table/col are constants
                            f"WHERE agent_id = %s AND {col} ILIKE %s LIMIT 1",
                            (agent_id, pattern),
                        )
                        if cur.fetchone() is not None:
                            return True
        return False
    except psycopg.Error as exc:
        raise DiagnosticsUnavailable(f"eval DB query failed: {exc}") from exc


def classify(correct: bool, ingested: bool) -> str:
    """Map (graded-correct, gold-stored-in-memory) to an attribution label."""
    if correct:
        return "success"
    return "stored_but_wrong" if ingested else "write_loss"
