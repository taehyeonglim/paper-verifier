"""LLM provider abstraction for Phase-2 semantic checks.

paper-verifier never talks to an LLM API directly. Phase 2 shells out to a
local CLI: the prompt is piped to stdin and a small JSON object is expected
on stdout. Which CLI runs is declared here::

    [llm]
    provider = "codex"            # or "claude", or "none"
    # argv = ["mycli", "--flag"]  # custom command (overrides provider preset)
    # timeout = 120

Presets deliberately do NOT pin a model — the user's CLI default applies.
To pin one, declare a custom argv, e.g. for Codex::

    argv = ["codex", "exec", "--sandbox", "read-only", "--skip-git-repo-check",
            "-c", "model=\\"gpt-5.6-terra\\"", "-"]

When no provider is available (``provider = "none"`` or the binary is not on
PATH), semantic checks degrade to MANUAL instead of failing the run.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LLMProvider:
    name: str
    argv: tuple[str, ...]  # prompt is piped via stdin; JSON parsed from stdout


PRESETS: dict[str, LLMProvider] = {
    "codex": LLMProvider(
        "codex",
        ("codex", "exec", "--sandbox", "read-only", "--skip-git-repo-check", "-"),
    ),
    "claude": LLMProvider(
        "claude",
        ("claude", "-p"),
    ),
}

_OFF = {"none", "off", ""}


def resolve(provider: str = "codex", argv: tuple[str, ...] = ()) -> LLMProvider | None:
    """Resolve config values to a provider. ``None`` means "no LLM available".

    A custom ``argv`` wins over the preset. Unknown provider names raise so
    config typos fail loudly instead of silently disabling Phase 2.
    """
    if argv:
        return LLMProvider(provider if provider not in _OFF else "custom", tuple(argv))
    if provider is None or provider.lower() in _OFF:
        return None
    try:
        return PRESETS[provider]
    except KeyError:
        raise ValueError(
            f"unknown [llm].provider {provider!r} — use one of "
            f"{sorted(PRESETS)}, 'none', or declare a custom argv"
        ) from None
