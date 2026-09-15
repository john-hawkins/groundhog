"""Launches the configured coding agent to run one experiment loop.

The provider (Claude Code, OpenCode, Codex) decides the executable and the
argument shape; this module only cares about starting the process in the
project directory and streaming its output back.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

from . import fs, providers, runs


class AgentRunError(Exception):
    """Raised when the coding agent process exits with a non-zero status."""


class AgentConfigError(Exception):
    """Raised when the selected provider is missing required configuration."""


class AgentAlreadyRunningError(Exception):
    """Raised when another run already holds this project's lock.

    Raised before any subprocess is spawned, so a second click (from another
    tab, another user, or a double-click) never starts a second process.
    """


_PREAMBLE = {
    "analysis": (
        "Follow the instructions below to analyse the dataset for this data "
        "science project. The current working directory is the project "
        "directory."
    ),
    "experiment": (
        "Follow the instructions below to run the next experiment for this "
        "data science project. The current working directory is the project "
        "directory."
    ),
}


def _build_prompt(kind: str) -> str:
    instructions = fs.read_prompt(kind)
    if not instructions:
        raise AgentConfigError(
            f"No agent instructions found. Expected them in prompts/{kind}.md."
        )
    return f"{_PREAMBLE[kind]}\n\n{instructions}"


def _subprocess_env(provider: providers.Provider, config: dict) -> dict[str, str]:
    env = dict(os.environ)
    for var in provider.strip_env:
        env.pop(var, None)
    for key, var in provider.env_from_config.items():
        value = (config.get(key) or "").strip()
        if value:
            env[var] = value
    return env


def resolve_provider(settings: dict) -> tuple[providers.Provider, dict]:
    """Pick the provider named in settings and return it with its config."""
    provider = providers.get(settings.get("provider", providers.DEFAULT_PROVIDER_ID))
    config = (settings.get("provider_config") or {}).get(provider.id, {})
    missing = provider.missing_fields(config)
    if missing:
        raise AgentConfigError(
            f"{provider.label} is missing required settings: {', '.join(missing)}. "
            "Open the settings dialog to fill them in."
        )
    return provider, config


async def run_analysis(
    project_name: str, settings: dict | None = None
) -> AsyncIterator[str]:
    """Run the one-off data analysis pass, which writes ANALYSIS.md."""
    async for line in _run(project_name, "analysis", settings):
        yield line


async def run_experiment(
    project_name: str, settings: dict | None = None
) -> AsyncIterator[str]:
    """Run one experiment loop.

    A project that has not been analysed yet has to be analysed first, since the
    experiment prompt treats ANALYSIS.md as established context. Projects that
    already have experiments predate the analysis stage and are not blocked —
    they would otherwise be unable to continue work they had already started.
    """
    if not fs.has_analysis(project_name) and not fs.has_experiments(project_name):
        raise AgentConfigError(
            "Run the analysis first, or write one yourself — the experiment "
            "prompt uses ANALYSIS.md as its reference."
        )
    async for line in _run(project_name, "experiment", settings):
        yield line


async def _run(
    project_name: str, kind: str, settings: dict | None
) -> AsyncIterator[str]:
    """Resolve the provider, build the prompt for ``kind``, stream the output.

    Raises AgentAlreadyRunningError if the project's lock is already held,
    AgentRunError if the process exits non-zero (or times out), AgentConfigError
    if the provider is not configured, or FileNotFoundError if its CLI isn't
    installed.
    """
    resolved = settings or fs.read_settings()
    provider, config = resolve_provider(resolved)
    prompt = _build_prompt(kind)
    timeout_seconds = resolved.get("run_timeout_seconds")
    async for line in _stream(
        project_name, kind, prompt, provider, config, timeout_seconds
    ):
        yield line


async def stop(project_name: str) -> bool:
    """Ask the run for ``project_name`` to stop. False if nothing is running."""
    return runs.request_stop(project_name)


async def _stream(
    project_name: str,
    kind: str,
    prompt: str,
    provider: providers.Provider,
    config: dict,
    timeout_seconds: float | None,
) -> AsyncIterator[str]:
    try:
        lock = runs.acquire(project_name, kind, provider.id)
    except runs.AlreadyRunningError as exc:
        raise AgentAlreadyRunningError(
            f"{provider.label} is already running for this project "
            f"(started {exc.lock.started_at})."
        ) from exc

    try:
        proc = await asyncio.create_subprocess_exec(
            *provider.argv(prompt, config),
            cwd=fs.project_dir(project_name),
            env=_subprocess_env(provider, config),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except BaseException:
        runs.release(project_name, lock.run_id)
        raise

    runs.update_pid(project_name, lock.run_id, proc.pid)
    runs.register_process(project_name, lock.run_id, proc)

    timed_out = False
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_seconds if timeout_seconds else None
    assert proc.stdout is not None
    try:
        while True:
            if deadline is not None:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    timed_out = True
                    break
                try:
                    raw_line = await asyncio.wait_for(proc.stdout.readline(), remaining)
                except asyncio.TimeoutError:
                    timed_out = True
                    break
            else:
                raw_line = await proc.stdout.readline()
            if not raw_line:
                break
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            runs.append_log_line(project_name, lock.run_id, line)
            yield line
    finally:
        # Make sure we never leave the agent running if the consumer stops
        # reading (browser closed, exception upstream) or it timed out.
        if proc.returncode is None:
            proc.terminate()

    returncode = await proc.wait()
    stopped = runs.stop_requested(project_name)
    runs.unregister_process(project_name)
    runs.release(project_name, lock.run_id)

    if timed_out:
        status = "timeout"
    elif stopped:
        status = "stopped"
    elif returncode == 0:
        status = "completed"
    else:
        status = "failed"
    runs.append_record(
        project_name,
        {
            "run_id": lock.run_id,
            "kind": kind,
            "provider": provider.id,
            "started_at": lock.started_at,
            "ended_at": runs._now(),
            "exit_code": returncode,
            "status": status,
            "log_file": f"runs/{lock.run_id}.log",
        },
    )

    if timed_out:
        raise AgentRunError(
            f"{provider.label} timed out after {timeout_seconds}s and was stopped."
        )
    if returncode != 0 and not stopped:
        raise AgentRunError(f"{provider.label} exited with status {returncode}")
