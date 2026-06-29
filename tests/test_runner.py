"""Runner tests: per-instance isolation and error handling (no live server)."""

from __future__ import annotations

import pytest

from mab import runner
from mab.adapter import IngestStats
from mab.config import HarnessSettings, PRESETS
from mab.datasets import Competency, MabInstance, Question


def _inst(idx: int) -> MabInstance:
    return MabInstance(
        competency=Competency.ACCURATE_RETRIEVAL, source="s", instance_id=f"s#{idx}",
        context="ctx", questions=[Question(prompt=f"q{idx}", gold_answers=["a"], metric="substring_exact_match")],
    )


class _FakeRunning:
    def __init__(self, agent_id):
        self.base_url = "http://fake"
        self.agent_id = agent_id


@pytest.mark.asyncio
async def test_run_config_launches_one_server_per_instance(monkeypatch):
    """MAB evaluates each context independently -> a fresh server+agent_id per instance."""
    launched_agent_ids: list[str] = []

    class FakeInstance:
        def __init__(self, settings, config, agent_id):
            self._agent_id = agent_id

        async def __aenter__(self):
            launched_agent_ids.append(self._agent_id)
            return _FakeRunning(self._agent_id)

        async def __aexit__(self, *exc):
            return False

    class FakeMethod:
        def __init__(self, client, base_url, settings):
            pass

        async def ingest(self, inst):
            return IngestStats(chunks_sent=1, chunks_truncated=0)

        async def consolidate(self):
            return True

        async def answer(self, prompt):
            return "a"  # always correct (gold is "a")

    monkeypatch.setattr(runner, "NousInstance", FakeInstance)
    monkeypatch.setattr(runner, "NousMemoryMethod", FakeMethod)

    instances = [_inst(0), _inst(1), _inst(2)]
    result = await runner.run_config(HarnessSettings(), PRESETS["baseline"], instances)

    assert len(launched_agent_ids) == 3              # one server per instance
    assert len(set(launched_agent_ids)) == 3         # all agent_ids distinct
    assert len(result.question_results) == 3
    assert all(r.correct for r in result.question_results)


@pytest.mark.asyncio
async def test_run_config_marks_instance_errored_on_server_failure(monkeypatch):
    class BoomInstance:
        def __init__(self, settings, config, agent_id):
            pass

        async def __aenter__(self):
            raise RuntimeError("server failed to start")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(runner, "NousInstance", BoomInstance)
    result = await runner.run_config(HarnessSettings(), PRESETS["baseline"], [_inst(0), _inst(1)])

    assert len(result.question_results) == 2
    assert all(r.error and not r.correct for r in result.question_results)
