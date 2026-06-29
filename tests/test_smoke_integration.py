"""M0 plumbing smoke test against a LIVE nous server (opt-in).

Validates the full machinery — server launch, ingest, session-end + settle,
sleep consolidation, recall via /chat, grading — on a tiny synthetic fact,
before paying for real MAB ingestion.

Requires:
  - a migrated eval DB reachable per MAB_DB_* (e.g. `docker-compose --profile eval up`)
  - MAB_NOUS_REPO / MAB_NOUS_PYTHON pointing at a runnable nous checkout
  - OPENAI_API_KEY and ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN) in the env

Run with:  pytest -m integration tests/test_smoke_integration.py
Skipped unless MAB_RUN_INTEGRATION=1 to avoid accidental cost.
"""

from __future__ import annotations

import os
import uuid

import httpx
import pytest

from mab.adapter import NousMemoryMethod
from mab.config import HarnessSettings, PRESETS
from mab.datasets import Competency, MabInstance, Question
from mab.grading import get_grader
from mab.instance import NousInstance

pytestmark = pytest.mark.integration

_SECRET = "The Glorptax annual parcel fee is 4297 credits."
_QUESTION = "What is the Glorptax annual parcel fee, in credits?"
_GOLD = "4297"


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("MAB_RUN_INTEGRATION") != "1",
    reason="set MAB_RUN_INTEGRATION=1 (and DB/keys) to run the live smoke test",
)
async def test_m0_smoke_fact_survives_pipeline():
    settings = HarnessSettings()
    agent_id = f"{settings.agent_id_prefix}-smoke-{uuid.uuid4().hex[:8]}"
    instance = MabInstance(
        competency=Competency.ACCURATE_RETRIEVAL,
        source="smoke",
        instance_id=f"smoke#{agent_id}",
        context=_SECRET,
        questions=[Question(prompt=_QUESTION, gold_answers=[_GOLD], metric="substring_exact_match")],
    )

    async with NousInstance(settings, PRESETS["baseline"], agent_id) as running:
        async with httpx.AsyncClient() as client:
            method = NousMemoryMethod(client, running.base_url, settings)
            ingest = await method.ingest(instance)
            assert ingest.chunks_sent >= 1
            await method.consolidate()
            answer = await method.answer(_QUESTION)

    result = get_grader("substring_exact_match").grade(answer, [_GOLD])
    assert result.correct, f"nous did not recall the fact. answer was: {answer!r}"
