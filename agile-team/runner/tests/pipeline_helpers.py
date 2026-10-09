"""Helpers for s19 tests: a scripted fake query and a pipeline-aware command runner."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from agile_team import gates
from agile_team.dispatch import Runtime
from agile_team.po_tools import Start
from claude_agent_sdk import AssistantMessage, TextBlock

from .conftest import handoff, result_message

PO_ROLE = "product-owner"


class Script:
    """A fake ``query``: PO turns run ``po`` actions; role steps pop ``replies[role]``.

    A reply is handoff text, an exception to raise, or a callable run before the
    default. Roles with no reply left answer ``done``. ``rt`` must be set before use.
    """

    def __init__(self, replies: dict[str, list[Any]] | None = None, po: list[Any] | None = None):
        self.replies = {k: list(v) for k, v in (replies or {}).items()}
        self.po = list(po or [])
        self.rt: Runtime | None = None
        self.calls: list[tuple[str, str]] = []

    @property
    def po_prompts(self) -> list[str]:
        return [p for r, p in self.calls if r == PO_ROLE]

    @property
    def prompts(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for role, prompt in self.calls:
            out.setdefault(role, []).append(prompt)
        return out

    def __call__(self, *, prompt: str, options: Any) -> AsyncIterator[Any]:
        role = PO_ROLE if options.mcp_servers else self.rt.events.events()[-1].role
        self.calls.append((role, prompt))
        return self._gen(role)

    async def _gen(self, role: str) -> AsyncIterator[Any]:
        queue = self.po if role == PO_ROLE else self.replies.get(role, [])
        item = queue.pop(0) if queue else None
        if callable(item):
            await item(self.rt)
            item = None
        if isinstance(item, BaseException):
            raise item
        yield AssistantMessage(content=[TextBlock(text="thinking")], model="m")
        yield result_message(item if isinstance(item, str) else handoff())


class PipelineRunner:
    """Gate commands: the test run is red at ``tests`` and green elsewhere.

    ``failures`` is how many times the implement gate's test run fails first.
    """

    def __init__(self, failures: int = 0):
        self.rt: Runtime | None = None
        self.failures = failures

    def __call__(self, command: str) -> tuple[int, str]:
        if command == "pytest --cov":
            return 0, "TOTAL   10   0   100%"
        step = next(iter(s.step for s in self.rt.state.stories.values()), "")
        if step == "tests":
            return 1, "red"
        if step == "implement" and self.failures:
            self.failures -= 1
            return 1, "boom: assertion failed"
        return 0, "ok"


def build(make_runtime: Callable[..., Runtime], script: Script, **kw: Any) -> Runtime:
    """A runtime on ``script`` and a pipeline runner, steps trimmed by ``steps``."""
    steps = kw.pop("steps", ["design", "tests", "implement", "review"])
    runner = PipelineRunner(kw.pop("failures", 0))
    rt = make_runtime(script, runner=runner, **kw)
    script.rt = runner.rt = rt
    rt.pipeline.steps = list(steps)
    return rt


def add_story(rt: Runtime, sid: str = "s1", step: str = "design", **kw: Any) -> gates.StoryState:
    """Put a story in the current sprint (sprint 1 unless told otherwise)."""
    rt.state.sprint = max(rt.state.sprint, 1)
    kw.setdefault("sprint", 1)
    rt.state.stories[sid] = gates.StoryState(sid, f"Title {sid}", step, **kw)
    return rt.state.stories[sid]


def step_roles(rt: Runtime) -> list[str]:
    """The role of every ``step-start`` event, in order."""
    return [e.role for e in rt.events.events() if e.kind == "step-start"]


def handover_events(rt: Runtime) -> list[Any]:
    return [e for e in rt.events.events() if e.kind == "handover"]


def drive(rt: Runtime, task: str = "go") -> Any:
    """Run the whole driver once from a kickoff."""
    from agile_team import po_tools

    return asyncio.run(po_tools.run_po(rt, Start(task)))


def ask_and_answer(rt: Runtime, text: str = "Which DB?", stories=("s1",), answer="sqlite") -> str:
    """Post a question and record its answer; returns the question id."""
    from agile_team.relay import Note

    msg = rt.relay.post(Note("question", text, list(stories)))
    rt.relay.answer(msg.id, answer)
    return msg.id


def write_file(rt: Runtime, rel: str, text: str = "x") -> Path:
    path: Path = rt.config.repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path
