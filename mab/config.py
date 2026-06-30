"""Harness configuration: HarnessSettings (env-driven) and Config presets.

``HarnessSettings`` are the harness's own knobs (``MAB_*`` env). A ``Config`` is
one benchmark configuration: a name + a set of ``NOUS_*`` env overrides applied
to the nous server for that run. Presets are data, so adding an axis is an edit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class HarnessSettings(BaseSettings):
    """Harness-side configuration, read from ``MAB_*`` env vars."""

    model_config = SettingsConfigDict(env_prefix="MAB_", extra="ignore")

    # --- nous server launch ---
    nous_repo: Path = Path("../nous")
    # Interpreter that has nous installed; the server runs as `<python> -m nous.main`
    # with cwd=nous_repo. Must NOT be the harness venv (which lacks nous).
    nous_python: str = "python"
    health_timeout_s: float = 90.0
    health_poll_s: float = 1.0

    # --- eval database (passed to the server as UNPREFIXED DB_* env) ---
    db_host: str = "127.0.0.1"
    db_port: int = 5433
    db_user: str = "nous"
    db_password: str = "nous_eval"
    # Must be a MIGRATED nous DB distinct from dev/prod. The nous eval container
    # (docker-compose --profile eval / nous-eval-scratch) provisions this schema.
    db_name: str = "nous_eval_scratch"

    # --- run isolation ---
    agent_id_prefix: str = "mab-eval"
    # Session-idle backstop (seconds). Ingest sessions are closed explicitly via
    # DELETE, so this is intentionally HIGH: it must NOT auto-close the per-question
    # ask sessions mid-run (which would trigger background summarization and mutate
    # memory between questions). The whole server is torn down after the run anyway.
    session_timeout_backstop: int = 3600

    # --- ingest shape & cost caps ---
    chunk_chars: int = 4000
    # Primary cost bound: cap ingest turns per instance (chunks beyond this are
    # dropped, logged). 60 * 4000 = up to 240K chars ingested per instance.
    max_ingest_chunks: int = 60
    # Optional whole-instance skip by raw context size. Default None: do NOT drop
    # instances (max_ingest_chunks already bounds cost). Set to skip huge contexts.
    max_context_chars: int | None = None
    max_questions_per_instance: int | None = 5

    # --- rate-limit resilience / pacing ---
    # nous wraps Anthropic 429s as HTTP 500, so retry 5xx with exponential backoff.
    max_chat_retries: int = 6
    retry_base_delay_s: float = 5.0
    retry_max_delay_s: float = 90.0
    # Optional fixed delay before each /chat turn to throttle request rate (helps
    # leave rate-limit headroom for nous's background LLM calls).
    turn_delay_s: float = 0.0

    # --- settle timeouts ---
    ingest_settle_timeout_s: float = 180.0
    ingest_settle_poll_s: float = 2.0
    ingest_quiescence_polls: int = 3
    sleep_settle_timeout_s: float = 300.0
    sleep_settle_poll_s: float = 2.0

    # --- output ---
    report_dir: Path = Path("reports")

    # --- cost estimate (optional; tokens are always recorded precisely) ---
    # Set these to your model's price to get a $ estimate in the report.
    usd_per_mtok_input: float | None = None
    usd_per_mtok_output: float | None = None

    # --- failure attribution (Phase 0) ---
    # DB-backed check of whether a gold answer was actually stored/recalled.
    # Requires psycopg + read access to the eval DB. Disable to skip.
    diagnostics_enabled: bool = True


@dataclass(frozen=True)
class Config:
    """One benchmark configuration: a name + NOUS_* env overrides."""

    name: str
    env: dict[str, str] = field(default_factory=dict)
    description: str = ""


# Built-in presets. Centered on the levers that move Accurate Retrieval
# (episode chunks = verbatim recall; fact-extraction coverage; recall depth).
PRESETS: dict[str, Config] = {
    "baseline": Config(
        name="baseline",
        env={},
        description="nous defaults: episode chunks off; summary + <=5 candidate facts.",
    ),
    "episode_chunks_on": Config(
        name="episode_chunks_on",
        env={"NOUS_EPISODE_CHUNKS_ENABLED": "true"},
        description="F067: chunk raw transcript into episode_chunks for verbatim recall.",
    ),
    "coverage_broadened": Config(
        name="coverage_broadened",
        env={"NOUS_EXTRACTION_COVERAGE_BROADENED": "true"},
        description="Broaden fact extraction (5 -> 15 stable candidate facts).",
    ),
    "cross_encoder_on": Config(
        name="cross_encoder_on",
        env={"NOUS_CROSS_ENCODER_ENABLED": "true"},
        description="F042 cross-encoder rerank (downloads bge-reranker on first use).",
    ),
    "sleep_off": Config(
        name="sleep_off",
        env={"NOUS_SLEEP_ENABLED": "false"},
        description="Disable consolidation; /sleep/trigger -> 503, adapter skips it.",
    ),
    "model_haiku": Config(
        name="model_haiku",
        env={"NOUS_MODEL": "claude-haiku-4-5-20251001"},
        description="Cheaper/faster agent model.",
    ),
}


# Harness-owned vars that a config env file must never set (isolation/infra).
_RESERVED_ENV = {"NOUS_HOST", "NOUS_PORT", "NOUS_AGENT_ID", "NOUS_SESSION_TIMEOUT"}


def config_from_env_file(path: str | Path, name: str | None = None) -> Config:
    """Build a Config from a `.env`-style file, keeping only NOUS_* memory knobs.

    Skips reserved isolation vars (NOUS_HOST/PORT/AGENT_ID/SESSION_TIMEOUT) and
    multi-line/quoted-with-newline values. Intended for capturing a deployment's
    memory settings (e.g. prod) without its secrets/infra — curate the file so it
    contains only the behavior knobs you want to benchmark.
    """
    p = Path(path)
    env: dict[str, str] = {}
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key.startswith("NOUS_") or key in _RESERVED_ENV:
            continue
        env[key] = value.strip().strip('"').strip("'")
    return Config(name=name or p.stem, env=env, description=f"loaded from {p.name}")


def resolve_configs(names: list[str]) -> list[Config]:
    """Map preset names to Config objects, erroring on unknown names."""
    unknown = [n for n in names if n not in PRESETS]
    if unknown:
        raise ValueError(
            f"Unknown config preset(s): {unknown}. Known: {sorted(PRESETS)}"
        )
    return [PRESETS[n] for n in names]
