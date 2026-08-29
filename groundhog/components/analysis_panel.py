"""The analysis prompt shown until a project has an ANALYSIS.md.

Rendered as a panel inside the project view rather than as a screen of its own,
so a project that already has experiments keeps showing them.
"""

from __future__ import annotations

import reflex as rx

from ..states.project_detail import ProjectState


def _write_it_yourself() -> rx.Component:
    return rx.vstack(
        rx.text(
            "Or write the analysis yourself, based on work you've already done:",
            size="2",
            color="gray",
        ),
        rx.text_area(
            value=ProjectState.analysis_draft,
            on_change=ProjectState.set_analysis_draft,
            placeholder=(
                "Markdown. Distributions, missing values, the target variable, "
                "anything that should shape the experiments."
            ),
            rows="6",
            width="100%",
        ),
        rx.button(
            "Save analysis",
            on_click=ProjectState.save_analysis,
            variant="soft",
            disabled=ProjectState.is_running,
        ),
        rx.cond(
            ProjectState.analysis_error != "",
            rx.text(ProjectState.analysis_error, color="red", size="2"),
        ),
        align="start",
        spacing="2",
        width="100%",
        margin_top="1em",
    )


def analysis_panel() -> rx.Component:
    return rx.box(
        rx.callout(
            "This project hasn't been analysed yet. The agent explores the "
            "dataset once — variable distributions, missing values, the nature "
            "of the target variable and univariate relationships — and writes "
            "the findings to ANALYSIS.md, which every later experiment reads.",
            icon="info",
            size="1",
            width="100%",
        ),
        rx.button(
            "Run Analysis",
            on_click=ProjectState.run_analysis,
            loading=ProjectState.is_running,
            disabled=ProjectState.is_running,
            margin_top="1em",
        ),
        _write_it_yourself(),
        width="100%",
    )
