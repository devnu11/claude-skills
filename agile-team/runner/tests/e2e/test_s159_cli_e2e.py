"""s159 through the real ``agile-team`` CLI: config checks, the removed command, accept-checkout.

Real git and real files in a scratch repo; ``cli.main`` is the entry point.
"""

from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path
from typing import Any

import pytest
import tomli_w
from agile_team import cli, config, system
from agile_team import state as state_mod
from agile_team.state import RunStatus

from ..test_s61 import stored


def edit_config(repo: Path, **sections: dict[str, Any]) -> None:
    """Merge ``sections`` into the repo's ``.agile-team.toml``."""
    path = repo / config.CONFIG_NAME
    data = tomllib.loads(path.read_text())
    for name, values in sections.items():
        data.setdefault(name, {}).update(values)
    path.write_text(tomli_w.dumps(data))


def check(repo: Path, home: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = cli.main(["--repo", str(repo), "--home", str(home), "config", "check"])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def test_ac1_5_and_ac6_1_and_ac12_1_the_defaults_pass(
    configured: Path, key_home: Path, capsys
) -> None:
    loaded = config.load(configured)
    assert loaded.upstream.story_prefix == "team/story-"
    assert loaded.team.max_open_stories == 5 and loaded.team.step_reserve_usd == 1.0
    assert "problem" not in check(configured, key_home, capsys)[1]


@pytest.mark.parametrize(
    ("section", "values", "message"),
    [
        ("upstream", {"story_prefix": "team/sprint-"}, "story_prefix must differ"),
        ("upstream", {"prefix": "team/", "story_prefix": "team/story-"}, "story_prefix"),
        ("upstream", {"story_prefix": "bad prefix!"}, "story_prefix must be a branch name"),
        ("team", {"max_open_stories": 0}, "max_open_stories must be an integer of at least 1"),
        ("team", {"max_open_stories": 1.5}, "max_open_stories"),
        ("team", {"step_reserve_usd": 10.0}, "step_reserve_usd must be at least 0 and below"),
        ("team", {"step_reserve_usd": -1.0}, "step_reserve_usd"),
    ],
)
def test_ac1_5_ac6_1_ac12_1_unsafe_settings_are_refused_with_their_text(
    configured: Path, key_home: Path, capsys, section: str, values: dict[str, Any], message: str
) -> None:
    edit_config(configured, **{section: values})
    code, out = check(configured, key_home, capsys)
    assert code == 1 and message in out


def test_ac4_1_the_pending_tests_command_is_gone(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["pending-tests"])
    assert exc.value.code == 2
    assert "pending-tests" not in {c.name for c in cli.COMMANDS}


def test_ac1_4_accept_checkout_for_a_story_queues_a_request_while_the_runner_runs(
    configured: Path, key_home: Path, capsys
) -> None:
    run_dir = stored(configured, status=RunStatus.RUNNING)
    system.write_text(run_dir / state_mod.PID_FILE, str(os.getpid()))
    args = ["--repo", str(configured), "--home", str(key_home), "accept-checkout"]
    assert cli.main([*args, "--story", "s1"]) == 0
    assert "s1" in capsys.readouterr().out
    [request] = list((run_dir / "checkouts").iterdir())
    assert json.loads(request.read_text()) == {"story": "s1"}
    assert cli.main(args) == 1
    assert "the runner is running" in capsys.readouterr().err


def test_ac10_2_an_older_state_file_without_story_branch_fields_loads(configured: Path) -> None:
    run_dir = config.load(configured).run_dir
    old = {
        "status": "idle",
        "stories": {"s1": {"id": "s1", "title": "Old", "step": "design"}},
    }
    system.make_dirs(run_dir)
    (run_dir / "state.json").write_text(json.dumps(old))
    story = state_mod.load(run_dir).stories["s1"]
    assert (story.branch, story.base_sha, story.pushed, story.pr, story.replays) == (
        "",
        "",
        "",
        None,
        0,
    )
    assert story.landed is None
