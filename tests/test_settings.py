"""Persisting the agent configuration (issue #5)."""

from __future__ import annotations

from groundhog.lib import fs, providers


def test_missing_settings_file_reads_as_empty(sandbox):
    assert fs.read_settings() == {}


def test_settings_round_trip(sandbox):
    fs.write_settings({"provider": "codex", "provider_config": {"codex": {"api_key": "k"}}})
    assert fs.read_settings()["provider"] == "codex"


def test_corrupt_settings_file_does_not_raise(sandbox):
    fs.SETTINGS_FILE.write_text("{not json")
    assert fs.read_settings() == {}


def test_write_is_atomic(sandbox):
    """A torn write would leave a .tmp file behind; it must be renamed away."""
    fs.write_settings({"provider": "opencode"})
    assert not list(sandbox.glob("settings.json.tmp"))
    assert fs.read_settings() == {"provider": "opencode"}


def test_defaults_to_claude_code_when_unset(sandbox):
    settings = fs.read_settings()
    provider = providers.get(settings.get("provider", providers.DEFAULT_PROVIDER_ID))
    assert provider.label == "Claude Code"
