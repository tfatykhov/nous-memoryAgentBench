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

_ATTR_ORDER = ["success", "stored_but_wrong", "write_loss", "unknown"]
_LIFT_ORDER = ["memory_win", "both_right", "both_wrong", "memory_regression"]

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


@dataclass(frozen=True)
class Lift:
    """Memory-lift over the no-memory control, on paired questions only.

    A question is *paired* when its memory answer was graded (no error) and its
    control answer was graded (control_correct is not None). Lift is meaningless
    without both, so unpaired questions are excluded.
    """

    n_paired: int
    n_memory_correct: int
    n_control_correct: int
    buckets: dict[str, int]

    @property
    def memory_accuracy(self) -> float:
        return self.n_memory_correct / self.n_paired if self.n_paired else 0.0

    @property
    def control_accuracy(self) -> float:
        return self.n_control_correct / self.n_paired if self.n_paired else 0.0

    @property
    def lift_pp(self) -> float:
        return (self.memory_accuracy - self.control_accuracy) * 100


def _lift(results: list[QuestionResult]) -> Lift:
    paired = [r for r in results if r.error is None and r.control_correct is not None]
    buckets = dict.fromkeys(_LIFT_ORDER, 0)
    for r in paired:
        if r.correct and not r.control_correct:
            buckets["memory_win"] += 1
        elif r.correct and r.control_correct:
            buckets["both_right"] += 1
        elif not r.correct and not r.control_correct:
            buckets["both_wrong"] += 1
        else:  # control right, memory wrong
            buckets["memory_regression"] += 1
    return Lift(
        n_paired=len(paired),
        n_memory_correct=sum(1 for r in paired if r.correct),
        n_control_correct=sum(1 for r in paired if r.control_correct),
        buckets=buckets,
    )


def _by_source(results: list[QuestionResult]) -> dict[str, Accuracy]:
    sources: dict[str, list[QuestionResult]] = {}
    for r in results:
        sources.setdefault(r.source, []).append(r)
    return {s: _accuracy(rs) for s, rs in sorted(sources.items())}


def summarize(report: RunReport) -> dict:
    """Build a plain-dict summary keyed by config name."""
    out: dict = {"competency": report.competency, "configs": {}}
    rate_in = report.settings.usd_per_mtok_input
    rate_out = report.settings.usd_per_mtok_output
    for cr in report.config_results:
        acc = _accuracy(cr.question_results)
        ingest_in = sum(s.input_tokens for s in cr.ingest_stats)
        ingest_out = sum(s.output_tokens for s in cr.ingest_stats)
        answer_in = sum(r.answer_input_tokens for r in cr.question_results)
        answer_out = sum(r.answer_output_tokens for r in cr.question_results)
        control_in = sum(r.control_input_tokens for r in cr.question_results)
        control_out = sum(r.control_output_tokens for r in cr.question_results)
        fg_in = ingest_in + answer_in + control_in
        fg_out = ingest_out + answer_out + control_out
        settle_timeouts = sum(1 for s in cr.ingest_stats if not s.settled)
        consolidate_timeouts = sum(1 for ok in cr.consolidate_settled if ok is False)
        truncated_instances = sum(1 for s in cr.ingest_stats if s.chunks_truncated)
        chunks_truncated_total = sum(s.chunks_truncated for s in cr.ingest_stats)
        est_usd = None
        if rate_in is not None and rate_out is not None:
            est_usd = round(fg_in / 1e6 * rate_in + fg_out / 1e6 * rate_out, 4)
        # Count attribution across GRADED questions; graded-but-unattributed
        # (diagnostics off/unavailable) is counted as 'unknown' so partial
        # coverage can't masquerade as complete.
        attr_counts: dict[str, int] = {}
        for r in cr.question_results:
            if r.error is not None:
                continue
            label = r.attribution or "unknown"
            attr_counts[label] = attr_counts.get(label, 0) + 1
        lift = _lift(cr.question_results)
        out["configs"][cr.config.name] = {
            "description": cr.config.description,
            "env": cr.config.env,
            "accuracy": round(acc.accuracy, 4),
            "n_correct": acc.n_correct,
            "n_graded": acc.n_graded,
            "n_errored": acc.n_errored,
            "n_total": acc.n_total,
            "memory_accuracy_paired": round(lift.memory_accuracy, 4) if lift.n_paired else None,
            "control_accuracy": round(lift.control_accuracy, 4) if lift.n_paired else None,
            "memory_lift_pp": round(lift.lift_pp, 1) if lift.n_paired else None,
            "n_paired": lift.n_paired,
            "lift_buckets": lift.buckets if lift.n_paired else {},
            "attribution": attr_counts,
            "settle_timeouts": settle_timeouts,
            "consolidate_timeouts": consolidate_timeouts,
            "truncated_instances": truncated_instances,
            "chunks_truncated_total": chunks_truncated_total,
            "answer_input_tokens": answer_in,
            "answer_output_tokens": answer_out,
            "foreground_input_tokens": fg_in,
            "foreground_output_tokens": fg_out,
            "est_usd_foreground": est_usd,
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
        ">",
        "> Token/$ figures are FOREGROUND /chat turns only; background work "
        "(summarization, fact extraction, sleep) is not fully captured, so true "
        "cost is higher.",
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
    # run-health caveats: conditions that bias scores (usually downward) and that
    # a reader must see before trusting a number.
    health: list[str] = []
    for name, c in configs.items():
        if c["consolidate_timeouts"]:
            health.append(f"⚠ {name}: {c['consolidate_timeouts']} instance(s) where sleep "
                          "consolidation never settled — those answers may run against "
                          "incompletely-consolidated memory (biases scores down).")
        if c["truncated_instances"]:
            health.append(f"⚠ {name}: {c['truncated_instances']} instance(s) had ingest "
                          f"truncated ({c['chunks_truncated_total']} chunks dropped) — a "
                          "never-ingested needle can look like a recall failure.")
        graded, paired = c["n_graded"], c["n_paired"]
        if paired and graded and paired < 0.7 * graded:
            health.append(f"⚠ {name}: memory-lift covers only {paired}/{graded} graded "
                          "questions (control errored on the rest) — lift is computed on a "
                          "partial sample.")
    if health:
        lines.append("## Run health caveats")
        lines.append("")
        lines.extend(health)
        lines.append("")
    # memory-lift over the no-memory control (the validity-honest metric)
    if any(c["n_paired"] for c in configs.values()):
        lines.append("## Memory lift (vs no-memory control)")
        lines.append("")
        lines.append("Control = the SAME question answered on the empty agent (no ingest), "
                     "same prompt framing. **Lift = memory accuracy − control accuracy** on "
                     "paired questions — this isolates what the *memory* contributed from what "
                     "the model already knew / read in the prompt.")
        lines.append("")
        lines.append("`memory_win` = control wrong, memory right (true memory contribution) · "
                     "`both_right` = answerable without memory (parametric/in-prompt) · "
                     "`both_wrong` = neither · `memory_regression` = control right, memory wrong.")
        lines.append("")
        lines.append("| Config | Memory acc | Control acc | Lift | Paired | "
                     + " | ".join(_LIFT_ORDER) + " |")
        lines.append("|--------|-----------|-------------|------|--------|"
                     + "|".join(["------"] * len(_LIFT_ORDER)) + "|")
        for name, c in configs.items():
            if not c["n_paired"]:
                continue
            cells = [str(c["lift_buckets"].get(k, 0)) for k in _LIFT_ORDER]
            lines.append(
                f"| {name} | {c['memory_accuracy_paired']:.3f} | {c['control_accuracy']:.3f} | "
                f"{c['memory_lift_pp']:+.1f} pp | {c['n_paired']} | " + " | ".join(cells) + " |"
            )
        lines.append("")
    # failure attribution breakdown (Phase 0)
    if any(c["attribution"] for c in configs.values()):
        lines.append("## Failure attribution")
        lines.append("")
        lines.append("`success` = correct · `write_loss` = gold never stored in memory · "
                     "`stored_but_wrong` = gold stored but answer wrong (retrieval or synthesis) · "
                     "`unknown` = attribution unavailable.")
        # Warn if attribution coverage is partial.
        for name, c in configs.items():
            unknown = c["attribution"].get("unknown", 0)
            graded = c["n_graded"]
            if unknown and graded:
                lines.append("")
                lines.append(f"> ⚠ {name}: attribution covered {graded - unknown}/{graded} "
                             f"graded questions ({unknown} unknown — diagnostics off/unavailable).")
        lines.append("")
        lines.append("| Config | " + " | ".join(_ATTR_ORDER) + " |")
        lines.append("|--------|" + "|".join(["------"] * len(_ATTR_ORDER)) + "|")
        for name, c in configs.items():
            cells = [str(c["attribution"].get(k, 0)) for k in _ATTR_ORDER]
            lines.append(f"| {name} | " + " | ".join(cells) + " |")
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


def sample_manifest(report: RunReport) -> list[dict]:
    """The pinned sample (source/instance/qa_pair/prompt), deduped across configs.

    The sample is identical for every config, so future runs can be checked
    against this manifest for comparability.
    """
    seen: dict[tuple, dict] = {}
    for cr in report.config_results:
        for r in cr.question_results:
            key = (r.source, r.instance_id, r.qa_pair_id, r.prompt)
            if key not in seen:
                seen[key] = {
                    "source": r.source, "instance_id": r.instance_id,
                    "qa_pair_id": r.qa_pair_id, "prompt": r.prompt,
                }
    return list(seen.values())


def render_json(report: RunReport, metadata: dict | None = None) -> dict:
    summary = summarize(report)
    summary["note"] = _NON_COMPARABLE_NOTE
    summary["metadata"] = metadata or {}
    summary["sample_manifest"] = sample_manifest(report)
    summary["per_question"] = [
        {
            "config": r.config_name, "source": r.source, "instance_id": r.instance_id,
            "qa_pair_id": r.qa_pair_id, "prompt": r.prompt, "answer": r.answer,
            "golds": r.golds, "metric": r.metric, "correct": r.correct, "error": r.error,
            "attribution": r.attribution,
            "control_answer": r.control_answer,
            "control_correct": r.control_correct,
            "control_error": r.control_error,
            "recalled_fact_ids": r.recalled_fact_ids,
            "recalled_episode_ids": r.recalled_episode_ids,
            "answer_input_tokens": r.answer_input_tokens,
            "answer_output_tokens": r.answer_output_tokens,
            "control_input_tokens": r.control_input_tokens,
            "control_output_tokens": r.control_output_tokens,
        }
        for cr in report.config_results
        for r in cr.question_results
    ]
    return summary


def write_reports(
    report: RunReport, report_dir: Path, stamp: str, metadata: dict | None = None
) -> tuple[Path, Path]:
    """Write `<stamp>_<competency>.md` and `.json`; return their paths."""
    report_dir.mkdir(parents=True, exist_ok=True)
    configs = "-".join(cr.config.name for cr in report.config_results)
    base = f"{stamp}_{report.competency}_{configs}"
    md_path = report_dir / f"{base}.md"
    json_path = report_dir / f"{base}.json"
    md_path.write_text(render_markdown(report), encoding="utf-8")
    json_path.write_text(json.dumps(render_json(report, metadata), indent=2), encoding="utf-8")
    return md_path, json_path
