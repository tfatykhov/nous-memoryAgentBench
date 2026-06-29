"""Launch and tear down an isolated nous HTTP server for one benchmark run.

Each run gets a unique ``NOUS_AGENT_ID`` (isolation does not depend on wiping)
and points the server at the shared eval DB via UNPREFIXED ``DB_*`` env vars.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from mab.config import Config, HarnessSettings


class NousServerError(RuntimeError):
    """Raised when the nous server fails to launch or become healthy."""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


_API_KEY_VARS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def _read_env_file_keys(repo: Path) -> dict[str, str]:
    """Read only the API-key vars from ``repo/.env`` (never DB settings).

    nous loads its own .env (env_file='.env') from cwd, so keys may live there
    rather than in the shell. We surface them so preflight reflects what the
    server will actually have. DB_* is intentionally NOT read here — the harness
    sets DB_* explicitly to point at the eval DB.
    """
    path = repo / ".env"
    found: dict[str, str] = {}
    if not path.exists():
        return found
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key in _API_KEY_VARS:
            found[key] = value.strip().strip('"').strip("'")
    return found


def _build_env(settings: HarnessSettings, config: Config, port: int, agent_id: str) -> dict[str, str]:
    """Compose the subprocess environment: inherit creds, set DB_*/NOUS_*, apply overrides."""
    env = os.environ.copy()
    # Backfill API keys from nous/.env when absent in the shell (server loads
    # .env too, but preflight must see them). setdefault => shell env wins.
    for key, value in _read_env_file_keys(settings.nous_repo.resolve()).items():
        env.setdefault(key, value)
    # Per-config NOUS_* overrides applied FIRST so the harness-controlled vars
    # below always win (a prod env file may carry NOUS_PORT/NOUS_AGENT_ID/DB_*
    # that would otherwise clobber free-port + unique-agent-id isolation).
    env.update(config.env)
    # nous reads UNPREFIXED DB_* (validation_alias beats the NOUS_ prefix).
    env["DB_HOST"] = settings.db_host
    env["DB_PORT"] = str(settings.db_port)
    env["DB_USER"] = settings.db_user
    env["DB_PASSWORD"] = settings.db_password
    env["DB_NAME"] = settings.db_name
    # Server binding + isolation — harness-owned, never overridable by a config.
    env["NOUS_HOST"] = "127.0.0.1"
    env["NOUS_PORT"] = str(port)
    env["NOUS_AGENT_ID"] = agent_id
    env["NOUS_SESSION_TIMEOUT"] = str(settings.session_timeout_backstop)
    return env


def preflight_keys(env: dict[str, str]) -> None:
    """Fail loudly if creds required for a meaningful run are absent.

    OPENAI_API_KEY is mandatory: without it nous builds no embedding provider and
    silently degrades to keyword-only FTS, making config comparisons meaningless.
    """
    if not env.get("OPENAI_API_KEY"):
        raise NousServerError(
            "OPENAI_API_KEY is required: without it nous has no embedding provider "
            "and recall degrades to keyword-only FTS (config comparisons become meaningless)."
        )
    if not (env.get("ANTHROPIC_API_KEY") or env.get("ANTHROPIC_AUTH_TOKEN")):
        raise NousServerError(
            "ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN is required for the agent loop."
        )


@dataclass
class RunningInstance:
    base_url: str
    agent_id: str
    config: Config


class NousInstance:
    """Async context manager that runs a nous server for one config."""

    def __init__(self, settings: HarnessSettings, config: Config, agent_id: str):
        self._settings = settings
        self._config = config
        self._agent_id = agent_id
        self._proc: subprocess.Popen | None = None
        self._log_path: Path | None = None
        self._port: int | None = None

    async def __aenter__(self) -> RunningInstance:
        s = self._settings
        repo = s.nous_repo.resolve()
        if not repo.exists():
            raise NousServerError(f"nous repo not found at {repo}")
        self._port = _free_port()
        env = _build_env(s, self._config, self._port, self._agent_id)
        preflight_keys(env)

        s.report_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = s.report_dir / f"server_{self._agent_id}.log"
        creationflags = (
            subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        )
        with open(self._log_path, "w", encoding="utf-8") as log:
            self._proc = subprocess.Popen(
                [s.nous_python, "-m", "nous.main"],
                cwd=str(repo),
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
        try:
            await self._await_health()
        except Exception:
            await self.__aexit__(*sys.exc_info())
            raise
        return RunningInstance(
            base_url=f"http://127.0.0.1:{self._port}",
            agent_id=self._agent_id,
            config=self._config,
        )

    async def _await_health(self) -> None:
        url = f"http://127.0.0.1:{self._port}/health"
        deadline = time.monotonic() + self._settings.health_timeout_s
        async with httpx.AsyncClient(timeout=5.0) as client:
            while time.monotonic() < deadline:
                if self._proc is not None and self._proc.poll() is not None:
                    raise NousServerError(
                        f"nous server exited early (code {self._proc.returncode}). "
                        f"See log: {self._log_path}\n{self._tail_log()}"
                    )
                try:
                    r = await client.get(url)
                    if r.status_code == 200 and r.json().get("status") == "healthy":
                        return
                except (httpx.HTTPError, ValueError):
                    pass
                await asyncio.sleep(self._settings.health_poll_s)
        raise NousServerError(
            f"nous server did not become healthy within {self._settings.health_timeout_s}s. "
            f"See log: {self._log_path}\n{self._tail_log()}"
        )

    def _tail_log(self, n: int = 40) -> str:
        if not self._log_path or not self._log_path.exists():
            return ""
        lines = self._log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])

    async def __aexit__(self, *exc) -> None:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        # Graceful first, so nous's lifespan cleanup drains the DB pool (avoids
        # orphaned eval-DB connections across many per-instance server launches).
        with contextlib.suppress(Exception):
            if sys.platform == "win32":
                # CTRL_BREAK_EVENT reaches the new process group (creationflags).
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                proc.terminate()  # SIGTERM
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(Exception):
                proc.kill()
                proc.wait(timeout=5)
