"""Unit tests for failure attribution (classification + gold_in_memory logic)."""

from __future__ import annotations

import sys
import types

import pytest

from mab.config import HarnessSettings
from mab.diagnostics import (
    DiagnosticsUnavailable,
    _word_boundary_regex,
    classify,
    gold_in_memory,
)


# --- word-boundary regex builder (P1-1 escaping, P1-3 boundaries) -----------
def test_word_boundary_wraps_alnum_gold():
    assert _word_boundary_regex("43") == r"\y43\y"
    assert _word_boundary_regex("France") == r"\yFrance\y"


def test_word_boundary_escapes_regex_metachars():
    # Real regex metacharacters are escaped so the gold matches literally in
    # Postgres ('\y' boundary semantics are validated against the live DB, not here).
    assert _word_boundary_regex("3.5") == r"\y3\.5\y"   # '.' -> '\.'
    assert "\\+" in _word_boundary_regex("a+b")          # '+' escaped
    # '%' and '_' are NOT regex wildcards, so they pass through (P1-1 is moot
    # under regex matching, unlike ILIKE).
    assert _word_boundary_regex("item_A") == r"\yitem_A\y"
    p = _word_boundary_regex("100%")
    assert p.startswith(r"\y100") and not p.endswith(r"\y")  # trailing % is non-word


# --- classify ---------------------------------------------------------------
@pytest.mark.parametrize(
    "correct,ingested,expected",
    [
        (True, True, "success"),
        (True, False, "success"),          # correct wins regardless
        (False, True, "stored_but_wrong"),  # gold stored, answer wrong -> downstream
        (False, False, "write_loss"),       # gold never stored -> write/consolidation loss
    ],
)
def test_classify(correct, ingested, expected):
    assert classify(correct, ingested) == expected


# --- gold_in_memory with a fake psycopg ------------------------------------
class _FakeCursor:
    def __init__(self, hit_on, executed):
        self._hit_on = hit_on  # predicate(sql, params) -> bool
        self._executed = executed  # shared list of (sql, params)
        self._last = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        self._last = (sql, params)
        self._executed.append((sql, params))

    def fetchone(self):
        return (1,) if self._hit_on(*self._last) else None


class _FakeConn:
    def __init__(self, hit_on, executed):
        self._hit_on = hit_on
        self._executed = executed

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return _FakeCursor(self._hit_on, self._executed)


def _install_fake_psycopg(monkeypatch, hit_on):
    mod = types.ModuleType("psycopg")
    mod.Error = Exception
    executed: list = []

    def connect(*a, **k):
        return _FakeConn(hit_on, executed)

    mod.connect = connect
    monkeypatch.setitem(sys.modules, "psycopg", mod)
    return executed


def test_gold_in_memory_true_when_substring_present(monkeypatch):
    # any row whose pattern contains "4297" is a hit
    _install_fake_psycopg(monkeypatch, lambda sql, params: "4297" in params[1])
    assert gold_in_memory(HarnessSettings(), "agent-x", ["4297"]) is True


def test_gold_in_memory_filters_active_and_uses_regex(monkeypatch):
    executed = _install_fake_psycopg(monkeypatch, lambda sql, params: False)
    gold_in_memory(HarnessSettings(), "agent-x", ["4297"])
    facts_sql = [s for s, _ in executed if "heart.facts" in s][0]
    episode_chunks_sql = [s for s, _ in executed if "heart.episode_chunks" in s][0]
    assert "active = TRUE" in facts_sql           # superseded rows excluded
    assert "~*" in facts_sql                        # regex (word-boundary), not ILIKE
    assert "active = TRUE" not in episode_chunks_sql  # chunks have no active column


def test_gold_in_memory_false_when_absent(monkeypatch):
    _install_fake_psycopg(monkeypatch, lambda sql, params: False)
    assert gold_in_memory(HarnessSettings(), "agent-x", ["4297"]) is False


def test_gold_in_memory_empty_golds_is_false(monkeypatch):
    _install_fake_psycopg(monkeypatch, lambda sql, params: True)
    assert gold_in_memory(HarnessSettings(), "agent-x", ["", "  "]) is False


def test_gold_in_memory_raises_when_psycopg_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "psycopg", None)  # force ImportError
    with pytest.raises(DiagnosticsUnavailable):
        gold_in_memory(HarnessSettings(), "agent-x", ["x"])
