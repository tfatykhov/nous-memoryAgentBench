"""Adapter settle/consolidate logic with mocked nous HTTP endpoints."""

from __future__ import annotations

import httpx
import pytest
import respx

from mab.adapter import NousMemoryMethod
from mab.config import HarnessSettings

BASE = "http://test"


def _fast_settings(**kw):
    defaults = dict(
        ingest_settle_poll_s=0.001, ingest_settle_timeout_s=2.0, ingest_quiescence_polls=2,
        sleep_settle_poll_s=0.001, sleep_settle_timeout_s=2.0,
    )
    defaults.update(kw)
    return HarnessSettings(**defaults)


def _stats_payload(total_sleeps, sleeping=False):
    return {"component_stats": {"sleep_handler": {
        "total_sleeps": total_sleeps, "currently_sleeping": sleeping, "last_sleep_at": None}}}


def _recent(*types):
    return {"events": [{"type": t} for t in types], "source": "memory", "count": len(types)}


@pytest.mark.asyncio
@respx.mock
async def test_consolidate_detects_sleep_completed_event():
    # Primary signal: a new sleep_completed event appears in /events/recent.
    respx.get(f"{BASE}/events/recent").mock(side_effect=[
        httpx.Response(200, json=_recent()),                    # before-count
        httpx.Response(200, json=_recent()),                    # still running
        httpx.Response(200, json=_recent("sleep_completed")),   # done
    ])
    respx.get(f"{BASE}/events/stats").mock(return_value=httpx.Response(200, json=_stats_payload(0)))
    respx.post(f"{BASE}/sleep/trigger").mock(return_value=httpx.Response(200, json={"status": "started"}))
    async with httpx.AsyncClient() as client:
        m = NousMemoryMethod(client, BASE, _fast_settings())
        assert await m.consolidate() is True


@pytest.mark.asyncio
@respx.mock
async def test_consolidate_tolerates_events_stats_500():
    # Live finding: /events/stats can 500. Completion still detected via the event.
    respx.get(f"{BASE}/events/recent").mock(side_effect=[
        httpx.Response(200, json=_recent()),
        httpx.Response(200, json=_recent("sleep_completed")),
    ])
    respx.get(f"{BASE}/events/stats").mock(return_value=httpx.Response(500, text="Internal Server Error"))
    respx.post(f"{BASE}/sleep/trigger").mock(return_value=httpx.Response(200, json={"status": "started"}))
    async with httpx.AsyncClient() as client:
        m = NousMemoryMethod(client, BASE, _fast_settings())
        assert await m.consolidate() is True


@pytest.mark.asyncio
@respx.mock
async def test_consolidate_skips_when_sleep_disabled_503():
    respx.get(f"{BASE}/events/recent").mock(return_value=httpx.Response(200, json=_recent()))
    respx.get(f"{BASE}/events/stats").mock(return_value=httpx.Response(200, json=_stats_payload(0)))
    respx.post(f"{BASE}/sleep/trigger").mock(return_value=httpx.Response(503, json={"error": "no sleep"}))
    async with httpx.AsyncClient() as client:
        m = NousMemoryMethod(client, BASE, _fast_settings())
        assert await m.consolidate() is True  # gracefully skipped


@pytest.mark.asyncio
@respx.mock
async def test_consolidate_times_out_returns_false():
    respx.get(f"{BASE}/events/recent").mock(return_value=httpx.Response(200, json=_recent()))
    respx.get(f"{BASE}/events/stats").mock(return_value=httpx.Response(200, json=_stats_payload(5)))
    respx.post(f"{BASE}/sleep/trigger").mock(return_value=httpx.Response(200, json={"status": "started"}))
    async with httpx.AsyncClient() as client:
        m = NousMemoryMethod(client, BASE, _fast_settings(sleep_settle_timeout_s=0.05))
        assert await m.consolidate() is False  # no sleep_completed, total_sleeps static


@pytest.mark.asyncio
@respx.mock
async def test_settle_ingest_waits_for_summary_then_fact_quiescence():
    # episode_summarized appears on 2nd poll; facts then stable across quiescence polls.
    respx.get(f"{BASE}/events/recent").mock(side_effect=[
        httpx.Response(200, json={"events": []}),
        httpx.Response(200, json={"events": [{"type": "episode_summarized"}]}),
        httpx.Response(200, json={"events": [{"type": "episode_summarized"}]}),
        httpx.Response(200, json={"events": [{"type": "episode_summarized"}]}),
    ])
    respx.get(f"{BASE}/status").mock(return_value=httpx.Response(200, json={"memory": {"total_facts": 7}}))
    async with httpx.AsyncClient() as client:
        m = NousMemoryMethod(client, BASE, _fast_settings())
        assert await m._settle_ingest(baseline_summarized=0) is True


@pytest.mark.asyncio
@respx.mock
async def test_ingest_sends_chunks_and_deletes_session():
    routes = {
        "chat": respx.post(f"{BASE}/chat").mock(
            return_value=httpx.Response(200, json={"response": "ok", "session_id": "x", "usage": {"input_tokens": 3, "output_tokens": 1}})
        ),
        "delete": respx.delete(url__regex=rf"{BASE}/chat/.+").mock(return_value=httpx.Response(200, json={"status": "ended"})),
        "events": respx.get(f"{BASE}/events/recent").mock(return_value=httpx.Response(200, json={"events": [{"type": "episode_summarized"}]})),
        "status": respx.get(f"{BASE}/status").mock(return_value=httpx.Response(200, json={"memory": {"total_facts": 0}})),
    }
    from mab.datasets import Competency, MabInstance, Question
    inst = MabInstance(
        competency=Competency.ACCURATE_RETRIEVAL, source="s", instance_id="s#0",
        context="a" * 250, questions=[Question(prompt="q", gold_answers=["a"], metric="substring_exact_match")],
    )
    async with httpx.AsyncClient() as client:
        m = NousMemoryMethod(client, BASE, _fast_settings(chunk_chars=100, max_ingest_chunks=10))
        stats = await m.ingest(inst)
    assert stats.chunks_sent == 3  # 250 chars / 100 -> 3 chunks
    assert stats.input_tokens == 9  # 3 chunks * 3 tokens
    assert routes["delete"].called
