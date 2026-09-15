"""Spawning a configured agent headlessly (issue #5)."""

from __future__ import annotations

import asyncio
import json
import os
import stat

import pytest

from groundhog.lib import agent, fs, runs


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


def _read_records(project) -> list[dict]:
    path = fs.project_dir(project) / ".groundhog" / "runs.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


async def _wait_for(path, timeout=5):
    for _ in range(int(timeout / 0.05)):
        if path.exists():
            return
        await asyncio.sleep(0.05)
    pytest.fail(f"{path} never appeared")


def _sleeper_body(marker) -> str:
    """A script that sleeps long enough to reliably still be running when a
    test sends it SIGTERM, and dies immediately when it is.

    Backgrounding `sleep` and trapping TERM to kill it explicitly matters: a
    bare foreground `sleep 30` would leave that child process — and its
    inherited copy of the stdout pipe — running after the shell itself exits,
    which keeps the reader on the other end of the pipe blocked indefinitely
    instead of seeing EOF.
    """
    return (
        "trap 'kill $CHILD 2>/dev/null; exit 143' TERM\n"
        f"touch {marker}\n"
        "sleep 30 &\n"
        "CHILD=$!\n"
        "wait $CHILD\n"
        "echo done\n"
    )


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


# --- cross-session locking (issue: two tabs can run two agents) ------------


async def test_second_run_while_one_in_flight_raises_without_spawning(
    sandbox, analysed_project
):
    marker = sandbox / "started"
    command = _fake_agent(sandbox, _sleeper_body(marker))
    settings = _settings(command)

    task = asyncio.create_task(_collect(analysed_project, settings))
    await _wait_for(marker)

    with pytest.raises(agent.AgentAlreadyRunningError):
        await _collect(analysed_project, settings)

    # Still exactly one run tracked — the second call never spawned anything.
    assert runs.current(analysed_project) is not None

    assert await agent.stop(analysed_project) is True
    await asyncio.wait_for(task, timeout=5)


async def test_completed_run_appends_one_runs_jsonl_record_with_exit_code(
    sandbox, analysed_project
):
    command = _fake_agent(sandbox, "echo hi\n")
    await _collect(analysed_project, _settings(command))
    records = _read_records(analysed_project)
    assert len(records) == 1
    assert records[0]["status"] == "completed"
    assert records[0]["exit_code"] == 0
    assert records[0]["provider"] == "claude_code"
    assert records[0]["kind"] == "experiment"


async def test_failed_run_records_status_failed_with_exit_code(
    sandbox, analysed_project
):
    command = _fake_agent(sandbox, "exit 3\n")
    with pytest.raises(agent.AgentRunError):
        await _collect(analysed_project, _settings(command))
    records = _read_records(analysed_project)
    assert records[-1]["status"] == "failed"
    assert records[-1]["exit_code"] == 3


async def test_lock_is_released_after_success_and_after_failure(
    sandbox, analysed_project
):
    ok_command = _fake_agent(sandbox, "echo hi\n")
    await _collect(analysed_project, _settings(ok_command))
    assert runs.current(analysed_project) is None

    fail_command = _fake_agent(sandbox, "exit 1\n")
    with pytest.raises(agent.AgentRunError):
        await _collect(analysed_project, _settings(fail_command))
    assert runs.current(analysed_project) is None


async def test_stopped_run_is_recorded_as_stopped_not_failed(sandbox, analysed_project):
    marker = sandbox / "started"
    command = _fake_agent(sandbox, _sleeper_body(marker))
    task = asyncio.create_task(_collect(analysed_project, _settings(command)))
    await _wait_for(marker)

    assert await agent.stop(analysed_project) is True
    lines = await asyncio.wait_for(task, timeout=5)
    assert lines == []

    records = _read_records(analysed_project)
    assert records[-1]["status"] == "stopped"
    assert runs.current(analysed_project) is None


async def test_timeout_terminates_a_hanging_agent_and_records_status_timeout(
    sandbox, analysed_project
):
    command = _fake_agent(sandbox, "sleep 5\n")
    settings = _settings(command)
    settings["run_timeout_seconds"] = 0.2
    with pytest.raises(agent.AgentRunError, match="timed out"):
        await _collect(analysed_project, settings)
    records = _read_records(analysed_project)
    assert records[-1]["status"] == "timeout"


async def test_stdout_is_persisted_to_the_run_log_file_on_disk(
    sandbox, analysed_project
):
    command = _fake_agent(sandbox, 'echo "line one"\necho "line two"\n')
    await _collect(analysed_project, _settings(command))
    records = _read_records(analysed_project)
    log_file = fs.project_dir(analysed_project) / ".groundhog" / records[-1]["log_file"]
    assert log_file.read_text().splitlines() == ["line one", "line two"]
