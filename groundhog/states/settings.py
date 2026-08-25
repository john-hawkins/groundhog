"""Global application settings (coding agent configuration).

Settings are persisted to ``settings.json`` in the repo root rather than kept
in session state, so the choice of agent survives a reload and is the same for
every browser session driving the same install.
"""

from __future__ import annotations

import reflex as rx

from ..lib import fs, providers


def _field_key(provider_id: str, field_key: str) -> str:
    return f"{provider_id}.{field_key}"


class SettingsState(rx.State):
    show_settings: bool = False
    provider_id: str = providers.DEFAULT_PROVIDER_ID
    # Flat "<provider_id>.<field>" -> value map, so each input can bind to a
    # single key. Reassembled into nested form when written to disk.
    values: dict[str, str] = {}
    error: str = ""

    @rx.var
    def provider_label(self) -> str:
        return providers.label_for_id(self.provider_id)

    @rx.event
    def load_settings(self):
        settings = fs.read_settings()
        self.provider_id = providers.get(
            settings.get("provider", providers.DEFAULT_PROVIDER_ID)
        ).id
        stored = settings.get("provider_config") or {}
        # Seed every key so the inputs always have a defined value.
        values: dict[str, str] = {}
        for provider in providers.PROVIDERS:
            for field in provider.fields:
                key = _field_key(provider.id, field.key)
                values[key] = str(stored.get(provider.id, {}).get(field.key, ""))
        self.values = values
        self.error = ""

    @rx.event
    def open_settings(self):
        self.load_settings()
        self.show_settings = True

    @rx.event
    def set_settings_open(self, value: bool):
        self.show_settings = value

    @rx.event
    def set_provider_label(self, label: str):
        self.provider_id = providers.id_for_label(label)
        self.error = ""

    @rx.event
    def set_field(self, key: str, value: str):
        self.values = {**self.values, key: value}

    @rx.event
    def save_settings(self):
        provider = providers.get(self.provider_id)
        config = self._config_for(provider.id)
        missing = provider.missing_fields(config)
        if missing:
            self.error = f"Required for {provider.label}: {', '.join(missing)}"
            return
        fs.write_settings(
            {
                "provider": provider.id,
                "provider_config": {
                    p.id: self._config_for(p.id) for p in providers.PROVIDERS
                },
            }
        )
        self.error = ""
        self.show_settings = False

    def _config_for(self, provider_id: str) -> dict:
        prefix = f"{provider_id}."
        return {
            key[len(prefix):]: value
            for key, value in self.values.items()
            if key.startswith(prefix) and value.strip()
        }
