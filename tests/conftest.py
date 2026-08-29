"""Shared fixtures. Every test runs against a temporary root so nothing
touches the real ``projects/`` tree or ``settings.json``."""

from __future__ import annotations

import pytest

from groundhog.lib import fs

ANALYSIS_PROMPT = "# Analysis Prompt\n\n---\nAnalyse the dataset.\n"
EXPERIMENT_PROMPT = "# Experiment Prompt\n\n---\nRun the next experiment.\n"


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Point the fs module at a throwaway root and return that root."""
    projects = tmp_path / "projects"
    projects.mkdir()
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "analysis.md").write_text(ANALYSIS_PROMPT)
    (prompts / "experiment.md").write_text(EXPERIMENT_PROMPT)

    monkeypatch.setattr(fs, "ROOT", tmp_path)
    monkeypatch.setattr(fs, "PROJECTS_DIR", projects)
    monkeypatch.setattr(fs, "PROMPTS_DIR", prompts)
    monkeypatch.setattr(fs, "SETTINGS_FILE", tmp_path / "settings.json")
    return tmp_path


@pytest.fixture
def project(sandbox):
    """A configured project: dataset + metadata, no analysis yet."""
    slug = fs.create_project("Churn Model")
    fs.save_data_file(
        slug,
        "churn.csv",
        b"age,income,churned\n31,50000,0\n45,72000,1\n28,41000,0\n",
    )
    fs.write_metadata(
        slug,
        {
            "dataset_files": ["churn.csv"],
            "record_count": 3,
            "target_variable": {"name": "churned", "dtype": "int64", "n_unique": 2},
            "split": {"mode": "percentage", "value": "0.8"},
            "eval_metric": "AUC",
        },
    )
    return slug


@pytest.fixture
def analysed_project(project):
    """A project that has already been through the analysis stage."""
    fs.analysis_path(project).write_text("# Analysis\n\nTarget is balanced.\n")
    return project
