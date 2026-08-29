"""Project detail page, route /project/[name]."""

from __future__ import annotations

import reflex as rx

from ..components.configure_view import configure_view
from ..components.header import header
from ..components.summary_view import summary_view
from ..components.upload_view import upload_view
from ..states.project_detail import ProjectState

# Which view each stage renders. The analysis and summary stages deliberately
# share one: a project that has not been analysed still has to show its
# metadata and any experiments it already ran, so the analysis prompt appears
# as a panel inside that view rather than replacing it.
STAGE_VIEWS = {
    "upload": upload_view,
    "configure": configure_view,
    "analysis": summary_view,
    "summary": summary_view,
}


def project() -> rx.Component:
    return rx.vstack(
        header(),
        rx.match(
            ProjectState.stage,
            *[(stage, view()) for stage, view in STAGE_VIEWS.items()],
            ("not_found", rx.center(
                rx.text("Project not found.", color="gray"),
                padding="4em",
            )),
            rx.center(rx.spinner(), padding="4em"),
        ),
        width="100%",
        spacing="0",
        on_mount=ProjectState.load_project,
    )
