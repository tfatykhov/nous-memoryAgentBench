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

This is a HEURISTIC, not an oracle. We search only RECALL-ACCESSIBLE storage
(facts/episode_chunks/episodes summaries — what nous can actually retrieve), and
deliberately exclude heart.episodes.transcript: the raw transcript is stored but
NOT searched by recall, so if the gold survives only there it is correctly a
"write_loss" w.r.t. usable memory. Matching uses WORD BOUNDARIES (so gold "43"
does not match "143") with regex metacharacters escaped, and excludes superseded
rows (active = FALSE). Residual error remains: a gold that appears verbatim in
stored text but is unrelated to the answer still reads as "stored". Treat the
attribution split as a strong signal, not ground truth.

Content sources (verified against nous schema): heart.facts.content (active),
heart.episode_chunks.content, heart.episodes.summary + structured_summary::text
(active), brain.decisions.description — all agent_id-scoped.
"""

from __future__ import annotations

import logging
import re

from mab.config import HarnessSettings

logger = logging.getLogger("mab.diagnostics")

# (schema.table, text-column-expression, has_active_column) to search.
_CONTENT_SOURCES = [
    ("heart.facts", "content", True),
    ("heart.episode_chunks", "content", False),
    ("heart.episodes", "summary", True),
    ("heart.episodes", "structured_summary::text", True),
    ("brain.decisions", "description", False),
]


def _word_boundary_regex(gold: str) -> str:
    """POSIX regex matching ``gold`` as a whole token (word boundaries where the
    gold edge is a word char), with all regex metacharacters escaped."""
    escaped = re.escape(gold)
    left = r"\y" if (gold[:1].isalnum() or gold[:1] == "_") else ""
    right = r"\y" if (gold[-1:].isalnum() or gold[-1:] == "_") else ""
    return f"{left}{escaped}{right}"


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
                    pattern = _word_boundary_regex(gold)
                    for table, col, has_active in _CONTENT_SOURCES:
                        active = "AND active = TRUE " if has_active else ""
                        cur.execute(
                            f"SELECT 1 FROM {table} "  # noqa: S608 - table/col are constants
                            f"WHERE agent_id = %s {active}AND {col} ~* %s LIMIT 1",
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
