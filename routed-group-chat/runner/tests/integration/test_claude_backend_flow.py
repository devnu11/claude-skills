"""Integration tests: ClaudeBackend wired through GroupChat end to end.

The Agent SDK's ``query`` is replaced by a fake that yields real
``claude_agent_sdk`` message objects; everything else is production code.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    CLINotFoundError,
    ResultMessage,
    SystemMessage,
    TextBlock,
)
from group_chat.backend import BackendError, ClaudeBackend
from group_chat.chat import PartialReplyError
from group_chat.state import Turn

from .conftest import MakeChat

pytestmark = pytest.mark.integration

CUE_RE = re.compile(r"Reply as @([a-z][a-z0-9-]*)\.$")


@dataclass
class FakeSdk:
    """Stands in for ``claude_agent_sdk.query``, answering per role cue."""

    replies: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    seen: list[tuple[str, ClaudeAgentOptions]] = field(default_factory=list)

    async def query(self, *, prompt: str, options: ClaudeAgentOptions) -> AsyncIterator[Any]:
        self.seen.append((prompt, options))
        cue = CUE_RE.search(prompt)
        text = self.replies.get(cue.group(1), "ok") if cue else "SDK SUMMARY"
        yield SystemMessage("init", {"session_id": "s"})
        yield AssistantMessage([TextBlock(text)], "claude-test")
        is_error = self.error is not None
        yield ResultMessage("success", 5, 4, is_error, 1, "s", result=self.error or text)


def test_reply_flows_through_sdk_messages(make_chat: MakeChat) -> None:
    sdk = FakeSdk({"po": "Cut search.\nDECISION: no search in v1"})
    chat = make_chat(ClaudeBackend(sdk.query))
    replies = chat.send("@po what do we cut?")
    assert replies[0].text == "Cut search.\nDECISION: no search in v1"
    assert chat.store.load().log.decisions[0].text == "no search in v1"


def test_options_are_tool_free_with_role_model(make_chat: MakeChat) -> None:
    sdk = FakeSdk()
    make_chat(ClaudeBackend(sdk.query)).send("@po @manager hi")
    (_, po_opts), (_, mgr_opts) = sdk.seen
    assert (po_opts.model, mgr_opts.model) == ("haiku", None)
    for opts in (po_opts, mgr_opts):
        assert opts.allowed_tools == []
        assert opts.setting_sources == []
        assert opts.max_turns == 1
    assert isinstance(po_opts.system_prompt, str)
    assert po_opts.system_prompt.startswith("You own the backlog.")


def test_handoff_and_compaction_through_sdk(make_chat: MakeChat) -> None:
    sdk = FakeSdk({"manager": "Over to PO.\nHANDOFF: @po"})
    chat = make_chat(ClaudeBackend(sdk.query), recent_tokens=1, keep_turns=1)
    replies = chat.send("@manager scope?")
    assert [t.speaker for t in replies] == ["manager", "po"]
    assert chat.store.load().summary == "SDK SUMMARY"


def test_sdk_error_keeps_human_turn_and_notes_failure(make_chat: MakeChat) -> None:
    sdk = FakeSdk(error="overloaded")
    chat = make_chat(ClaudeBackend(sdk.query))
    with pytest.raises(PartialReplyError, match="overloaded") as exc:
        chat.send("@po hi")
    assert isinstance(exc.value.__cause__, BackendError)
    assert chat.store.load().turns == [
        Turn("human", "@po hi"),
        Turn("orchestrator", "@po could not answer: overloaded"),
    ]


def test_sdk_exception_becomes_partial_reply_with_note(make_chat: MakeChat) -> None:
    sdk = FakeSdk({"manager": "Fine."})

    async def query(*, prompt: str, options: ClaudeAgentOptions) -> AsyncIterator[Any]:
        if prompt.endswith("Reply as @po."):
            raise CLINotFoundError("Claude Code not found")
        async for message in sdk.query(prompt=prompt, options=options):
            yield message

    chat = make_chat(ClaudeBackend(query))
    with pytest.raises(PartialReplyError) as exc:
        chat.send("@manager @po plan?")
    assert isinstance(exc.value, BackendError)
    note = Turn("orchestrator", "@po could not answer: CLINotFoundError: Claude Code not found")
    assert exc.value.replies == [Turn("manager", "Fine."), note]
    assert chat.store.load().turns[-2:] == exc.value.replies
