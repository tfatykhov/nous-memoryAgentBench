"""Aggregate run results into per-config metrics + markdown/JSON reports.

Accuracy = correct / graded, where errored questions are EXCLUDED from the
denominator (never silently scored as wrong). The errored count is reported
separately so a degenerate run can't masquerade as a low score.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from mab.runner import QuestionResult, RunReport

_NON_COMPARABLE_NOTE = (
    "Scores are nous-relative ('fraction of MAB questions answerable through nous's "
    "real memory pipeline'). They are NOT comparable to MemoryAgentBench published "
    "per-method numbers (nous ingests lossily and runs a full agent loop)."
)


@dataclass(frozen=True)
class Accuracy:
    n_total: int
    n_graded: int
    n_correct: int
    n_errored: int

    @property
    def accuracy(self) -> float:
        return self.n_correct / self.n_graded if self.n_graded else 0.0


def _accuracy(results: list[QuestionResult]) -> Accuracy:
    graded = [r for r in results if r.error is None]
    correct = sum(1 for r in graded if r.correct)
    return Accuracy(
        n_total=len(results),
        n_graded=len(graded),
        n_correct=correct,
        n_errored=len(results) - len(graded),
    )


def _by_source(results: list[QuestionResult]) -> dict[str, Accuracy]:
    sources: dict[str, list[QuestionResult]] = {}
    for r in results:
        sources.setdefault(r.source, []).append(r)
    return {s: _accuracy(rs) for s, rs in sorted(sources.items())}


def summarize(report: RunReport) -> dict:
    """Build a plain-dict summary keyed by config name."""
    out: dict = {"competency": report.competency, "configs": {}}
    for cr in report.config_results:
        acc = _accuracy(cr.question_results)
        ingest_in = sum(s.input_tokens for s in cr.ingest_stats)
        ingest_out = sum(s.output_tokens for s in cr.ingest_stats)
        settle_timeouts = sum(1 for s in cr.ingest_stats if not s.settled)
        out["configs"][cr.config.name] = {
            "description": cr.config.description,
            "env": cr.config.env,
            "accuracy": round(acc.accuracy, 4),
            "n_correct": acc.n_correct,
            "n_graded": acc.n_graded,
            "n_errored": acc.n_errored,
            "n_total": acc.n_total,
            "settle_timeouts": settle_timeouts,
            "by_source": {
                s: {"accuracy": round(a.accuracy, 4), "n_correct": a.n_correct, "n_graded": a.n_graded}
                for s, a in _by_source(cr.question_results).items()
            },
            "ingest_input_tokens": ingest_in,
            "ingest_output_tokens": ingest_out,
            "duration_s": round(cr.duration_s, 1),
            "run_error": cr.error,
        }
    return out


def render_markdown(report: RunReport) -> str:
    summary = summarize(report)
    configs = summary["configs"]
    baseline = configs.get("baseline", {}).get("accuracy")
    lines = [
        f"# MAB Harness Report — {report.competency}",
        "",
        f"> {_NON_COMPARABLE_NOTE}",
        "",
        "| Config | Accuracy | Δ vs baseline | Correct/Graded | Errored | Settle timeouts | Ingest tok (in/out) | Time |",
        "|--------|----------|---------------|----------------|---------|-----------------|---------------------|------|",
    ]
    for name, c in configs.items():
        delta = ""
        if baseline is not None and name != "baseline":
            delta = f"{(c['accuracy'] - baseline) * 100:+.1f} pp"
        run_err = f" ⚠ {c['run_error']}" if c["run_error"] else ""
        settle = c["settle_timeouts"]
        settle_cell = f"⚠ {settle}" if settle else "0"
        lines.append(
            f"| {name} | {c['accuracy']:.3f} | {delta or '—'} | "
            f"{c['n_correct']}/{c['n_graded']} | {c['n_errored']} | {settle_cell} | "
            f"{c['ingest_input_tokens']}/{c['ingest_output_tokens']} | {c['duration_s']}s |{run_err}"
        )
    lines.append("")
    # per-source breakdown
    for name, c in configs.items():
        if not c["by_source"]:
            continue
        lines.append(f"## {name} — by source")
        lines.append("")
        lines.append("| Source | Accuracy | Correct/Graded |")
        lines.append("|--------|----------|----------------|")
        for s, a in c["by_source"].items():
            lines.append(f"| {s} | {a['accuracy']:.3f} | {a['n_correct']}/{a['n_graded']} |")
        lines.append("")
    return "\n".join(lines)


def render_json(report: RunReport) -> dict:
    summary = summarize(report)
    summary["note"] = _NON_COMPARABLE_NOTE
    summary["per_question"] = [
        {
            "config": r.config_name, "source": r.source, "instance_id": r.instance_id,
            "qa_pair_id": r.qa_pair_id, "prompt": r.prompt, "answer": r.answer,
            "golds": r.golds, "metric": r.metric, "correct": r.correct, "error": r.error,
        }
        for cr in report.config_results
        for r in cr.question_results
    ]
    return summary


def write_reports(report: RunReport, report_dir: Path, stamp: str) -> tuple[Path, Path]:
    """Write `<stamp>_<competency>.md` and `.json`; return their paths."""
    report_dir.mkdir(parents=True, exist_ok=True)
    configs = "-".join(cr.config.name for cr in report.config_results)
    base = f"{stamp}_{report.competency}_{configs}"
    md_path = report_dir / f"{base}.md"
    json_path = report_dir / f"{base}.json"
    md_path.write_text(render_markdown(report), encoding="utf-8")
    json_path.write_text(json.dumps(render_json(report), indent=2), encoding="utf-8")
    return md_path, json_path
