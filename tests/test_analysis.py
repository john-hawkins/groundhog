"""The analysis stage that gates experimentation (issue #6)."""

from __future__ import annotations

import stat

import pytest

from groundhog.lib import agent, fs


def _fake_agent(sandbox, body: str) -> str:
    script = sandbox / "fake-agent"
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def _settings(command: str) -> dict:
    return {
        "provider": "claude_code",
        "provider_config": {"claude_code": {"command": command}},
    }


async def _collect(project, settings, runner):
    return [line async for line in runner(project, settings)]


# --- has_analysis -----------------------------------------------------------

def test_new_project_has_no_analysis(project):
    assert fs.has_analysis(project) is False


def test_analysis_detected_once_written(project):
    fs.analysis_path(project).write_text("# Analysis\n\nfindings\n")
    assert fs.has_analysis(project) is True


def test_empty_analysis_file_does_not_count(project):
    """An agent that creates the file but writes nothing hasn't done the work."""
    fs.analysis_path(project).write_text("   \n\n")
    assert fs.has_analysis(project) is False


def test_read_analysis_returns_empty_when_absent(project):
    assert fs.read_analysis(project) == ""


# --- gating -----------------------------------------------------------------

async def test_experiment_blocked_until_analysis_exists(sandbox, project):
    command = _fake_agent(sandbox, "echo should-not-run\n")
    with pytest.raises(agent.AgentConfigError, match="Run the analysis first"):
        await _collect(project, _settings(command), agent.run_experiment)


async def test_experiment_allowed_after_analysis(sandbox, analysed_project):
    command = _fake_agent(sandbox, "echo ran\n")
    lines = await _collect(analysed_project, _settings(command), agent.run_experiment)
    assert lines == ["ran"]


async def test_analysis_run_needs_no_analysis_file(sandbox, project):
    command = _fake_agent(sandbox, "echo analysing\n")
    lines = await _collect(project, _settings(command), agent.run_analysis)
    assert lines == ["analysing"]


# --- prompt selection -------------------------------------------------------

async def test_analysis_run_uses_the_analysis_prompt(sandbox, project):
    command = _fake_agent(sandbox, 'echo "$*"\n')
    output = " ".join(await _collect(project, _settings(command), agent.run_analysis))
    assert "Analyse the dataset." in output
    assert "Run the next experiment." not in output


async def test_experiment_run_uses_the_experiment_prompt(sandbox, analysed_project):
    command = _fake_agent(sandbox, 'echo "$*"\n')
    output = " ".join(
        await _collect(analysed_project, _settings(command), agent.run_experiment)
    )
    assert "Run the next experiment." in output
    assert "Analyse the dataset." not in output


def test_prompt_header_is_stripped(sandbox):
    """The human-facing header above '---' must not reach the agent."""
    assert not fs.read_prompt("analysis").startswith("# Analysis Prompt")
    assert fs.read_prompt("analysis") == "Analyse the dataset."


def test_missing_prompt_reads_as_empty(sandbox):
    assert fs.read_prompt("does-not-exist") == ""


# --- the prompts actually shipped in the repo -------------------------------

def test_shipped_prompts_are_present_and_non_empty():
    for kind in ("analysis", "experiment"):
        assert fs.read_prompt(kind).strip(), f"prompts/{kind}.md is empty"


def test_analysis_prompt_covers_what_the_issue_asked_for():
    body = fs.read_prompt("analysis").lower()
    for topic in ("distribution", "missing", "target", "univariate", "analysis.md"):
        assert topic in body, f"analysis prompt does not mention {topic}"


def test_analysis_prompt_asks_for_tables_and_prose():
    body = fs.read_prompt("analysis").lower()
    assert "markdown table" in body
    assert "key findings" in body


def test_experiment_prompt_references_the_analysis_file():
    assert "ANALYSIS.md" in fs.read_prompt("experiment")


def test_analysis_prompt_does_not_ask_for_modelling():
    body = fs.read_prompt("analysis").lower()
    assert "do not build models" in body


# --- stage machine ----------------------------------------------------------

def test_stage_not_found_for_unknown_project(sandbox):
    assert fs.project_stage("nope") == "not_found"


def test_stage_upload_for_empty_project(sandbox):
    slug = fs.create_project("Empty")
    assert fs.project_stage(slug) == "upload"


def test_stage_configure_once_data_uploaded(sandbox):
    slug = fs.create_project("Data Only")
    fs.save_data_file(slug, "d.csv", b"a,b\n1,2\n")
    assert fs.project_stage(slug) == "configure"


def test_stage_analysis_once_configured(project):
    """The new gate: configured but not yet analysed."""
    assert fs.project_stage(project) == "analysis"


def test_stage_summary_once_analysed(analysed_project):
    assert fs.project_stage(analysed_project) == "summary"


def test_stage_advances_when_agent_writes_analysis(project):
    assert fs.project_stage(project) == "analysis"
    fs.analysis_path(project).write_text("# Analysis\n\nfindings\n")
    assert fs.project_stage(project) == "summary"
