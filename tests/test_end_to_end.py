"""Full project lifecycle: create -> upload -> configure -> analyse -> experiment.

Uses a stub agent that behaves like a real one (it writes ANALYSIS.md and
appends to RESULTS.md), so this exercises the real fs, provider and runner code
paths rather than mocking them out.
"""

from __future__ import annotations

import stat

import pytest

from groundhog.lib import agent, fs

# Branches on the prompt it receives, which also proves the correct prompt was
# routed for each run type. Runs with the project directory as cwd.
STUB = """#!/bin/sh
case "$*" in
  *"Analyse the dataset"*)
    echo "reading data/"
    printf '# Analysis\\n\\n| column | missing |\\n| --- | --- |\\n| age | 0 |\\n\\n## Key findings\\n\\nTarget is balanced.\\n' > ANALYSIS.md
    echo "wrote ANALYSIS.md"
    ;;
  *"Run the next experiment"*)
    mkdir -p experiments/logreg-baseline
    echo "# logreg baseline" > experiments/logreg-baseline/README.md
    echo "| logreg-baseline | 2026-08-24 | AUC | 0.83 | first pass |" >> RESULTS.md
    echo "wrote result"
    ;;
  *)
    echo "unexpected prompt" >&2
    exit 9
    ;;
esac
"""


@pytest.fixture
def stub_agent(sandbox):
    """Install the stub as the configured agent, persisted to settings.json."""
    script = sandbox / "stub-agent"
    script.write_text(STUB)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    fs.write_settings(
        {
            "provider": "claude_code",
            "provider_config": {"claude_code": {"command": str(script)}},
        }
    )
    return script


async def _run(runner, name):
    return [line async for line in runner(name)]


async def test_full_project_lifecycle(sandbox, stub_agent):
    # 1. create
    slug = fs.create_project("Customer Churn")
    assert slug == "customer-churn"
    assert fs.project_stage(slug) == "upload"

    # 2. upload a dataset
    fs.save_data_file(
        slug,
        "churn.csv",
        b"age,income,churned\n31,50000,0\n45,72000,1\n28,41000,0\n52,88000,1\n",
    )
    assert fs.project_stage(slug) == "configure"

    preview = fs.dataset_preview(slug)
    assert preview["record_count"] == 4
    assert [c["name"] for c in preview["columns"]] == ["age", "income", "churned"]

    # 3. configure
    fs.write_metadata(
        slug,
        {
            "dataset_files": fs.list_data_files(slug),
            "record_count": preview["record_count"],
            "target_variable": {"name": "churned", "dtype": "int64", "n_unique": 2},
            "split": {"mode": "percentage", "value": "0.8"},
            "eval_metric": "AUC",
        },
    )
    assert fs.project_stage(slug) == "analysis"

    # 4. experiments are locked until the analysis has run
    with pytest.raises(agent.AgentConfigError, match="Run the analysis first"):
        await _run(agent.run_experiment, slug)
    assert fs.list_experiments(slug) == []

    # 5. analysis run — reads settings from disk, no settings passed in
    log = await _run(agent.run_analysis, slug)
    assert "wrote ANALYSIS.md" in log
    assert fs.has_analysis(slug)
    assert "Key findings" in fs.read_analysis(slug)
    assert fs.project_stage(slug) == "summary"

    # 6. experiment run is now allowed
    log = await _run(agent.run_experiment, slug)
    assert "wrote result" in log
    assert fs.list_experiments(slug) == ["logreg-baseline"]

    # 7. the result is picked up by the UI layer
    rows = fs.parse_results(slug)
    assert len(rows) == 1
    assert rows[0]["experiment"] == "logreg-baseline"
    assert rows[0]["value"] == "0.83"
    assert fs.top_result(slug, "AUC", rows) == "0.83 (AUC)"

    # 8. a second experiment appends rather than replacing
    await _run(agent.run_experiment, slug)
    assert len(fs.parse_results(slug)) == 2


async def test_lifecycle_survives_switching_agent(sandbox, stub_agent):
    """Switching provider in settings changes which binary is launched."""
    slug = fs.create_project("Switch")
    fs.save_data_file(slug, "d.csv", b"a,b\n1,2\n")
    fs.write_metadata(slug, {"eval_metric": "AUC"})

    # Codex, pointed at the same stub, with its required key supplied.
    fs.write_settings(
        {
            "provider": "codex",
            "provider_config": {
                "codex": {"command": str(stub_agent), "api_key": "sk-test"}
            },
        }
    )
    log = await _run(agent.run_analysis, slug)
    assert "wrote ANALYSIS.md" in log
    assert fs.project_stage(slug) == "summary"


async def test_unconfigured_agent_blocks_before_spawning(sandbox):
    slug = fs.create_project("No Config")
    fs.save_data_file(slug, "d.csv", b"a\n1\n")
    fs.write_metadata(slug, {"eval_metric": "AUC"})
    fs.write_settings({"provider": "opencode"})

    with pytest.raises(agent.AgentConfigError, match="Model, API key"):
        await _run(agent.run_analysis, slug)
