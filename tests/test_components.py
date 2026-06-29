"""Offline unit tests for config, chunker, instance env, and reporting."""

from __future__ import annotations

import pytest

from mab.adapter import chunk_context
from mab.config import HarnessSettings, resolve_configs
from mab.datasets import Competency, MabInstance, Question
from mab.instance import NousServerError, _build_env, preflight_keys
from mab.report import render_markdown, summarize
from mab.runner import ConfigResult, QuestionResult, RunReport


# --- config -----------------------------------------------------------------
def test_resolve_known_configs():
    cfgs = resolve_configs(["baseline", "episode_chunks_on"])
    assert [c.name for c in cfgs] == ["baseline", "episode_chunks_on"]
    assert cfgs[1].env["NOUS_EPISODE_CHUNKS_ENABLED"] == "true"


def test_resolve_unknown_config_raises():
    with pytest.raises(ValueError, match="Unknown config preset"):
        resolve_configs(["baseline", "does_not_exist"])


# --- chunker ----------------------------------------------------------------
def _inst(context="", turns=None):
    return MabInstance(
        competency=Competency.ACCURATE_RETRIEVAL, source="s", instance_id="s#0",
        context=context, questions=[Question(prompt="q", gold_answers=["a"], metric="substring_exact_match")],
        haystack_turns=turns or [],
    )


def test_chunk_monolithic_context_and_truncation():
    chunks, truncated = chunk_context(_inst(context="x" * 1000), chunk_chars=100, max_chunks=5)
    assert len(chunks) == 5
    assert truncated == 5  # 10 would-be chunks, capped at 5
    assert all(len(c) == 100 for c in chunks)


def test_chunk_prefers_haystack_turns():
    turns = [{"role": "user", "content": "alpha"}, {"role": "assistant", "content": "beta"}]
    chunks, truncated = chunk_context(_inst(turns=turns), chunk_chars=10, max_chunks=10)
    assert chunks == ["alpha", "beta"]
    assert truncated == 0


# --- instance env & preflight ----------------------------------------------
def test_build_env_sets_unprefixed_db_and_overrides():
    s = HarnessSettings()
    from mab.config import PRESETS
    env = _build_env(s, PRESETS["episode_chunks_on"], port=12345, agent_id="mab-x")
    assert env["DB_PORT"] == str(s.db_port)
    assert env["DB_HOST"] == s.db_host
    assert "NOUS_DB_PORT" not in env  # must be unprefixed
    assert env["NOUS_PORT"] == "12345"
    assert env["NOUS_AGENT_ID"] == "mab-x"
    assert env["NOUS_EPISODE_CHUNKS_ENABLED"] == "true"  # config override applied


def test_preflight_requires_openai_key():
    with pytest.raises(NousServerError, match="OPENAI_API_KEY"):
        preflight_keys({"ANTHROPIC_API_KEY": "x"})


def test_preflight_requires_anthropic_key():
    with pytest.raises(NousServerError, match="ANTHROPIC"):
        preflight_keys({"OPENAI_API_KEY": "x"})


def test_preflight_passes_with_both():
    preflight_keys({"OPENAI_API_KEY": "x", "ANTHROPIC_API_KEY": "y"})


def test_build_env_backfills_keys_from_nous_dotenv_but_not_db(tmp_path, monkeypatch):
    # nous repo with a .env holding keys + a (prod) DB pointer.
    repo = tmp_path / "nous"
    repo.mkdir()
    (repo / ".env").write_text(
        'OPENAI_API_KEY="sk-from-dotenv"\n'
        "ANTHROPIC_API_KEY=ant-from-dotenv\n"
        "DB_PORT=5432\nDB_NAME=nous\n",
        encoding="utf-8",
    )
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(k, raising=False)

    from mab.config import PRESETS
    s = HarnessSettings(nous_repo=repo)  # eval DB defaults (5433 / nous_eval)
    env = _build_env(s, PRESETS["baseline"], port=9000, agent_id="mab-x")

    assert env["OPENAI_API_KEY"] == "sk-from-dotenv"      # backfilled from .env
    assert env["ANTHROPIC_API_KEY"] == "ant-from-dotenv"
    assert env["DB_PORT"] == "5433"                        # harness eval DB, NOT .env's 5432
    assert env["DB_NAME"] == "nous_eval"                   # NOT .env's "nous"
    preflight_keys(env)  # should now pass


# --- report -----------------------------------------------------------------
def _qr(config, correct, source="s", error=None):
    return QuestionResult(
        config_name=config, source=source, instance_id="s#0", qa_pair_id=None,
        prompt="q", answer="a", golds=["a"], metric="substring_exact_match",
        correct=correct, error=error,
    )


def _report():
    from mab.config import PRESETS
    base = ConfigResult(config=PRESETS["baseline"], question_results=[
        _qr("baseline", True), _qr("baseline", False), _qr("baseline", False, error="boom"),
    ])
    chunks = ConfigResult(config=PRESETS["episode_chunks_on"], question_results=[
        _qr("episode_chunks_on", True), _qr("episode_chunks_on", True),
        _qr("episode_chunks_on", False, error="boom"),
    ])
    return RunReport(competency="accurate_retrieval", config_results=[base, chunks],
                     settings=HarnessSettings())


def test_summarize_excludes_errored_from_denominator():
    s = summarize(_report())
    base = s["configs"]["baseline"]
    assert base["n_total"] == 3 and base["n_graded"] == 2 and base["n_errored"] == 1
    assert base["accuracy"] == 0.5  # 1 correct / 2 graded, errored excluded


def test_markdown_has_delta_and_note():
    md = render_markdown(_report())
    assert "NOT comparable" in md
    assert "+50.0 pp" in md  # episode_chunks_on 1.0 vs baseline 0.5
