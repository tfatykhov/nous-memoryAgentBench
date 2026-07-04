"""Normalized MemoryAgentBench instance schema.

A MAB row pairs one long ``context`` with many questions ("inject once, query
many"). We normalize each row into a :class:`MabInstance` holding the raw
context plus a list of :class:`Question` objects, each carrying its acceptable
gold answers and the grading metric for its competency.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Competency(str, Enum):
    """The four MemoryAgentBench competencies (one parquet file each)."""

    ACCURATE_RETRIEVAL = "accurate_retrieval"
    TEST_TIME_LEARNING = "test_time_learning"
    LONG_RANGE_UNDERSTANDING = "long_range_understanding"
    CONFLICT_RESOLUTION = "conflict_resolution"


class Question(BaseModel):
    """A single question against an instance's context.

    ``gold_answers`` is the list of acceptable answer strings (MAB stores
    multiple golds per question). A grader counts the answer correct if it
    matches *any* gold under ``metric``.
    """

    prompt: str
    gold_answers: list[str] = Field(default_factory=list)
    metric: str
    qa_pair_id: str | None = None
    question_type: str | None = None


class MabInstance(BaseModel):
    """One MAB row: a context and the questions asked against it."""

    competency: Competency
    source: str  # e.g. "ruler_qa1_197K", "eventqa_65536"
    instance_id: str  # stable id, derived from source + row index
    context: str
    questions: list[Question]
    # Pre-chunked conversational turns when MAB provides them (longmemeval-style
    # rows); empty for ruler/eventqa where ``context`` is a monolithic document.
    haystack_turns: list[dict] = Field(default_factory=list)
    # infbench_sum (LRU summarization): reference key points the summary is judged
    # against (paper's recall metric). Empty for all other sources.
    keypoints: list[str] = Field(default_factory=list)

    @property
    def context_chars(self) -> int:
        return len(self.context)
