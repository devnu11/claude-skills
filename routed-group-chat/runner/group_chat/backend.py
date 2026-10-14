"""The model call behind each role: one tool-free, single-turn completion.

``ClaudeBackend`` runs on the user's Claude Code login through the Agent SDK,
loading no settings, tools or connectors so each turn's context is only what
``context`` builds. Tests pass a fake that satisfies ``Backend``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query

QueryFn = Callable[..., AsyncIterator[Any]]


class BackendError(RuntimeError):
    """The model returned an error or nothing."""


class Backend(Protocol):
    def complete(self, system: str, prompt: str, model: str | None) -> str: ...


def options_for(system: str, model: str | None) -> ClaudeAgentOptions:
    """A single turn with no tools and none of the user's settings."""
    return ClaudeAgentOptions(
        system_prompt=system,
        model=model,
        max_turns=1,
        allowed_tools=[],
        setting_sources=[],
    )


def text_of(message: Any) -> str:
    if not isinstance(message, AssistantMessage):
        return ""
    return "\n".join(block.text for block in message.content if isinstance(block, TextBlock))


@dataclass(frozen=True)
class ClaudeBackend:
    """Completes through ``claude_agent_sdk.query``."""

    query_fn: QueryFn = query

    def complete(self, system: str, prompt: str, model: str | None) -> str:
        return asyncio.run(self._collect(system, prompt, model))

    async def _collect(self, system: str, prompt: str, model: str | None) -> str:
        text, result = "", None
        async for message in self.query_fn(prompt=prompt, options=options_for(system, model)):
            text = text_of(message) or text
            if isinstance(message, ResultMessage):
                result = message
        return _final(text, result)


def _final(text: str, result: ResultMessage | None) -> str:
    if result is not None and result.is_error:
        raise BackendError(result.result or "model returned an error")
    final = (result.result if result else None) or text
    if not final.strip():
        raise BackendError("model returned no text")
    return final.strip()
