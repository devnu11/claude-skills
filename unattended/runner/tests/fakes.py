"""A fake Claude Code session for prompt-job tests: a scripted ``ClaudeSDKClient``.

A script is a list of items, played in order once a prompt is sent:

- an SDK message is yielded as the CLI would send it;
- ``Tool`` is a tool step: the PreToolUse hook runs, then (unless it refused the
  step) the tool, then the PostToolUse hook. A hook that ends the loop
  (``continue_: False``) makes the fake end the response with ``STOPPED``;
- ``Sleep`` pauses the response; ``Sleep(math.inf)`` hangs until cancelled.

Each later prompt plays the next script in ``FakeClient.scripts``.
"""

from __future__ import annotations

import math
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import anyio
from claude_agent_sdk import ClaudeAgentOptions, ResultMessage
from unattended.steps import POST, PRE

USAGE = {"input_tokens": 10, "output_tokens": 5}
STOPPED = ResultMessage(
    "success", 1, 1, False, 2, "s1", total_cost_usd=0.1, usage=USAGE, result="stopped"
)


@dataclass(frozen=True)
class Tool:
    """A tool step: the hooks around one tool call."""

    name: str = "Bash"


@dataclass(frozen=True)
class Sleep:
    """A pause in the response; ``math.inf`` hangs until the run is cancelled."""

    seconds: float


@dataclass
class FakeClient:
    """Plays one script per prompt; records prompts, options, hook replies and cleanup."""

    script: list[Any] = field(default_factory=list)
    error: BaseException | None = None
    scripts: list[list[Any]] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    replies: list[dict[str, Any]] = field(default_factory=list)
    on_message: list[Any] = field(default_factory=list)
    closed: bool = False

    def __call__(self, options: ClaudeAgentOptions) -> FakeSession:
        return FakeSession(self, options)

    def next_script(self) -> list[Any]:
        """The script for the next prompt: ``script`` first, then ``scripts`` in turn."""
        return self.scripts.pop(0) if self.calls[1:] and self.scripts else self.script


@dataclass
class FakeSession:
    """One connected session of a ``FakeClient``."""

    fake: FakeClient
    options: ClaudeAgentOptions

    async def connect(self) -> None:
        self.fake.closed = False

    async def query(self, prompt: str) -> None:
        self.fake.calls.append({"prompt": prompt, "options": self.options})

    async def receive_response(self) -> AsyncIterator[Any]:
        for item in self.fake.next_script():
            if isinstance(item, Sleep):
                await pause(item.seconds)
            elif isinstance(item, Tool):
                if await self.run_step(item):
                    yield STOPPED
                    return
            else:
                yield item
                for check in self.fake.on_message:
                    check()
        if self.fake.error and len(self.fake.calls) == 1:
            raise self.fake.error

    async def run_step(self, tool: Tool) -> bool:
        """Run the hooks around ``tool``; True when a hook ended the loop."""
        if ended(await self.call_hook(PRE, tool)):
            return True
        reply = await self.call_hook(POST, tool)
        self.fake.replies.append(reply)
        return ended(reply)

    async def call_hook(self, event: str, tool: Tool) -> dict[str, Any]:
        hooks = (self.options.hooks or {}).get(event, [])  # type: ignore[call-overload]
        data = {"hook_event_name": event, "tool_name": tool.name, "tool_input": {}}
        replies = [await hook(data, "tool-1", {"signal": None}) for m in hooks for hook in m.hooks]
        return {key: value for reply in replies for key, value in reply.items()}

    async def disconnect(self) -> None:
        self.fake.closed = True


def ended(reply: dict[str, Any]) -> bool:
    return reply.get("continue_") is False


async def pause(seconds: float) -> None:
    if math.isinf(seconds):
        await anyio.sleep_forever()
    await anyio.sleep(seconds)
