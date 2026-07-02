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


@pytest.mark.parametrize(
    "answer,golds,expected",
    [
        # gold appears ONLY inside an abstention clause -> NOT correct
        ("I cannot find any information about 43", ["43"], False),
        ("I don't have anything about Italy in my memory.", ["Italy"], False),
        ("I don't know Italy — not in my memory.", ["Italy"], False),
        # gold asserted in a clean clause, even alongside a hedge -> correct
        ("The country is Belgium, though I don't recall the date.", ["Belgium"], True),
        ("I can't find the date, but the answer is Paris.", ["Paris"], True),
        # second, clean occurrence with NO punctuation before it still counts
        ("I don't know Italy but I recall it's Italy", ["Italy"], True),
        # comma-less coordinating conjunction opens a clean clause (Codex #1)
        ("I don't recall the date but the answer is Paris", ["Paris"], True),
        ("I can't find it though the country is Belgium", ["Belgium"], True),
        ("I don't have the year however the sport began in Italy", ["Italy"], True),
        # affirmative + caveat joined by "and" -> gold still counts (Codex #4)
        ("The country is Belgium and I don't recall the date.", ["Belgium"], True),
        ("The sport began in Italy and I'm not sure of the year", ["Italy"], True),
        # gold BEFORE the cue in the same clause -> abstention (Codex #2)
        ("Italy is not in my memory.", ["Italy"], False),
        ("Paris? I do not know.", ["Paris"], False),
        # typographic (curly) apostrophe in the cue must still match (Codex #3)
        ("I don’t know anything about Italy", ["Italy"], False),
        ("Italy? I don’t know.", ["Italy"], False),
        # listed alternatives stay under the abstention across "or"/"and" (Codex #5)
        ("I don't know whether it is France or Belgium", ["Belgium"], False),
        ("I can't recall if it was Italy or Spain", ["Italy"], False),
        # "don't remember" is an abstention cue (Codex #5)
        ("I don't remember Italy", ["Italy"], False),
        ("I have no idea, maybe Italy", ["Italy"], False),
        # gold asserted in a clean clause after an unrelated earlier refusal -> correct
        ("I don't know the date. The country: Italy.", ["Italy"], True),
        # plain affirmative still correct (no regression)
        ("It is France.", ["France"], True),
    ],
)
def test_substring_rejects_gold_inside_abstention(answer, golds, expected):
    assert SubstringExactMatch().grade(answer, golds).correct is expected


def test_get_grader_returns_registered():
    assert get_grader("substring_exact_match").metric == "substring_exact_match"
    assert get_grader("exact_match").metric == "exact_match"


def test_get_grader_unknown_raises():
    with pytest.raises(ValueError, match="No grader registered"):
        get_grader("bleu")


def test_matched_gold_reported():
    res = SubstringExactMatch().grade("answer: Paris", ["London", "Paris"])
    assert res.correct and res.matched_gold == "Paris"
