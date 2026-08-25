"""Coding agent providers and how to launch them in headless mode.

Each provider knows its own executable, the argument shape needed to run a
single prompt non-interactively, and which configuration the user has to
supply for it. ``agent.py`` stays provider-agnostic and just asks for an
argv and an environment.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class ConfigField:
    """One input rendered in the settings modal for a provider."""

    key: str
    label: str
    placeholder: str = ""
    secret: bool = False
    required: bool = False


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    default_command: str
    # Builds the argv for one headless run, given the executable, the
    # prompt, the provider config and any user-supplied extra flags.
    build_argv: Callable[[str, str, dict, list[str]], list[str]]
    fields: tuple[ConfigField, ...] = ()
    # Env vars to remove before launching (e.g. to force subscription auth).
    strip_env: tuple[str, ...] = ()
    # Config key -> env var the provider reads its credential from.
    env_from_config: dict = field(default_factory=dict)

    def command(self, config: dict) -> str:
        return (config.get("command") or "").strip() or self.default_command

    def argv(self, prompt: str, config: dict) -> list[str]:
        extra = shlex.split(config.get("extra_args", "") or "")
        return self.build_argv(self.command(config), prompt, config, extra)

    def missing_fields(self, config: dict) -> list[str]:
        return [
            f.label
            for f in self.fields
            if f.required and not (config.get(f.key) or "").strip()
        ]


def _model_args(flag: str, config: dict) -> list[str]:
    model = (config.get("model") or "").strip()
    return [flag, model] if model else []


def _claude_argv(command, prompt, config, extra) -> list[str]:
    # Claude Code takes the prompt as the value of -p.
    return [
        command,
        "--dangerously-skip-permissions",
        *_model_args("--model", config),
        *extra,
        "-p",
        prompt,
    ]


def _opencode_argv(command, prompt, config, extra) -> list[str]:
    # OpenCode and Codex both take the prompt as a trailing positional, so
    # flags have to go before it.
    return [command, "run", *_model_args("--model", config), *extra, prompt]


def _codex_argv(command, prompt, config, extra) -> list[str]:
    return [
        command,
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        *_model_args("--model", config),
        *extra,
        prompt,
    ]


_COMMAND_FIELD = ConfigField(
    key="command",
    label="Executable",
    placeholder="leave blank to use the default on PATH",
)
_EXTRA_ARGS_FIELD = ConfigField(
    key="extra_args",
    label="Extra arguments",
    placeholder="optional, appended to every run",
)

PROVIDERS: tuple[Provider, ...] = (
    Provider(
        id="claude_code",
        label="Claude Code",
        default_command="claude",
        build_argv=_claude_argv,
        fields=(
            _COMMAND_FIELD,
            ConfigField("model", "Model", "optional, e.g. claude-opus-5"),
            _EXTRA_ARGS_FIELD,
        ),
        # Claude Code runs on the user's claude.ai subscription login, so any
        # API-key vars in the parent shell are removed to stop it switching
        # to API billing mid-run.
        strip_env=("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"),
    ),
    Provider(
        id="opencode",
        label="OpenCode",
        default_command="opencode",
        build_argv=_opencode_argv,
        fields=(
            _COMMAND_FIELD,
            ConfigField("model", "Model", "e.g. anthropic/claude-sonnet-5", required=True),
            ConfigField("api_key", "API key", "stored locally", secret=True, required=True),
            _EXTRA_ARGS_FIELD,
        ),
        env_from_config={"api_key": "OPENCODE_API_KEY"},
    ),
    Provider(
        id="codex",
        label="Codex",
        default_command="codex",
        build_argv=_codex_argv,
        fields=(
            _COMMAND_FIELD,
            ConfigField("model", "Model", "optional, e.g. gpt-5-codex"),
            ConfigField("api_key", "API key", "stored locally", secret=True, required=True),
            _EXTRA_ARGS_FIELD,
        ),
        env_from_config={"api_key": "OPENAI_API_KEY"},
    ),
)

DEFAULT_PROVIDER_ID = PROVIDERS[0].id
PROVIDER_LABELS = [p.label for p in PROVIDERS]

_BY_ID = {p.id: p for p in PROVIDERS}
_BY_LABEL = {p.label: p for p in PROVIDERS}


def get(provider_id: str) -> Provider:
    """Look up a provider by id, falling back to the default."""
    return _BY_ID.get(provider_id, _BY_ID[DEFAULT_PROVIDER_ID])


def id_for_label(label: str) -> str:
    provider = _BY_LABEL.get(label)
    return provider.id if provider else DEFAULT_PROVIDER_ID


def label_for_id(provider_id: str) -> str:
    return get(provider_id).label
