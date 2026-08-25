"""Spawning a configured agent headlessly (issue #5)."""

from __future__ import annotations

import os
import stat

import pytest

from groundhog.lib import agent, fs


def _fake_agent(sandbox, body: str) -> str:
    """Write an executable stub we can point a provider at, and return its path."""
    script = sandbox / "fake-agent"
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def _settings(command: str, provider: str = "claude_code", **config) -> dict:
    return {
        "provider": provider,
        "provider_config": {provider: {"command": command, **config}},
    }


@pytest.fixture(autouse=True)
def instructions(sandbox):
    """run_experiment refuses to run without agent instructions."""
    fs.AGENTS_MD.write_text(
        "developer docs\n<!-- reflex managed end -->\nRun the next experiment.\n"
    )


async def _collect(project, settings):
    return [line async for line in agent.run_experiment(project, settings)]


async def test_streams_agent_output(sandbox, project):
    command = _fake_agent(sandbox, 'echo "line one"\necho "line two"\n')
    assert await _collect(project, _settings(command)) == ["line one", "line two"]


async def test_runs_inside_the_project_directory(sandbox, project):
    command = _fake_agent(sandbox, "pwd\n")
    lines = await _collect(project, _settings(command))
    assert os.path.realpath(lines[0]) == os.path.realpath(fs.project_dir(project))


async def test_nonzero_exit_raises(sandbox, project):
    command = _fake_agent(sandbox, 'echo "boom"\nexit 3\n')
    with pytest.raises(agent.AgentRunError, match="status 3"):
        await _collect(project, _settings(command))


async def test_missing_executable_raises_file_not_found(sandbox, project):
    with pytest.raises(FileNotFoundError):
        await _collect(project, _settings("/nonexistent/agent"))


async def test_prompt_includes_the_agent_instructions(sandbox, project):
    command = _fake_agent(sandbox, 'echo "$*"\n')
    lines = await _collect(project, _settings(command))
    assert "Run the next experiment." in " ".join(lines)


async def test_reflex_managed_docs_are_never_sent_as_the_prompt(sandbox, project):
    """If the marker is gone the instructions are gone, and we must refuse
    rather than pass the Reflex developer docs to the agent."""
    fs.AGENTS_MD.write_text("developer docs with no marker")
    command = _fake_agent(sandbox, "echo hi\n")
    with pytest.raises(agent.AgentConfigError, match="instructions"):
        await _collect(project, _settings(command))


async def test_unconfigured_provider_is_rejected_before_spawning(project):
    with pytest.raises(agent.AgentConfigError, match="API key"):
        await _collect(project, {"provider": "codex"})


async def test_api_key_reaches_the_agent_env(sandbox, project):
    command = _fake_agent(sandbox, 'echo "key=$OPENAI_API_KEY"\n')
    settings = _settings(command, provider="codex", api_key="sk-test")
    assert "key=sk-test" in await _collect(project, settings)


async def test_claude_code_strips_api_key_vars(sandbox, project, monkeypatch):
    """Claude Code runs on the subscription login, so a stray API key in the
    parent shell must not switch it to API billing."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "leaked")
    command = _fake_agent(sandbox, 'echo "key=[$ANTHROPIC_API_KEY]"\n')
    assert "key=[]" in await _collect(project, _settings(command))


async def test_provider_label_used_in_error_message(sandbox, project):
    command = _fake_agent(sandbox, "exit 1\n")
    settings = _settings(command, provider="opencode", api_key="k", model="m")
    with pytest.raises(agent.AgentRunError, match="OpenCode"):
        await _collect(project, settings)
