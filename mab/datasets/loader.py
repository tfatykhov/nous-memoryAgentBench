"""Load MemoryAgentBench parquet files and normalize into MabInstance objects.

The HF dataset ``ai-hyz/MemoryAgentBench`` ships one parquet per competency.
Each row has columns: ``context`` (str), ``questions`` (list[str]),
``answers`` (list[list[str]] — acceptable golds per question), and
``metadata`` (struct with ``source``, ``qa_pair_ids``, ``question_types``,
``haystack_sessions``, ...).
"""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download

from mab.datasets.schema import Competency, MabInstance, Question

HF_REPO_ID = "ai-hyz/MemoryAgentBench"

COMPETENCY_FILES: dict[Competency, str] = {
    Competency.ACCURATE_RETRIEVAL: "data/Accurate_Retrieval-00000-of-00001.parquet",
    Competency.TEST_TIME_LEARNING: "data/Test_Time_Learning-00000-of-00001.parquet",
    Competency.LONG_RANGE_UNDERSTANDING: "data/Long_Range_Understanding-00000-of-00001.parquet",
    Competency.CONFLICT_RESOLUTION: "data/Conflict_Resolution-00000-of-00001.parquet",
}

# Grading metric per competency (MAB convention): AR/CR use substring exact
# match; TTL/LRU use strict exact match.
DEFAULT_METRIC: dict[Competency, str] = {
    Competency.ACCURATE_RETRIEVAL: "substring_exact_match",
    Competency.CONFLICT_RESOLUTION: "substring_exact_match",
    Competency.TEST_TIME_LEARNING: "exact_match",
    Competency.LONG_RANGE_UNDERSTANDING: "exact_match",
}


def _download_parquet(competency: Competency, cache_dir: Path | None = None) -> Path:
    """Fetch the competency's parquet from HF (cached) and return its local path."""
    filename = COMPETENCY_FILES[competency]
    local = hf_hub_download(
        repo_id=HF_REPO_ID,
        filename=filename,
        repo_type="dataset",
        cache_dir=str(cache_dir) if cache_dir else None,
    )
    return Path(local)


def _flatten_haystack(haystack_sessions: object) -> list[dict]:
    """Flatten MAB's deeply-nested haystack_sessions into a flat [{role, content}] list.

    The column type is list<list<list<struct{content, has_answer, role}>>>; it is
    None/empty for ruler/eventqa rows and populated for longmemeval-style rows.
    """
    turns: list[dict] = []
    if not haystack_sessions:
        return turns

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if "content" in node and "role" in node:
                turns.append({"role": node.get("role"), "content": node.get("content")})
            return
        if isinstance(node, (list, tuple)):
            for child in node:
                walk(child)

    walk(haystack_sessions)
    return turns


def load_competency(
    competency: Competency,
    *,
    parquet_path: Path | None = None,
    cache_dir: Path | None = None,
    sources: list[str] | None = None,
    max_context_chars: int | None = None,
    max_questions_per_instance: int | None = None,
) -> list[MabInstance]:
    """Load and normalize one competency's parquet into MabInstance objects.

    Args:
        competency: which competency (parquet file) to load.
        parquet_path: read this local parquet instead of downloading from HF.
        cache_dir: HF download cache dir (ignored when ``parquet_path`` is given).
        sources: keep only rows whose ``metadata.source`` is in this list.
        max_context_chars: skip instances whose context exceeds this size
            (cost/feasibility guard — MAB AR contexts reach ~1M chars).
        max_questions_per_instance: truncate each instance to the first N
            questions (sampling; "inject once query many" keeps ingest shared).
    """
    path = parquet_path or _download_parquet(competency, cache_dir=cache_dir)
    table = pq.read_table(path)
    rows = table.to_pylist()
    metric = DEFAULT_METRIC[competency]

    instances: list[MabInstance] = []
    for row_idx, row in enumerate(rows):
        context = row.get("context") or ""
        if max_context_chars is not None and len(context) > max_context_chars:
            continue

        metadata = row.get("metadata") or {}
        source = metadata.get("source") or f"{competency.value}_row{row_idx}"
        if sources is not None and source not in sources:
            continue

        prompts = row.get("questions") or []
        answers = row.get("answers") or []
        qa_pair_ids = metadata.get("qa_pair_ids") or []
        question_types = metadata.get("question_types") or []

        questions: list[Question] = []
        for q_idx, prompt in enumerate(prompts):
            golds = answers[q_idx] if q_idx < len(answers) else []
            # De-duplicate golds while preserving order (MAB often repeats a gold).
            seen: set[str] = set()
            uniq_golds = [g for g in golds if not (g in seen or seen.add(g))]
            questions.append(
                Question(
                    prompt=prompt,
                    gold_answers=uniq_golds,
                    metric=metric,
                    qa_pair_id=qa_pair_ids[q_idx] if q_idx < len(qa_pair_ids) else None,
                    question_type=(
                        question_types[q_idx] if q_idx < len(question_types) else None
                    ),
                )
            )

        if max_questions_per_instance is not None:
            questions = questions[:max_questions_per_instance]

        if not questions:
            continue

        instances.append(
            MabInstance(
                competency=competency,
                source=source,
                instance_id=f"{source}#{row_idx}",
                context=context,
                questions=questions,
                haystack_turns=_flatten_haystack(metadata.get("haystack_sessions")),
            )
        )

    return instances
