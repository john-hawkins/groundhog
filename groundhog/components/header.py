"""App header: title on the left, settings gear on the right."""

from __future__ import annotations

import reflex as rx

from ..states.settings import SettingsState
from .settings_modal import settings_modal


def header() -> rx.Component:
    return rx.hstack(
        rx.heading("🦦 Groundhog", size="6"),
        rx.spacer(),
        rx.icon_button(
            rx.icon("settings", size=18),
            on_click=SettingsState.open_settings,
            variant="ghost",
            color_scheme="gray",
        ),
        settings_modal(),
        width="100%",
        padding="1em 1.5em",
        align="center",
        border_bottom="1px solid var(--gray-5)",
    )
