"""Paper summarization judge (infbench_sum / LRU), vendored from MemoryAgentBench.

Source: https://github.com/HUST-AI-HYZ/MemoryAgentBench (llm_based_eval/summarization_evaluate.py)
License: MIT (c) 2026 Yuanzhe Hu.

Three gpt-4-class judge calls per summary (fluency 0/1, recall = # key points
present, precision = # supported sentences), combined EXACTLY as the paper:

    rec  = recall_count / len(keypoints)
    prec = precision_count / sentence_count
    f1   = fluency * 2*rec*prec/(rec+prec)     # fluency-gated harmonic mean

The result is a fractional 0-1 score per summary (averaged over instances) — NOT
binary accuracy. Uses the *_book prompt variants (infbench En.Sum is book summ).
The completer is injectable so tests run offline.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from mab.grading._paper_sum_prompts import (
    fluency_prompt_book,
    precision_prompt_book,
    recall_prompt_book,
)
from mab.grading.paper_llm_judge import Completer


def parse_json(text: str):
    """Verbatim from summarization_evaluate.py: last {...}, or a ```json fence."""
    matches = re.findall(r"\{.*?\}", text, re.DOTALL)
    if len(matches) > 0:
        try:
            json.loads(matches[-1])
        except Exception:
            matches = re.findall(r"(?:```json)(.+)(?:```)", text, re.DOTALL)
            try:
                json.loads(matches[-1])
            except Exception:
                return None
        return json.loads(matches[-1])
    return None


@dataclass
class SummScore:
    fluency: int
    recall: float
    precision: float
    f1: float


class SummarizationJudge:
    """infbench_sum judge. ``completer`` is an async (prompt, model)->reply."""

    metric = "paper_summarization_f1"

    def __init__(self, completer: Completer, model: str = "gpt-4o"):
        self._complete = completer
        self.model = model

    async def score(self, summary: str, keypoints: list[str], expert_summary: str) -> SummScore:
        s = summary.strip()
        fp = fluency_prompt_book.format(text=s)
        rp = recall_prompt_book.format(
            keypoints="\n".join(f"{i + 1}. {kp}" for i, kp in enumerate(keypoints)), summary=s
        )
        pp = precision_prompt_book.format(expert_summary=expert_summary, summary=s)
        # order matters: fluency, recall, precision
        fo = parse_json(await self._complete(fp, self.model)) or {}
        ro = parse_json(await self._complete(rp, self.model)) or {}
        po = parse_json(await self._complete(pp, self.model)) or {}
        rec = ro.get("recall", 0) / len(keypoints) if keypoints else 0.0
        sc = po.get("sentence_count", 0)
        prec = po.get("precision", 0) / sc if sc else 0.0
        f1 = fo.get("fluency", 0) * 2 * (rec * prec) / (rec + prec) if rec + prec > 0 else 0.0
        return SummScore(fo.get("fluency", 0), rec, prec, f1)
