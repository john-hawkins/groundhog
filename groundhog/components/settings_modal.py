"""Gear-icon settings modal: coding agent configuration."""

from __future__ import annotations

import reflex as rx

from ..lib import providers
from ..states.settings import SettingsState


def _field(provider_id: str, field: providers.ConfigField) -> rx.Component:
    key = f"{provider_id}.{field.key}"
    return rx.vstack(
        rx.text(field.label, size="2", weight="bold"),
        rx.input(
            value=SettingsState.values[key],
            on_change=lambda value: SettingsState.set_field(key, value),
            placeholder=field.placeholder,
            type="password" if field.secret else "text",
            width="100%",
        ),
        align="start",
        spacing="1",
        width="100%",
    )


def _provider_fields(provider: providers.Provider) -> rx.Component:
    return rx.vstack(
        *[_field(provider.id, field) for field in provider.fields],
        spacing="3",
        width="100%",
    )


def settings_modal() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Settings"),
            rx.dialog.description(
                "Choose the coding agent used to run experiments.",
                margin_bottom="1em",
            ),
            rx.vstack(
                rx.text("Coding agent", size="2", weight="bold"),
                rx.select(
                    providers.PROVIDER_LABELS,
                    value=SettingsState.provider_label,
                    on_change=SettingsState.set_provider_label,
                ),
                align="start",
                spacing="1",
                width="100%",
            ),
            rx.divider(margin_y="1em"),
            # Only the selected provider's fields are shown.
            rx.match(
                SettingsState.provider_id,
                *[(p.id, _provider_fields(p)) for p in providers.PROVIDERS],
                rx.fragment(),
            ),
            rx.cond(
                SettingsState.error != "",
                rx.text(SettingsState.error, color="red", size="2", margin_top="0.75em"),
            ),
            rx.flex(
                rx.dialog.close(
                    rx.button("Cancel", variant="soft", color_scheme="gray")
                ),
                rx.button("Save", on_click=SettingsState.save_settings),
                spacing="3",
                justify="end",
                margin_top="1.5em",
            ),
            max_width="480px",
        ),
        open=SettingsState.show_settings,
        on_open_change=SettingsState.set_settings_open,
    )
