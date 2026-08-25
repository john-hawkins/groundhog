"""Filesystem helpers for Groundhog projects.

All project state lives on disk under ``projects/<name>/`` so that the
coding agent (which edits these files directly) and the Reflex app always
agree on the source of truth.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
PROJECTS_DIR = ROOT / "projects"
AGENTS_MD = ROOT / "AGENTS.md"
SETTINGS_FILE = ROOT / "settings.json"
REFLEX_MANAGED_END_MARKER = "<!-- reflex managed end -->"

RESULTS_HEADER = (
    "# Results\n\n"
    "| Experiment | Date | Metric | Value | Notes |\n"
    "| --- | --- | --- | --- | --- |\n"
)

EVAL_METRICS = ["AUC", "RMSE", "MASE", "MAPE"]
SPLIT_MODES = ["percentage", "column", "cv_folds"]
LOWER_IS_BETTER = {"RMSE", "MASE", "MAPE"}


def slugify(name: str) -> str:
    """Turn a user-supplied project name into a filesystem-safe slug."""
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip()).strip("-").lower()


def project_dir(name: str) -> Path:
    return PROJECTS_DIR / name


def data_dir(name: str) -> Path:
    return project_dir(name) / "data"


def experiments_dir(name: str) -> Path:
    return project_dir(name) / "experiments"


def results_path(name: str) -> Path:
    return project_dir(name) / "RESULTS.md"


def metadata_path(name: str) -> Path:
    return project_dir(name) / "metadata.json"


def project_exists(name: str) -> bool:
    return project_dir(name).is_dir()


def list_project_names() -> list[str]:
    if not PROJECTS_DIR.is_dir():
        return []
    return sorted(p.name for p in PROJECTS_DIR.iterdir() if p.is_dir())


def create_project(raw_name: str) -> str:
    """Create the on-disk skeleton for a new project and return its slug."""
    slug = slugify(raw_name)
    if not slug:
        raise ValueError(
            "Project name must contain at least one letter, number, - or _."
        )
    if project_exists(slug):
        raise ValueError(f"A project named '{slug}' already exists.")
    data_dir(slug).mkdir(parents=True, exist_ok=True)
    experiments_dir(slug).mkdir(parents=True, exist_ok=True)
    results_path(slug).write_text(RESULTS_HEADER)
    return slug


def list_data_files(name: str) -> list[str]:
    d = data_dir(name)
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if p.is_file())


def save_data_file(name: str, filename: str, content: bytes) -> None:
    d = data_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name
    (d / safe_name).write_bytes(content)


def dataset_preview(name: str) -> dict:
    """Read the first dataset file and summarize row count + column stats."""
    files = list_data_files(name)
    if not files:
        return {"record_count": 0, "columns": []}
    path = data_dir(name) / files[0]
    df = pd.read_csv(path)
    columns = [
        {"name": col, "dtype": str(df[col].dtype), "n_unique": int(df[col].nunique())}
        for col in df.columns
    ]
    return {"record_count": len(df), "columns": columns}


def read_metadata(name: str) -> dict | None:
    path = metadata_path(name)
    if not path.is_file():
        return None
    return json.loads(path.read_text())


def write_metadata(name: str, metadata: dict) -> None:
    metadata_path(name).write_text(json.dumps(metadata, indent=2))


def parse_results(name: str) -> list[dict]:
    """Parse the experiment rows out of RESULTS.md's markdown table."""
    path = results_path(name)
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 5:
            continue
        if cells[0] in {"Experiment", ""} or set(cells[0]) == {"-"}:
            continue
        rows.append(
            {
                "experiment": cells[0],
                "date": cells[1],
                "metric": cells[2],
                "value": cells[3],
                "notes": cells[4],
            }
        )
    return rows


def top_result(name: str, eval_metric: str | None, rows: list[dict] | None = None) -> str:
    """Format the best metric value achieved so far, e.g. '0.91 (AUC)'."""
    rows = rows if rows is not None else parse_results(name)
    scored = []
    for row in rows:
        try:
            scored.append((float(row["value"]), row.get("metric") or eval_metric or ""))
        except (KeyError, ValueError):
            continue
    if not scored:
        return "—"
    metric = eval_metric or scored[0][1]
    values = [v for v, _ in scored]
    best = min(values) if metric in LOWER_IS_BETTER else max(values)
    return f"{best:g} ({metric})" if metric else f"{best:g}"


def list_experiments(name: str) -> list[str]:
    d = experiments_dir(name)
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if p.is_dir())


def experiment_agent_instructions() -> str:
    """Return the app-specific portion of AGENTS.md (after the Reflex-managed block)."""
    if not AGENTS_MD.is_file():
        return ""
    text = AGENTS_MD.read_text()
    idx = text.find(REFLEX_MANAGED_END_MARKER)
    if idx == -1:
        # Falling back to the whole file would hand the agent the
        # Reflex-managed developer docs as its prompt, which is worse than
        # refusing to run.
        return ""
    return text[idx + len(REFLEX_MANAGED_END_MARKER):].strip()


def _write_json(path: Path, payload: dict) -> None:
    """Write JSON via a temp file + rename so a crash can't leave a torn file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    os.replace(tmp, path)


def read_settings() -> dict:
    """Read app settings, returning an empty dict if absent or unreadable."""
    if not SETTINGS_FILE.is_file():
        return {}
    try:
        return json.loads(SETTINGS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def write_settings(settings: dict) -> None:
    _write_json(SETTINGS_FILE, settings)
