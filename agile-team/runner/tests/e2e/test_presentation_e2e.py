"""s13 end to end: presentation gate, sandbox copy, Proxy file access and the init error."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from agile_team import cli, gates
from agile_team.dispatch import StepRequest
from agile_team.gates import StoryStatus
from claude_agent_sdk import AssistantMessage, TextBlock

from ..conftest import GUIDE_TEXT, FakeQuery, handoff, present, result_message


def run(rt, role: str, story: str = "s1") -> dict[str, Any]:
    return asyncio.run(rt.run_role(StepRequest(role, "go", story)))


def open_story(rt, step: str) -> None:
    rt.state.sprint = 1
    rt.state.stories["s1"] = gates.StoryState("s1", "Add todo", step, sprint=1)


def gate_events(rt) -> list[Any]:
    return [e for e in rt.events.events() if e.kind == "gate"]


class ProxyProbe:
    """A Proxy step that tries tool calls through the real PreToolUse hook."""

    def __init__(self, repo: Path, calls: list[tuple[str, dict[str, Any]]]):
        self.repo, self.calls = repo, calls
        self.denied: list[bool] = []
        self.prompt = ""

    def __call__(self, *, prompt: str, options: Any) -> AsyncIterator[Any]:
        self.prompt = prompt
        return self._gen(options.hooks["PreToolUse"][0].hooks[0])

    async def _gen(self, hook) -> AsyncIterator[Any]:
        for name, tool_input in self.calls:
            out = await hook({"tool_name": name, "tool_input": tool_input}, None, None)
            self.denied.append(bool(out))
        yield AssistantMessage(content=[TextBlock(text="probing")], model="m")
        yield result_message(handoff("done"))


# ----- the e2e gate -----------------------------------------------------------


def test_e2e_gate_fails_without_a_presentation_and_passes_with_one(make_runtime) -> None:
    """AC3: done at e2e bounces to e2e until the presentation is complete."""
    q = FakeQuery()
    rt = make_runtime(q)
    rt.pipeline.steps = ["e2e", "acceptance"]
    open_story(rt, "e2e")
    first = run(rt, "integration-tester")
    story = rt.state.stories["s1"]
    assert first["gate"]["verdict"] == "bounce" and "has no presentation" in first["gate"]["reason"]
    assert (story.step, story.rounds) == ("e2e", 1)
    # The runner laid out the dir (git workspace) but the tester wrote nothing into it.
    assert (rt.config.run_dir / "presentation/s1/workspace/.git").exists()
    q.action = lambda: present(rt.config)  # the tester builds it during the step
    second = run(rt, "integration-tester")
    assert second["gate"]["verdict"] == "pass"
    assert story.step == "acceptance"


def test_each_delivery_gets_its_own_presentation_dir(make_runtime) -> None:
    """AC1: the runner lays out a fresh dir per story; a second story is unaffected."""
    rt = make_runtime(FakeQuery())
    rt.pipeline.steps = ["e2e", "acceptance"]
    open_story(rt, "e2e")
    present(rt.config, "s2")
    stale = present(rt.config, "s1")
    run(rt, "integration-tester")
    assert (rt.config.run_dir / "presentation/s2/PRESENTATION.md").exists()
    assert not (stale / "PRESENTATION.md").exists()  # s1's old presentation was wiped


def test_proxy_on_an_unpresented_story_is_returned_free(make_runtime) -> None:
    """AC2/AC3: no presentation means no Proxy, no sandbox and no round."""
    q = FakeQuery()
    rt = make_runtime(q)
    rt.pipeline.steps = ["e2e", "acceptance"]
    open_story(rt, "acceptance")
    report = run(rt, "customer-proxy")
    story = rt.state.stories["s1"]
    assert report["status"] == "returned"
    assert (story.step, story.rounds, story.status) == ("e2e", 0, StoryStatus.ACTIVE)
    assert q.calls == [] and gate_events(rt)[-1].data["verdict"] == "return"


# ----- the copy and the Proxy's file access ------------------------------------


def test_presentation_is_copied_into_the_proxy_sandbox(make_runtime) -> None:
    """AC3: the sandbox holds the copy, its symlink stays a link, the prompt quotes the guide."""
    probe = ProxyProbe(Path(), [])
    rt = make_runtime(probe)
    rt.pipeline.steps = ["e2e", "acceptance"]
    open_story(rt, "acceptance")
    source = present(rt.config)
    os.symlink(rt.config.repo / "src" / "app.py", source / "workspace" / "link")
    assert run(rt, "customer-proxy")["status"] == "done"
    copy = rt.config.run_dir / "customer/cli/presentation"
    assert (copy / "workspace/todo.txt").read_text() == "milk\n"
    assert (copy / "workspace/link").is_symlink()
    assert "## What the team presents" in probe.prompt and GUIDE_TEXT.strip() in probe.prompt


def test_proxy_reads_and_rewrites_its_report_but_not_source(make_runtime) -> None:
    """AC3/AC5: acceptance file and copied workspace readable; source, tests, the link are not."""
    repo_cfg = make_runtime(FakeQuery()).config
    copy = repo_cfg.run_dir / "customer/cli/presentation/workspace"
    report = ".team/acceptance/s1.md"
    calls = [
        ("Write", {"file_path": str(repo_cfg.repo / report)}),
        ("Read", {"file_path": str(repo_cfg.repo / report)}),
        ("Read", {"file_path": str(copy / "todo.txt")}),
        ("Read", {"file_path": str(repo_cfg.repo / "src/app.py")}),
        ("Read", {"file_path": str(repo_cfg.repo / "tests/test_x.py")}),
        ("Read", {"file_path": str(copy / "link")}),
        ("Write", {"file_path": str(repo_cfg.repo / "src/app.py")}),
    ]
    probe = ProxyProbe(repo_cfg.repo, calls)
    rt = make_runtime(probe)
    rt.pipeline.steps = ["e2e", "acceptance"]
    open_story(rt, "acceptance")
    source = present(rt.config)
    (rt.config.repo / "src/app.py").parent.mkdir(exist_ok=True)
    os.symlink(rt.config.repo / "src" / "app.py", source / "workspace" / "link")
    run(rt, "customer-proxy")
    assert probe.denied == [False, False, False, True, True, True, True]


# ----- agile-team init outside git ---------------------------------------------


def test_init_outside_git_exits_1_with_a_message(tmp_path, monkeypatch, capsys) -> None:
    """AC6: no traceback, the promised message on stderr, exit code 1."""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    plain = tmp_path / "plain"
    plain.mkdir()
    for target in (plain, tmp_path / "missing"):
        code = cli.main(
            ["--repo", str(target), "init", "--preset", "python", "--delivery", "package"]
        )
        err = capsys.readouterr().err
        assert code == 1
        assert err == f"agile-team init: not a git repository: {target}; run git init first\n"
