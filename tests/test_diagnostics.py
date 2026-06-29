"""Unit tests for failure attribution (classification + gold_in_memory logic)."""

from __future__ import annotations

import sys
import types

import pytest

from mab.config import HarnessSettings
from mab.diagnostics import DiagnosticsUnavailable, classify, gold_in_memory


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
    def __init__(self, hit_on):
        self._hit_on = hit_on  # predicate(sql, params) -> bool
        self._last = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        self._last = (sql, params)

    def fetchone(self):
        return (1,) if self._hit_on(*self._last) else None


class _FakeConn:
    def __init__(self, hit_on):
        self._hit_on = hit_on

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return _FakeCursor(self._hit_on)


def _install_fake_psycopg(monkeypatch, hit_on):
    mod = types.ModuleType("psycopg")
    mod.Error = Exception

    def connect(*a, **k):
        return _FakeConn(hit_on)

    mod.connect = connect
    monkeypatch.setitem(sys.modules, "psycopg", mod)


def test_gold_in_memory_true_when_substring_present(monkeypatch):
    # any row whose pattern contains "4297" is a hit
    _install_fake_psycopg(monkeypatch, lambda sql, params: "4297" in params[1])
    assert gold_in_memory(HarnessSettings(), "agent-x", ["4297"]) is True


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
