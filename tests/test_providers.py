"""Provider definitions and headless invocation shape (issue #5)."""

from __future__ import annotations

import pytest

from groundhog.lib import providers


def test_all_three_agents_are_available():
    assert [p.id for p in providers.PROVIDERS] == ["claude_code", "opencode", "codex"]


def test_claude_code_is_the_default():
    assert providers.DEFAULT_PROVIDER_ID == "claude_code"
    assert providers.get("nonexistent").id == "claude_code"


def test_label_and_id_round_trip():
    for provider in providers.PROVIDERS:
        assert providers.id_for_label(provider.label) == provider.id
        assert providers.label_for_id(provider.id) == provider.label


@pytest.mark.parametrize(
    "provider_id,expected",
    [
        ("claude_code", ["claude", "--dangerously-skip-permissions", "-p", "GO"]),
        ("opencode", ["opencode", "run", "GO"]),
        ("codex", ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox", "GO"]),
    ],
)
def test_headless_argv(provider_id, expected):
    assert providers.get(provider_id).argv("GO", {}) == expected


def test_prompt_stays_last_for_positional_agents():
    """OpenCode and Codex take the prompt as a trailing positional, so any
    flags we add must come before it."""
    config = {"model": "m", "extra_args": "--quiet"}
    for provider_id in ("opencode", "codex"):
        argv = providers.get(provider_id).argv("GO", config)
        assert argv[-1] == "GO"
        assert "--quiet" in argv[:-1]


def test_executable_can_be_overridden():
    argv = providers.get("codex").argv("GO", {"command": "/opt/bin/codex"})
    assert argv[0] == "/opt/bin/codex"


def test_blank_command_falls_back_to_default():
    assert providers.get("opencode").command({"command": "   "}) == "opencode"


def test_extra_args_are_shell_split():
    argv = providers.get("claude_code").argv("GO", {"extra_args": '--a "b c"'})
    assert "--a" in argv and "b c" in argv


def test_model_flag_omitted_when_blank():
    assert "--model" not in providers.get("codex").argv("GO", {"model": "  "})


def test_required_fields_reported_per_provider():
    assert providers.get("claude_code").missing_fields({}) == []
    assert providers.get("opencode").missing_fields({}) == ["Model", "API key"]
    assert providers.get("codex").missing_fields({}) == ["API key"]
    assert providers.get("codex").missing_fields({"api_key": "k"}) == []


def test_api_key_fields_are_marked_secret():
    for provider_id in ("opencode", "codex"):
        secret = {f.key for f in providers.get(provider_id).fields if f.secret}
        assert secret == {"api_key"}
