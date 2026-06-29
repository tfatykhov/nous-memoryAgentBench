"""Table-driven tests for the answer graders."""

from __future__ import annotations

import pytest

from mab.grading import ExactMatch, SubstringExactMatch, get_grader


@pytest.mark.parametrize(
    "answer,golds,expected",
    [
        ("The answer is France.", ["France"], True),       # substring hit
        ("france", ["France"], True),                        # case-insensitive
        ("It is located in   France ", ["France"], True),    # whitespace
        ("Germany", ["France", "Paris"], False),             # no gold present
        ("The label is 43 here", ["43"], True),              # substring of longer answer
        ("nothing", [], False),                              # no golds
    ],
)
def test_substring_exact_match(answer, golds, expected):
    assert SubstringExactMatch().grade(answer, golds).correct is expected


@pytest.mark.parametrize(
    "answer,golds,expected",
    [
        ("43", ["43"], True),                  # exact
        ("43", ["42", "43"], True),            # any gold
        ("label: 43", ["43"], False),          # strict: not equal (MAB's note)
        ("France.", ["France"], False),        # trailing punctuation breaks equality
        ("Banking", ["banking"], True),        # case-folded equality
        (" yes ", ["yes"], True),              # stripped
    ],
)
def test_exact_match_is_strict(answer, golds, expected):
    assert ExactMatch().grade(answer, golds).correct is expected


def test_get_grader_returns_registered():
    assert get_grader("substring_exact_match").metric == "substring_exact_match"
    assert get_grader("exact_match").metric == "exact_match"


def test_get_grader_unknown_raises():
    with pytest.raises(ValueError, match="No grader registered"):
        get_grader("bleu")


def test_matched_gold_reported():
    res = SubstringExactMatch().grade("answer: Paris", ["London", "Paris"])
    assert res.correct and res.matched_gold == "Paris"
