"""The model call behind each role: one tool-free, single-turn completion.

``ClaudeBackend`` runs on the user's Claude Code login through the Agent SDK.
``build_options`` isolates each call the way agile-team's ``dispatch`` does: no
tools exist (``tools=[]``, not just none pre-approved), no MCP servers load
(``strict_mcp_config``, and claude.ai connectors are switched off in the env),
and no user or project settings apply, so a role's context is only what
``context`` builds. Tests pass a fake that satisfies ``Backend``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKError,
    ResultMessage,
    TextBlock,
    query,
)

type QueryFn = Callable[..., AsyncIterator[Any]]
ISOLATION_ENV = {"ENABLE_CLAUDEAI_MCP_SERVERS": "false"}


class BackendError(RuntimeError):
    """The model returned an error or nothing, or the SDK or CLI failed."""


class Backend(Protocol):
    """Anything that turns a system prompt and a user prompt into reply text."""

    def complete(self, system: str, prompt: str, model: str | None) -> str: ...


def build_options(system: str, model: str | None) -> ClaudeAgentOptions:
    """A single turn with no tools, MCP servers, connectors or user settings."""
    return ClaudeAgentOptions(
        system_prompt=system,
        model=model,
        max_turns=1,
        tools=[],
        allowed_tools=[],
        strict_mcp_config=True,
        env=dict(ISOLATION_ENV),
        setting_sources=[],
    )


def join_text(message: Any) -> str:
    """The text blocks of an assistant message, joined; ``""`` for anything else."""
    if not isinstance(message, AssistantMessage):
        return ""
    return "\n".join(block.text for block in message.content if isinstance(block, TextBlock))


@dataclass(frozen=True)
class ClaudeBackend:
    """Completes through ``claude_agent_sdk.query``."""

    query_fn: QueryFn = query

    def complete(self, system: str, prompt: str, model: str | None) -> str:
        """The reply text; ``BackendError`` on an error result, no text or an SDK error."""
        try:
            return asyncio.run(self._collect(system, prompt, model))
        except ClaudeSDKError as exc:
            raise BackendError(f"{type(exc).__name__}: {exc}") from exc

    async def _collect(self, system: str, prompt: str, model: str | None) -> str:
        text, result = "", None
        async for message in self.query_fn(prompt=prompt, options=build_options(system, model)):
            text = join_text(message) or text
            if isinstance(message, ResultMessage):
                result = message
        return _pick_final_text(text, result)


def _pick_final_text(text: str, result: ResultMessage | None) -> str:
    if result is not None and result.is_error:
        raise BackendError(result.result or "model returned an error")
    final = (result.result if result else None) or text
    if not final.strip():
        raise BackendError("model returned no text")
    return final.strip()
