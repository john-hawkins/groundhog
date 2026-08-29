"""Projects that predate the analysis stage must not lose their experiments.

Regression tests for the review feedback on the analysis-stage PR: opening a
project created before this feature showed the analysis screen and none of the
experiments that had already been run.
"""

from __future__ import annotations

import stat

import pytest

from groundhog.lib import agent, fs
from groundhog.pages.project import STAGE_VIEWS


@pytest.fixture
def legacy_project(project):
    """A project as it would exist before the analysis stage: metadata, two
    experiments on disk and two rows in RESULTS.md, but no ANALYSIS.md."""
    (fs.experiments_dir(project) / "logreg-baseline").mkdir(parents=True)
    (fs.experiments_dir(project) / "xgboost-tuned").mkdir(parents=True)
    fs.results_path(project).write_text(
        fs.RESULTS_HEADER
        + "| logreg-baseline | 2026-01-10 | AUC | 0.81 | baseline |\n"
        + "| xgboost-tuned | 2026-01-12 | AUC | 0.88 | tuned |\n"
    )
    assert not fs.has_analysis(project)
    return project


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


def _literals(node, out=None):
    """Every literal string in a rendered component tree."""
    out = [] if out is None else out
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "contents" and isinstance(value, str):
                out.append(value)
            else:
                _literals(value, out)
    elif isinstance(node, (list, tuple)):
        for value in node:
            _literals(value, out)
    return out


# --- the experiments stay readable -----------------------------------------

def test_existing_experiments_are_still_on_disk(legacy_project):
    assert fs.list_experiments(legacy_project) == [
        "logreg-baseline",
        "xgboost-tuned",
    ]
    assert len(fs.parse_results(legacy_project)) == 2
    assert fs.top_result(legacy_project, "AUC") == "0.88 (AUC)"


def test_analysis_stage_renders_the_same_view_as_summary():
    """The regression: the analysis stage used to render a screen with no
    experiments table on it."""
    assert STAGE_VIEWS["analysis"] is STAGE_VIEWS["summary"]


def test_that_view_contains_both_the_experiments_table_and_the_analysis_prompt():
    text = " ".join(_literals(STAGE_VIEWS["analysis"]().render()))
    # experiments table
    for header in ("Experiment", "Date", "Metric", "Notes"):
        assert header in text, f"experiments table missing {header!r}"
    # and the analysis prompt is a panel within it, not a replacement
    assert "Run Analysis" in text
    assert "Save analysis" in text


# --- the gate no longer locks out existing work -----------------------------

def test_has_experiments_detects_directories(legacy_project):
    assert fs.has_experiments(legacy_project) is True


def test_has_experiments_detects_results_rows_without_directories(project):
    """A results row with no matching directory still counts as prior work."""
    fs.results_path(project).write_text(
        fs.RESULTS_HEADER + "| orphan | 2026-01-01 | AUC | 0.7 | note |\n"
    )
    assert fs.list_experiments(project) == []
    assert fs.has_experiments(project) is True


def test_fresh_project_has_no_experiments(project):
    assert fs.has_experiments(project) is False


async def test_legacy_project_can_still_run_experiments(sandbox, legacy_project):
    command = _fake_agent(sandbox, 'echo "ran"\n')
    lines = [
        line
        async for line in agent.run_experiment(legacy_project, _settings(command))
    ]
    assert lines == ["ran"]


async def test_fresh_project_is_still_gated(sandbox, project):
    """The feature's original point must survive the backwards-compat fix."""
    command = _fake_agent(sandbox, 'echo "should not run"\n')
    with pytest.raises(agent.AgentConfigError, match="Run the analysis first"):
        [
            line
            async for line in agent.run_experiment(project, _settings(command))
        ]


async def test_legacy_project_experiment_appends_to_results(sandbox, legacy_project):
    """End to end: a legacy project continues where it left off."""
    command = _fake_agent(
        sandbox,
        'mkdir -p experiments/third-run\n'
        'echo "# third" > experiments/third-run/README.md\n'
        'echo "| third-run | 2026-02-01 | AUC | 0.90 | continued |" >> RESULTS.md\n',
    )
    async for _ in agent.run_experiment(legacy_project, _settings(command)):
        pass
    assert fs.list_experiments(legacy_project) == [
        "logreg-baseline",
        "third-run",
        "xgboost-tuned",
    ]
    rows = fs.parse_results(legacy_project)
    assert len(rows) == 3
    assert fs.top_result(legacy_project, "AUC", rows) == "0.9 (AUC)"


# --- a run that produces nothing must not look like no run at all -----------

def test_silent_experiment_failure_is_reported(project):
    """An agent can exit 0 having written no result — usually because its own
    script failed. That must not render as an empty table with no explanation."""
    from groundhog.states.project_detail import ProjectState

    fs.write_analysis(project, "findings")
    before = len(fs.parse_results(project))
    msg = ProjectState._nothing_produced(project, "experiment", before)
    assert "without recording a result" in msg


def test_successful_experiment_produces_no_warning(project):
    from groundhog.states.project_detail import ProjectState

    fs.write_analysis(project, "findings")
    before = len(fs.parse_results(project))
    fs.results_path(project).write_text(
        fs.RESULTS_HEADER + "| run | 2026-01-01 | AUC | 0.8 | ok |\n"
    )
    assert ProjectState._nothing_produced(project, "experiment", before) == ""


def test_silent_analysis_failure_is_reported(project):
    from groundhog.states.project_detail import ProjectState

    msg = ProjectState._nothing_produced(project, "analysis", 0)
    assert "without writing ANALYSIS.md" in msg


def test_successful_analysis_produces_no_warning(project):
    from groundhog.states.project_detail import ProjectState

    fs.write_analysis(project, "findings")
    assert ProjectState._nothing_produced(project, "analysis", 0) == ""
