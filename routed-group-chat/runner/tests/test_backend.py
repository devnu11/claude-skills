"""Unit tests for ``backend``: the Agent SDK call, with ``query`` faked."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
)
from group_chat.backend import BackendError, ClaudeBackend, options_for, text_of

pytestmark = pytest.mark.unit


def assistant(text: str) -> AssistantMessage:
    return AssistantMessage([TextBlock(text)], "model")


def result(text: str | None, is_error: bool = False) -> ResultMessage:
    return ResultMessage("success", 1, 1, is_error, 1, "s", result=text)


def scripted(*messages: Any) -> tuple[ClaudeBackend, list[dict[str, Any]]]:
    seen: list[dict[str, Any]] = []

    async def query_fn(**kwargs: Any) -> AsyncIterator[Any]:
        seen.append(kwargs)
        for message in messages:
            yield message

    return ClaudeBackend(query_fn), seen


def test_options_are_single_turn_and_tool_free() -> None:
    options = options_for("sys", "haiku")
    assert options.system_prompt == "sys"
    assert options.model == "haiku"
    assert options.max_turns == 1
    assert options.allowed_tools == []
    assert options.setting_sources == []


def test_complete_prefers_result_text() -> None:
    backend, seen = scripted(assistant("draft"), result(" final "))
    assert backend.complete("sys", "hi", None) == "final"
    assert seen[0]["prompt"] == "hi"


def test_complete_falls_back_to_assistant_text() -> None:
    backend, _ = scripted(assistant("only text"), result(None))
    assert backend.complete("sys", "hi", None) == "only text"


def test_complete_without_result_message() -> None:
    backend, _ = scripted(assistant("a"), "noise")
    assert backend.complete("sys", "hi", None) == "a"


def test_error_result_raises() -> None:
    backend, _ = scripted(result("rate limited", is_error=True))
    with pytest.raises(BackendError, match="rate limited"):
        backend.complete("sys", "hi", None)


def test_error_result_without_text() -> None:
    backend, _ = scripted(result(None, is_error=True))
    with pytest.raises(BackendError, match="model returned an error"):
        backend.complete("sys", "hi", None)


def test_empty_reply_raises() -> None:
    backend, _ = scripted(result("  "))
    with pytest.raises(BackendError, match="no text"):
        backend.complete("sys", "hi", None)


def test_text_of_ignores_other_messages() -> None:
    assert text_of(result("x")) == ""


def test_options_default_model_is_none() -> None:
    assert options_for("sys", None).model is None


def test_text_of_joins_text_blocks_and_skips_thinking() -> None:
    message = AssistantMessage([TextBlock("a"), ThinkingBlock("hmm", "sig"), TextBlock("b")], "m")
    assert text_of(message) == "a\nb"


def test_last_non_empty_assistant_text_wins() -> None:
    thinking = AssistantMessage([ThinkingBlock("hmm", "sig")], "m")
    backend, _ = scripted(assistant("first"), assistant("second"), thinking)
    assert backend.complete("sys", "hi", None) == "second"


def test_system_messages_are_ignored() -> None:
    backend, _ = scripted(SystemMessage("init", {}), assistant("ok"), result("ok"))
    assert backend.complete("sys", "hi", None) == "ok"


def test_no_messages_raises() -> None:
    backend, _ = scripted()
    with pytest.raises(BackendError, match="no text"):
        backend.complete("sys", "hi", None)


def test_query_gets_options_for_role() -> None:
    backend, seen = scripted(result("x"))
    backend.complete("the system", "p", "opus")
    options = seen[0]["options"]
    assert (options.system_prompt, options.model) == ("the system", "opus")
