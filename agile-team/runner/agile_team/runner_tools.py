"""The developer's runner tools: named tests only, run as a runner chore (s69 R1-R10)."""

from __future__ import annotations

import asyncio
import json
import shlex
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from . import stages, system
from .config import Targeted, Toolchain
from .events import EventKind
from .gates import StoryState, test_file
from .results import result_tail
from .suite_check import is_target

if TYPE_CHECKING:
    from .dispatch import Plan, Runtime

SERVER = "runner"
TESTS_CHORE = "running named tests for {role} on {story}"
NO_TESTS_NAMED = "name at least one test file or node id"
NOT_A_TARGET = "{test} names no test file or node id; the runner never runs the full suite"
UNTRACKED_TEST = "{test}: no single tracked file matches {file}"
NO_TARGETED = "no [[toolchain.targeted]] command is configured; run the tests by name in Bash"
NO_ROOT = "{test}: no [[toolchain.targeted]] root holds {path}"
NO_STORY = "this step has no story; name the tests with run_tests"
NO_NEW_TESTS = "no new tests are recorded for {story}; name them with run_tests"
TEST_FILE_NAMES = ("test_*.py", "*_test.py")
TESTS_PLACEHOLDER = "{tests}"
NO_STORY_ID = "-"
SCHEMAS = {
    "run_tests": (
        "Run named tests (test files or node ids, repo-relative or as pytest prints "
        "them) and get their output. The runner never runs the full suite.",
        {"tests": list},
    ),
    "run_new_tests": (
        "Run the story's new tests (the test files the unit-tester committed for it) "
        "and get their output.",
        {},
    ),
}


def text_result(data: Any) -> dict[str, Any]:
    """MCP tool result carrying ``data`` as JSON text."""
    return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]}


class Refused(Exception):
    """A request the runner will not run; the message is the reason."""


def located(test: str, path: str) -> str:
    """``test`` with its file part replaced by the tracked repo path (R3)."""
    return path + test.removeprefix(test_file(test))


@dataclass(frozen=True)
class Batch:
    """One targeted command and the root-relative ids it runs (R5)."""

    row: Targeted
    tests: tuple[str, ...]

    @property
    def command(self) -> str:
        """The row's command with the quoted ids in place of ``{tests}``."""
        ids = " ".join(shlex.quote(t) for t in self.tests)
        return self.row.command.replace(TESTS_PLACEHOLDER, ids)


def _row_for(path: str, toolchain: Toolchain) -> Targeted:
    row = toolchain.targeted_for(test_file(path))
    if row is None:
        raise Refused(NO_ROOT.format(test=path, path=test_file(path)))
    return row


def batches(paths: list[str], toolchain: Toolchain) -> list[Batch]:
    """Located ids grouped by their targeted row, rows in first-seen order (R5)."""
    if not toolchain.targeted:
        raise Refused(NO_TARGETED)
    grouped: dict[Targeted, list[str]] = {}
    for path in paths:
        row = _row_for(path, toolchain)
        grouped.setdefault(row, []).append(row.relative(path))
    return [Batch(row, tuple(tests)) for row, tests in grouped.items()]


def new_tests(story: StoryState, repo: Path) -> list[str]:
    """The story's recorded test files that match TEST_FILE_NAMES and exist now (R6)."""
    return [f for f in story.test_files if _is_test_file(f) and system.is_file(repo / f)]


def _is_test_file(path: str) -> bool:
    name = PurePosixPath(path).name
    return any(fnmatch(name, pattern) for pattern in TEST_FILE_NAMES)


@dataclass
class RunnerTools:
    """A developer step's runner tools: named tests only, run as a runner chore (R1-R10)."""

    runtime: Runtime
    plan: Plan

    async def run_tests(self, args: dict[str, Any]) -> dict[str, Any]:
        """Run the named tests."""
        return text_result(await self._reply(list(args.get("tests") or []), stages.RUNNER_TOOL["run_tests"]))

    async def run_new_tests(self, args: dict[str, Any]) -> dict[str, Any]:
        """Run the story's new test files."""
        return text_result(await self._reply(self._new_tests, stages.RUNNER_TOOL["run_new_tests"]))

    @property
    def _new_tests(self) -> list[str] | Refused:
        story = self.plan.story
        if story is None:
            return Refused(NO_STORY)
        found = new_tests(story, self.runtime.config.repo)
        return found or Refused(NO_NEW_TESTS.format(story=story.id))

    async def _reply(self, tests: list[str] | Refused, stage: stages.Name) -> dict[str, Any]:
        try:
            ids = self._locate(self._named(tests))
            plan = batches(ids, self.runtime.config.toolchain)
            with self.runtime.stage_log.open(stage):
                return await self._run(ids, plan)
        except Refused as refusal:
            return {"status": "refused", "reason": str(refusal)}

    @staticmethod
    def _named(tests: list[str] | Refused) -> list[str]:
        if isinstance(tests, Refused):
            raise tests
        if not tests:
            raise Refused(NO_TESTS_NAMED)
        bad = next((t for t in tests if not is_target(t)), None)
        if bad is not None:
            raise Refused(NOT_A_TARGET.format(test=bad))
        return tests

    def _locate(self, tests: list[str]) -> list[str]:
        return [located(t, self._path(t)) for t in tests]

    def _path(self, test: str) -> str:
        file = test_file(test)
        path = self.runtime.pipeline.checks.tracked(file)
        if path is None:
            raise Refused(UNTRACKED_TEST.format(test=test, file=file))
        return path

    async def _run(self, ids: list[str], plan: list[Batch]) -> dict[str, Any]:
        story = self.plan.story.id if self.plan.story else NO_STORY_ID
        started = system.monotonic()
        with self.runtime.pulse.doing(TESTS_CHORE.format(role=self.plan.role.name, story=story)):
            runs = [await self._run_batch(batch) for batch in plan]
        seconds = round(system.monotonic() - started, 1)
        self._log(ids, runs, seconds)
        return {"status": "ran", "runs": runs, "seconds": seconds}

    async def _run_batch(self, batch: Batch) -> dict[str, Any]:
        code, out = await asyncio.to_thread(self.runtime.pipeline.checks.run, batch.command)
        return {"command": batch.command, "exit": code, "output": result_tail(out)}

    def _log(self, ids: list[str], runs: list[dict[str, Any]], seconds: float) -> None:
        exits = [r["exit"] for r in runs]
        self.runtime.emit(EventKind.TESTS_RUN, self.plan, tests=ids, exits=exits, seconds=seconds)


def mcp_server(tools: RunnerTools) -> Any:
    """SDK MCP server ``runner`` exposing SCHEMAS (same shape as ``po_tools.mcp_server``)."""
    defs = [
        tool(name, desc, schema)(getattr(tools, name)) for name, (desc, schema) in SCHEMAS.items()
    ]
    return create_sdk_mcp_server(SERVER, tools=defs)


def tool_names() -> list[str]:
    """``mcp__runner__<name>`` for each tool."""
    return [f"mcp__{SERVER}__{name}" for name in SCHEMAS]
