"""nous "memory method": drive ingest / consolidation / answering over HTTP.

Implements the MemoryAgentBench-style interface against a running nous server:

    ingest(instance)   -> feed context as /chat turns in one session, DELETE to
                          force the post-session durable-write chain, then settle
    consolidate()      -> trigger a sleep cycle and wait for it to complete
    answer(prompt)     -> ask one question in a FRESH session, return the answer

Settle is event-based where a reliable signal exists (sleep via total_sleeps;
ingest via the episode_summarized event), with count/quiescence fallback and an
always-logged timeout. JSON shapes from /events/* are parsed defensively.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field

import httpx

from mab.config import HarnessSettings
from mab.datasets import MabInstance

logger = logging.getLogger("mab.adapter")


@dataclass
class IngestStats:
    chunks_sent: int
    chunks_truncated: int
    input_tokens: int = 0
    output_tokens: int = 0
    settled: bool = True
    notes: list[str] = field(default_factory=list)


def chunk_context(instance: MabInstance, chunk_chars: int, max_chunks: int) -> tuple[list[str], int]:
    """Return (chunks, n_truncated). Prefer MAB's pre-chunked turns when present."""
    if instance.haystack_turns:
        texts = [str(t.get("content", "")) for t in instance.haystack_turns if t.get("content")]
    else:
        ctx = instance.context
        texts = [ctx[i : i + chunk_chars] for i in range(0, len(ctx), chunk_chars)]
    truncated = max(0, len(texts) - max_chunks)
    return texts[:max_chunks], truncated


class NousMemoryMethod:
    def __init__(self, client: httpx.AsyncClient, base_url: str, settings: HarnessSettings):
        self._client = client
        self._base = base_url.rstrip("/")
        self._s = settings

    # --- HTTP helpers ---------------------------------------------------
    async def _post_chat(self, message: str, session_id: str, debug: bool = False) -> dict:
        r = await self._client.post(
            f"{self._base}/chat",
            json={"message": message, "session_id": session_id, "debug": debug},
            timeout=600.0,
        )
        r.raise_for_status()
        return r.json()

    async def _delete_session(self, session_id: str) -> None:
        r = await self._client.delete(f"{self._base}/chat/{session_id}", timeout=60.0)
        # tolerate already-gone sessions
        if r.status_code not in (200, 404):
            r.raise_for_status()

    async def _status_counts(self) -> dict:
        r = await self._client.get(f"{self._base}/status", timeout=30.0)
        r.raise_for_status()
        return (r.json() or {}).get("memory", {}) or {}

    def _sleep_stats_from(self, payload: dict) -> dict:
        """Defensively pull sleep_handler stats out of /events/stats."""
        # Expected: {"component_stats": {"sleep_handler": {currently_sleeping, total_sleeps, ...}}}
        comp = payload.get("component_stats") or payload.get("components") or {}
        sh = comp.get("sleep_handler") or {}
        # Fallbacks if flattened.
        total = sh.get("total_sleeps", payload.get("total_sleeps"))
        sleeping = sh.get("currently_sleeping", payload.get("currently_sleeping"))
        return {"total_sleeps": total, "currently_sleeping": sleeping}

    async def _events_stats(self) -> dict:
        r = await self._client.get(f"{self._base}/events/stats", timeout=30.0)
        r.raise_for_status()
        return self._sleep_stats_from(r.json() or {})

    async def _count_event_type(self, event_type: str) -> int:
        """Count recent events of a type. Defensive against response shape."""
        try:
            r = await self._client.get(f"{self._base}/events/recent", timeout=30.0)
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError):
            return -1  # signal "unavailable"
        events = data.get("events", data) if isinstance(data, dict) else data
        if not isinstance(events, list):
            return -1
        return sum(1 for e in events if isinstance(e, dict) and e.get("type") == event_type)

    # --- pipeline -------------------------------------------------------
    async def ingest(self, instance: MabInstance) -> IngestStats:
        chunks, truncated = chunk_context(instance, self._s.chunk_chars, self._s.max_ingest_chunks)
        stats = IngestStats(chunks_sent=len(chunks), chunks_truncated=truncated)
        if truncated:
            stats.notes.append(f"truncated {truncated} chunks over cap {self._s.max_ingest_chunks}")
            logger.warning("ingest truncated %d chunks (cap %d) for %s",
                           truncated, self._s.max_ingest_chunks, instance.instance_id)

        session_id = f"ingest-{instance.instance_id}-{uuid.uuid4().hex[:8]}"
        baseline_summarized = await self._count_event_type("episode_summarized")
        for idx, chunk in enumerate(chunks):
            preamble = (
                "Please remember the following information for later questions "
                f"(part {idx + 1}/{len(chunks)}):\n\n"
            )
            resp = await self._post_chat(preamble + chunk, session_id)
            usage = resp.get("usage", {}) or {}
            stats.input_tokens += int(usage.get("input_tokens", 0) or 0)
            stats.output_tokens += int(usage.get("output_tokens", 0) or 0)

        await self._delete_session(session_id)
        stats.settled = await self._settle_ingest(baseline_summarized)
        return stats

    async def _settle_ingest(self, baseline_summarized: int) -> bool:
        """Wait for episode_summarized (preferred) then fact-count quiescence."""
        deadline = time.monotonic() + self._s.ingest_settle_timeout_s
        saw_summary = baseline_summarized < 0  # if events unavailable, skip this gate
        last_facts = None
        stable = 0
        while time.monotonic() < deadline:
            if not saw_summary:
                cur = await self._count_event_type("episode_summarized")
                if cur < 0:
                    saw_summary = True  # events endpoint unusable; fall back to counts
                elif cur > baseline_summarized:
                    saw_summary = True
            if saw_summary:
                facts = (await self._status_counts()).get("total_facts")
                if facts == last_facts:
                    stable += 1
                    if stable >= self._s.ingest_quiescence_polls:
                        return True
                else:
                    stable = 0
                    last_facts = facts
            await asyncio.sleep(self._s.ingest_settle_poll_s)
        logger.warning("ingest settle timed out after %ss", self._s.ingest_settle_timeout_s)
        return False

    async def consolidate(self) -> bool:
        """Trigger a sleep cycle and wait for total_sleeps to increment."""
        before = await self._events_stats()
        before_total = before.get("total_sleeps")
        r = await self._client.post(f"{self._base}/sleep/trigger", timeout=30.0)
        if r.status_code == 503:
            logger.info("sleep disabled (503); skipping consolidation")
            return True
        if r.status_code == 409:
            logger.info("sleep already in progress; will wait for completion")
        elif r.status_code != 200:
            r.raise_for_status()

        deadline = time.monotonic() + self._s.sleep_settle_timeout_s
        while time.monotonic() < deadline:
            stats = await self._events_stats()
            total, sleeping = stats.get("total_sleeps"), stats.get("currently_sleeping")
            if before_total is not None and total is not None and total > before_total:
                return True
            if before_total is None and sleeping is False:
                return True
            await asyncio.sleep(self._s.sleep_settle_poll_s)
        logger.warning("sleep settle timed out after %ss", self._s.sleep_settle_timeout_s)
        return False

    async def answer(self, prompt: str) -> str:
        """Ask one question in a fresh session (no residual activation leak)."""
        session_id = f"ask-{uuid.uuid4().hex}"
        resp = await self._post_chat(prompt, session_id, debug=False)
        return resp.get("response", "")
