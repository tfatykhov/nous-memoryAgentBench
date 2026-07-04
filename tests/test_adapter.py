"""Adapter settle/consolidate logic with mocked nous HTTP endpoints."""

from __future__ import annotations

import httpx
import pytest
import respx

from mab.adapter import AnswerResult, NousMemoryMethod
from mab.config import HarnessSettings

BASE = "http://test"


def _fast_settings(**kw):
    defaults = dict(
        ingest_settle_poll_s=0.001, ingest_settle_timeout_s=2.0, ingest_quiescence_polls=2,
        sleep_settle_poll_s=0.001, sleep_settle_timeout_s=2.0,
        retry_base_delay_s=0.001, retry_max_delay_s=0.01,
    )
    defaults.update(kw)
    return HarnessSettings(**defaults)


def _stats_payload(total_sleeps, sleeping=False):
    return {"component_stats": {"sleep_handler": {
        "total_sleeps": total_sleeps, "currently_sleeping": sleeping, "last_sleep_at": None}}}


@pytest.mark.asyncio
@respx.mock
async def test_post_chat_retries_5xx_then_succeeds():
    # nous wraps Anthropic 429 as HTTP 500; the adapter should retry and recover.
    respx.post(f"{BASE}/chat").mock(side_effect=[
        httpx.Response(500, text="Internal Server Error"),
        httpx.Response(500, text="Internal Server Error"),
        httpx.Response(200, json={"response": "ok", "usage": {}, "debug": {}}),
    ])
    async with httpx.AsyncClient() as client:
        m = NousMemoryMethod(client, BASE, _fast_settings(max_chat_retries=5))
        res = await m.answer("q")
    assert res.text == "ok"


@pytest.mark.asyncio
@respx.mock
async def test_post_chat_raises_after_exhausting_retries():
    respx.post(f"{BASE}/chat").mock(return_value=httpx.Response(500, text="boom"))
    async with httpx.AsyncClient() as client:
        m = NousMemoryMethod(client, BASE, _fast_settings(max_chat_retries=2))
        with pytest.raises(httpx.HTTPStatusError):
            await m.answer("q")


@pytest.mark.asyncio
@respx.mock
async def test_post_chat_does_not_retry_4xx():
    route = respx.post(f"{BASE}/chat").mock(return_value=httpx.Response(400, text="bad request"))
    async with httpx.AsyncClient() as client:
        m = NousMemoryMethod(client, BASE, _fast_settings(max_chat_retries=5))
        with pytest.raises(httpx.HTTPStatusError):
            await m.answer("q")
    assert route.call_count == 1  # no retries on client error


def _recent(*types):
    return {"events": [{"type": t} for t in types], "source": "memory", "count": len(types)}


@pytest.mark.asyncio
@respx.mock
async def test_answer_captures_tokens_and_recalled_ids():
    respx.post(f"{BASE}/chat").mock(return_value=httpx.Response(200, json={
        "response": "It is France.",
        "session_id": "ask-1",
        "usage": {"input_tokens": 1200, "output_tokens": 8},
        "debug": {"recalled_fact_ids": ["f1", "f2"], "recalled_episode_ids": ["e1"]},
    }))
    async with httpx.AsyncClient() as client:
        m = NousMemoryMethod(client, BASE, _fast_settings())
        res = await m.answer("Where is Normandy?")
    assert isinstance(res, AnswerResult)
    assert res.text == "It is France."
    assert (res.input_tokens, res.output_tokens) == (1200, 8)
    assert res.recalled_fact_ids == ["f1", "f2"]
    assert res.recalled_episode_ids == ["e1"]
    # request used debug=true so the debug block is populated
    sent = respx.calls.last.request
    assert b'"debug": true' in sent.content or b'"debug":true' in sent.content


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
async def test_consolidate_runs_multiple_cycles():
    # sleep_cycles=3 -> three independent trigger+settle passes (a single sleep
    # may not create all connections). Each cycle sees one more sleep_completed.
    def k(n):  # response with n sleep_completed events
        return httpx.Response(200, json=_recent(*(["sleep_completed"] * n)))
    respx.get(f"{BASE}/events/recent").mock(side_effect=[
        k(0), k(1),   # cycle 1: before=0, poll=1 -> settle
        k(1), k(2),   # cycle 2: before=1, poll=2 -> settle
        k(2), k(3),   # cycle 3: before=2, poll=3 -> settle
    ])
    respx.get(f"{BASE}/events/stats").mock(return_value=httpx.Response(200, json=_stats_payload(0)))
    trigger = respx.post(f"{BASE}/sleep/trigger").mock(
        return_value=httpx.Response(200, json={"status": "started"}))
    async with httpx.AsyncClient() as client:
        m = NousMemoryMethod(client, BASE, _fast_settings(sleep_cycles=3))
        assert await m.consolidate() is True
    assert trigger.call_count == 3  # one trigger per cycle


@pytest.mark.asyncio
@respx.mock
async def test_consolidate_multi_cycle_stops_on_first_timeout():
    # If a cycle never settles, stop and report incomplete (don't fire the rest).
    respx.get(f"{BASE}/events/recent").mock(return_value=httpx.Response(200, json=_recent()))
    respx.get(f"{BASE}/events/stats").mock(return_value=httpx.Response(200, json=_stats_payload(5)))
    trigger = respx.post(f"{BASE}/sleep/trigger").mock(
        return_value=httpx.Response(200, json={"status": "started"}))
    async with httpx.AsyncClient() as client:
        m = NousMemoryMethod(client, BASE, _fast_settings(sleep_cycles=3, sleep_settle_timeout_s=0.05))
        assert await m.consolidate() is False
    assert trigger.call_count == 1  # bailed after the first cycle timed out


@pytest.mark.asyncio
@respx.mock
async def test_ingest_frames_chunk_as_document_not_instructions():
    # S2: the old "Please remember the following information ... (part N/M):"
    # preamble was misread by the nous summarizer as user-provided instructions,
    # contaminating fact extraction. The ingest turn must frame content as a
    # SOURCE DOCUMENT, not an instruction to follow.
    from mab.datasets import Competency, MabInstance, Question

    respx.post(f"{BASE}/chat").mock(return_value=httpx.Response(
        200, json={"response": "ok", "usage": {}, "debug": {}}))
    respx.delete(url__regex=rf"{BASE}/chat/.*").mock(return_value=httpx.Response(200, json={}))
    respx.get(f"{BASE}/events/recent").mock(return_value=httpx.Response(
        200, json=_recent("episode_summarized")))
    respx.get(f"{BASE}/status").mock(return_value=httpx.Response(
        200, json={"memory": {"total_facts": 1}}))

    inst = MabInstance(
        competency=Competency.CONFLICT_RESOLUTION, source="s", instance_id="s#0",
        context="David Farragut is a citizen of Denmark.",
        questions=[Question(prompt="q", gold_answers=["Denmark"], metric="substring_exact_match")],
    )
    async with httpx.AsyncClient() as client:
        m = NousMemoryMethod(client, BASE, _fast_settings())
        await m.ingest(inst)

    chat_calls = [c for c in respx.calls if c.request.method == "POST" and c.request.url.path == "/chat"]
    assert chat_calls, "ingest must POST the chunk to /chat"
    body = chat_calls[0].request.content.decode().lower()
    assert "source document" in body                       # framed as data
    assert "remember the following information" not in body  # not instruction-framed
    assert "David Farragut".lower() in body                 # the content is still sent


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
    # session id derives from instance_id "s#0"; '#' MUST be percent-encoded in
    # the DELETE path, else the server sees a truncated session and never closes it.
    deleted_path = str(routes["delete"].calls.last.request.url)
    assert "%23" in deleted_path and "#" not in deleted_path.split("/chat/")[1]
