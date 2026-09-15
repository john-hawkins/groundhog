"""Shared streaming-output panel for agent runs."""

from __future__ import annotations

import reflex as rx

from ..states.project_detail import ProjectState


def run_log() -> rx.Component:
    return rx.fragment(
        rx.cond(
            ProjectState.is_running,
            rx.hstack(
                rx.cond(
                    ProjectState.run_started_at != "",
                    rx.text(
                        f"Running {ProjectState.run_kind} — started "
                        f"{ProjectState.run_started_at}",
                        size="1",
                        color="gray",
                    ),
                ),
                rx.button(
                    "Stop",
                    on_click=ProjectState.stop_run,
                    color_scheme="red",
                    variant="soft",
                    size="1",
                ),
                justify="between",
                align="center",
                margin_top="1em",
                width="100%",
            ),
        ),
        rx.cond(
            ProjectState.run_error != "",
            rx.callout(
                ProjectState.run_error,
                icon="triangle_alert",
                color_scheme="red",
                size="1",
                margin_top="1em",
                width="100%",
            ),
        ),
        rx.cond(
            ProjectState.run_warning != "",
            rx.callout(
                ProjectState.run_warning,
                icon="triangle_alert",
                color_scheme="amber",
                size="1",
                margin_top="1em",
                width="100%",
            ),
        ),
        rx.cond(
            ProjectState.log_lines.length() > 0,
            rx.box(
                rx.foreach(
                    ProjectState.log_lines, lambda line: rx.text(line, size="1")
                ),
                font_family="monospace",
                background="var(--gray-2)",
                border="1px solid var(--gray-5)",
                border_radius="0.5em",
                padding="1em",
                margin_top="1em",
                max_height="320px",
                overflow_y="auto",
                width="100%",
            ),
        ),
    )
