"""Tests for the MAB dataset loader.

The default tests run against the real Accurate_Retrieval parquet (downloaded
once and cached by huggingface_hub). They assert the normalization contract, not
exact counts, so they stay robust to dataset revisions.
"""

from __future__ import annotations

import pytest

from mab.datasets import Competency, load_competency
from mab.datasets.loader import DEFAULT_METRIC


@pytest.fixture(scope="module")
def ar_instances():
    return load_competency(Competency.ACCURATE_RETRIEVAL)


def test_loads_some_instances(ar_instances):
    assert len(ar_instances) > 0


def test_instance_contract(ar_instances):
    inst = ar_instances[0]
    assert inst.competency is Competency.ACCURATE_RETRIEVAL
    assert inst.source
    assert inst.instance_id
    assert inst.context_chars > 0
    assert len(inst.questions) > 0


def test_questions_have_golds_and_metric(ar_instances):
    for inst in ar_instances:
        for q in inst.questions:
            assert q.prompt
            assert q.metric == DEFAULT_METRIC[Competency.ACCURATE_RETRIEVAL]
            assert len(q.gold_answers) > 0
            # golds are de-duplicated
            assert len(q.gold_answers) == len(set(q.gold_answers))


def test_source_filter(ar_instances):
    all_sources = {inst.source for inst in ar_instances}
    pick = sorted(all_sources)[0]
    filtered = load_competency(Competency.ACCURATE_RETRIEVAL, sources=[pick])
    assert filtered
    assert {inst.source for inst in filtered} == {pick}


def test_max_questions_truncation(ar_instances):
    capped = load_competency(
        Competency.ACCURATE_RETRIEVAL, max_questions_per_instance=3
    )
    assert capped
    assert all(len(inst.questions) <= 3 for inst in capped)


def test_max_context_chars_skips_large(ar_instances):
    smallest = min(inst.context_chars for inst in ar_instances)
    kept = load_competency(
        Competency.ACCURATE_RETRIEVAL, max_context_chars=smallest
    )
    assert all(inst.context_chars <= smallest for inst in kept)
    assert len(kept) < len(ar_instances)  # at least the largest got dropped
