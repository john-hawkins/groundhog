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


async def _collect(project, settings):
    return [line async for line in agent.run_experiment(project, settings)]


async def test_streams_agent_output(sandbox, analysed_project):
    command = _fake_agent(sandbox, 'echo "line one"\necho "line two"\n')
    assert await _collect(analysed_project, _settings(command)) == ["line one", "line two"]


async def test_runs_inside_the_project_directory(sandbox, analysed_project):
    command = _fake_agent(sandbox, "pwd\n")
    lines = await _collect(analysed_project, _settings(command))
    assert os.path.realpath(lines[0]) == os.path.realpath(fs.project_dir(analysed_project))


async def test_nonzero_exit_raises(sandbox, analysed_project):
    command = _fake_agent(sandbox, 'echo "boom"\nexit 3\n')
    with pytest.raises(agent.AgentRunError, match="status 3"):
        await _collect(analysed_project, _settings(command))


async def test_missing_executable_raises_file_not_found(sandbox, analysed_project):
    with pytest.raises(FileNotFoundError):
        await _collect(analysed_project, _settings("/nonexistent/agent"))


async def test_prompt_includes_the_agent_instructions(sandbox, analysed_project):
    command = _fake_agent(sandbox, 'echo "$*"\n')
    lines = await _collect(analysed_project, _settings(command))
    assert "Run the next experiment." in " ".join(lines)


async def test_refuses_to_run_without_a_prompt_file(sandbox, analysed_project):
    (fs.PROMPTS_DIR / "experiment.md").unlink()
    command = _fake_agent(sandbox, "echo hi\n")
    with pytest.raises(agent.AgentConfigError, match="prompts/experiment.md"):
        await _collect(analysed_project, _settings(command))


async def test_unconfigured_provider_is_rejected_before_spawning(analysed_project):
    with pytest.raises(agent.AgentConfigError, match="API key"):
        await _collect(analysed_project, {"provider": "codex"})


async def test_api_key_reaches_the_agent_env(sandbox, analysed_project):
    command = _fake_agent(sandbox, 'echo "key=$OPENAI_API_KEY"\n')
    settings = _settings(command, provider="codex", api_key="sk-test")
    lines = await _collect(analysed_project, settings)
    assert "key=sk-test" in lines


async def test_claude_code_strips_api_key_vars(sandbox, analysed_project, monkeypatch):
    """Claude Code runs on the subscription login, so a stray API key in the
    parent shell must not switch it to API billing."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "leaked")
    command = _fake_agent(sandbox, 'echo "key=[$ANTHROPIC_API_KEY]"\n')
    assert "key=[]" in await _collect(analysed_project, _settings(command))


async def test_provider_label_used_in_error_message(sandbox, analysed_project):
    command = _fake_agent(sandbox, "exit 1\n")
    settings = _settings(command, provider="opencode", api_key="k", model="m")
    with pytest.raises(agent.AgentRunError, match="OpenCode"):
        await _collect(analysed_project, settings)
