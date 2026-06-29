"""Command-line entry point for the MAB harness.

    mab run --competency accurate_retrieval --configs baseline,episode_chunks_on \
            --sources eventqa_65536 --max-questions 5
    mab presets
    mab sources --competency accurate_retrieval
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from mab.config import PRESETS, HarnessSettings, config_from_env_file, resolve_configs
from mab.datasets import Competency, load_competency
from mab.report import write_reports
from mab.runner import run_matrix


def _utc_stamp() -> str:
    # Local import keeps module import side-effect free.
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _settings_with_overrides(args: argparse.Namespace) -> HarnessSettings:
    s = HarnessSettings()
    overrides = {}
    if args.max_context_chars is not None:
        overrides["max_context_chars"] = args.max_context_chars
    if args.max_questions is not None:
        overrides["max_questions_per_instance"] = args.max_questions
    if args.max_ingest_chunks is not None:
        overrides["max_ingest_chunks"] = args.max_ingest_chunks
    if args.report_dir is not None:
        overrides["report_dir"] = args.report_dir
    return s.model_copy(update=overrides) if overrides else s


def cmd_run(args: argparse.Namespace) -> int:
    settings = _settings_with_overrides(args)
    competency = Competency(args.competency)
    sources = args.sources.split(",") if args.sources else None
    # Explicit --configs and/or --config-env-file; if NEITHER given, use defaults.
    names = [c for c in args.configs.split(",") if c] if args.configs else []
    configs = resolve_configs(names)
    for path in args.config_env_file or []:
        configs.append(config_from_env_file(path))
    if not configs:
        configs = resolve_configs(["baseline", "episode_chunks_on"])

    instances = load_competency(
        competency,
        sources=sources,
        max_context_chars=settings.max_context_chars,
        max_questions_per_instance=settings.max_questions_per_instance,
    )
    if args.max_instances is not None:
        instances = instances[: args.max_instances]
    if not instances:
        print("No instances matched the filters.", file=sys.stderr)
        return 2

    n_q = sum(len(i.questions) for i in instances)
    est_ingest_turns = sum(
        min(
            (len(i.haystack_turns) or (len(i.context) // settings.chunk_chars + 1)),
            settings.max_ingest_chunks,
        )
        for i in instances
    )
    print(
        f"Plan: competency={competency.value} | configs={[c.name for c in configs]} | "
        f"instances={len(instances)} | questions={n_q}\n"
        f"Estimated agent turns per config ~ {est_ingest_turns} ingest + {n_q} answer "
        f"= {est_ingest_turns + n_q}; total across configs ~ "
        f"{(est_ingest_turns + n_q) * len(configs)} (plus sleep cycles)."
    )
    if args.dry_run:
        return 0

    report = asyncio.run(run_matrix(settings, competency.value, configs, instances))
    md_path, json_path = write_reports(report, settings.report_dir, _utc_stamp())
    print(f"\nWrote:\n  {md_path}\n  {json_path}\n")
    print(md_path.read_text(encoding="utf-8"))
    return 0


def cmd_presets(_args: argparse.Namespace) -> int:
    for name, cfg in PRESETS.items():
        print(f"{name:20s} {cfg.description}")
        if cfg.env:
            print(f"{'':20s}   env: {cfg.env}")
    return 0


def cmd_sources(args: argparse.Namespace) -> int:
    insts = load_competency(Competency(args.competency))
    counts: dict[str, int] = {}
    for i in insts:
        counts[i.source] = counts.get(i.source, 0) + 1
    for src, n in sorted(counts.items()):
        chars = next(i.context_chars for i in insts if i.source == src)
        print(f"{src:24s} rows={n}  context_chars~{chars}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mab", description="MemoryAgentBench harness for nous")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run the benchmark")
    r.add_argument("--competency", default="accurate_retrieval",
                   choices=[c.value for c in Competency])
    r.add_argument("--configs", default=None,
                   help="comma-separated preset names (see `mab presets`); "
                        "defaults to baseline,episode_chunks_on only if neither "
                        "--configs nor --config-env-file is given")
    r.add_argument("--config-env-file", action="append", default=None,
                   help="path to a .env-style file of NOUS_* settings to run as a config "
                        "(repeatable; e.g. a captured prod config)")
    r.add_argument("--sources", default=None, help="comma-separated source filter")
    r.add_argument("--max-context-chars", type=int, default=None)
    r.add_argument("--max-questions", type=int, default=None)
    r.add_argument("--max-ingest-chunks", type=int, default=None)
    r.add_argument("--max-instances", type=int, default=None,
                   help="cap number of MAB instances (cost control)")
    r.add_argument("--report-dir", default=None)
    r.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    r.set_defaults(func=cmd_run)

    pr = sub.add_parser("presets", help="list config presets")
    pr.set_defaults(func=cmd_presets)

    sc = sub.add_parser("sources", help="list sources for a competency")
    sc.add_argument("--competency", default="accurate_retrieval",
                    choices=[c.value for c in Competency])
    sc.set_defaults(func=cmd_sources)
    return p


def main(argv: list[str] | None = None) -> int:
    # Markdown reports use unicode (Δ, arrows); ensure stdout can print them on Windows.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
