"""Project page, stage 3: metadata summary, experiments, run controls."""

from __future__ import annotations

import reflex as rx

from ..states.project_detail import ExperimentRow, ProjectState
from .analysis_panel import analysis_panel
from .run_log import run_log


def _metadata_row(label: str, value: rx.Var | str) -> rx.Component:
    return rx.table.row(
        rx.table.cell(label, weight="bold"),
        rx.table.cell(value),
    )


def _experiment_row(row: ExperimentRow) -> rx.Component:
    return rx.table.row(
        rx.table.cell(row.experiment),
        rx.table.cell(row.date),
        rx.table.cell(row.metric),
        rx.table.cell(row.value),
        rx.table.cell(row.notes),
    )


def _metadata_table() -> rx.Component:
    return rx.table.root(
        rx.table.body(
            _metadata_row(
                "Target variable",
                f"{ProjectState.target_variable} "
                f"({ProjectState.target_dtype}, "
                f"{ProjectState.target_n_unique} unique values)",
            ),
            _metadata_row(
                "Train / test strategy",
                f"{ProjectState.split_mode}: {ProjectState.split_value}",
            ),
            _metadata_row("Evaluation metric", ProjectState.eval_metric),
        ),
        width="100%",
    )


def _experiments_table() -> rx.Component:
    return rx.cond(
        ProjectState.experiments.length() == 0,
        rx.text("No experiments yet.", color="gray", margin_top="1em"),
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("Experiment"),
                    rx.table.column_header_cell("Date"),
                    rx.table.column_header_cell("Metric"),
                    rx.table.column_header_cell("Value"),
                    rx.table.column_header_cell("Notes"),
                ),
            ),
            rx.table.body(rx.foreach(ProjectState.experiments, _experiment_row)),
            width="100%",
            margin_top="1em",
        ),
    )


def _analysis_section() -> rx.Component:
    """The analysis document once it exists, or the prompt to produce one."""
    return rx.box(
        rx.heading("Data analysis", size="4", margin_top="1.5em"),
        rx.cond(
            ProjectState.has_analysis,
            rx.accordion.root(
                rx.accordion.item(
                    header="ANALYSIS.md",
                    content=rx.markdown(ProjectState.analysis_text),
                ),
                collapsible=True,
                variant="soft",
                width="100%",
                margin_top="0.5em",
            ),
            analysis_panel(),
        ),
        width="100%",
    )


def summary_view() -> rx.Component:
    return rx.vstack(
        rx.heading("Project summary", size="6"),
        rx.text(
            f"{ProjectState.dataset_files.join(', ')} — "
            f"{ProjectState.record_count} records",
            color="gray",
        ),
        _metadata_table(),
        _analysis_section(),
        rx.heading("Experiments", size="4", margin_top="1.5em"),
        _experiments_table(),
        rx.cond(
            ProjectState.can_run_experiments,
            rx.hstack(
                rx.button(
                    rx.cond(
                        ProjectState.experiments.length() == 0,
                        "Start Experiment",
                        "Run Next Experiment",
                    ),
                    on_click=ProjectState.run_experiment,
                    loading=ProjectState.is_running,
                    disabled=ProjectState.is_running,
                ),
                margin_top="1.5em",
            ),
        ),
        run_log(),
        width="100%",
        max_width="840px",
        margin="0 auto",
        padding="2em 1.5em",
        spacing="2",
    )
