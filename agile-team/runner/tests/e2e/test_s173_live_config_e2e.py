"""s173 end to end on real git: a committed ``.agile-team.toml`` is live without a restart.

``cli.make_runtime`` builds the runtime as ``agile-team start`` does; a scratch commit on the
main checkout stands for a storyless DevOps step. One group per AC id.
"""

from __future__ import annotations

import asyncio
import copy
from pathlib import Path

import tomli_w
from agile_team import cli, system
from agile_team.config import CONFIG_NAME
from agile_team.dispatch import Runtime, StepRequest
from agile_team.events import EventKind
from agile_team.git_ops import Authored
from agile_team.handover import Trigger
from agile_team.po_tools import Start
from agile_team.scheduler import Scheduler

from ..conftest import PY_CONFIG, FakeQuery, git

DRAFT = (
    '---\ntitle: "Add todo"\nacceptance:\n'
    '  - id: AC1\n    text: "adds an item"\n    environment: {env}\n'
    "---\n\nAs a user, I want to add items.\n"
)
HOUSE = {"name": "house-rules", "kind": "package", "prepare": "", "bin": ["bin"]}


def runtime(repo: Path, home: Path) -> Runtime:
    return cli.make_runtime(cli.Place(repo, home), FakeQuery())


def commit_config(rt: Runtime, **changes) -> str:
    """A storyless step's commit of ``.agile-team.toml``; the runner records the checkout."""
    raw = copy.deepcopy(PY_CONFIG) | changes
    system.write_text(rt.config.repo / CONFIG_NAME, tomli_w.dumps(raw))
    sha = rt.git.commit_by([CONFIG_NAME], Authored("chore: change the config"))
    rt.record_checkout()
    return sha


def queue(repo: Path, *args: str) -> None:
    assert cli.main(["--repo", str(repo), "story", *args]) == 0


def draft(repo: Path, env: str, name: str) -> str:
    path = repo / ".team" / "run" / name
    system.make_dirs(path.parent)
    system.write_text(path, DRAFT.format(env=env))
    return str(path)


def kinds(rt: Runtime, kind: EventKind) -> list:
    return [e for e in rt.events.events() if e.kind == kind]


def ticked(rt: Runtime) -> Scheduler:
    """One scheduler tick, inside a loop as ``Scheduler.run`` has."""

    async def once() -> Scheduler:
        sched = Scheduler(rt, Start("task"))
        sched.tick()
        return sched

    return asyncio.run(once())


def test_ac1_an_amend_naming_a_committed_environment_is_accepted(
    configured: Path, key_home: Path
) -> None:
    rt = runtime(configured, key_home)
    queue(configured, "new", draft(configured, "cli", "new.md"), "--approved-by", "none")
    ticked(rt)
    assert "s1" in rt.state.stories
    commit_config(rt, environment=[*PY_CONFIG["environment"], HOUSE])
    queue(
        configured,
        "amend",
        "s1",
        draft(configured, "house-rules", "amend.md"),
        "--approved-by",
        "none",
    )
    ticked(rt)
    assert [e.story for e in kinds(rt, EventKind.STORY_AMENDED)] == ["s1"]
    assert kinds(rt, EventKind.STORY_REFUSED) == []
    assert "house-rules" in (configured / ".team/stories/s1.md").read_text()
    assert "house-rules" in [e.name for e in rt.config.environments]


def test_ac1_a_changed_test_command_reaches_the_gate_and_a_new_role_is_known(
    configured: Path, key_home: Path
) -> None:
    rt = runtime(configured, key_home)
    assert rt.refusal(StepRequest("qa", "go")) == "unknown role 'qa'"
    toolchain = PY_CONFIG["toolchain"] | {"test": "pytest -n 2"}
    commit_config(rt, toolchain=toolchain, roles={"qa": {"extends": "developer-cli"}})
    ticked(rt)
    assert rt.pipeline.checks.commands["test"] == "pytest -n 2"
    assert "unknown role" not in (rt.refusal(StepRequest("qa", "go")) or "")


def test_ac2_one_config_event_records_the_sha_and_changed_sections(
    configured: Path, key_home: Path
) -> None:
    rt = runtime(configured, key_home)
    sha = commit_config(rt, environment=[*PY_CONFIG["environment"], HOUSE])
    ticked(rt)
    ticked(rt)
    [event] = kinds(rt, EventKind.CONFIG)
    assert event.data["sha"] == sha
    assert event.data["blob"] == git(configured, "rev-parse", "HEAD:" + CONFIG_NAME).strip()
    assert event.data["sections"] == ["environment"]
    assert not event.data.get("error")


def test_ac3_a_broken_commit_keeps_the_last_good_config_and_tells_the_po(
    configured: Path, key_home: Path
) -> None:
    rt = runtime(configured, key_home)
    before = rt.config
    system.write_text(configured / CONFIG_NAME, "[team\n")
    rt.git.commit_by([CONFIG_NAME], Authored("chore: break the config"))
    rt.record_checkout()
    sched = ticked(rt)
    assert rt.config is before
    [event] = kinds(rt, EventKind.CONFIG)
    assert event.data["error"].startswith(".agile-team.toml:")
    taken = sched.desk.take()
    assert taken is not None and Trigger.CONFIG_INVALID in taken.kinds
