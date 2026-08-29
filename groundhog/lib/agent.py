"""Launches the configured coding agent to run one experiment loop.

The provider (Claude Code, OpenCode, Codex) decides the executable and the
argument shape; this module only cares about starting the process in the
project directory and streaming its output back.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

from . import fs, providers


class AgentRunError(Exception):
    """Raised when the coding agent process exits with a non-zero status."""


class AgentConfigError(Exception):
    """Raised when the selected provider is missing required configuration."""


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

    Raises AgentRunError if the process exits non-zero, AgentConfigError if the
    provider is not configured, or FileNotFoundError if its CLI isn't installed.
    """
    provider, config = resolve_provider(settings or fs.read_settings())
    async for line in _stream(project_name, _build_prompt(kind), provider, config):
        yield line


async def _stream(
    project_name: str,
    prompt: str,
    provider: providers.Provider,
    config: dict,
) -> AsyncIterator[str]:
    proc = await asyncio.create_subprocess_exec(
        *provider.argv(prompt, config),
        cwd=fs.project_dir(project_name),
        env=_subprocess_env(provider, config),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert proc.stdout is not None
    try:
        async for raw_line in proc.stdout:
            yield raw_line.decode("utf-8", errors="replace").rstrip()
    finally:
        # Make sure we never leave the agent running if the consumer stops
        # reading (browser closed, exception upstream).
        if proc.returncode is None:
            proc.terminate()
    returncode = await proc.wait()
    if returncode != 0:
        raise AgentRunError(f"{provider.label} exited with status {returncode}")
