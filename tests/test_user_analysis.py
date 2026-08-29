"""Writing the analysis by hand instead of running the agent.

From the review feedback: the analysis should be skippable by letting the user
supply a free-text analysis based on work they've already done.
"""

from __future__ import annotations

import stat

import pytest

from groundhog.lib import agent, fs

SAMPLE = """## What I already know

- `income` is about half missing, median-impute it.
- Target is imbalanced at roughly 20% positive.
"""


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


# --- writing it ------------------------------------------------------------

def test_written_analysis_lands_in_the_project(project):
    fs.write_analysis(project, SAMPLE)
    assert fs.analysis_path(project).is_file()


def test_user_text_is_preserved_verbatim(project):
    fs.write_analysis(project, SAMPLE)
    stored = fs.read_analysis(project)
    assert "`income` is about half missing, median-impute it." in stored
    assert "## What I already know" in stored


def test_provenance_is_recorded(project):
    """A reader, and the agent, should be able to tell it wasn't generated."""
    fs.write_analysis(project, SAMPLE)
    assert fs.USER_ANALYSIS_NOTE in fs.read_analysis(project)


def test_agent_written_analysis_carries_no_user_note(project):
    """The two sources stay distinguishable."""
    fs.analysis_path(project).write_text("# Analysis\n\ngenerated\n")
    assert fs.USER_ANALYSIS_NOTE not in fs.read_analysis(project)


def test_surrounding_whitespace_is_trimmed(project):
    fs.write_analysis(project, "\n\n   findings   \n\n")
    assert fs.read_analysis(project).rstrip().endswith("findings")


@pytest.mark.parametrize("text", ["", "   ", "\n\n", "\t\n  "])
def test_empty_analysis_is_rejected(project, text):
    """An empty ANALYSIS.md would leave the project stuck at the analysis
    stage, so it must not be written at all."""
    with pytest.raises(ValueError, match="cannot be empty"):
        fs.write_analysis(project, text)
    assert not fs.analysis_path(project).exists()


# --- it satisfies the gate -------------------------------------------------

def test_project_advances_to_summary(project):
    assert fs.project_stage(project) == "analysis"
    fs.write_analysis(project, SAMPLE)
    assert fs.has_analysis(project) is True
    assert fs.project_stage(project) == "summary"


async def test_experiments_unlock_without_running_the_agent_analysis(
    sandbox, project
):
    command = _fake_agent(sandbox, 'echo "ran"\n')

    with pytest.raises(agent.AgentConfigError):
        [line async for line in agent.run_experiment(project, _settings(command))]

    fs.write_analysis(project, SAMPLE)

    lines = [
        line async for line in agent.run_experiment(project, _settings(command))
    ]
    assert lines == ["ran"]


async def test_written_analysis_reaches_the_experiment_agent(sandbox, project):
    """The experiment prompt tells the agent to read ANALYSIS.md, so whatever
    the user wrote has to be the thing sitting in that file."""
    fs.write_analysis(project, SAMPLE)
    command = _fake_agent(sandbox, "cat ANALYSIS.md\n")
    lines = [
        line async for line in agent.run_experiment(project, _settings(command))
    ]
    assert "## What I already know" in "\n".join(lines)


async def test_full_skip_path_end_to_end(sandbox, project):
    """Fresh project, no agent analysis, straight to a recorded experiment."""
    fs.write_analysis(project, SAMPLE)
    command = _fake_agent(
        sandbox,
        'mkdir -p experiments/hand-analysed\n'
        'echo "# run" > experiments/hand-analysed/README.md\n'
        'echo "| hand-analysed | 2026-03-01 | AUC | 0.77 | after a written analysis |" >> RESULTS.md\n',
    )
    async for _ in agent.run_experiment(project, _settings(command)):
        pass
    assert fs.list_experiments(project) == ["hand-analysed"]
    rows = fs.parse_results(project)
    assert len(rows) == 1
    assert fs.top_result(project, "AUC", rows) == "0.77 (AUC)"
    assert fs.project_stage(project) == "summary"
